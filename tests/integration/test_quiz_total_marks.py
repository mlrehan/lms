"""A paper has a total, and the questions have to fit inside it.

A quiz used to be worth whatever its questions happened to add up to. There
was no way to say "this paper is out of 50" before writing it, so nothing
could tell a tutor they had written 60 marks into a 50-mark paper -- and the
pass mark, which is a percentage of the total, then meant something other
than what was intended.

The three things worth pinning, because each is a different way to get this
wrong:

* the ceiling is **enforced on the server**, not merely greyed out in the
  console -- the console is where the request is composed, not where it is
  decided;
* a quiz with **no** total keeps working exactly as before, because every
  quiz written before this field existed has one of those and inventing a
  ceiling for them would start refusing their next question;
* the limit is **recoverable** -- lowering or removing a question makes room
  again, which is the difference between a limit and a dead end.
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
from backend.core.errors import ValidationError
from backend.db.manager import DatabaseManager
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.quiz import Quiz
from backend.schemas.quiz import QuestionCreateRequest, QuestionUpdateRequest
from backend.services.quiz_service import QuizService
from backend.utils.enums import (
    AssessmentScope,
    CourseStatus,
    Platforms,
    QuestionType,
    UserStatus,
)


@pytest.fixture()
def env():
    tag = f"qtm{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="quiz-total-tests")
    world: dict = {}
    now = datetime.now(timezone.utc)

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}
        tutor = User(
            username=f"{tag}.tutor", slug=f"{tag}-tutor", email=f"{tag}.tutor@t.test",
            hashed_password="x", status=UserStatus.ACTIVE, roles=[roles["TUTOR"]],
        )
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([tutor, course])
        await s.flush()

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=20)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()
        row = BatchSession(
            batch_id=batch.id, tutor_id=tutor.id, session_start_time=now + timedelta(days=1),
            session_end_time=now + timedelta(days=1, hours=1),
            duration_minutes=60, platform=Platforms.Zoom,
        )
        row.attendances = []
        s.add(row)

        def quiz(name: str, total: Decimal | None) -> Quiz:
            return Quiz(
                course_id=course.id, batch_id=batch.id, scope=AssessmentScope.BATCH,
                title=f"{tag} {name}", passing_score=Decimal("50.00"), is_published=False,
                attempts_allowed=5, weight=Decimal("1.00"), total_marks=total,
            )

        capped, uncapped = quiz("capped", Decimal("10.00")), quiz("uncapped", None)
        s.add_all([capped, uncapped])
        await s.flush()
        world.update(capped=capped.public_id, uncapped=uncapped.public_id,
                     tutor=tutor.username)

    run(build)

    def as_tutor(fn):  # noqa: ANN001, ANN202
        async def go(s):  # noqa: ANN001, ANN202
            actor = (await s.execute(
                select(User).where(User.username == world["tutor"])
            )).scalar_one()
            return await fn(QuizService(s), actor)
        return run(go)

    ns = type("Env", (), dict(tag=tag, world=world, run=staticmethod(run),
                              as_tutor=staticmethod(as_tutor)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                for stmt in (
                    "DELETE FROM question_options WHERE question_id IN (SELECT id FROM questions "
                    "WHERE quiz_id IN (SELECT id FROM quizzes WHERE title LIKE :t))",
                    "DELETE FROM questions WHERE quiz_id IN (SELECT id FROM quizzes WHERE title LIKE :t)",
                    "DELETE FROM quizzes WHERE title LIKE :t",
                    "DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batches WHERE batch_code LIKE :c",
                    "DELETE FROM courses WHERE title LIKE :t",
                    "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM users WHERE username LIKE :u",
                ):
                    await s.execute(text(stmt), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _essay(points: str) -> QuestionCreateRequest:
    """An essay: no answer key to satisfy, so the only thing under test is
    the arithmetic."""
    return QuestionCreateRequest(
        question_text="Discuss.", question_type=QuestionType.ESSAY,
        points=Decimal(points), options=[],
    )


def _add(env, quiz_key: str, points: str):  # noqa: ANN202
    return env.as_tutor(
        lambda service, actor: service.add_question(
            env.world[quiz_key], _essay(points), actor=actor
        )
    )


def test_questions_fit_inside_the_paper(env) -> None:
    _add(env, "capped", "6")
    _add(env, "capped", "4")  # exactly 10 of 10 is fine; it is the paper

    with pytest.raises(ValidationError) as refused:
        _add(env, "capped", "1")
    assert "past its total" in str(refused.value)


def test_the_refusal_says_how_much_room_is_left(env) -> None:
    """A limit nobody can see is a limit nobody can work within."""
    _add(env, "capped", "7")
    with pytest.raises(ValidationError) as refused:
        _add(env, "capped", "5")
    details = refused.value.details or {}
    assert details.get("remaining") == "3.00"
    assert details.get("total_marks") == "10.00"


def test_a_quiz_with_no_total_is_unchanged(env) -> None:
    """Every quiz written before this field existed has no total, and must
    keep behaving exactly as it did."""
    for points in ("50", "50", "50"):
        _add(env, "uncapped", points)
    # Nothing raised; the paper is simply worth 150.


def test_lowering_a_question_makes_room_again(env) -> None:
    """The limit has to be recoverable, or a tutor who front-loads the marks
    has to delete the paper and start again."""
    first = _add(env, "capped", "9")
    with pytest.raises(ValidationError):
        _add(env, "capped", "4")

    env.as_tutor(
        lambda service, actor: service.update_question(
            first.public_id, QuestionUpdateRequest(points=Decimal("5")), actor=actor
        )
    )
    _add(env, "capped", "4")  # 5 + 4 fits where 9 + 4 did not


def test_a_question_can_be_edited_on_a_paper_that_is_exactly_full(env) -> None:
    """The check subtracts what the question already contributes.

    Without that, raising a 6 to a 7 on a full paper is measured as 10 + 7 and
    refused -- so the last question written could never be touched again.
    """
    only = _add(env, "capped", "10")
    env.as_tutor(
        lambda service, actor: service.update_question(
            only.public_id, QuestionUpdateRequest(points=Decimal("8")), actor=actor
        )
    )
    with pytest.raises(ValidationError):
        env.as_tutor(
            lambda service, actor: service.update_question(
                only.public_id, QuestionUpdateRequest(points=Decimal("11")), actor=actor
            )
        )
