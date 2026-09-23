"""Who an assessment is for.

This is the rule that decides who is handed work and whose absence counts as a
missing submission, so it is tested against real enrolments in real batches
rather than against a fake — the whole thing is a join across three tables and
a status filter, and a stubbed repository would assert only that I called it.

The shape under test is one resolver shared by assignments, quizzes and
examinations (§3). Each scope is checked for both who it *includes* and who it
*excludes*, because an eligibility rule that is too generous and one that is too
mean fail in opposite, equally damaging directions.
"""

from __future__ import annotations

import asyncio
import selectors
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.core.errors import ValidationError
from backend.db.manager import DatabaseManager
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.services.assessment_scope import (
    AssessmentScopeResolver,
    AssessmentTarget,
    validate,
)
from backend.utils.enums import (
    AssessmentScope as Sc,
    CourseStatus,
    EnrollmentStatus,
    Platforms,
    UserStatus,
)


@pytest.fixture()
def env():
    tag = "as" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="scope-tests")

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        role = (await s.execute(select(Role).where(Role.name == "STUDENT"))).scalar_one()
        tutor_role = (await s.execute(select(Role).where(Role.name == "TUTOR"))).scalar_one()

        def user(kind: str, r=role) -> User:
            return User(
                username=f"{tag}.{kind}", slug=f"{tag}-{kind}", email=f"{tag}.{kind}@t.test",
                hashed_password="x", status=UserStatus.ACTIVE, roles=[r],
            )

        tutor = user("tutor", tutor_role)
        # a and b are in batch A; c is in batch B; d withdrew; e is on a
        # different course entirely.
        people = {k: user(k) for k in ("a", "b", "c", "d", "e")}
        course = Course(title=f"{tag} course", code=f"{tag}-C", status=CourseStatus.PUBLISHED)
        other = Course(title=f"{tag} other", code=f"{tag}-O", status=CourseStatus.PUBLISHED)
        for c in (course, other):
            c.batches, c.resources, c.tags, c.tutors = [], [], [], []
        s.add_all([tutor, *people.values(), course, other])
        await s.flush()

        def batch(code: str, course_id: int, active: bool = True) -> Batch:
            b = Batch(batch_code=f"{tag}-{code}", course_id=course_id,
                      start_date=date.today(), end_date=date.today() + timedelta(days=60),
                      is_active=active, capacity=30)
            b.sessions, b.enrollments, b.student_reviews = [], [], []
            return b

        batch_a, batch_b = batch("A", course.id), batch("B", course.id)
        # Inactive: a course-wide assessment must not reach a closed batch.
        batch_dead = batch("DEAD", course.id, active=False)
        batch_other = batch("OTH", other.id)
        s.add_all([batch_a, batch_b, batch_dead, batch_other])
        await s.flush()

        now = datetime.now(UTC)

        def session_for(b: Batch, offset: int) -> BatchSession:
            row = BatchSession(
                batch_id=b.id, tutor_id=tutor.id,
                session_start_time=now + timedelta(days=offset),
                session_end_time=now + timedelta(days=offset, hours=2),
                duration_minutes=120, platform=Platforms.Zoom,
            )
            row.attendances = []
            return row

        sess_a, sess_b = session_for(batch_a, 1), session_for(batch_b, 2)
        s.add_all([sess_a, sess_b])

        def enrol(student: User, b: Batch, status=EnrollmentStatus.CONFIRMED) -> Enrollments:
            return Enrollments(batch_id=b.id, student_id=student.id,
                               enrollment_date=now, status=status)

        s.add_all([
            enrol(people["a"], batch_a),
            enrol(people["b"], batch_a),
            enrol(people["c"], batch_b),
            enrol(people["d"], batch_a, EnrollmentStatus.DROPPED),
            enrol(people["e"], batch_other),
        ])
        # Somebody in the closed batch, so "active batches only" is testable.
        s.add(enrol(people["e"], batch_dead))
        await s.flush()

        return {
            "course": course, "batch_a": batch_a, "batch_b": batch_b,
            "batch_dead": batch_dead, "sess_a": sess_a, "sess_b": sess_b,
            **people,
        }

    ns = type("Env", (), dict(tag=tag, run=staticmethod(run), build=staticmethod(build)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"u": f"{tag}.%", "c": f"{tag}-%"}
                b = "(SELECT id FROM batches WHERE batch_code LIKE :c)"
                await s.execute(text(f"DELETE FROM batch_sessions WHERE batch_id IN {b}"), p)
                await s.execute(text(f"DELETE FROM enrollments WHERE batch_id IN {b}"), p)
                await s.execute(text("DELETE FROM batches WHERE batch_code LIKE :c"), p)
                await s.execute(text("DELETE FROM courses WHERE code LIKE :c"), p)
                await s.execute(text("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _eligible(env, make_target) -> set[str]:
    """The eligible population, as the usernames that make it readable."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            target = make_target(made)
            ids = await AssessmentScopeResolver(s).eligible_student_ids(target)
            rows = (await s.execute(select(User.username).where(User.id.in_(ids)))).scalars().all()
            return {u.rsplit(".", 1)[-1] for u in rows}
        return go()
    return env.run(f)


# ------------------------------------------------------------ course scope ---


def test_a_course_wide_assessment_reaches_every_active_batch(env) -> None:
    """§3: "Students from all active Batches of that Course"."""
    who = _eligible(env, lambda m: AssessmentTarget(Sc.COURSE, m["course"].id))
    assert who == {"a", "b", "c"}


def test_and_not_a_closed_batch(env) -> None:
    """"Active" is load-bearing: last year's cohort should not be set this
    year's coursework. Student `e` is in the closed batch and in another
    course, so their absence above proves both."""
    who = _eligible(env, lambda m: AssessmentTarget(Sc.COURSE, m["course"].id))
    assert "e" not in who


def test_and_not_a_withdrawn_student(env) -> None:
    """A dropped student is not handed new work, and must not turn up on a
    tutor's missing-submissions list for it."""
    who = _eligible(env, lambda m: AssessmentTarget(Sc.COURSE, m["course"].id))
    assert "d" not in who


# ------------------------------------------------------------- batch scope ---


def test_a_batch_assessment_reaches_only_that_batch(env) -> None:
    who = _eligible(env, lambda m: AssessmentTarget(Sc.BATCH, m["course"].id, batch_id=m["batch_a"].id))
    assert who == {"a", "b"}


def test_the_other_batch_of_the_same_course_is_excluded(env) -> None:
    """The case the old course-only model could not express at all."""
    who = _eligible(env, lambda m: AssessmentTarget(Sc.BATCH, m["course"].id, batch_id=m["batch_b"].id))
    assert who == {"c"}


# ----------------------------------------------------------- session scope ---


def test_a_session_assessment_reaches_the_batch_behind_the_session(env) -> None:
    """Resolved through the batch, never through the attendance register: a
    student who missed the class must still be set the work arising from it."""
    who = _eligible(env, lambda m: AssessmentTarget(
        Sc.SESSION, m["course"].id, batch_id=m["batch_a"].id, session_id=m["sess_a"].id))
    assert who == {"a", "b"}


def test_a_session_of_a_different_batch_reaches_different_people(env) -> None:
    who = _eligible(env, lambda m: AssessmentTarget(
        Sc.SESSION, m["course"].id, batch_id=m["batch_b"].id, session_id=m["sess_b"].id))
    assert who == {"c"}


# ------------------------------------------------------------- membership ---


def test_is_eligible_agrees_with_the_population(env) -> None:
    """The two must never disagree: one decides whether a submission is
    accepted, the other decides who appears on the tutor's list."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            resolver = AssessmentScopeResolver(s)
            target = AssessmentTarget(Sc.BATCH, made["course"].id, batch_id=made["batch_a"].id)
            population = await resolver.eligible_student_ids(target)
            return [
                (await resolver.is_eligible(target, made["a"].id), made["a"].id in population),
                (await resolver.is_eligible(target, made["c"].id), made["c"].id in population),
                (await resolver.is_eligible(target, made["d"].id), made["d"].id in population),
                await resolver.count_eligible(target),
            ]
        return go()

    a, c, d, count = env.run(f)
    assert a == (True, True)
    assert c == (False, False)
    assert d == (False, False)   # withdrawn
    assert count == 2


# --------------------------------------------------------------- deriving ---


def test_choosing_a_session_derives_its_batch_and_course(env) -> None:
    """A tutor picks a class; they should not have to restate which batch and
    course it belongs to, and a mistyped course id must not be believed."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            target = await AssessmentScopeResolver(s).resolve_ids(
                scope=Sc.SESSION,
                course_id=999_999,          # deliberately wrong; must be ignored
                batch_id=None,
                session_id=made["sess_a"].id,
            )
            return target, made["batch_a"].id, made["course"].id
        return go()

    target, batch_id, course_id = env.run(f)
    assert target.batch_id == batch_id
    assert target.course_id == course_id   # derived, not the 999999 passed in


def test_a_course_wide_assessment_clears_any_batch_it_was_given(env) -> None:
    """Otherwise a stale batch id sits on the row, and somebody later "fixes"
    the scope by reading the wrong column."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            return await AssessmentScopeResolver(s).resolve_ids(
                scope=Sc.COURSE, course_id=made["course"].id,
                batch_id=made["batch_a"].id, session_id=made["sess_a"].id,
            )
        return go()

    target = env.run(f)
    assert target.batch_id is None and target.session_id is None


# -------------------------------------------------------------- validation ---


def test_a_scope_that_names_nothing_is_refused() -> None:
    """The database has the same CHECK. This one produces a message a tutor
    can act on; the constraint catches whatever reaches the table by another
    route. Neither makes the other redundant."""
    with pytest.raises(ValidationError):
        validate(AssessmentTarget(Sc.BATCH, course_id=1))
    with pytest.raises(ValidationError):
        validate(AssessmentTarget(Sc.SESSION, course_id=1, batch_id=2))
    with pytest.raises(ValidationError):
        validate(AssessmentTarget(Sc.COURSE, course_id=1, batch_id=2))


def test_a_coherent_scope_passes() -> None:
    validate(AssessmentTarget(Sc.COURSE, course_id=1))
    validate(AssessmentTarget(Sc.BATCH, course_id=1, batch_id=2))
    validate(AssessmentTarget(Sc.SESSION, course_id=1, batch_id=2, session_id=3))
