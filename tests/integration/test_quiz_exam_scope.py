"""Quizzes and examinations answer to the same eligibility rule as assignments.

§3's requirement is that there is *one* implementation, not three that agree
today. So these tests do not re-prove the resolver — `test_assessment_scope.py`
does that — they prove the two services actually route through it.

**One of them is a bug fix, not a refactor.** `ExamService` carried its own copy
of the eligibility join, and the copy quietly differed: for a course-wide exam
it never filtered on `Batch.is_active`, so students from closed batches appeared
on the mark sheet. Last year's cohort, on this year's examination. That is
asserted below, and it fails against the code as it was.
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
from backend.core.errors import ConflictError
from backend.db.manager import DatabaseManager
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course, TutorCourse
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.schemas.exam import ExamCreateRequest
from backend.schemas.quiz import OptionInput, QuestionCreateRequest, QuizCreateRequest
from backend.services.exam_service import ExamService
from backend.services.quiz_service import QuizService
from backend.utils.enums import (
    AssessmentScope as Sc,
    QuestionType,
    CourseStatus,
    EnrollmentStatus,
    ExamType,
    Platforms,
    UserStatus,
)

D = Decimal


@pytest.fixture()
def env():
    tag = "qe" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="quiz-exam-scope")

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
        alice, bob, ghost = (user("alice", "STUDENT"), user("bob", "STUDENT"),
                             user("ghost", "STUDENT"))
        course = Course(title=f"{tag} course", code=f"{tag}-C", status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([tutor, alice, bob, ghost, course])
        await s.flush()
        s.add(TutorCourse(tutor_id=tutor.id, course_id=course.id))

        def batch(code: str, active: bool = True) -> Batch:
            b = Batch(batch_code=f"{tag}-{code}", course_id=course.id,
                      start_date=date.today(), end_date=date.today() + timedelta(days=60),
                      is_active=active, capacity=20)
            b.sessions, b.enrollments, b.student_reviews = [], [], []
            return b

        batch_a, batch_b = batch("A"), batch("B")
        # Last year's cohort. The batch is closed; `ghost` must not appear on
        # anything set this year.
        batch_old = batch("OLD", active=False)
        s.add_all([batch_a, batch_b, batch_old])
        await s.flush()

        now = datetime.now(UTC)
        sess = BatchSession(batch_id=batch_a.id, tutor_id=tutor.id,
                            session_start_time=now + timedelta(days=1),
                            session_end_time=now + timedelta(days=1, hours=2),
                            duration_minutes=120, platform=Platforms.Zoom)
        sess.attendances = []
        s.add(sess)
        s.add_all([
            Enrollments(batch_id=batch_a.id, student_id=alice.id, enrollment_date=now,
                        status=EnrollmentStatus.CONFIRMED),
            Enrollments(batch_id=batch_b.id, student_id=bob.id, enrollment_date=now,
                        status=EnrollmentStatus.CONFIRMED),
            Enrollments(batch_id=batch_old.id, student_id=ghost.id, enrollment_date=now,
                        status=EnrollmentStatus.CONFIRMED),
        ])
        await s.flush()
        return {"tutor": tutor, "alice": alice, "bob": bob, "ghost": ghost,
                "course": course, "batch_a": batch_a, "batch_b": batch_b,
                "batch_old": batch_old, "session": sess}

    ns = type("Env", (), dict(tag=tag, run=staticmethod(run), build=staticmethod(build)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"u": f"{tag}.%", "c": f"{tag}-%", "t": f"{tag}%"}
                b = "(SELECT id FROM batches WHERE batch_code LIKE :c)"
                q = "(SELECT id FROM quizzes WHERE title LIKE :t)"
                e = "(SELECT id FROM exams WHERE title LIKE :t)"
                await s.execute(text(f"DELETE FROM quiz_answers WHERE attempt_id IN (SELECT id FROM quiz_attempts WHERE quiz_id IN {q})"), p)
                await s.execute(text(f"DELETE FROM quiz_attempts WHERE quiz_id IN {q}"), p)
                await s.execute(text(f"DELETE FROM question_options WHERE question_id IN (SELECT id FROM questions WHERE quiz_id IN {q})"), p)
                await s.execute(text(f"DELETE FROM questions WHERE quiz_id IN {q}"), p)
                await s.execute(text("DELETE FROM quizzes WHERE title LIKE :t"), p)
                await s.execute(text(f"DELETE FROM exam_results WHERE exam_id IN {e}"), p)
                await s.execute(text(f"DELETE FROM exam_invigilators WHERE exam_id IN {e}"), p)
                await s.execute(text("DELETE FROM exams WHERE title LIKE :t"), p)
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


def _quiz(env, **over) -> QuizCreateRequest:
    base = dict(title=f"{env.tag} Quiz", passing_score=D("50"), attempts_allowed=2)
    base.update(over)
    return QuizCreateRequest(**base)


async def _open_quiz(svc: QuizService, made, env, **over):
    """A published quiz with one question.

    The question is not incidental: `set_published` refuses a quiz with an
    empty bank, and that guard is right -- a quiz students can open and cannot
    answer is worse than one that is not there. Satisfying it is the correct
    response, rather than reaching past it.
    """
    quiz = await svc.create(made["course"].public_id, _quiz(env, **over), actor=made["tutor"])
    await svc.add_question(
        quiz.public_id,
        QuestionCreateRequest(
            question_text="2 + 2?",
            question_type=QuestionType.MCQ_SINGLE,
            points=D("1"),
            options=[
                OptionInput(option_text="4", is_correct=True, order=0),
                OptionInput(option_text="5", is_correct=False, order=1),
            ],
        ),
        actor=made["tutor"],
    )
    await svc.set_published(quiz.public_id, True, actor=made["tutor"])
    return quiz


def _exam(env, **over) -> ExamCreateRequest:
    base = dict(
        title=f"{env.tag} Exam", exam_type=ExamType.FINAL,
        scheduled_at=datetime.now(UTC) + timedelta(days=5),
        total_marks=D("100"), passing_marks=D("40"),
    )
    base.update(over)
    return ExamCreateRequest(**base)


# ------------------------------------------------------------------ quizzes ---


def test_a_batch_quiz_refuses_a_student_from_another_batch(env) -> None:
    """The quiz service routes through the shared resolver, so the rule proved
    in `test_assessment_scope.py` applies here without being reimplemented."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = QuizService(s)
            quiz = await _open_quiz(svc, made, env, scope=Sc.BATCH, batch_id=made["batch_a"].public_id)
            await s.flush()

            ok = await svc.start_attempt(quiz.public_id, actor=made["alice"])
            with pytest.raises(ConflictError) as refused:
                await svc.start_attempt(quiz.public_id, actor=made["bob"])
            return ok.attempt_number, str(refused.value)
        return go()

    attempt, message = env.run(f)
    assert attempt == 1
    assert "not set for you" in message.lower()


