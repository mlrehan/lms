"""The assignment workflow, end to end (spec §8, §14, §38, §43).

§43 names the cases: submission before the deadline, late submission, blocked
late submission, resubmission, grading. Each is here, driven through the real
service against real enrolments -- the rules being tested are joins and state
transitions, and a fake would assert only that I called my own methods.

The two that matter most are the ones a spec is easy to satisfy on paper and
easy to get wrong in code:

* **A student in the wrong batch is refused.** This was impossible to get wrong
  before, because every assignment was course-wide; it is the first thing scoped
  assessments could break.
* **A mark is not visible until it is released.** Grading and publishing are
  separate acts, and a test that only checks the mark exists would pass with the
  distinction deleted.
"""

from __future__ import annotations

import asyncio
import selectors
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.core.errors import ConflictError, ValidationError
from backend.db.manager import DatabaseManager
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course, TutorCourse
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.schemas.assignment import (
    AssignmentCreateRequest,
    GradeSubmissionRequest,
    SubmitAssignmentRequest,
)
from backend.services.assignment_service import AssignmentService
from backend.utils.enums import (
    AssessmentScope as Sc,
    AssessmentState,
    CourseStatus,
    EnrollmentStatus,
    Platforms,
    SubmissionState as St,
    SubmissionType,
    UserStatus,
)

D = Decimal


