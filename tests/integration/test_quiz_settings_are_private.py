"""How a paper is run is the author's business, not the candidate's.

`GET /quizzes/{id}` returned the whole configuration to anybody who could
read the quiz -- every student set it included. The console drew a Settings
tab for them with the inputs disabled, which is the giveaway: the fields were
in the payload and only the styling was withholding them.

Knowing them is an advantage, not a curiosity. "Answers are shown
immediately" and "ten questions drawn from a bank of forty" both change how a
quiz is best attempted, and "shuffled" tells a candidate whether comparing
notes with the person beside them is worth anything.

What a candidate legitimately needs is unchanged and checked here too, because
a test that only proves fields are missing would pass with the endpoint
returning nothing at all.
"""

from __future__ import annotations

import asyncio
import random
import selectors
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.main import app
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.quiz import Quiz
from backend.security.password import hash_password
from backend.utils.enums import (
    AssessmentScope,
    CourseStatus,
    EnrollmentStatus,
    Platforms,
    UserStatus,
)

PASSWORD = "QuizPrivacy!2026"

#: The author's working notes. None of these may reach a candidate.
CONFIGURATION = (
    "shuffle_questions",
    "shuffle_answers",
    "questions_per_attempt",
    "show_result_immediately",
    "show_correct_answers",
    "show_explanations",
    "auto_submit_on_expiry",
    "is_auto_graded",
    "grading_policy",
    "weight",
)

#: What a candidate is entitled to: what the paper is, how long they have,
#: how many goes, what it is out of, when it opens.
CANDIDATE_FACTS = (
    "title",
    "duration_minutes",
    "attempts_allowed",
    "passing_score",
    "total_points",
    "question_count",
    "my_attempts_used",
    # `available_from` is deliberately absent: it is legitimately null on a
    # quiz with no opening date, so asserting it is not null would be testing
    # the fixture rather than the withholding.
)


