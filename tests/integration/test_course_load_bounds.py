"""The course list and detail load what their responses read, and no more.

Every relationship on `Course` is `lazy="selectin"`, and so is almost every
relationship behind them, so one course used to drag in its batches ->
sessions -> enrolments -> users and its resources -> versions -> shares. A
catalogue page of twenty scalar rows materialised over a thousand ORM objects
and took ~140 ms of CPU; one course detail ~600 ms. `COURSE_LIST_LOAD` and
`COURSE_DETAIL_LOAD` in `repositories/course.py` bound that graph.

Two kinds of test, both over real HTTP against real Postgres:

* **Shape.** The exact response, field for field, so bounding the graph can
  never quietly drop something the mapper used to read. The fixture gives the
  course every relationship the detail mapper touches -- category,
  department, tags, a tutor, several batches -- because a course without tags
  would pass with tags never loaded.
* **Cost.** A query-count ceiling, with enough batches, sessions and
  enrolments behind the courses that the old cascade would blow through it.
  A count rather than a clock: latency on one laptop is not an assertion, and
  the count is exactly what regressed.
"""

from __future__ import annotations

import asyncio
import random
import selectors
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import event, select, text
from sqlalchemy.engine import Engine

from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.main import app
from backend.models.administration import Category, CourseTag, Department, Tag
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.security.password import hash_password
from backend.utils.enums import CourseStatus, EnrollmentStatus, Platforms, UserStatus

PASSWORD = "LoadBounds!2026"
COURSES, BATCHES, SESSIONS, STUDENTS = 3, 3, 4, 3


