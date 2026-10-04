"""Quiz shuffling (spec §9), which was a stored setting nothing ever read.

The console offered a switch labelled "Shuffle question order for each
attempt" and the questions came back in authored order every time. A control
that does nothing is worse than an absent one: somebody sets it and believes
the paper is shuffled.

Two properties matter and they pull against each other:

* it must actually permute, per attempt, or it is not shuffling;
* it must be **stable within one attempt**, or a student who reloads is
  handed a different paper and every answer they have already chosen is
  silently remapped onto a different question.

A test that only checked the first would pass against an implementation that
reshuffles on every request -- which is the dangerous one.
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
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.quiz import Question, QuestionOption, Quiz, QuizAttempt
from backend.services.quiz_service import QuizService
from backend.utils.enums import (
    AssessmentScope,
    CourseStatus,
    EnrollmentStatus,
    QuestionType,
    UserStatus,
)

QUESTION_COUNT = 12
OPTION_COUNT = 6


@pytest.fixture()
def env():
    tag = f"qs{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="quiz-shuffle-tests")
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

        alice, bob = user("alice"), user("bob")
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([alice, bob, course])
        await s.flush()

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=20)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()
        for u in (alice, bob):
            s.add(Enrollments(batch_id=batch.id, student_id=u.id,
                              enrollment_date=now, status=EnrollmentStatus.CONFIRMED))

        def make_quiz(name: str, *, shuffle_questions: bool, shuffle_answers: bool) -> Quiz:
            return Quiz(
                course_id=course.id, batch_id=batch.id, scope=AssessmentScope.BATCH,
                title=f"{tag} {name}", passing_score=Decimal("50.00"), is_published=True,
                shuffle_questions=shuffle_questions, shuffle_answers=shuffle_answers,
                attempts_allowed=5, weight=Decimal("1.00"),
            )

        shuffled = make_quiz("shuffled", shuffle_questions=True, shuffle_answers=True)
        plain = make_quiz("plain", shuffle_questions=False, shuffle_answers=False)
        s.add_all([shuffled, plain])
        await s.flush()

        # Enough questions and options that an unchanged order cannot be
        # mistaken for a shuffle that happened to land the same way.
        for quiz in (shuffled, plain):
            for index in range(QUESTION_COUNT):
                q = Question(
                    quiz_id=quiz.id, question_text=f"Q{index}",
                    question_type=QuestionType.MCQ_SINGLE,
                    points=Decimal("1.00"), order=index,
                )
                s.add(q)
                await s.flush()
                for opt in range(OPTION_COUNT):
                    s.add(QuestionOption(
                        question_id=q.id, option_text=f"Q{index}-O{opt}",
                        is_correct=opt == 0, order=opt,
                    ))
        await s.flush()

        world.update(
            shuffled=shuffled.public_id, plain=plain.public_id,
            quiz_pks={"shuffled": shuffled.id, "plain": plain.id},
            alice=alice.id, bob=bob.id, course_title=course.title,
        )

    run(build)

    def start(quiz_pk: int, student_id: int, number: int = 1) -> None:
        async def go(s):  # noqa: ANN001, ANN202
            s.add(QuizAttempt(quiz_id=quiz_pk, student_id=student_id,
                              started_at=datetime.now(timezone.utc),
                              attempt_number=number))
        run(go)

    def paper(quiz_public_id, student_id: int) -> tuple[list[str], list[list[str]]]:
        async def go(s):  # noqa: ANN001, ANN202
            student = await s.get(User, student_id)
            rows = await QuizService(s).questions_for_attempt(quiz_public_id, actor=student)
            return (
                [q.question_text for q, _o in rows],
                [[o.option_text for o in opts] for _q, opts in rows],
            )
        return run(go)

    ns = type("Env", (), dict(
        tag=tag, world=world, run=staticmethod(run),
        start=staticmethod(start), paper=staticmethod(paper),
    ))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                for stmt in (
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


AUTHORED = [f"Q{i}" for i in range(QUESTION_COUNT)]


def test_questions_are_permuted_once_an_attempt_is_under_way(env) -> None:
    env.start(env.world["quiz_pks"]["shuffled"], env.world["alice"])
    order, _options = env.paper(env.world["shuffled"], env.world["alice"])

    assert sorted(order) == sorted(AUTHORED)  # same paper
    assert order != AUTHORED  # different order


def test_the_same_attempt_gets_the_same_paper_back(env) -> None:
    env.start(env.world["quiz_pks"]["shuffled"], env.world["alice"])

    first, first_options = env.paper(env.world["shuffled"], env.world["alice"])
    second, second_options = env.paper(env.world["shuffled"], env.world["alice"])

    # The property a naive `random.shuffle` fails. A student who reloads
    # mid-quiz must not have their chosen answers remapped.
    assert first == second
    assert first_options == second_options


def test_two_students_get_different_papers(env) -> None:
    env.start(env.world["quiz_pks"]["shuffled"], env.world["alice"])
    env.start(env.world["quiz_pks"]["shuffled"], env.world["bob"])

    alice, _ = env.paper(env.world["shuffled"], env.world["alice"])
    bob, _ = env.paper(env.world["shuffled"], env.world["bob"])

    # Otherwise the shuffle is one fixed reordering and buys nothing.
    assert alice != bob


def test_answer_options_are_shuffled_per_question(env) -> None:
    env.start(env.world["quiz_pks"]["shuffled"], env.world["alice"])
    _order, options = env.paper(env.world["shuffled"], env.world["alice"])

    permuted = [
        opts for opts in options if opts != sorted(opts)
    ]
    assert permuted, "no question had its options reordered"

    # Seeded per question, not once per attempt: the same permutation applied
    # to every question would make the correct answer's position guessable
    # from a single question.
    shapes = {tuple(o.rsplit("-", 1)[1] for o in opts) for opts in options}
    assert len(shapes) > 1, "every question was permuted identically"


def test_a_quiz_that_does_not_shuffle_is_untouched(env) -> None:
    env.start(env.world["quiz_pks"]["plain"], env.world["alice"])
    order, options = env.paper(env.world["plain"], env.world["alice"])

    assert order == AUTHORED
    assert all(opts == sorted(opts) for opts in options)


def test_before_an_attempt_starts_the_authored_order_is_shown(env) -> None:
    order, options = env.paper(env.world["shuffled"], env.world["alice"])

    # An author previewing, or a student who has not pressed start. Inventing
    # a shuffle here would show a paper different from the one they get.
    assert order == AUTHORED
    assert all(opts == sorted(opts) for opts in options)
