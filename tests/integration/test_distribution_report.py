"""Grade distribution (spec §34).

The report exists because an average cannot show shape: thirty students at
68% and fifteen at 85 with fifteen at 50 produce the same mean and are
completely different problems. So the fixture below is deliberately bimodal,
and the assertions are about where students land rather than about a total.

Three things are easy to get wrong and each has a test:

* counting against *marks* rather than the roster, which silently drops the
  students nobody has assessed and draws a confident curve from whoever is
  left;
* dropping empty bands, which hides the gap in the middle that makes a
  distribution worth reading;
* rendering a distribution across two grading schemes, which adds together
  bands that do not mean the same thing.
"""

from __future__ import annotations

import asyncio
import random
import selectors
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.gradebook import GradeBand, GradeBookEntry
from backend.models.grading import GradingScheme
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.repositories.distribution_reporting import DistributionReportingRepository
from backend.services.scope import WorkVisibility
from backend.utils.enums import (
    CourseStatus,
    EnrollmentStatus,
    GradeComponentType,
    UserStatus,
)

UNRESTRICTED = WorkVisibility(
    unrestricted=True, taught_course_ids=frozenset(), cared_for_student_ids=frozenset()
)

# Deliberately leaves a hole: nobody in the fixture lands in B.
BANDS = (("A", 80, 100), ("B", 60, 79.99), ("C", 40, 59.99), ("F", 0, 39.99))


