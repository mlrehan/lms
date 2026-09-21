"""Setting coursework reaches no further than reading it back.

Creating an assignment or a quiz was gated only on holding `assignment.create` / `quiz.create`, never on
teaching the course, while every read of the result is scoped by `ScopeResolver.visible_course_ids`. A tutor
could therefore set coursework on a colleague's course and afterwards get 404 for the very row they made --
having already notified that course's students.

These drive the services against real Postgres with two genuine tutors, because the defect is precisely that
the actor's relationship to the course was never consulted; a fake that returns a fixed scope would assert
nothing about it.
"""

from __future__ import annotations

import asyncio
import selectors
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.core.errors import AuthorizationError
from backend.db.manager import DatabaseManager
from backend.models.course import Course, TutorCourse
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.schemas.assignment import AssignmentCreateRequest
from backend.schemas.quiz import QuizCreateRequest
from backend.services.assignment_service import AssignmentService
from backend.services.quiz_service import QuizService
from backend.utils.enums import CourseStatus, SubmissionType, UserStatus


@pytest.fixture()
def env():
    tag = "cws" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="coursework-scoping-tests")

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        """Two tutors, one course each, each tutor linked only to their own."""
        role = (await s.execute(select(Role).where(Role.name == "TUTOR"))).scalar_one()
        made = {}
        for who in ("mine", "theirs"):
            tutor = User(
                username=f"{tag}.{who}", slug=f"{tag}-{who}", email=f"{tag}.{who}@t.test",
                hashed_password="x", status=UserStatus.ACTIVE, roles=[role],
            )
            course = Course(title=f"{tag} {who} course", code=f"{tag}-{who}", status=CourseStatus.PUBLISHED)
            s.add_all([tutor, course])
            await s.flush()
            s.add(TutorCourse(tutor_id=tutor.id, course_id=course.id))
            made[who] = (tutor, course)
        await s.flush()
        return made

    ns = type("Env", (), dict(tag=tag, run=staticmethod(run), build=staticmethod(build)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                courses = "(SELECT id FROM courses WHERE code LIKE :c)"
                await s.execute(text(f"DELETE FROM quizzes WHERE course_id IN {courses}"), {"c": f"{tag}-%"})
                await s.execute(text(f"DELETE FROM assignments WHERE course_id IN {courses}"), {"c": f"{tag}-%"})
                await s.execute(text(f"DELETE FROM tutor_courses WHERE course_id IN {courses}"), {"c": f"{tag}-%"})
                await s.execute(text("DELETE FROM courses WHERE code LIKE :c"), {"c": f"{tag}-%"})
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), {"u": f"{tag}.%"})
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _assignment(title: str) -> AssignmentCreateRequest:
    return AssignmentCreateRequest(
        title=title,
        due_date=datetime.now(UTC) + timedelta(days=7),
        max_score=100,
        submission_type=SubmissionType.TEXT,
    )


def _quiz(title: str) -> QuizCreateRequest:
    return QuizCreateRequest(title=title, passing_score=50)


# ------------------------------------------------------------------ assignments


def test_a_tutor_may_set_an_assignment_on_a_course_they_teach(env) -> None:
    """The positive case, so the refusals below cannot be passing vacuously."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            tutor, course = made["mine"]
            return await AssignmentService(s).create(course.public_id, _assignment("Week 1"), actor=tutor)
        return go()

    row = env.run(f)
    assert row.title == "Week 1"


def test_a_tutor_cannot_set_an_assignment_on_a_course_they_do_not_teach(env) -> None:
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            tutor, _ = made["mine"]
            _, foreign = made["theirs"]
            with pytest.raises(AuthorizationError):
                await AssignmentService(s).create(foreign.public_id, _assignment("Planted"), actor=tutor)
            # ...and nothing was written, so the colleague's course is untouched.
            return (await s.execute(
                text("SELECT count(*) FROM assignments WHERE course_id = :c"), {"c": foreign.id}
            )).scalar_one()
        return go()

    assert env.run(f) == 0


# ----------------------------------------------------------------------- quizzes


def test_a_tutor_may_set_a_quiz_on_a_course_they_teach(env) -> None:
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            tutor, course = made["mine"]
            return await QuizService(s).create(course.public_id, _quiz("Checkpoint"), actor=tutor)
        return go()

    assert env.run(f).title == "Checkpoint"


def test_a_tutor_cannot_set_a_quiz_on_a_course_they_do_not_teach(env) -> None:
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            tutor, _ = made["mine"]
            _, foreign = made["theirs"]
            with pytest.raises(AuthorizationError):
                await QuizService(s).create(foreign.public_id, _quiz("Planted"), actor=tutor)
            return (await s.execute(
                text("SELECT count(*) FROM quizzes WHERE course_id = :c"), {"c": foreign.id}
            )).scalar_one()
        return go()

    assert env.run(f) == 0


# -------------------------------------------------------------------- the admin

def test_an_unrestricted_actor_is_not_caught_by_the_new_check(env) -> None:
    """A Super Admin teaches nothing, so a scope check that ignored `is_unrestricted` would lock
    administrators out of setting coursework anywhere -- the obvious way to get this fix wrong."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            _, course = made["theirs"]
            admin = (await s.execute(select(User).where(User.username == "superadmin"))).scalar_one()
            return await AssignmentService(s).create(course.public_id, _assignment("From admin"), actor=admin)
        return go()

    assert env.run(f).title == "From admin"