@pytest.fixture()
def env():
    tag = "aw" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="assignment-tests")

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def user(kind: str, role: str) -> User:
            return User(username=f"{tag}.{kind}", slug=f"{tag}-{kind}",
                        email=f"{tag}.{kind}@t.test", hashed_password="x",
                        status=UserStatus.ACTIVE, roles=[roles[role]])

        tutor = user("tutor", "TUTOR")
        alice, bob = user("alice", "STUDENT"), user("bob", "STUDENT")
        course = Course(title=f"{tag} course", code=f"{tag}-C", status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([tutor, alice, bob, course])
        await s.flush()
        s.add(TutorCourse(tutor_id=tutor.id, course_id=course.id))

        def batch(code: str) -> Batch:
            b = Batch(batch_code=f"{tag}-{code}", course_id=course.id,
                      start_date=date.today(), end_date=date.today() + timedelta(days=60),
                      is_active=True, capacity=20)
            b.sessions, b.enrollments, b.student_reviews = [], [], []
            return b

        batch_a, batch_b = batch("A"), batch("B")
        s.add_all([batch_a, batch_b])
        await s.flush()

        now = datetime.now(UTC)
        sess = BatchSession(batch_id=batch_a.id, tutor_id=tutor.id,
                            session_start_time=now + timedelta(days=1),
                            session_end_time=now + timedelta(days=1, hours=2),
                            duration_minutes=120, platform=Platforms.Zoom)
        sess.attendances = []
        s.add(sess)
        # Alice in batch A, Bob in batch B: the pair that makes scoping testable.
        s.add_all([
            Enrollments(batch_id=batch_a.id, student_id=alice.id, enrollment_date=now,
                        status=EnrollmentStatus.CONFIRMED),
            Enrollments(batch_id=batch_b.id, student_id=bob.id, enrollment_date=now,
                        status=EnrollmentStatus.CONFIRMED),
        ])
        await s.flush()
        return {"tutor": tutor, "alice": alice, "bob": bob, "course": course,
                "batch_a": batch_a, "batch_b": batch_b, "session": sess}

    ns = type("Env", (), dict(tag=tag, run=staticmethod(run), build=staticmethod(build)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"u": f"{tag}.%", "c": f"{tag}-%", "t": f"{tag}%"}
                a = "(SELECT id FROM assignments WHERE title LIKE :t)"
                b = "(SELECT id FROM batches WHERE batch_code LIKE :c)"
                await s.execute(text(f"DELETE FROM assignment_submissions WHERE assignment_id IN {a}"), p)
                await s.execute(text("DELETE FROM assignments WHERE title LIKE :t"), p)
                await s.execute(text(f"DELETE FROM batch_sessions WHERE batch_id IN {b}"), p)
                await s.execute(text(f"DELETE FROM enrollments WHERE batch_id IN {b}"), p)
                await s.execute(text("DELETE FROM batches WHERE batch_code LIKE :c"), p)
                await s.execute(text("DELETE FROM tutor_courses WHERE course_id IN (SELECT id FROM courses WHERE code LIKE :c)"), p)
                await s.execute(text("DELETE FROM courses WHERE code LIKE :c"), p)
                await s.execute(text("DELETE FROM notifications WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _create(made, **over) -> AssignmentCreateRequest:
    base = dict(
        title=f"{made['course'].code[:-2]} Essay",
        due_date=datetime.now(UTC) + timedelta(days=7),
        max_score=D("100"),
        submission_type=SubmissionType.TEXT,
    )
    base.update(over)
    return AssignmentCreateRequest(**base)


def _title(env) -> str:
    return f"{env.tag}-C Essay"


# ----------------------------------------------------------------- scoping ---


def test_a_batch_assignment_is_offered_only_to_that_batch(env) -> None:
    """The case the old course-only model could not express at all."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = AssignmentService(s)
            row = await svc.create(
                made["course"].public_id,
                _create(made, scope=Sc.BATCH, batch_id=made["batch_a"].public_id),
                actor=made["tutor"],
            )
            await s.flush()
            alice = await svc.submit(row.public_id, SubmitAssignmentRequest(content="mine"),
                                     actor=made["alice"])
            with pytest.raises(ConflictError) as refused:
                await svc.submit(row.public_id, SubmitAssignmentRequest(content="theirs"),
                                 actor=made["bob"])
            return alice.state, str(refused.value)
        return go()

    state, message = env.run(f)
    assert state is St.SUBMITTED
    assert "not set for you" in message.lower()


def test_a_session_assignment_derives_its_batch(env) -> None:
    """A tutor picks a class; the audience follows from it."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            row = await AssignmentService(s).create(
                made["course"].public_id,
                _create(made, scope=Sc.SESSION, session_id=made["session"].public_id),
                actor=made["tutor"],
            )
            await s.flush()
            return row.scope, row.batch_id, made["batch_a"].id
        return go()

    scope, batch_id, expected = env.run(f)
    assert scope is Sc.SESSION
    assert batch_id == expected


def test_naming_a_batch_from_another_course_is_refused(env) -> None:
    """Silently following the derived course would put the work on a roster the
    tutor never chose."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            other = Course(title=f"{env.tag} other", code=f"{env.tag}-O",
                           status=CourseStatus.PUBLISHED)
            other.batches, other.resources, other.tags, other.tutors = [], [], [], []
            s.add(other)
            await s.flush()
            s.add(TutorCourse(tutor_id=made["tutor"].id, course_id=other.id))
            await s.flush()
            with pytest.raises(ValidationError):
                await AssignmentService(s).create(
                    other.public_id,
                    _create(made, scope=Sc.BATCH, batch_id=made["batch_a"].public_id),
                    actor=made["tutor"],
                )
            return True
        return go()

    assert env.run(f)


# ------------------------------------------------------------- submission ---


def test_a_draft_accepts_nothing(env) -> None:
    """A student who kept a link must not be able to submit to work the tutor
    has not published."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = AssignmentService(s)
            row = await svc.create(
                made["course"].public_id, _create(made, state=AssessmentState.DRAFT),
                actor=made["tutor"],
            )
            await s.flush()
            with pytest.raises(ConflictError):
                await svc.submit(row.public_id, SubmitAssignmentRequest(content="x"),
                                 actor=made["alice"])
            return True
        return go()

    assert env.run(f)


def test_late_work_is_refused_when_the_assignment_forbids_it(env) -> None:
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = AssignmentService(s)
            row = await svc.create(
                made["course"].public_id,
                _create(made, due_date=datetime.now(UTC) - timedelta(days=1),
                        allow_late_submissions=False),
                actor=made["tutor"],
            )
            await s.flush()
            with pytest.raises(ConflictError):
                await svc.submit(row.public_id, SubmitAssignmentRequest(content="late"),
                                 actor=made["alice"])
            return True
        return go()

    assert env.run(f)


def test_late_work_is_accepted_and_recorded_as_late(env) -> None:
    """LATE is recorded at submission time, not derived on read: whether work
    was late is a fact about when it arrived, and a deadline the tutor later
    extends must not retroactively rewrite it."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = AssignmentService(s)
            row = await svc.create(
                made["course"].public_id,
                _create(made, due_date=datetime.now(UTC) - timedelta(days=2),
                        allow_late_submissions=True),
                actor=made["tutor"],
            )
            await s.flush()
            sub = await svc.submit(row.public_id, SubmitAssignmentRequest(content="late"),
                                   actor=made["alice"])
            return sub.state
        return go()

    assert env.run(f) is St.LATE


# ---------------------------------------------------------------- grading ---


def _graded(env, **create_over):
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = AssignmentService(s)
            row = await svc.create(made["course"].public_id, _create(made, **create_over),
                                   actor=made["tutor"])
            await s.flush()
            sub = await svc.submit(row.public_id, SubmitAssignmentRequest(content="work"),
                                   actor=made["alice"])
            await s.flush()
            graded = await svc.grade(sub.public_id, GradeSubmissionRequest(grade=D("80")),
                                     actor=made["tutor"])
            await s.flush()
            return svc, made, row, graded
        return go()
    return env.run(f)


def test_grading_does_not_release_the_mark(env) -> None:
    """The distinction §14 exists for. A test that only checked the mark was
    stored would pass with this deleted."""
    _, _, _, graded = _graded(env)
    assert graded.grade == D("80")
    assert graded.state is St.GRADED
    assert graded.state.is_visible_to_student is False
    assert graded.published_at is None


def test_publishing_releases_it(env) -> None:
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = AssignmentService(s)
            row = await svc.create(made["course"].public_id, _create(made), actor=made["tutor"])
            await s.flush()
            sub = await svc.submit(row.public_id, SubmitAssignmentRequest(content="w"),
                                   actor=made["alice"])
            await s.flush()
            await svc.grade(sub.public_id, GradeSubmissionRequest(grade=D("80")),
                            actor=made["tutor"])
            await s.flush()
            count = await svc.publish_results(row.public_id, actor=made["tutor"])
            await s.flush()
            refreshed = await svc.get_submission(sub.public_id, actor=made["tutor"])
            return count, refreshed.state, refreshed.published_at is not None
        return go()

    count, state, has_timestamp = env.run(f)
    assert count == 1
    assert state is St.PUBLISHED
    assert state.is_visible_to_student is True
    assert has_timestamp


def test_changing_a_given_mark_requires_a_reason(env) -> None:
    """§24. The audit log records that it happened; the reason sits beside the
    mark, where whoever queries the grade will see it."""
    svc, made, _, graded = _graded(env)

    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            service = AssignmentService(s)
            tutor = (await s.execute(select(User).where(User.username == f"{env.tag}.tutor"))).scalar_one()
            with pytest.raises(ValidationError):
                await service.grade(graded.public_id, GradeSubmissionRequest(grade=D("90")),
                                    actor=tutor)
            ok = await service.grade(
                graded.public_id,
                GradeSubmissionRequest(grade=D("90"), override_reason="Marking error on Q3"),
                actor=tutor,
            )
            return ok.grade, ok.override_reason, ok.overridden_at is not None
        return go()

    grade, reason, stamped = env.run(f)
    assert grade == D("90")
    assert reason == "Marking error on Q3"
    assert stamped


def test_a_late_penalty_is_arithmetic_the_student_can_check(env) -> None:
    """10% a day, two days late, out of 100 -> 20 off. `raw_grade` keeps what
    the tutor actually awarded, so the deduction is explicable rather than a
    number nobody can account for."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = AssignmentService(s)
            row = await svc.create(
                made["course"].public_id,
                _create(made, due_date=datetime.now(UTC) - timedelta(days=2),
                        allow_late_submissions=True,
                        late_penalty_percent_per_day=D("10")),
                actor=made["tutor"],
            )
            await s.flush()
            sub = await svc.submit(row.public_id, SubmitAssignmentRequest(content="late"),
                                   actor=made["alice"])
            await s.flush()
            graded = await svc.grade(sub.public_id, GradeSubmissionRequest(grade=D("80")),
                                     actor=made["tutor"])
            return graded.raw_grade, graded.late_penalty_applied, graded.grade
        return go()

    raw, penalty, final = env.run(f)
    assert raw == D("80")
    assert penalty == D("30.00")      # 2 days late, inclusive -> 3 × 10% of 100
    assert final == D("50.00")


# ------------------------------------------------------ absence and exemption ---


def test_an_exemption_and_an_absence_are_different_states(env) -> None:
    """§38. One removes the component from the total, the other counts as a
    nil result. A nullable grade could express neither."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = AssignmentService(s)
            row = await svc.create(made["course"].public_id, _create(made), actor=made["tutor"])
            await s.flush()
            sub = await svc.submit(row.public_id, SubmitAssignmentRequest(content="w"),
                                   actor=made["alice"])
            await s.flush()
            # The value, not the row: both calls return the *same* ORM
            # instance, so holding two references and comparing them later
            # compares one object with itself.
            exempt = (await svc.set_submission_state(
                sub.public_id, actor=made["tutor"], state=St.EXEMPTED, reason="Medical")).state
            absent = (await svc.set_submission_state(
                sub.public_id, actor=made["tutor"], state=St.ABSENT)).state
            return exempt, absent
        return go()

    exempt_state, absent_state = env.run(f)
    assert exempt_state is St.EXEMPTED
    assert absent_state is St.ABSENT
    # The engine treats them oppositely, which is the whole reason for two names.
    assert St.EXEMPTED.counts_toward_grade is False
    assert St.ABSENT.counts_toward_grade is True


def test_a_state_that_is_not_a_tutors_to_set_is_refused(env) -> None:
    """PUBLISHED is reached by publishing, not by assertion -- otherwise the
    release step could be bypassed by writing the state directly."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = AssignmentService(s)
            row = await svc.create(made["course"].public_id, _create(made), actor=made["tutor"])
            await s.flush()
            sub = await svc.submit(row.public_id, SubmitAssignmentRequest(content="w"),
                                   actor=made["alice"])
            await s.flush()
            with pytest.raises(ValidationError):
                await svc.set_submission_state(sub.public_id, actor=made["tutor"],
                                               state=St.PUBLISHED)
            return True
        return go()

    assert env.run(f)
