"""Other people's email addresses, phone numbers and login names stay hidden -- over real HTTP.

The rule (`core/privacy.py`): only a holder of `user.view_contact` (the Super Admin) sees them; everybody else
sees names, and being related to someone changes nothing. These tests drive the whole app in-process with real
logins, so they prove the request-scoped viewer actually reaches the response mappers -- a unit test of the
helper could not.

The test users' login names are deliberately email-shaped, as 54 of the real 77 are, because hiding an `email`
field while returning the `username` would leak exactly what is being protected.
"""

from __future__ import annotations

import asyncio
import random
import selectors
import uuid
from datetime import date, datetime, timedelta, timezone

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
from backend.utils.enums import CourseStatus, EnrollmentStatus, Platforms, UserStatus

PASSWORD = "Priv!Test2026xx"


@pytest.fixture()
def world():
    tag = f"prv{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="privacy-tests")
    ids: dict[str, str] = {}
    people: dict[str, dict] = {}
    tokens: dict[str, str] = {}

    async def build() -> None:
        async with db.session_factory.begin() as s:
            roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

            def person(key: str, role: str) -> User:
                email = f"{tag}.{key}@t.test"
                u = User(username=email, slug=f"{tag}-{key}", email=email, first_name=key.title(), last_name=tag, hashed_password=hash_password(PASSWORD),
                         status=UserStatus.ACTIVE, can_login=True, mobile=f"+4477{random.randint(10000000, 99999999)}", roles=[roles[role]])
                people[key] = {"email": email, "mobile": u.mobile, "name": f"{key.title()} {tag}"}
                return u

            u = {k: person(k, r) for k, r in [("admin", "ADMIN"), ("tutora", "TUTOR"), ("tutorb", "TUTOR"), ("stua", "STUDENT"), ("stub", "STUDENT"), ("stuc", "STUDENT")]}
            course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
            course.batches, course.resources, course.tags = [], [], []
            course.tutors = [u["tutora"], u["tutorb"]]
            s.add_all([*u.values(), course])
            await s.flush()
            batches = {}
            for code, tutor in (("A", u["tutora"]), ("B", u["tutorb"])):
                b = Batch(batch_code=f"{tag}-{code}", course_id=course.id, start_date=date.today(), end_date=date.today() + timedelta(days=30), is_active=True, capacity=10)
                b.sessions, b.enrollments, b.student_reviews = [], [], []
                s.add(b)
                await s.flush()
                sess = BatchSession(batch_id=b.id, tutor_id=tutor.id, session_start_time=datetime.now(timezone.utc) + timedelta(days=1), session_end_time=datetime.now(timezone.utc) + timedelta(days=1, hours=1),
                                    duration_minutes=60, platform=Platforms.Zoom)
                sess.attendances = []
                s.add(sess)
                batches[code] = b
            await s.flush()
            for stu, code in (("stua", "A"), ("stub", "A"), ("stuc", "B")):
                s.add(Enrollments(batch_id=batches[code].id, student_id=u[stu].id, enrollment_date=datetime.now(timezone.utc), status=EnrollmentStatus.CONFIRMED))
            await s.flush()
            for k, v in u.items():
                people[k]["public_id"] = str(v.public_id)
            ids["course"], ids["batch_a"] = str(course.public_id), str(batches["A"].public_id)
            ids["sess_a"] = str((await s.execute(select(BatchSession.public_id).where(BatchSession.batch_id == batches["A"].id))).scalar_one())

    loop.run_until_complete(build())
    lifespan = app.router.lifespan_context(app)
    loop.run_until_complete(lifespan.__aenter__())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")

    def get(who: str, path: str, **params):  # noqa: ANN202
        async def go():  # noqa: ANN202
            if who not in tokens:
                ident = "superadmin" if who == "superadmin" else people[who]["email"]
                pwd = "ConsoleDrive!2026" if who == "superadmin" else PASSWORD
                r = await client.post("/api/v1/auth/login", json={"identifier": ident, "password": pwd})
                assert r.status_code == 200, r.text
                tokens[who] = r.json()["access_token"]
            return await client.get(f"/api/v1{path}", params=params, headers={"Authorization": f"Bearer {tokens[who]}"})
        return loop.run_until_complete(go())

    ns = type("W", (), dict(tag=tag, people=people, ids=ids, get=staticmethod(get)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                await s.execute(text("DELETE FROM tokens WHERE user_id IN (SELECT id FROM users WHERE email LIKE :u)"), p)
                await s.execute(text("DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM tutor_courses WHERE course_id IN (SELECT id FROM courses WHERE title LIKE :t)"), p)
                await s.execute(text("DELETE FROM batches WHERE batch_code LIKE :c"), p)
                await s.execute(text("DELETE FROM courses WHERE title LIKE :t"), p)
                await s.execute(text("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE email LIKE :u)"), p)
                await s.execute(text("DELETE FROM users WHERE email LIKE :u"), p)
        loop.run_until_complete(client.aclose())
        loop.run_until_complete(lifespan.__aexit__(None, None, None))
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _others(w, me: str) -> list[str]:  # noqa: ANN001
    """Every string that would identify another person's contact details."""
    out: list[str] = []
    for key, p in w.people.items():
        if key != me:
            out += [p["email"], p["mobile"]]
    return out


def _endpoints(w) -> list[str]:  # noqa: ANN001
    return [
        f"/courses/{w.ids['course']}",
        "/courses",
        f"/batches/{w.ids['batch_a']}",
        "/batches",
        "/sessions",
        f"/sessions/{w.ids['sess_a']}",
        f"/sessions/{w.ids['sess_a']}/overview",
        "/enrollments",
        "/search",
    ]


@pytest.mark.parametrize("viewer", ["tutora", "tutorb", "stua", "stub", "stuc", "admin"])
def test_nobody_but_the_super_admin_sees_another_persons_email_or_phone(world, viewer: str) -> None:
    """Across every screen that mentions people. Being in the same batch changes nothing."""
    leaked: list[str] = []
    for path in _endpoints(world):
        r = world.get(viewer, path, **({"q": world.tag} if path == "/search" else {}))
        if r.status_code >= 500:
            pytest.fail(f"{path} -> {r.status_code}")
        if r.status_code != 200:
            continue  # a screen this role cannot open shows nothing, which is also fine
        leaked += [f"{path}: {token}" for token in _others(world, viewer) if token in r.text]
    assert leaked == []


def test_the_super_admin_still_sees_them(world) -> None:
    r = world.get("superadmin", f"/sessions/{world.ids['sess_a']}/overview")
    assert r.status_code == 200
    assert world.people["stua"]["email"] in r.text and world.people["stua"]["mobile"] in r.text


def test_people_see_their_own_details(world) -> None:
    me = world.get("stua", "/auth/me").json()
    assert me["email"] == world.people["stua"]["email"] and me["username"] == world.people["stua"]["email"]


def test_an_administrator_works_from_names_and_cannot_probe_for_an_address(world) -> None:
    me = world.people["admin"]["public_id"]
    rows = [r for r in world.get("admin", "/users", query=world.tag, limit=50).json()["items"] if r["public_id"] != me]  # not themselves
    assert len(rows) == 5 and all(r["email"] is None for r in rows)
    assert all("@" not in r["username"] for r in rows)  # the login name is the email; it is replaced by the name
    # Searching by an address must not confirm it exists.
    assert world.get("admin", "/users", query=world.people["stua"]["email"]).json()["items"] == []
    # ... whereas the Super Admin can search by it.
    assert world.get("superadmin", "/users", query=world.people["stua"]["email"]).json()["items"]


def test_a_student_sees_only_their_own_tutor_on_a_course(world) -> None:
    body = world.get("stua", f"/courses/{world.ids['course']}").json()
    assert body["tutors"] == [world.people["tutora"]["name"]]          # tutor B has no session for student A


def test_a_tutor_is_not_shown_their_colleagues(world) -> None:
    body = world.get("tutora", f"/courses/{world.ids['course']}").json()
    assert body["tutors"] == [world.people["tutora"]["email"]]         # themselves only, by their own login name
    assert world.people["tutorb"]["name"] not in str(body)


def test_an_administrator_sees_every_tutor_by_name(world) -> None:
    body = world.get("admin", f"/courses/{world.ids['course']}").json()
    assert sorted(body["tutors"]) == sorted([world.people["tutora"]["name"], world.people["tutorb"]["name"]])
