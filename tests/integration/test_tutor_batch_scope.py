"""A tutor reaches the cohorts they teach, and no others (QA brief §4.2, §4.7, §4.8).

**Tutors are set per session of a batch.** `batch_sessions.tutor_id` is the
only route; being tutor of record for the course grants nothing here.

That used to be a union, and the second half of it was the leak. Measured
against real data, one tutor reached five cohorts taught entirely by a
colleague -- and with them those students, their enrollments, their
attendance and their grades -- while taking no session in any of them. Being
tutor of record is an authoring relationship with the *course*; teaching is a
relationship with a *cohort*, and only the second is a reason to see who is
in it.

`_taught_batch_ids` is the single definition behind batch, session,
enrollment, grade-book, dashboard and mail-audience scope, so these tests
check the consequences as well as the rule -- a narrowing that stopped at the
batch list would leave the students reachable one endpoint over.
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
from backend.security.password import hash_password
from backend.utils.enums import (
    CourseStatus,
    EnrollmentStatus,
    Platforms,
    UserStatus,
)

PASSWORD = "BatchScope!2026"


@pytest.fixture()
def world():
    tag = f"tbs{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="tutor-batch-scope-tests")
    people: dict[str, dict] = {}
    ids: dict[str, str] = {}
    tokens: dict[str, str] = {}

    async def build() -> None:
        async with db.session_factory.begin() as s:
            roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

            def person(key: str, role: str) -> User:
                email = f"{tag}.{key}@t.test"
                u = User(
                    username=email, slug=f"{tag}-{key}", email=email,
                    first_name=key.title(), last_name=tag,
                    hashed_password=hash_password(PASSWORD),
                    status=UserStatus.ACTIVE, can_login=True, roles=[roles[role]],
                )
                people[key] = {"email": email}
                return u

            lead = person("lead", "TUTOR")          # tutor of record for the course
            teacher = person("teacher", "TUTOR")    # takes the sessions
            mine_student = person("minestudent", "STUDENT")
            their_student = person("theirstudent", "STUDENT")
            # The only role that may still read commercial terms, so the
            # withholding below is proved rather than assumed.
            boss = person("boss", "SUPER_ADMIN")

            course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
            course.batches, course.resources, course.tags, course.tutors = [], [], [], []
            # `lead` is tutor of record for the whole course. That is the
            # grant this test exists to prove is *not* enough.
            course.tutors = [lead]
            s.add_all([lead, teacher, mine_student, their_student, boss, course])
            await s.flush()

            batches = {}
            for key, tutor, student in (("taught", teacher, mine_student),
                                        ("other", lead, their_student)):
                b = Batch(batch_code=f"{tag}-{key[:4]}", course_id=course.id,
                          start_date=date.today(), end_date=date.today() + timedelta(days=30),
                          is_active=True, capacity=10, batch_fee=Decimal("499.00"))
                b.sessions, b.enrollments, b.student_reviews = [], [], []
                s.add(b)
                await s.flush()
                # Inserted out of order on purpose: a list that happens to
                # come back sorted because that is how the rows were written
                # proves nothing about the ORDER BY.
                for days in (9, 2, 5):
                    sess = BatchSession(
                        batch_id=b.id, tutor_id=tutor.id,
                        session_start_time=datetime.now(timezone.utc) + timedelta(days=days),
                        session_end_time=datetime.now(timezone.utc) + timedelta(days=days, hours=1),
                        duration_minutes=60, platform=Platforms.Zoom,
                    )
                    sess.attendances = []
                    s.add(sess)
                s.add(Enrollments(batch_id=b.id, student_id=student.id,
                                  enrollment_date=datetime.now(timezone.utc),
                                  status=EnrollmentStatus.CONFIRMED))
                batches[key] = b
            await s.flush()
            ids["taught"] = str(batches["taught"].public_id)
            ids["other"] = str(batches["other"].public_id)
            ids["taught_code"] = batches["taught"].batch_code
            ids["other_code"] = batches["other"].batch_code

    loop.run_until_complete(build())
    lifespan = app.router.lifespan_context(app)
    loop.run_until_complete(lifespan.__aenter__())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")

    def get(who: str, path: str, **params):  # noqa: ANN202
        async def go():  # noqa: ANN202
            if who not in tokens:
                r = await client.post("/api/v1/auth/login",
                                      json={"identifier": people[who]["email"], "password": PASSWORD})
                assert r.status_code == 200, r.status_code
                tokens[who] = r.json()["access_token"]
            return await client.get(f"/api/v1{path}", params=params,
                                    headers={"Authorization": f"Bearer {tokens[who]}"})
        return loop.run_until_complete(go())

    ns = type("W", (), dict(tag=tag, ids=ids, people=people, get=staticmethod(get)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                for stmt in (
                    "DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batches WHERE batch_code LIKE :c",
                    "DELETE FROM tutor_courses WHERE course_id IN (SELECT id FROM courses WHERE title LIKE :t)",
                    "DELETE FROM courses WHERE title LIKE :t",
                    "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM users WHERE username LIKE :u",
                ):
                    await s.execute(text(stmt), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(lifespan.__aexit__(None, None, None))
        loop.run_until_complete(client.aclose())
        loop.run_until_complete(db.dispose())
        loop.close()


def _codes(response) -> set[str]:  # noqa: ANN001
    return {b["batch_code"] for b in response.json()["items"]}


def test_a_tutor_sees_the_batch_they_take_sessions_for(world) -> None:
    codes = _codes(world.get("teacher", "/batches", limit=100))

    assert world.ids["taught_code"] in codes
    # Same course, a colleague's cohort. The positive above matters: an empty
    # list would satisfy the negative while proving the feature broken.
    assert world.ids["other_code"] not in codes


def test_being_tutor_of_record_does_not_hand_over_a_colleagues_cohort(world) -> None:
    """The leak this narrowing closed.

    `lead` owns the course and takes one session, in the *other* batch. The
    batch `teacher` runs is not theirs to see.
    """
    codes = _codes(world.get("lead", "/batches", limit=100))

    assert world.ids["other_code"] in codes
    assert world.ids["taught_code"] not in codes


def test_the_colleagues_batch_is_not_reachable_by_id(world) -> None:
    # 404, not 403: scoping the list while the detail route answers would be
    # theatre, and a 403 would confirm the batch exists.
    assert world.get("teacher", f"/batches/{world.ids['other']}").status_code == 404
    assert world.get("teacher", f"/batches/{world.ids['taught']}").status_code == 200


def test_the_students_do_not_leak_through_the_enrollment_list(world) -> None:
    """`_taught_batch_ids` feeds enrollment scope too, so this must follow.

    A narrowing that stopped at the batch list would leave the colleague's
    students reachable one endpoint over -- which is how "their batch is
    hidden" and "their cohort is private" come apart.
    """
    rows = world.get("teacher", "/enrollments", limit=100).json()["items"]
    names = {r.get("student") or r.get("student_name") or "" for r in rows}

    assert not any(world.tag in n and "theirstudent" in n.lower() for n in names)
    assert len(rows) == 1


def test_the_tutors_own_students_are_still_visible(world) -> None:
    # The narrowing must not cost a tutor sight of their own cohort.
    rows = world.get("teacher", "/enrollments", limit=100).json()["items"]
    assert len(rows) == 1


def test_the_batch_fee_is_the_super_admins_alone(world) -> None:
    """The batch list was publishing the fee to every role that could open it.

    Withheld on the server, not by leaving a column out of the table: a column
    the client declines to draw is still in the payload, and this is the screen
    the price was actually leaking from.
    """
    def fees(who: str) -> set[object]:
        rows = world.get(who, "/batches", limit=100).json()["items"]
        return {r["batch_fee"] for r in rows if r["batch_code"].startswith(world.tag)}

    # `None`, not `0`: a free batch and a withheld fee are different facts.
    assert fees("teacher") == {None}
    assert fees("minestudent") == {None}
    assert fees("boss") == {499.0}


def test_the_timetable_reads_forwards(world) -> None:
    """Soonest first.

    It was ordered newest-first, which put the furthest-out class at the top
    and a tutor's next lesson wherever the page size happened to leave it. A
    timetable is read forwards.
    """
    rows = world.get("teacher", "/sessions", limit=100).json()["items"]
    starts = [r["session_start_time"] for r in rows]
    assert starts == sorted(starts)
    assert len(starts) >= 3  # not vacuously true of a one-row list