def test_a_quiz_that_has_not_opened_is_refused(env) -> None:
    """§9's availability period. `is_published` alone could not express "opens
    Monday", so a quiz was either live or invisible."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = QuizService(s)
            quiz = await _open_quiz(svc, made, env, available_from=datetime.now(UTC) + timedelta(days=2))
            await s.flush()
            with pytest.raises(ConflictError) as refused:
                await svc.start_attempt(quiz.public_id, actor=made["alice"])
            return str(refused.value)
        return go()

    assert "not opened" in env.run(f).lower()


def test_a_quiz_that_has_closed_is_refused(env) -> None:
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = QuizService(s)
            quiz = await _open_quiz(svc, made, env, available_until=datetime.now(UTC) - timedelta(hours=1))
            await s.flush()
            with pytest.raises(ConflictError) as refused:
                await svc.start_attempt(quiz.public_id, actor=made["alice"])
            return str(refused.value)
        return go()

    assert "closed" in env.run(f).lower()


def test_an_open_window_lets_the_attempt_start(env) -> None:
    """The positive case, so the two refusals above cannot be passing because
    attempts never start at all."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = QuizService(s)
            quiz = await _open_quiz(svc, made, env,
                      available_from=datetime.now(UTC) - timedelta(hours=1),
                      available_until=datetime.now(UTC) + timedelta(hours=1))
            await s.flush()
            return (await svc.start_attempt(quiz.public_id, actor=made["alice"])).attempt_number
        return go()

    assert env.run(f) == 1


# --------------------------------------------------------------- examinations ---


def _exam_roster(env, **over) -> set[str]:
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = ExamService(s)
            exam = await svc.create(
                _exam(env, course_id=made["course"].public_id, **over), actor=made["tutor"]
            )
            await s.flush()
            ids = await svc._eligible_student_ids(exam)
            rows = (await s.execute(select(User.username).where(User.id.in_(ids)))).scalars().all()
            return {u.rsplit(".", 1)[-1] for u in rows}
        return go()
    return env.run(f)


def test_a_course_wide_exam_excludes_a_closed_batch(env) -> None:
    """The bug the shared resolver fixes.

    `ExamService` had its own copy of this join which never filtered on
    `Batch.is_active`, so `ghost` -- enrolled in a batch that finished -- was
    listed as eligible for this year's final examination and could be given a
    mark. This assertion fails against the code as it was.
    """
    who = _exam_roster(env)
    assert who == {"alice", "bob"}
    assert "ghost" not in who


def test_a_batch_exam_is_limited_to_that_batch(env) -> None:
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = ExamService(s)
            exam = await svc.create(
                _exam(env, course_id=made["course"].public_id, scope=Sc.BATCH,
                      batch_id=made["batch_a"].public_id),
                actor=made["tutor"],
            )
            await s.flush()
            ids = await svc._eligible_student_ids(exam)
            rows = (await s.execute(select(User.username).where(User.id.in_(ids)))).scalars().all()
            return {u.rsplit(".", 1)[-1] for u in rows}
        return go()

    assert env.run(f) == {"alice"}


def test_an_exam_records_whether_it_is_sat_online(env) -> None:
    """§10: both styles feed the same grade book, and this is what lets a
    screen know which workflow to offer."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = ExamService(s)
            offline = await svc.create(
                _exam(env, course_id=made["course"].public_id), actor=made["tutor"])
            online = await svc.create(
                _exam(env, course_id=made["course"].public_id, is_online=True),
                actor=made["tutor"])
            await s.flush()
            return offline.is_online, online.is_online
        return go()

    assert env.run(f) == (False, True)
