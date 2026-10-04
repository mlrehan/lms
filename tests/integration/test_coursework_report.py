"""The coursework report (spec §34–§35): submission, missing work, grading status.

**The denominator is the test.** A submission rate computed over
`assignment_submissions` is 100% by construction -- the student who never
handed anything in has no row to count -- and it looks entirely plausible on
a screen. So every assertion below is written against a cohort where some
students deliberately did nothing, and the number that must be right is
`missing`.

Scoping is checked the same way the calendar feed's is, and for the same
reason: an aggregate computed over rows the caller cannot see leaks exactly
what the row filter withholds, one number at a time. "How many of my students
failed" is a smaller answer than the list, not a safer one.
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
from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.repositories.coursework_reporting import CourseworkReportingRepository
from backend.services.scope import WorkVisibility
from backend.utils.enums import (
    AssessmentScope,
    AssessmentState,
    CourseStatus,
    EnrollmentStatus,
    SubmissionState,
    SubmissionType,
    UserStatus,
)

UNRESTRICTED = WorkVisibility(
    unrestricted=True, taught_course_ids=frozenset(), cared_for_student_ids=frozenset()
)


@pytest.fixture()
def env():
    tag = f"cw{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="coursework-report-tests")
    world: dict = {}
    now = datetime.now(timezone.utc)

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def user(name: str, role: str) -> User:
            return User(
                username=f"{tag}.{name}", slug=f"{tag}-{name}", email=f"{tag}.{name}@t.test",
                hashed_password="x", status=UserStatus.ACTIVE, roles=[roles[role]],
            )

        # Four students in one batch: one submits and passes, one submits and
        # fails, one submits and is not marked yet, one does nothing at all.
        passer, failer, unmarked, ghost = (
            user("passer", "STUDENT"), user("failer", "STUDENT"),
            user("unmarked", "STUDENT"), user("ghost", "STUDENT"),
        )
        other_student = user("other", "STUDENT")
        # `straggler` is in a second active batch of the same course, and
        # `archived` is in a closed one. Without them the scope rule and a
        # naive "same course" join give identical answers, and the test proves
        # nothing about which is in use.
        straggler, archived = user("straggler", "STUDENT"), user("archived", "STUDENT")
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        other_course = Course(title=f"{tag} Other", code=f"{tag}o", status=CourseStatus.PUBLISHED)
        other_course.batches, other_course.resources, other_course.tags, other_course.tutors = [], [], [], []
        s.add_all([passer, failer, unmarked, ghost, other_student, straggler, archived,
                   course, other_course])
        await s.flush()

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=10)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        other_batch = Batch(batch_code=f"{tag}-B", course_id=other_course.id, start_date=date.today(),
                            end_date=date.today() + timedelta(days=60), is_active=True, capacity=10)
        other_batch.sessions, other_batch.enrollments, other_batch.student_reviews = [], [], []
        second = Batch(batch_code=f"{tag}-D", course_id=course.id, start_date=date.today(),
                       end_date=date.today() + timedelta(days=60), is_active=True, capacity=10)
        second.sessions, second.enrollments, second.student_reviews = [], [], []
        closed = Batch(batch_code=f"{tag}-Z", course_id=course.id, start_date=date.today(),
                       end_date=date.today() + timedelta(days=60), is_active=False, capacity=10)
        closed.sessions, closed.enrollments, closed.student_reviews = [], [], []
        s.add_all([batch, other_batch, second, closed])
        await s.flush()

        for student in (passer, failer, unmarked, ghost):
            s.add(Enrollments(batch_id=batch.id, student_id=student.id,
                              enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        s.add(Enrollments(batch_id=other_batch.id, student_id=other_student.id,
                          enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        s.add(Enrollments(batch_id=second.id, student_id=straggler.id,
                          enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        s.add(Enrollments(batch_id=closed.id, student_id=archived.id,
                          enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        await s.flush()

        def assignment(title: str, *, state, course_row=None, passing=Decimal("50.00"),
                       batch_row=None) -> Assignment:
            return Assignment(
                course_id=(course_row or course).id,
                batch_id=batch_row.id if batch_row is not None else None,
                session_id=None,
                scope=AssessmentScope.BATCH if batch_row is not None else AssessmentScope.COURSE,
                state=state,
                title=title,
                due_date=now + timedelta(days=5),
                max_score=Decimal("100.00"),
                passing_score=passing,
                submission_type=SubmissionType.TEXT,
                weight=Decimal("1.00"),
            )

        live = assignment("Live", state=AssessmentState.PUBLISHED)
        draft = assignment("Draft", state=AssessmentState.DRAFT)
        elsewhere = assignment("Elsewhere", state=AssessmentState.PUBLISHED, course_row=other_course)
        batch_only = assignment("Batch only", state=AssessmentState.PUBLISHED, batch_row=second)
        s.add_all([live, draft, elsewhere, batch_only])
        await s.flush()

        def submission(student, *, state, grade, attempt=1) -> AssignmentSubmission:
            return AssignmentSubmission(
                assignment_id=live.id, student_id=student.id, submitted_at=now,
                state=state, grade=grade, attempt_number=attempt,
                graded_at=now if grade is not None else None,
            )

        s.add_all([
            # `attempt=2` on one row, not two rows: a replacement updates the
            # submission in place, which the unique constraint enforces.
            submission(passer, state=SubmissionState.GRADED, grade=Decimal("80.00"), attempt=2),
            submission(failer, state=SubmissionState.GRADED, grade=Decimal("20.00")),
            submission(unmarked, state=SubmissionState.SUBMITTED, grade=None),
        ])
        # `ghost` deliberately has no row at all -- the case the report exists
        # to surface, and the one a submission-row query cannot see.
        await s.flush()

        world.update(
            course=course.public_id, batch=batch.public_id, live=live.public_id,
            course_pk=course.id, batch_pk=batch.id,
            other_course_pk=other_course.id, second_pk=second.id,
            ghost=ghost.username, passer=passer.username,
        )

    run(build)

    def report(group: str, *, visibility: WorkVisibility = UNRESTRICTED, **kw):  # noqa: ANN001, ANN202
        return run(lambda s: CourseworkReportingRepository(s).coursework_by(
            group, visibility=visibility, **kw
        ))

    ns = type("Env", (), dict(tag=tag, world=world, run=staticmethod(run), report=staticmethod(report)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                for stmt in (
                    "DELETE FROM assignment_submissions WHERE student_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM assignments WHERE course_id IN (SELECT id FROM courses WHERE title LIKE :t)",
                    "DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batches WHERE batch_code LIKE :c",
                    "DELETE FROM courses WHERE title LIKE :t",
                    "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM users WHERE username LIKE :u",
                ):
                    await s.execute(text(stmt), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _row(rows: list, label: str) -> dict:
    return next(metrics for _key, lbl, metrics in rows if lbl == label)


def test_a_student_who_submitted_nothing_still_counts_against_the_rate(env) -> None:
    metrics = _row(env.report("assignment", course_id=env.world["course_pk"]), "Live")

    # Five eligible students across the course's two *active* batches, three
    # submissions. Counting over submission rows would report 3 expected, 3
    # submitted and a flawless 100%.
    assert metrics["expected"] == 5
    assert metrics["submitted"] == 3
    assert metrics["missing"] == 2
    assert metrics["submission_rate"] == 60.0


def test_drafts_are_not_work_anybody_is_missing(env) -> None:
    labels = {label for _key, label, _m in env.report("assignment", course_id=env.world["course_pk"])}

    # A draft has been set for nobody, so its four "missing submissions"
    # would be a chase list for work that was never given out.
    assert "Live" in labels
    assert "Draft" not in labels


def test_pass_rate_ignores_work_that_has_not_been_marked(env) -> None:
    metrics = _row(env.report("assignment", course_id=env.world["course_pk"]), "Live")

    # Two marked: one above the threshold, one below. The unmarked
    # submission and the missing student are not failures -- they are not yet
    # facts, which is the distinction §38 insists on.
    assert metrics["pass_rate"] == 50.0
    assert metrics["awaiting_grading"] == 1


def test_a_student_row_names_who_to_chase(env) -> None:
    rows = env.report("student", course_id=env.world["course_pk"])

    assert _row(rows, env.world["ghost"])["missing"] == 1
    assert _row(rows, env.world["ghost"])["submitted"] == 0
    assert _row(rows, env.world["passer"])["missing"] == 0


def test_a_tutor_sees_only_the_courses_they_teach(env) -> None:
    taught_elsewhere = WorkVisibility(
        unrestricted=False,
        taught_course_ids=frozenset({env.world["other_course_pk"]}),
        cared_for_student_ids=frozenset(),
    )
    labels = {label for _key, label, _m in env.report("assignment", visibility=taught_elsewhere)}

    # The positive matters as much as the negative: an empty result would
    # pass a "cannot see Live" assertion while proving the report broken.
    assert "Elsewhere" in labels
    assert "Live" not in labels


def test_an_empty_population_reports_nothing_rather_than_zero(env) -> None:
    metrics = _row(env.report("assignment", course_id=env.world["other_course_pk"]), "Elsewhere")

    # One eligible student, no submissions at all.
    assert metrics["expected"] == 1
    assert metrics["submission_rate"] == 0.0
    # Nothing has been marked, so there is no pass rate -- not a 0% one.
    assert metrics["pass_rate"] is None


def test_the_population_comes_from_the_scope_rule_not_the_course_id(env) -> None:
    """The shared `covers_batch` rule, exercised where a naive join differs.

    A batch-scoped assignment carries its course id too, so "join on the same
    course" looks right and quietly sets the work for every cohort. And §3
    says a course-wide assessment reaches *active* batches only -- the exam
    service once lost that clause and put a closed cohort on a live mark
    sheet.
    """
    rows = env.report("assignment", course_id=env.world["course_pk"])

    # Set for one batch of one student, not for the course's other five.
    assert _row(rows, "Batch only")["expected"] == 1
    # The closed batch's student is in the course and is not eligible.
    assert _row(rows, "Live")["expected"] == 5
