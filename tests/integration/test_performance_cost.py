"""What the grade-book grid costs, and what a quiz contributes to it.

Two findings from one profiling pass, and they are the same kind of defect:
something read a field it should not have, and nothing noticed because the
output still looked like a number.

**The cost.** `/performance/batches/{id}` ran **10,267 queries in 55 seconds
for eight students**. Three causes, each one invisible to a correctness test:

1. `User` eager-loaded seventeen collections, including every audit-log row
   that person had ever generated. A `User` is loaded on every authenticated
   request, and again for every row of anything that references one.
2. `_assignment_marks`, `_quiz_marks` and `_exam_marks` selected ORM entities
   when they read five scalar columns, so every row dragged its relationships
   -- and `Exam` eager-loads *every result*, each of which eager-loads its
   student.
3. `_evaluate` loaded the whole `Batch` entity for one integer, pulling in its
   tutor reviews and their students.

After: **89 queries, 0.3 seconds.** The query-count test below is the guard,
because latency on a developer's laptop is not a number a test can assert and
the query count is exactly what regressed.

**The quiz contribution.** `Mark.percentage` is `earned / possible`, and
`_quiz_marks` passed a percentage as `earned` with the quiz's raw question
total as `possible`. An 80% attempt on a 12-point quiz contributed **666%**.
Nothing caught it: the engine's own tests build marks by hand, and the
service's tests had no quiz in them at all.
"""

from __future__ import annotations

import asyncio
import random
import selectors
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import event, select, text

from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.exam import Exam, ExamResult
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.quiz import Question, QuestionOption, Quiz, QuizAttempt
from backend.services.performance_service import PerformanceService
from backend.utils.enums import (
    AssessmentScope,
    CourseStatus,
    EnrollmentStatus,
    ExamType,
    GradeComponentType,
    QuestionType,
    SubmissionState,
    SubmissionType,
    UserStatus,
)

STUDENTS = 6
#: Eleven per student is what the trimmed implementation runs, plus a couple
#: for the roster and warm-up. Deliberately a ceiling with headroom rather
#: than an exact figure: this guards against the N+1 coming back, not against
#: somebody adding one honest query.
MAX_QUERIES_PER_STUDENT = 20


