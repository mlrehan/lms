"""The LAIT sync service against the real local Postgres, with a fake LAIT.

Skipped when the database is unreachable. Every test creates rows under a
unique marker and removes them afterwards, so it is safe to run against the
development database (audit rows are append-only and are left behind).
"""

from __future__ import annotations

import asyncio
import selectors
import uuid
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select, text

from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.integrations.lait_client import LaitClient
from backend.models.identity.user import User
from backend.models.user_sync import UserSyncRun
from backend.services.lait_sync_service import LaitSyncService
from backend.utils.enums import UserStatus


def _loop() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop(selectors.SelectSelector())


class Fake:
    """A LAIT whose feeds the test controls."""

    def __init__(self) -> None:
        self.students: list[dict[str, Any]] = []
        self.tutors: list[dict[str, Any]] = []
        self.details: dict[str, dict[str, Any]] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/Students/latest":
            return httpx.Response(200, json=self.students)
        if path == "/api/Tutors":
            return httpx.Response(200, json=self.tutors)
        if "/guid/" in path:
            return httpx.Response(200, json=self.details.get(path.rsplit("/", 1)[-1], {}))
        return httpx.Response(404)


def _student(tag: str, n: int, **over: Any) -> dict[str, Any]:
    guid = str(uuid.uuid4())
    base = {
        "StudentID": 950000 + n, "UserID": guid, "UserName": f"{tag}.s{n}@sync.test",
        "Email": f"{tag}.s{n}@sync.test", "FirstName": "Sync", "LastName": f"Student{n}",
        "CountryName": "United Kingdom", "City": "", "RegistrationDate": "2026-07-01T09:30:00",
        "Roles": ["Student"],
    }
    base.update(over)
    return base


@pytest.fixture()
def env():
    tag = "t" + uuid.uuid4().hex[:8]
    fake = Fake()
    loop = _loop()
    settings = get_settings()
    settings = settings.model_copy(
        update={"lait": settings.lait.model_copy(update={"api_base_url": "https://lait.test", "api_key": SecretStr("k")})}
    )
    db = DatabaseManager(settings.database, application_name="sync-tests")

    def sync(dry_run: bool = False) -> UserSyncRun:
        async def go() -> UserSyncRun:
            client = LaitClient(settings.lait, transport=httpx.MockTransport(fake.handler))
            async with client:
                svc = LaitSyncService(db.session_factory, settings, client=client)
                return await svc.run(trigger_type="MANUAL", triggered_by_user_id=None, dry_run=dry_run)

        return loop.run_until_complete(go())

    def q(fn):  # noqa: ANN001
        async def go():  # noqa: ANN202
            async with db.session_factory() as s:
                return await fn(s)

        return loop.run_until_complete(go())

    async def _find(s, name):  # noqa: ANN001, ANN202
        return (await s.execute(select(User).where(User.username == name))).scalar_one_or_none()

    def find(name: str) -> User | None:
        return q(lambda s: _find(s, name))

    try:
        yield tag, fake, sync, q, find
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                await s.execute(delete(User).where(User.username.like(f"{tag}.%")))
                await s.execute(delete(UserSyncRun))

        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def test_a_created_account_is_active_but_cannot_log_in(env) -> None:
    tag, fake, sync, q, find = env
    fake.students = [_student(tag, 1)]
    run = sync()
    assert run.status == "SUCCEEDED" and run.stats["students"]["created"] == 1
    u = find(f"{tag}.s1@sync.test")
    assert u.status is UserStatus.ACTIVE and u.can_login is False and u.is_locked is False
    assert u.is_login_permitted is False
    assert u.hashed_password.startswith("$argon2id$")  # never the plaintext default
    assert u.slug.startswith("sync-student1")


def test_a_second_run_changes_nothing(env) -> None:
    tag, fake, sync, q, find = env
    fake.students = [_student(tag, 1)]
    sync()
    again = sync()
    assert again.stats["students"] == {**again.stats["students"], "created": 0, "updated": 0, "unchanged": 1}


def test_a_dry_run_writes_no_accounts(env) -> None:
    tag, fake, sync, q, find = env
    fake.students = [_student(tag, 1)]
    run = sync(dry_run=True)
    assert run.stats["students"]["created"] == 1  # reported...
    assert find(f"{tag}.s1@sync.test") is None  # ...but rolled back


