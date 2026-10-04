"""A tutor reaches their own courses, and no price -- over real HTTP.

Two rules, both expressed as permissions rather than role checks, because
four roles hold `course.read` and only one of them is being narrowed:

* **`course.view_all`** -- browse the whole catalogue. Students, guardians and
  corporate managers hold it (a manager who cannot browse cannot find a
  course to enrol employees into, which is why the catalogue was open in the
  first place). A tutor does not, so they reach the courses assigned to them.
* **`course.view_pricing`** -- see commercial terms. Same holders. Teaching a
  course and pricing it are different jobs.

Driven through the app rather than the service, because the price gate is a
field serialiser reading a request-scoped viewer: a unit test of
`visible_price` would pass with the viewer never set, which is the one thing
that would make it useless in production.

**Every test pairs the tutor with somebody else.** Asserting only that the
tutor sees six courses would pass just as well against a catalogue that had
broken for everyone.
"""

from __future__ import annotations

import asyncio
import random
import selectors
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.security.password import hash_password
from backend.db.manager import DatabaseManager
from backend.main import app
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.utils.enums import CourseStatus, Platforms, UserStatus

PASSWORD = "ScopeProbe!2026"


@pytest.fixture()
def world():
    tag = f"csp{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="course-scope-tests")
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

            u = {
                "tutor": person("tutor", "TUTOR"),
                "student": person("student", "STUDENT"),
                "manager": person("manager", "CORPORATE_MANAGER"),
            }

            # One course the tutor teaches, one they do not. Both published,
            # so status visibility cannot be what separates them -- only the
            # assignment can.
            mine = Course(title=f"{tag} Mine", code=f"{tag}m", status=CourseStatus.PUBLISHED,
                          price=250.00)
            theirs = Course(title=f"{tag} Theirs", code=f"{tag}t", status=CourseStatus.PUBLISHED,
                            price=410.00)
            # A course the tutor is *not* tutor-of-record for, but takes a
            # session of one of its batches -- how a stand-in or second tutor
            # is attached. Teaching it must count.
            standin = Course(title=f"{tag} Standin", code=f"{tag}s", status=CourseStatus.PUBLISHED,
                             price=99.00)
            for c in (mine, theirs, standin):
                c.batches, c.resources, c.tags, c.tutors = [], [], [], []
            mine.tutors = [u["tutor"]]
            s.add_all([*u.values(), mine, theirs, standin])
            await s.flush()

            batch = Batch(batch_code=f"{tag}-A", course_id=mine.id, start_date=date.today(),
                          end_date=date.today() + timedelta(days=30), is_active=True, capacity=10)
            batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
            s.add(batch)
            await s.flush()
            sess = BatchSession(
                batch_id=batch.id, tutor_id=u["tutor"].id,
                session_start_time=datetime.now(timezone.utc) + timedelta(days=1),
                session_end_time=datetime.now(timezone.utc) + timedelta(days=1, hours=1),
                duration_minutes=60, platform=Platforms.Zoom,
            )
            sess.attendances = []
            s.add(sess)

            stand_batch = Batch(batch_code=f"{tag}-S", course_id=standin.id,
                                start_date=date.today(),
                                end_date=date.today() + timedelta(days=30),
                                is_active=True, capacity=10)
            stand_batch.sessions, stand_batch.enrollments, stand_batch.student_reviews = [], [], []
            s.add(stand_batch)
            await s.flush()
            stand_sess = BatchSession(
                batch_id=stand_batch.id, tutor_id=u["tutor"].id,
                session_start_time=datetime.now(timezone.utc) + timedelta(days=2),
                session_end_time=datetime.now(timezone.utc) + timedelta(days=2, hours=1),
                duration_minutes=60, platform=Platforms.Zoom,
            )
            stand_sess.attendances = []
            s.add(stand_sess)

            ids["mine"], ids["theirs"] = str(mine.public_id), str(theirs.public_id)
            ids["standin"] = str(standin.public_id)

    loop.run_until_complete(build())
    lifespan = app.router.lifespan_context(app)
    loop.run_until_complete(lifespan.__aenter__())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")

    def get(who: str, path: str, **params):  # noqa: ANN202
        async def go():  # noqa: ANN202
            if who not in tokens:
                r = await client.post(
                    "/api/v1/auth/login",
                    json={"identifier": people[who]["email"], "password": PASSWORD},
                )
                assert r.status_code == 200, r.status_code
                tokens[who] = r.json()["access_token"]
            return await client.get(
                f"/api/v1{path}", params=params,
                headers={"Authorization": f"Bearer {tokens[who]}"},
            )
        return loop.run_until_complete(go())

    ns = type("W", (), dict(tag=tag, ids=ids, get=staticmethod(get)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                for stmt in (
                    "DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
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


def _titles(response) -> set[str]:  # noqa: ANN001
    return {c["title"] for c in response.json()["items"]}


def test_a_tutor_lists_only_the_courses_assigned_to_them(world) -> None:
    titles = _titles(world.get("tutor", "/courses", limit=100))

    assert f"{world.tag} Mine" in titles
    # Published, and still not theirs. Before this, `course.read` alone listed
    # every course in the institution.
    assert f"{world.tag} Theirs" not in titles


def test_everyone_else_still_browses_the_catalogue(world) -> None:
    for who in ("student", "manager"):
        titles = _titles(world.get(who, "/courses", limit=100))
        # The manager case is the reason the catalogue is open at all: they
        # cannot enrol an employee into a course they cannot find.
        assert f"{world.tag} Theirs" in titles, who
        assert f"{world.tag} Mine" in titles, who


def test_scoping_the_list_alone_would_be_theatre(world) -> None:
    """The hidden course is one guessable id away, so the detail route is gated too."""
    assert world.get("tutor", f"/courses/{world.ids['theirs']}").status_code == 404
    # 404 rather than 403: a course a tutor may not reach should not be
    # provable to exist by the shape of the refusal.
    assert world.get("manager", f"/courses/{world.ids['theirs']}").status_code == 200


def test_a_tutor_still_opens_their_own_course(world) -> None:
    response = world.get("tutor", f"/courses/{world.ids['mine']}")

    assert response.status_code == 200
    assert response.json()["title"] == f"{world.tag} Mine"


def test_a_tutor_sees_no_price_even_on_their_own_course(world) -> None:
    body = world.get("tutor", f"/courses/{world.ids['mine']}").json()

    # `None`, not `0`: a free course and a withheld price are different facts.
    assert body["price"] is None


def test_the_price_still_reaches_those_entitled_to_it(world) -> None:
    for who in ("student", "manager"):
        body = world.get(who, f"/courses/{world.ids['mine']}").json()
        assert body["price"] == 250.0, who

    listed = {c["title"]: c["price"] for c in world.get("manager", "/courses", limit=100).json()["items"]}
    assert listed[f"{world.tag} Theirs"] == 410.0


def test_the_price_is_withheld_in_the_listing_too(world) -> None:
    listed = {c["title"]: c["price"] for c in world.get("tutor", "/courses", limit=100).json()["items"]}

    # The listing is built with `model_validate` straight off the ORM row, so
    # a mapper-level gate would have missed it entirely.
    assert listed[f"{world.tag} Mine"] is None


def test_teaching_a_batch_counts_as_teaching_its_course(world) -> None:
    """The regression the first version of this scope introduced.

    Restricted to `tutor_courses` alone, a tutor taking sessions for a batch
    could see the batch, its students and the timetable -- and not the course
    they belong to. They could not have set an assignment for a class they
    teach every week, and nothing in the console would have said why.
    """
    titles = _titles(world.get("tutor", "/courses", limit=100))
    assert f"{world.tag} Standin" in titles

    # Reachable by id as well, since the detail route gates on the same rule.
    assert world.get("tutor", f"/courses/{world.ids['standin']}").status_code == 200
    # Still no price: teaching a course is not a reason to see what it sells for.
    assert world.get("tutor", f"/courses/{world.ids['standin']}").json()["price"] is None
