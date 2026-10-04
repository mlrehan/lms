"""The grading queue (spec §34's Tutor Grading Status).

Three assessment types, three different definitions of "waiting", and the
easy mistake is to treat them as one. The fixture therefore seeds work in
each of the four states that look similar and are not:

* a submission that arrived and has a mark -- done;
* a submission that arrived and has none -- waiting;
* a quiz attempt still in progress -- the *student's* outstanding work, not
  the tutor's;
* an exam with no result rows at all -- nobody has said anyone sat it, so
  there is nothing to mark.

A queue that counted any of those three as outstanding would show a tutor
work that does not exist, which is how a backlog figure stops being read.
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
from backend.models.exam import Exam, ExamResult
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.quiz import Quiz, QuizAttempt
from backend.repositories.grading_queue_reporting import GradingQueueRepository
from backend.services.scope import WorkVisibility
from backend.utils.enums import (
    AssessmentScope,
    AssessmentState,
    CourseStatus,
    EnrollmentStatus,
    ExamType,
    SubmissionState,
    SubmissionType,
    UserStatus,
)

UNRESTRICTED = WorkVisibility(
    unrestricted=True, taught_course_ids=frozenset(), cared_for_student_ids=frozenset()
)


@pytest.fixture()
def env():
    tag = f"gq{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="grading-queue-tests")
    world: dict = {}
    now = datetime.now(timezone.utc)

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def user(name: str, role: str = "STUDENT") -> User:
            return User(
                username=f"{tag}.{name}", slug=f"{tag}-{name}", email=f"{tag}.{name}@t.test",
                hashed_password="x", status=UserStatus.ACTIVE, roles=[roles[role]],
            )

        tutor = user("tutor", "TUTOR")
        marked, waiting, quizzer, sitter = (
            user("marked"), user("waiting"), user("quizzer"), user("sitter")
        )
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        quiet = Course(title=f"{tag} Quiet", code=f"{tag}q", status=CourseStatus.PUBLISHED)
        quiet.batches, quiet.resources, quiet.tags, quiet.tutors = [], [], [], []
        s.add_all([tutor, marked, waiting, quizzer, sitter, course, quiet])
        await s.flush()

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=20)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()
        for u in (marked, waiting, quizzer, sitter):
            s.add(Enrollments(batch_id=batch.id, student_id=u.id,
                              enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        await s.flush()

        work = Assignment(
            course_id=course.id, batch_id=batch.id, session_id=None,
            scope=AssessmentScope.BATCH, state=AssessmentState.PUBLISHED,
            title="Work", due_date=now + timedelta(days=3),
            max_score=Decimal("100.00"), submission_type=SubmissionType.TEXT,
            weight=Decimal("1.00"),
        )
        s.add(work)
        await s.flush()
        s.add_all([
            AssignmentSubmission(assignment_id=work.id, student_id=marked.id,
                                 submitted_at=now, state=SubmissionState.GRADED,
                                 grade=Decimal("70.00"), graded_at=now, attempt_number=1),
            AssignmentSubmission(assignment_id=work.id, student_id=waiting.id,
                                 submitted_at=now, state=SubmissionState.SUBMITTED,
                                 grade=None, attempt_number=1),
        ])

        # Withdrawn to draft, with a submission still attached. Without this
        # the draft filter cannot be told from its absence.
        shelved = Assignment(
            course_id=course.id, batch_id=batch.id, session_id=None,
            scope=AssessmentScope.BATCH, state=AssessmentState.DRAFT,
            title="Shelved", due_date=now + timedelta(days=3),
            max_score=Decimal("100.00"), submission_type=SubmissionType.TEXT,
            weight=Decimal("1.00"),
        )
        s.add(shelved)
        await s.flush()
        s.add(AssignmentSubmission(assignment_id=shelved.id, student_id=marked.id,
                                   submitted_at=now, state=SubmissionState.SUBMITTED,
                                   grade=None, attempt_number=1))

        quiz = Quiz(course_id=course.id, batch_id=batch.id, scope=AssessmentScope.BATCH,
                    title="Quiz", passing_score=Decimal("50.00"), is_published=True,
                    weight=Decimal("1.00"))
        s.add(quiz)
        await s.flush()
        s.add_all([
            # Finished with no score: something in it needed a person.
            QuizAttempt(quiz_id=quiz.id, student_id=quizzer.id, attempt_number=1,
                        started_at=now, finished_at=now, score=None),
            # Still in progress: the student's outstanding work, not the tutor's.
            QuizAttempt(quiz_id=quiz.id, student_id=waiting.id, attempt_number=1,
                        started_at=now, finished_at=None, score=None),
        ])

        exam = Exam(course_id=course.id, batch_id=batch.id, scope=AssessmentScope.BATCH,
                    exam_type=ExamType.MIDTERM, title="Exam",
                    scheduled_at=now + timedelta(days=7), duration_minutes=60,
                    total_marks=Decimal("100.00"), passing_marks=Decimal("40.00"),
                    is_published=True, is_online=False, weight=Decimal("1.00"))
        exam.invigilators, exam.results = [], []
        # An exam nobody has been recorded against at all.
        future = Exam(course_id=course.id, batch_id=batch.id, scope=AssessmentScope.BATCH,
                      exam_type=ExamType.FINAL, title="Untaken",
                      scheduled_at=now + timedelta(days=40), duration_minutes=60,
                      total_marks=Decimal("100.00"), passing_marks=Decimal("40.00"),
                      is_published=True, is_online=False, weight=Decimal("1.00"))
        future.invigilators, future.results = [], []
        s.add_all([exam, future])
        await s.flush()
        s.add_all([
            ExamResult(exam_id=exam.id, student_id=sitter.id, marks_obtained=None),
            # Already marked: a count of *result rows* rather than unmarked
            # ones would pick this up too.
            ExamResult(exam_id=exam.id, student_id=quizzer.id, marks_obtained=Decimal("61.00")),
        ])
        await s.flush()

        world.update(course_pk=course.id, batch_pk=batch.id, quiet_pk=quiet.id,
                     course_title=course.title, quiet_title=quiet.title)

    run(build)

    def queue(group: str = "course", **kw):  # noqa: ANN003, ANN202
        kw.setdefault("visibility", UNRESTRICTED)
        kw.setdefault("course_id", None)
        kw.setdefault("batch_id", None)
        return run(lambda s: GradingQueueRepository(s).queue_by(group, **kw))

    ns = type("Env", (), dict(tag=tag, world=world, run=staticmethod(run), queue=staticmethod(queue)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                for stmt in (
                    "DELETE FROM exam_results WHERE exam_id IN (SELECT id FROM exams WHERE course_id IN (SELECT id FROM courses WHERE title LIKE :t))",
                    "DELETE FROM exams WHERE course_id IN (SELECT id FROM courses WHERE title LIKE :t)",
                    "DELETE FROM quiz_attempts WHERE quiz_id IN (SELECT id FROM quizzes WHERE course_id IN (SELECT id FROM courses WHERE title LIKE :t))",
                    "DELETE FROM quizzes WHERE course_id IN (SELECT id FROM courses WHERE title LIKE :t)",
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
    return next(m for _k, lbl, m in rows if lbl == label)


def test_each_assessment_type_is_counted_once(env) -> None:
    metrics = _row(env.queue(course_id=env.world["course_pk"]), env.world["course_title"])

    assert metrics == {"assignments": 1, "quizzes": 1, "exams": 1, "total": 3}


def test_marked_work_is_not_waiting(env) -> None:
    metrics = _row(env.queue(course_id=env.world["course_pk"]), env.world["course_title"])

    # Two submissions exist; only the unmarked one is somebody's job.
    assert metrics["assignments"] == 1


def test_an_unfinished_attempt_is_the_students_problem_not_the_tutors(env) -> None:
    metrics = _row(env.queue(course_id=env.world["course_pk"]), env.world["course_title"])

    # Two attempts with no score; only the finished one is waiting on a
    # person. Counting both would tell a tutor to mark work still being done.
    assert metrics["quizzes"] == 1


def test_an_exam_nobody_has_been_recorded_against_is_not_a_backlog(env) -> None:
    metrics = _row(env.queue(course_id=env.world["course_pk"]), env.world["course_title"])

    # Two exams, one result row. An exam with no rows is not outstanding
    # marking -- otherwise every exam scheduled for next term is backlog.
    assert metrics["exams"] == 1


def test_a_course_with_nothing_outstanding_is_omitted(env) -> None:
    labels = {label for _k, label, _m in env.queue()}

    assert env.world["course_title"] in labels
    # An empty queue is the absence of work. Listing it as a zero makes the
    # report a directory.
    assert env.world["quiet_title"] not in labels


def test_a_tutor_sees_only_their_own_backlog(env) -> None:
    blind = WorkVisibility(
        unrestricted=False, taught_course_ids=frozenset(), cared_for_student_ids=frozenset()
    )
    assert env.queue(visibility=blind) == []


def test_grouping_by_batch_attributes_the_backlog_to_the_cohort(env) -> None:
    rows = env.queue("batch", course_id=env.world["course_pk"])

    assert len(rows) == 1
    assert rows[0][2]["total"] == 3