@pytest.fixture()
def world():
    tag = f"clb{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="course-load-tests")
    ids: dict[str, object] = {}
    tokens: dict[str, str] = {}
    emails: dict[str, str] = {}

    async def build() -> None:
        async with db.session_factory.begin() as s:
            roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

            def person(key: str, role: str, first: str) -> User:
                email = f"{tag}.{key}@t.test"
                emails[key] = email
                return User(
                    username=email, slug=f"{tag}-{key}", email=email,
                    first_name=first, last_name=tag,
                    hashed_password=hash_password(PASSWORD),
                    status=UserStatus.ACTIVE, can_login=True, roles=[roles[role]],
                )

            boss = person("boss", "SUPER_ADMIN", "Boss")
            tutor = person("tutor", "TUTOR", "Tess")
            students = [person(f"s{n}", "STUDENT", f"Stu{n}") for n in range(STUDENTS)]
            category = Category(name=f"{tag} Category")
            department = Department(name=f"{tag} Department")
            tags = [Tag(name=f"{tag}-zeta"), Tag(name=f"{tag}-alpha")]
            s.add_all([boss, tutor, *students, category, department, *tags])
            await s.flush()

            for c in range(COURSES):
                course = Course(
                    title=f"{tag} Course {c}", code=f"{tag}{c}", status=CourseStatus.PUBLISHED,
                    price=100.0 + c, description="d", prerequisites="p",
                    course_link="https://example.com/c", category_id=category.id,
                    department_id=department.id, duration_hours=10,
                    course_image="https://example.com/big.png",
                )
                course.batches, course.resources, course.tags, course.tutors = [], [], [], []
                course.tutors = [tutor]
                s.add(course)
                await s.flush()
                s.add_all([CourseTag(course_id=course.id, tag_id=t.id) for t in tags])
                ids[f"course{c}"] = course.public_id
                for b in range(BATCHES):
                    batch = Batch(
                        batch_code=f"{tag}-{c}{b}", course_id=course.id, is_active=b != 1,
                        start_date=date(2026, 1 + b, 1), end_date=date(2026, 2 + b, 1),
                        capacity=20 + b,
                    )
                    batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
                    s.add(batch)
                    await s.flush()
                    for n in range(SESSIONS):
                        start = datetime(2026, 1 + b, 2 + n, 9, tzinfo=timezone.utc)
                        sess = BatchSession(
                            batch_id=batch.id, tutor_id=tutor.id, session_start_time=start,
                            session_end_time=start + timedelta(hours=1), duration_minutes=60,
                            platform=Platforms.Zoom,
                        )
                        sess.attendances = []
                        s.add(sess)
                    for st in students:
                        s.add(Enrollments(batch_id=batch.id, student_id=st.id,
                                          status=EnrollmentStatus.CONFIRMED))
            ids["category"], ids["department"] = category.public_id, department.public_id

    loop.run_until_complete(build())
    lifespan = app.router.lifespan_context(app)
    loop.run_until_complete(lifespan.__aenter__())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")

    def get(who: str, path: str, *, count: dict | None = None, **params):  # noqa: ANN202
        async def go():  # noqa: ANN202
            if who not in tokens:
                r = await client.post(
                    "/api/v1/auth/login", json={"identifier": emails[who], "password": PASSWORD}
                )
                assert r.status_code == 200, r.status_code
                tokens[who] = r.json()["access_token"]

            def counter(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
                count["n"] += 1  # type: ignore[index]

            if count is not None:
                event.listen(Engine, "before_cursor_execute", counter)
            try:
                return await client.get(
                    f"/api/v1{path}", params=params,
                    headers={"Authorization": f"Bearer {tokens[who]}"},
                )
            finally:
                if count is not None:
                    event.remove(Engine, "before_cursor_execute", counter)
        return loop.run_until_complete(go())

    ns = type("W", (), dict(tag=tag, ids=ids, emails=emails, get=staticmethod(get)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                for stmt in (
                    "DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batches WHERE batch_code LIKE :c",
                    "DELETE FROM tutor_courses WHERE course_id IN (SELECT id FROM courses WHERE title LIKE :t)",
                    "DELETE FROM course_tags WHERE course_id IN (SELECT id FROM courses WHERE title LIKE :t)",
                    "DELETE FROM courses WHERE title LIKE :t",
                    "DELETE FROM tags WHERE name LIKE :t",
                    "DELETE FROM categories WHERE name LIKE :t",
                    "DELETE FROM departments WHERE name LIKE :t",
                    "DELETE FROM notifications WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM tokens WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM users WHERE username LIKE :u",
                ):
                    await s.execute(text(stmt), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(lifespan.__aexit__(None, None, None))
        loop.run_until_complete(client.aclose())
        loop.run_until_complete(db.dispose())
        loop.close()


# -- shape ---------------------------------------------------------------------


def test_the_catalogue_row_is_unchanged(world) -> None:
    r = world.get("boss", "/courses", query=world.tag, limit=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == COURSES
    first = body["items"][0]
    assert first == {
        "public_id": str(world.ids["course0"]),
        "title": f"{world.tag} Course 0",
        "code": f"{world.tag}0",
        "status": "PUBLISHED",
        "level": "BEGINNER",
        "duration_hours": 10,
        "price": 100.0,
        "course_image": "https://example.com/big.png",
        "small_course_image": None,
    }


def test_the_course_detail_is_unchanged(world) -> None:
    r = world.get("boss", f"/courses/{world.ids['course0']}")
    assert r.status_code == 200, r.text
    body = r.json()
    batches = body.pop("batches")
    created_at = body.pop("created_at")
    assert created_at
    assert body == {
        "public_id": str(world.ids["course0"]),
        "title": f"{world.tag} Course 0",
        "code": f"{world.tag}0",
        "status": "PUBLISHED",
        "level": "BEGINNER",
        "duration_hours": 10,
        "price": 100.0,
        "course_image": "https://example.com/big.png",
        "small_course_image": None,
        "description": "d",
        "prerequisites": "p",
        "course_link": "https://example.com/c",
        "category_id": str(world.ids["category"]),
        "category_name": f"{world.tag} Category",
        "department_id": str(world.ids["department"]),
        "department_name": f"{world.tag} Department",
        # Sorted by name, which is not the order they were attached in.
        "tags": [f"{world.tag}-alpha", f"{world.tag}-zeta"],
        "updated_at": None,
        # A Super Admin may see login names, which here are the address.
        "tutors": [world.emails["tutor"]],
        "batch_count": BATCHES,
    }
    # Newest start first, every field of the brief, and the cached counter as
    # stored (0 here: the fixture inserts enrolments without bumping it).
    assert batches == [
        {
            "public_id": batches[i]["public_id"],
            "batch_code": f"{world.tag}-0{b}",
            "is_active": b != 1,
            "start_date": f"2026-0{1 + b}-01",
            "end_date": f"2026-0{2 + b}-01",
            "capacity": 20 + b,
            "total_enrollments": 0,
        }
        for i, b in enumerate(reversed(range(BATCHES)))
    ]


# -- cost ----------------------------------------------------------------------

# Measured against this fixture as a Super Admin, including the per-request
# identity lookup: 6 queries for the list and 10 for the detail with the
# bounded graph, 24 and 23 with the model defaults restored. Against real data
# the gap is far wider (list: 35 queries and 1,137 ORM objects -> 3 and 20;
# detail: 89 and 2,133 -> 6 and 11), because the cascade reaches users'
# cities, organisations and resources that this fixture does not have. The
# ceilings sit between the two, so restoring the cascade fails both.
LIST_CEILING = 12
DETAIL_CEILING = 15


def test_the_catalogue_costs_a_bounded_number_of_queries(world) -> None:
    world.get("boss", "/courses", limit=1)  # sign in outside the count
    counted = {"n": 0}
    r = world.get("boss", "/courses", count=counted, query=world.tag, limit=20)
    assert r.status_code == 200
    assert len(r.json()["items"]) == COURSES
    assert counted["n"] <= LIST_CEILING, counted["n"]


def test_a_course_detail_costs_a_bounded_number_of_queries(world) -> None:
    world.get("boss", "/courses", limit=1)
    counted = {"n": 0}
    r = world.get("boss", f"/courses/{world.ids['course0']}", count=counted)
    assert r.status_code == 200
    assert len(r.json()["batches"]) == BATCHES
    assert counted["n"] <= DETAIL_CEILING, counted["n"]


def test_a_tutor_and_a_student_read_the_detail_through_the_same_bounds(world) -> None:
    """`tutors_visible_to` takes a different path for a restricted viewer --
    a query for the tutors of batches the viewer is enrolled in -- so the
    bounded `tutors` collection has to serve it too."""
    # A tutor sees their own login name; a student sees the tutor by full
    # name, reached through the enrolment query rather than the assignment.
    expected = {"tutor": world.emails["tutor"], "s0": f"Tess {world.tag}"}
    for who, name in expected.items():
        r = world.get(who, f"/courses/{world.ids['course0']}")
        assert r.status_code == 200, (who, r.text)
        assert r.json()["tutors"] == [name], who
