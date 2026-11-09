"""Changing a session's tutor, and generating a password for somebody else.

Driven over HTTP as real seeded roles. The fixture holds what each rule needs
to be able to fail:

* **two tutors with a class at the same hour**, so reassigning one tutor's
  class to the other is a double booking the server must refuse;
* **a tutor who holds `session.update`**, because that permission is exactly
  why a tutor could previously hand their class to somebody else;
* **an Administrator and a second Super Admin**, because an Administrator
  resetting a Super Admin's password is the takeover being closed.
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
from backend.db.manager import DatabaseManager
from backend.main import app
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.security.password import hash_password
from backend.utils.enums import CourseStatus, Platforms, UserStatus

PASSWORD = "TutorAndPassword!2026"


@pytest.fixture()
def env():
    tag = f"tp{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="tutor-password-tests")
    ids: dict[str, object] = {}
    at = (datetime.now(timezone.utc) + timedelta(days=3)).replace(minute=0, second=0, microsecond=0)

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

        people = {k: person(k, r) for k, r in (
            ("super", "SUPER_ADMIN"), ("super2", "SUPER_ADMIN"), ("admin", "ADMIN"),
            ("tutora", "TUTOR"), ("tutorb", "TUTOR"), ("tutorc", "TUTOR"), ("student", "STUDENT"),
        )}
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([*people.values(), course])
        await s.flush()

        def batch(code: str) -> Batch:
            b = Batch(batch_code=f"{tag}-{code}", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=10)
            b.sessions, b.enrollments, b.student_reviews = [], [], []
            return b

        ba, bb = batch("A"), batch("B")
        s.add_all([ba, bb])
        await s.flush()

        def session(b: Batch, key: str) -> BatchSession:
            row = BatchSession(batch_id=b.id, tutor_id=people[key].id, session_start_time=at,
                               session_end_time=at + timedelta(hours=1), duration_minutes=60,
                               platform=Platforms.Zoom)
            row.attendances = []
            return row

        # tutora teaches A and tutorb teaches B, at the same hour.
        sa, sb = session(ba, "tutora"), session(bb, "tutorb")
        s.add_all([sa, sb])
        await s.flush()
        ids.update(session_a=sa.public_id, session_b=sb.public_id,
                   **{f"{k}_id": p.public_id for k, p in people.items()})

    run(build)

    lifespan = app.router.lifespan_context(app)
    loop.run_until_complete(lifespan.__aenter__())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")
    tokens: dict[str, str] = {}

    def login(who: str, password: str = PASSWORD) -> httpx.Response:
        return loop.run_until_complete(client.post(
            "/api/v1/auth/login", json={"identifier": f"{tag}.{who}@t.test", "password": password}))

    def call(who: str, method: str, path: str, **kwargs):  # noqa: ANN202
        if who not in tokens:
            signed_in = login(who)
            assert signed_in.status_code == 200, signed_in.text[:200]
            tokens[who] = signed_in.json()["access_token"]
        return loop.run_until_complete(client.request(
            method, f"/api/v1{path}", headers={"Authorization": f"Bearer {tokens[who]}"}, **kwargs))

    def sql(statement: str, **params):  # noqa: ANN202
        async def go(s):  # noqa: ANN001, ANN202
            result = await s.execute(text(statement), params)
            return result.all() if result.returns_rows else []
        return run(go)

    ns = type("Env", (), dict(tag=tag, ids=ids, call=staticmethod(call), sql=staticmethod(sql),
                              login=staticmethod(login), tokens=tokens))
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
                    f"DELETE FROM notifications WHERE user_id IN {users}",
                    f"DELETE FROM tokens WHERE user_id IN {users}",
                    "DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batches WHERE batch_code LIKE :c",
                    "DELETE FROM courses WHERE title LIKE :t",
                    f"DELETE FROM user_roles WHERE user_id IN {users}",
                    "DELETE FROM users WHERE username LIKE :u",
                ):
                    await s.execute(text(stmt), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _ok(r: httpx.Response, code: int = 200) -> dict:
    assert r.status_code == code, r.text[:400]
    return r.json() if r.content else {}


# -- the session's tutor ----------------------------------------------------------


def test_a_scheduler_reassigns_a_session_and_the_response_names_the_new_tutor(env) -> None:
    path = f"/sessions/{env.ids['session_a']}"
    body = _ok(env.call("super", "PATCH", path, json={"tutor_id": str(env.ids["tutorc_id"])}))
    # The response is built from the same instance: it must not echo the old tutor.
    assert body["tutor_id"] == str(env.ids["tutorc_id"])
    assert body["tutor_name"] == f"Tutorc {env.tag}"
    assert _ok(env.call("super", "GET", path))["tutor_id"] == str(env.ids["tutorc_id"])
    listed = _ok(env.call("super", "GET", f"/batches/{_batch_of(env, 'session_a')}/sessions"))["items"]
    assert [r["tutor_name"] for r in listed] == [f"Tutorc {env.tag}"]
    # The audit entry says who it moved from and to.
    details = env.sql(
        "SELECT details FROM audit_logs WHERE entity_type = 'batch_session' AND action = 'UPDATE' "
        "AND details->'tutor'->>'to' = :t ORDER BY id DESC LIMIT 1", t=str(env.ids["tutorc_id"]))
    assert details and details[0][0]["tutor"]["from"] == str(env.ids["tutora_id"])


def test_reassigning_to_a_tutor_who_is_already_teaching_then_is_refused(env) -> None:
    refused = env.call("super", "PATCH", f"/sessions/{env.ids['session_a']}",
                       json={"tutor_id": str(env.ids["tutorb_id"])})
    assert refused.status_code == 409, refused.text[:300]
    assert _ok(env.call("super", "GET", f"/sessions/{env.ids['session_a']}"))["tutor_id"] == str(env.ids["tutora_id"])


def test_a_tutor_cannot_hand_their_class_to_somebody_else(env) -> None:
    path = f"/sessions/{env.ids['session_a']}"
    refused = env.call("tutora", "PATCH", path, json={"tutor_id": str(env.ids["tutorc_id"])})
    assert refused.status_code == 403, refused.text[:300]
    # Sending their own id back (what an edit form does) is not a change and stays allowed.
    _ok(env.call("tutora", "PATCH", path, json={"tutor_id": str(env.ids["tutora_id"]), "tutor_notes": "n"}))


def test_only_a_tutor_can_be_assigned(env) -> None:
    refused = env.call("super", "PATCH", f"/sessions/{env.ids['session_a']}",
                       json={"tutor_id": str(env.ids["student_id"])})
    assert refused.status_code == 422, refused.text[:300]


def _batch_of(env, key: str) -> str:  # noqa: ANN001
    return str(env.sql("SELECT b.public_id FROM batch_sessions s JOIN batches b ON b.id = s.batch_id "
                       "WHERE s.public_id = :p", p=env.ids[key])[0][0])


# -- generated passwords ----------------------------------------------------------


def test_a_generated_password_works_once_shown_and_ends_the_old_sessions(env) -> None:
    env.login("student")  # a live session from before the reset
    before = env.sql("SELECT max(t.id) FROM tokens t JOIN users u ON u.id = t.user_id WHERE u.username = :u",
                     u=f"{env.tag}.student@t.test")[0][0]
    r = env.call("admin", "POST", f"/users/{env.ids['student_id']}/password/generate")
    body = _ok(r)
    password = body["password"]
    assert len(password) == 16
    assert r.headers.get("cache-control") == "no-store"
    # The new one signs in; the old one does not; the old session is over.
    assert env.login("student", password).status_code == 200
    assert env.login("student").status_code == 401
    still_live = env.sql(
        "SELECT count(*) FROM tokens t JOIN users u ON u.id = t.user_id "
        "WHERE u.username = :u AND t.id <= :before AND NOT t.revoked", u=f"{env.tag}.student@t.test", before=before)
    assert before is not None and still_live[0][0] == 0
    # Stored hashed, never in clear.
    stored = env.sql("SELECT hashed_password FROM users WHERE username = :u", u=f"{env.tag}.student@t.test")[0][0]
    assert password not in stored
    # The owner is told, and the audit row records a generated reset with no password in it.
    told = env.sql("SELECT n.title FROM notifications n JOIN users u ON u.id = n.user_id "
                   "WHERE u.username = :u AND n.type = 'password_changed'", u=f"{env.tag}.student@t.test")
    assert told
    audit = env.sql("SELECT details::text FROM audit_logs WHERE action = 'PASSWORD_RESET_BY_ADMIN' "
                    "ORDER BY id DESC LIMIT 1")[0][0]
    assert '"generated": true' in audit and password not in audit


def test_regenerating_gives_a_different_password_and_retires_the_first(env) -> None:
    first = _ok(env.call("admin", "POST", f"/users/{env.ids['student_id']}/password/generate"))["password"]
    second = _ok(env.call("admin", "POST", f"/users/{env.ids['student_id']}/password/generate"))["password"]
    assert first != second
    assert env.login("student", first).status_code == 401
    assert env.login("student", second).status_code == 200


def test_an_administrator_cannot_reset_a_super_admins_password(env) -> None:
    for method, path, kwargs in (
        ("POST", f"/users/{env.ids['super_id']}/password/generate", {}),
        ("PUT", f"/users/{env.ids['super_id']}/password", {"json": {"new_password": "AnotherPassword!123"}}),
    ):
        refused = env.call("admin", method, path, **kwargs)
        assert refused.status_code == 403, (path, refused.text[:200])
    assert env.login("super").status_code == 200
    # A Super Admin may reset another Super Admin.
    _ok(env.call("super", "POST", f"/users/{env.ids['super2_id']}/password/generate"))


def test_nobody_resets_their_own_password_this_way_and_tutors_cannot_at_all(env) -> None:
    assert env.call("admin", "POST", f"/users/{env.ids['admin_id']}/password/generate").status_code == 409
    assert env.call("tutora", "POST", f"/users/{env.ids['student_id']}/password/generate").status_code == 403
    assert env.login("student").status_code == 200