@pytest.fixture()
def env():
    tag = f"qp{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="quiz-privacy-tests")
    ids: dict[str, object] = {}
    now = datetime.now(timezone.utc)

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def person(key: str, role: str) -> User:
            email = f"{tag}.{key}@t.test"
            return User(
                username=email, slug=f"{tag}-{key}", email=email,
                first_name=key.title(), last_name=tag,
                hashed_password=hash_password(PASSWORD), can_login=True,
                status=UserStatus.ACTIVE, roles=[roles[role]],
            )

        tutor, student = person("tutor", "TUTOR"), person("student", "STUDENT")
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([tutor, student, course])
        await s.flush()

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=10)
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
        s.add(Enrollments(batch_id=batch.id, student_id=student.id,
                          enrollment_date=now, status=EnrollmentStatus.CONFIRMED))

        quiz = Quiz(
            course_id=course.id, batch_id=batch.id, scope=AssessmentScope.BATCH,
            title=f"{tag} Paper", passing_score=Decimal("50.00"), is_published=True,
            attempts_allowed=3, weight=Decimal("1.00"), duration_minutes=30,
            # Every one of these is deliberately the *interesting* value, so a
            # leak shows up as a real answer rather than as a default.
            shuffle_questions=True, shuffle_answers=True, questions_per_attempt=10,
            show_result_immediately=False, show_correct_answers=True,
            show_explanations=True, auto_submit_on_expiry=False,
            # Set so the author's half is not vacuously satisfied by a column
            # that happens to be null for every quiz in the fixture.
            grading_policy={"negative_marking": 0.25},
        )
        s.add(quiz)
        await s.flush()
        ids["quiz"] = quiz.public_id
        ids["batch"] = batch.public_id
        ids["student"] = student.public_id

    run(build)

    lifespan = app.router.lifespan_context(app)
    loop.run_until_complete(lifespan.__aenter__())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")
    tokens: dict[str, str] = {}

    def call(who: str, method: str, path: str, **kwargs):  # noqa: ANN202
        async def go():  # noqa: ANN202
            if who not in tokens:
                signed_in = await client.post(
                    "/api/v1/auth/login",
                    json={"identifier": f"{tag}.{who}@t.test", "password": PASSWORD},
                )
                assert signed_in.status_code == 200, signed_in.text[:200]
                tokens[who] = signed_in.json()["access_token"]
            return await client.request(
                method, f"/api/v1{path}",
                headers={"Authorization": f"Bearer {tokens[who]}"}, **kwargs,
            )
        return loop.run_until_complete(go())

    ns = type("Env", (), dict(tag=tag, ids=ids, call=staticmethod(call)))
    try:
        yield ns
    finally:
        loop.run_until_complete(client.aclose())
        loop.run_until_complete(lifespan.__aexit__(None, None, None))

        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                users = "(SELECT id FROM users WHERE username LIKE :u)"
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                for stmt in (
                    # Publishing the schedule notifies the cohort, and a
                    # notification row holds the user it names.
                    f"DELETE FROM notifications WHERE user_id IN {users}",
                    "DELETE FROM exam_results WHERE exam_id IN (SELECT id FROM exams WHERE title LIKE :t)",
                    "DELETE FROM exams WHERE title LIKE :t",
                    "DELETE FROM quizzes WHERE title LIKE :t",
                    "DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batches WHERE batch_code LIKE :c",
                    "DELETE FROM courses WHERE title LIKE :t",
                    f"DELETE FROM user_roles WHERE user_id IN {users}",
                    "DELETE FROM users WHERE username LIKE :u",
                ):
                    await s.execute(text(stmt), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _quiz(env, who: str) -> dict:
    response = env.call(who, "GET", f"/quizzes/{env.ids['quiz']}")
    assert response.status_code == 200, response.text[:300]
    return response.json()


@pytest.mark.parametrize("field", CONFIGURATION)
def test_a_candidate_is_told_nothing_about_how_the_paper_is_run(env, field: str) -> None:
    """`None`, not the value. Absent would be better still, but the field is
    part of a response shape older clients already read, and a missing key
    crashes a strict one -- the same lesson the platform dashboard learned
    from `=== null`."""
    assert _quiz(env, "student")[field] is None, field


@pytest.mark.parametrize("field", CANDIDATE_FACTS)
def test_what_a_candidate_does_need_is_still_there(env, field: str) -> None:
    """Without this the test above would pass with the endpoint broken."""
    assert _quiz(env, "student")[field] is not None, field


@pytest.mark.parametrize("field", CONFIGURATION)
def test_the_author_still_sees_their_own_settings(env, field: str) -> None:
    """A tutor cannot edit what they cannot read -- and the settings screen
    is built entirely from these."""
    assert _quiz(env, "tutor")[field] is not None, field


def test_the_interesting_values_really_are_interesting(env) -> None:
    """The fixture sets each flag away from its default on purpose: a leak of
    `shuffle_questions=False` would otherwise be indistinguishable from the
    field being withheld."""
    author = _quiz(env, "tutor")
    assert author["shuffle_questions"] is True
    assert author["show_result_immediately"] is False
    assert author["questions_per_attempt"] == 10


# -- the same rule, on an examination ---------------------------------------


def test_a_candidate_is_not_told_how_the_cohort_is_marked(env) -> None:
    """"28 of 30 published" tells a student whose mark is missing that theirs
    is one of the two being withheld -- which is precisely what the release
    step exists to avoid saying."""
    from backend.utils.enums import ExamType  # local: only this test needs it

    created = env.call("tutor", "POST", "/exams", json={
        "title": f"{env.tag} Paper Exam",
        "batch_id": str(env.ids["batch"]),
        "exam_type": ExamType.MOCK.value,
        "scheduled_at": "2026-11-01T10:00:00Z",
        "duration_minutes": 60,
        "total_marks": 100,
        "passing_marks": 40,
    })
    assert created.status_code == 201, created.text[:300]
    exam_id = created.json()["public_id"]
    assert env.call("tutor", "PUT", f"/exams/{exam_id}/publish",
                    json={"is_published": True}).status_code == 200

    # Record and release a mark, or both counts are zero for everybody and
    # the assertions below are satisfied by an empty exam rather than by the
    # withholding.
    assert env.call("tutor", "PUT", f"/exams/{exam_id}/results", json={
        "entries": [{"student_id": str(env.ids["student"]), "marks_obtained": 61}]
    }).status_code == 200

    student = env.call("student", "GET", f"/exams/{exam_id}").json()
    assert student["result_count"] == 0
    assert student["published_result_count"] == 0
    # What a candidate sits the paper knowing is untouched.
    assert student["total_marks"] is not None
    assert student["passing_marks"] is not None
    assert student["scheduled_at"] is not None

    tutor = env.call("tutor", "GET", f"/exams/{exam_id}").json()
    assert tutor["result_count"] == 1  # the one just recorded, and theirs to see