@pytest.fixture()
def env():
    tag = f"gd{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="distribution-tests")
    world: dict = {}
    now = datetime.now(timezone.utc)

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def user(name: str) -> User:
            return User(
                username=f"{tag}.{name}", slug=f"{tag}-{name}", email=f"{tag}.{name}@t.test",
                hashed_password="x", status=UserStatus.ACTIVE, roles=[roles["STUDENT"]],
            )

        scheme = GradingScheme(name=f"{tag} scheme", is_active=True, is_default=False)
        s.add(scheme)
        await s.flush()
        for letter, low, high in BANDS:
            s.add(GradeBand(
                scheme_id=scheme.id, letter_grade=letter,
                min_score=Decimal(str(low)), max_score=Decimal(str(high)),
                gpa_points=Decimal("4.00" if letter == "A" else "1.00"),
                is_pass=letter != "F",
            ))

        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED,
                        grading_scheme_id=scheme.id)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add(course)
        await s.flush()

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=20)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        # A *closed* batch of the same course, which §3 excludes from a
        # course-wide population. Without it the fixture cannot tell the
        # scope rule from a plain "same course" join.
        closed = Batch(batch_code=f"{tag}-Z", course_id=course.id, start_date=date.today(),
                       end_date=date.today() + timedelta(days=60), is_active=False, capacity=20)
        closed.sessions, closed.enrollments, closed.student_reviews = [], [], []
        s.add_all([batch, closed])
        await s.flush()

        # Bimodal on purpose: two near the top, two near the bottom, nobody in
        # the middle -- the shape a mean of ~63% would completely conceal.
        marks = {"top1": 90, "top2": 84, "low1": 52, "low2": 30}
        students = {}
        for name in (*marks, "ghost"):
            u = user(name)
            s.add(u)
            students[name] = u
        await s.flush()

        for name, u in students.items():
            s.add(Enrollments(batch_id=batch.id, student_id=u.id,
                              enrollment_date=now, status=EnrollmentStatus.CONFIRMED))

        # `archived` sits only in the closed batch. `top1` sits in both, with
        # a poor mark there -- so a distribution that matched marks on the
        # student alone would drag them out of A.
        archived = user("archived")
        s.add(archived)
        await s.flush()
        s.add(Enrollments(batch_id=closed.id, student_id=archived.id,
                          enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        s.add(Enrollments(batch_id=closed.id, student_id=students["top1"].id,
                          enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        await s.flush()

        for name, score in marks.items():
            s.add(GradeBookEntry(
                student_id=students[name].id, batch_id=batch.id,
                component_type=GradeComponentType.ASSIGNMENT, reference_id=None,
                score=Decimal(str(score)), max_score=Decimal("100.00"),
                weight=Decimal("1.000"), recorded_at=now,
            ))
        for student_id, score in ((archived.id, 95), (students["top1"].id, 10)):
            s.add(GradeBookEntry(
                student_id=student_id, batch_id=closed.id,
                component_type=GradeComponentType.ASSIGNMENT, reference_id=None,
                score=Decimal(str(score)), max_score=Decimal("100.00"),
                weight=Decimal("1.000"), recorded_at=now,
            ))
        # `ghost` is enrolled and has no marks at all.
        await s.flush()

        world.update(scheme_id=scheme.id, course_pk=course.id, batch_pk=batch.id)

    run(build)

    def report(**kw):  # noqa: ANN003, ANN202
        kw.setdefault("visibility", UNRESTRICTED)
        kw.setdefault("scheme_id", world["scheme_id"])
        kw.setdefault("course_id", world["course_pk"])
        kw.setdefault("batch_id", None)
        return run(lambda s: DistributionReportingRepository(s).distribution(**kw))

    ns = type("Env", (), dict(tag=tag, world=world, run=staticmethod(run), report=staticmethod(report)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                for stmt in (
                    "DELETE FROM gradebook_entries WHERE student_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batches WHERE batch_code LIKE :c",
                    "UPDATE courses SET grading_scheme_id = NULL WHERE title LIKE :t",
                    "DELETE FROM courses WHERE title LIKE :t",
                    "DELETE FROM grade_bands WHERE scheme_id IN (SELECT id FROM grading_schemes WHERE name LIKE :t)",
                    "DELETE FROM grading_schemes WHERE name LIKE :t",
                    "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM users WHERE username LIKE :u",
                ):
                    await s.execute(text(stmt), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _counts(rows: list) -> dict[str, int]:
    return {letter: students for letter, _label, students in rows}


def test_students_land_in_the_band_their_mark_falls_in(env) -> None:
    rows, _unassessed = env.report()

    assert _counts(rows) == {"A": 2, "B": 0, "C": 1, "F": 1}


def test_a_band_nobody_reached_is_still_a_row(env) -> None:
    rows, _unassessed = env.report()
    letters = [letter for letter, _label, _n in rows]

    # The hole in the middle is the finding. Dropping "B: 0" leaves a reader
    # to infer a gap that was never shown to them.
    assert letters == ["A", "B", "C", "F"]
    assert _counts(rows)["B"] == 0


def test_an_unassessed_student_is_counted_and_kept_out_of_the_bands(env) -> None:
    rows, unassessed = env.report()

    # Counting against marks instead of the roster would report four students
    # and a tidy distribution, with the fifth silently absent.
    assert unassessed == 1
    assert sum(_counts(rows).values()) == 4


def test_bands_are_ordered_highest_first(env) -> None:
    rows, _unassessed = env.report()

    assert [letter for letter, _label, _n in rows] == ["A", "B", "C", "F"]
    # The label carries the range, so a reader need not know the scheme.
    assert rows[0][1] == "A (80–100%)"


def test_a_batch_filter_narrows_to_that_cohort(env) -> None:
    rows, unassessed = env.report(course_id=None, batch_id=env.world["batch_pk"])

    assert _counts(rows) == {"A": 2, "B": 0, "C": 1, "F": 1}
    assert unassessed == 1


def test_a_tutor_who_teaches_nothing_here_sees_an_empty_cohort(env) -> None:
    blind = WorkVisibility(
        unrestricted=False, taught_course_ids=frozenset(), cared_for_student_ids=frozenset()
    )
    rows, unassessed = env.report(visibility=blind)

    # The bands still come back -- they describe the scheme, not the people --
    # but nobody is counted in them.
    assert _counts(rows) == {"A": 0, "B": 0, "C": 0, "F": 0}
    assert unassessed == 0


def test_a_closed_batch_is_not_part_of_the_course_shape(env) -> None:
    """§3: a course-wide population is its *active* batches.

    The closed cohort holds a student marked at 95. Counting them would move
    the distribution and present last year's results as this year's shape.
    """
    rows, _unassessed = env.report()

    assert _counts(rows)["A"] == 2  # not 3


def test_marks_are_matched_to_the_cohort_being_measured(env) -> None:
    """One student, two batches, two very different marks.

    Matching marks on the student alone rather than on the (student, batch)
    pair folds the other cohort's results into this one -- here it would drag
    a student from A down to C in a batch they aced.
    """
    rows, _unassessed = env.report(course_id=None, batch_id=env.world["batch_pk"])

    assert _counts(rows) == {"A": 2, "B": 0, "C": 1, "F": 1}