def test_admin_roles_in_the_payload_are_never_granted(env) -> None:
    tag, fake, sync, q, find = env
    fake.students = [_student(tag, 1, Roles=["Student", "Admin", "SUPER_ADMIN", "super admin"])]
    run = sync()
    assert sorted(r.name for r in find(f"{tag}.s1@sync.test").roles) == ["STUDENT"]
    assert run.stats["unknown_roles"] == 3


def test_an_update_never_touches_status_login_password_or_username(env) -> None:
    tag, fake, sync, q, find = env
    s = _student(tag, 1)
    fake.students = [s]
    sync()

    async def tamper(sess):  # noqa: ANN001, ANN202
        u = (await sess.execute(select(User).where(User.username == f"{tag}.s1@sync.test"))).scalar_one()
        u.status = UserStatus.SUSPENDED
        u.can_login = True
        u.hashed_password = "sentinel-hash"
        await sess.commit()

    q(tamper)
    s["FirstName"] = "Renamed"
    sync()
    u = find(f"{tag}.s1@sync.test")
    assert u.first_name == "Renamed"  # LAIT owns the name...
    assert u.status is UserStatus.SUSPENDED  # ...an administrator owns access
    assert u.can_login is True and u.hashed_password == "sentinel-hash"


def test_an_existing_username_is_skipped_not_merged(env) -> None:
    tag, fake, sync, q, find = env
    fake.students = [_student(tag, 1)]
    sync()
    clash = _student(tag, 2, UserName=f"{tag}.s1@sync.test", Email=f"{tag}.other@sync.test")
    fake.students = [clash]
    run = sync()
    assert run.status == "PARTIAL" and run.stats["students"]["skipped"] == 1
    # The unique index would refuse this too; asserting the reason proves the
    # service's own check fired first rather than the database's backstop.
    assert "belongs to another account" in run.errors[0]["reason"]
    assert find(f"{tag}.other@sync.test") is None


def test_a_username_equal_to_another_accounts_email_is_refused(env) -> None:
    """Login resolves username *or* email, so this pairing would be ambiguous.

    Built so the database cannot catch it: the victim's *username* differs from
    its email, so no unique index is violated -- only the service's crosswise
    check stands between this record and an ambiguous login identifier.
    """
    tag, fake, sync, q, find = env

    async def seed(sess):  # noqa: ANN001, ANN202
        sess.add(User(username=f"{tag}.legacy", slug=f"{tag}-legacy", email=f"{tag}.victim@sync.test",
                      hashed_password="x", status=UserStatus.ACTIVE, roles=[]))
        await sess.commit()

    q(seed)
    fake.students = [_student(tag, 2, UserName=f"{tag}.victim@sync.test", Email=f"{tag}.new@sync.test")]
    run = sync()
    assert run.stats["students"]["skipped"] == 1
    assert "belongs to another account" in run.errors[0]["reason"]
    assert find(f"{tag}.victim@sync.test") is None


def test_a_tutor_gets_the_tutor_role_and_an_email_username_from_the_detail(env) -> None:
    tag, fake, sync, q, find = env
    guid = str(uuid.uuid4())
    fake.tutors = [{"tutor_id": 940001, "user_id": guid, "first_name": "Tia", "middle_name": "M", "last_name": "Tutor", "is_public": True}]
    fake.details[guid] = {"email_id": f"{tag}.tia@sync.test"}
    sync()
    u = find(f"{tag}.tia@sync.test")
    assert [r.name for r in u.roles] == ["TUTOR"] and u.last_name == "M Tutor" and u.external_tutor_id == 940001


def test_a_tutor_never_overwrites_a_students_name(env) -> None:
    tag, fake, sync, q, find = env
    s = _student(tag, 1)
    fake.students = [s]
    sync()
    fake.tutors = [{"tutor_id": 940002, "user_id": s["UserID"], "first_name": "Other", "last_name": "Name", "is_public": True}]
    sync()
    u = find(f"{tag}.s1@sync.test")
    assert u.first_name == "Sync" and u.external_tutor_id == 940002
    assert sorted(r.name for r in u.roles) == ["STUDENT", "TUTOR"]  # additive


def test_only_one_run_can_be_live_at_a_time(env) -> None:
    tag, fake, sync, q, find = env
    from backend.core.errors import ConflictError

    async def two(sess):  # noqa: ANN001, ANN202
        from datetime import datetime, timezone

        sess.add(UserSyncRun(trigger_type="MANUAL", dry_run=False, status="RUNNING", started_at=datetime.now(timezone.utc)))
        await sess.commit()

    q(two)
    with pytest.raises(ConflictError):
        sync()