@pytest.fixture()
def env():
    tag = f"pc{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="perf-cost-tests")
    world: dict = {}
    now = datetime.now(timezone.utc)
    counted: list[int] = [0]
    counting: list[bool] = [False]

    @event.listens_for(db.engine.sync_engine, "before_cursor_execute")
    def before(conn, cursor, statement, params, context, executemany):  # noqa: ANN001
        if counting[0]:
            counted[0] += 1

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}
        admin = User(
            username=f"{tag}.admin", slug=f"{tag}-admin", email=f"{tag}.admin@t.test",
            hashed_password="x", status=UserStatus.ACTIVE, roles=[roles["SUPER_ADMIN"]],
        )
        students = [
            User(
                username=f"{tag}.s{i}", slug=f"{tag}-s{i}", email=f"{tag}.s{i}@t.test",
                hashed_password="x", status=UserStatus.ACTIVE, roles=[roles["STUDENT"]],
            )
            for i in range(STUDENTS)
        ]
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([admin, *students, course])
        await s.flush()

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=50)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()
        for student in students:
            s.add(Enrollments(batch_id=batch.id, student_id=student.id,
                              enrollment_date=now, status=EnrollmentStatus.CONFIRMED))

        quiz = Quiz(
            course_id=course.id, batch_id=batch.id, scope=AssessmentScope.BATCH,
            title=f"{tag} Quiz", passing_score=Decimal("50.00"), is_published=True,
            attempts_allowed=3, weight=Decimal("1.00"),
        )
        s.add(quiz)
        await s.flush()

        # Twelve points of questions, so a percentage and a raw total cannot
        # be mistaken for each other: 80% of 12 points is 9.6, and dividing
        # 80 by 12 gives 666.67.
        for index in range(4):
            question = Question(
                quiz_id=quiz.id, question_text=f"Q{index}",
                question_type=QuestionType.MCQ_SINGLE,
                points=Decimal("3.00"), order=index,
            )
            s.add(question)
            await s.flush()
            s.add_all([
                QuestionOption(question_id=question.id, option_text="right",
                               is_correct=True, order=0),
                QuestionOption(question_id=question.id, option_text="wrong",
                               is_correct=False, order=1),
            ])

        # A finished attempt scoring 80 **percent**, written the way
        # `QuizService` writes it.
        for student in students:
            s.add(QuizAttempt(
                quiz_id=quiz.id, student_id=student.id, attempt_number=1,
                started_at=now - timedelta(hours=1), finished_at=now,
                score=Decimal("80.00"), is_passed=True,
            ))

        # An assignment and an exam as well, each with a mark for every
        # student. Without them `_assignment_marks` and `_exam_marks` fetch
        # nothing, and the query-count test passes against an implementation
        # that loads whole ORM graphs -- the mutation proved it does. A
        # fixture that is too kind is the recurring way a cost test says
        # nothing.
        assignment = Assignment(
            course_id=course.id, batch_id=batch.id, scope=AssessmentScope.BATCH,
            title=f"{tag} Coursework", due_date=now + timedelta(days=7),
            max_score=Decimal("40.00"), submission_type=SubmissionType.TEXT,
        )
        exam = Exam(
            course_id=course.id, batch_id=batch.id, scope=AssessmentScope.BATCH,
            title=f"{tag} Final", scheduled_at=now + timedelta(days=14),
            total_marks=Decimal("80.00"), passing_marks=Decimal("40.00"),
            exam_type=ExamType.FINAL, is_published=True,
        )
        s.add_all([assignment, exam])
        await s.flush()
        for student in students:
            s.add(AssignmentSubmission(
                assignment_id=assignment.id, student_id=student.id,
                submitted_at=now, content="Done.", grade=Decimal("32.00"),
                state=SubmissionState.PUBLISHED,
            ))
            s.add(ExamResult(
                exam_id=exam.id, student_id=student.id,
                marks_obtained=Decimal("64.00"), is_published=True,
            ))
        await s.flush()

        world.update(
            admin=admin.id, batch_pk=batch.id, course_pk=course.id,
            students=[student.id for student in students],
        )

    run(build)

    def load_one_user():  # noqa: ANN202
        """How many queries one `User` costs, by itself."""
        async def go(s):  # noqa: ANN001, ANN202
            await s.execute(select(User).where(User.id == world["admin"]))
            counted[0] = 0
            counting[0] = True
            try:
                s.expunge_all()
                row = (
                    await s.execute(select(User).where(User.id == world["admin"]))
                ).scalars().unique().one()
                # Permissions are resolved on every request, so roles and
                # their permissions are read here on purpose -- the test is
                # about what *else* comes with them.
                _ = {p.name for r in (row.roles or []) for p in (r.permissions or [])}
            finally:
                counting[0] = False
            return counted[0]
        return run(go)

    def grid():  # noqa: ANN202
        """The whole grid, with the queries it ran."""
        async def go(s):  # noqa: ANN001, ANN202
            admin = await s.get(User, world["admin"])
            service = PerformanceService(s)
            # One pass first, uncounted: the grading scheme and the roles are
            # read on the way in, and counting a cold cache would measure
            # warm-up rather than the shape of the work.
            await service.for_batch(batch_id=world["batch_pk"], actor=admin)
            counted[0] = 0
            counting[0] = True
            try:
                return await service.for_batch(batch_id=world["batch_pk"], actor=admin)
            finally:
                counting[0] = False
        rows = run(go)
        return rows, counted[0]

    ns = type("Env", (), dict(
        tag=tag, world=world, run=staticmethod(run), grid=staticmethod(grid),
        load_one_user=staticmethod(load_one_user),
    ))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                for stmt in (
                    "DELETE FROM gradebook_entries WHERE student_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM exam_results WHERE exam_id IN (SELECT id FROM exams WHERE title LIKE :t)",
                    "DELETE FROM exams WHERE title LIKE :t",
                    "DELETE FROM assignment_submissions WHERE assignment_id IN (SELECT id FROM assignments WHERE title LIKE :t)",
                    "DELETE FROM assignments WHERE title LIKE :t",
                    "DELETE FROM quiz_answers WHERE attempt_id IN (SELECT id FROM quiz_attempts WHERE student_id IN (SELECT id FROM users WHERE username LIKE :u))",
                    "DELETE FROM quiz_attempts WHERE student_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM question_options WHERE question_id IN (SELECT id FROM questions WHERE quiz_id IN (SELECT id FROM quizzes WHERE title LIKE :t))",
                    "DELETE FROM questions WHERE quiz_id IN (SELECT id FROM quizzes WHERE title LIKE :t)",
                    "DELETE FROM quizzes WHERE title LIKE :t",
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


def test_a_quiz_mark_is_a_percentage_not_a_fraction_of_its_points(env) -> None:
    rows, _queries = env.grid()

    assert len(rows) == STUDENTS
    quizzes = [
        component
        for component in rows[0].performance.components
        if component.component_type is GradeComponentType.QUIZ
    ]
    assert quizzes, "the quiz component is missing from the breakdown"
    # 80, not 666.67. The attempt scored 80% of a quiz worth 12 raw points,
    # and `QuizAttempt.score` is the percentage -- so 12 is not a denominator
    # anybody should divide by.
    assert quizzes[0].percentage == Decimal("80")


def test_the_grid_does_not_scale_its_queries_by_what_it_finds(env) -> None:
    """The guard for the N+1, and it is a count rather than a clock.

    Latency on one laptop is not an assertion; the query count is the thing
    that actually regressed, and it regressed by a factor of a hundred
    without a single test noticing.
    """
    rows, queries = env.grid()

    assert len(rows) == STUDENTS
    assert queries <= STUDENTS * MAX_QUERIES_PER_STUDENT, (
        f"{queries} queries for {STUDENTS} students"
    )


def test_every_student_in_the_batch_comes_back(env) -> None:
    # The cheap way to pass the test above is to return nothing, so the two
    # are asserted together.
    rows, _queries = env.grid()

    assert sorted(row.student_id for row in rows) == sorted(env.world["students"])
    assert all(
        row.performance.current_percentage is not None
        or row.performance.unconfigured
        for row in rows
    )


#: `users` itself, `roles`, `permissions`, and the two scalar lookups the user
#: forms need (`cities`, `countries`). Seven leaves room for one more without
#: leaving room for a history fan-out.
MAX_QUERIES_PER_USER = 7


def test_loading_one_user_does_not_load_their_whole_history(env) -> None:
    """The defect that made the grid slow, measured where it lives.

    A `User` is loaded on every authenticated request to resolve permissions,
    and seventeen of its relationships were `lazy="selectin"` -- so every
    request also fetched that person's tokens, enrollments, attendance,
    shared resources, organisation memberships and **every audit-log row they
    had ever generated**.

    Asserted here rather than through the grid, which no longer loads a
    single `User` entity at all now that its queries select columns: the
    cost is on the authenticated path of the whole API, and reverting the
    model would otherwise fail nothing.
    """
    queries = env.load_one_user()

    assert queries <= MAX_QUERIES_PER_USER, f"loading one user ran {queries} queries"
