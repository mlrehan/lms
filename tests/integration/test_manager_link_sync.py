"""Manager links: matched by email, skipped otherwise, never created.

Against real Postgres with a faked LAIT API, because the behaviour that
matters is what reaches `users` and `manager_students` -- and the point of the
policy is that one of those tables is *never written*.

The fixture deliberately contains one manager of each kind the live feed has:
one who is already an LMS user, one who is not, and one LAIT holds no email
for. A fixture with only the happy case would pass against a service that
creates accounts for everyone.
"""

from __future__ import annotations

import asyncio
import random
import selectors
import uuid
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text

from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.integrations.lait_client import LaitClient
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.organization import ManagedStudent
from backend.security.password import hash_password
from backend.services import manager_link_sync as mod
from backend.services.manager_link_sync import ManagerLinkSyncService
from backend.utils.enums import UserStatus


@pytest.fixture()
def env(monkeypatch):  # noqa: ANN001, ANN201
    tag = f"mgr{random.randint(100000, 900000)}"
    # `users.external_student_id` is unique across the whole table and the dev
    # database holds real LAIT ids, so these are derived per run rather than
    # hard-coded -- a fixed 770001 collides with a real student.
    base = random.randint(90_000_000, 98_000_000)
    EXT = {"s1": base + 1, "s2": base + 2, "absent": base + 3, "self": base + 4}
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    settings = get_settings()
    settings = settings.model_copy(
        update={
            "lait": settings.lait.model_copy(
                update={"api_base_url": "https://lait.test", "api_key": SecretStr("k")}
            )
        }
    )
    db = DatabaseManager(settings.database, application_name="manager-link-tests")

    known_email = f"{tag}.known@t.test"
    stranger_email = f"{tag}.stranger@t.test"
    ids: dict[str, int] = {}

    managers = [
        {  # already an LMS user
            "customer_id": 9001, "unique_key": str(uuid.uuid4()), "title": "Mr",
            "first_name": "Known", "middle_name": "", "last_name": tag,
            "company_name": "Known Ltd", "username": known_email,
            "date_created": "2024-01-01T09:00:00",
        },
        {  # not an LMS user -- must be skipped, not created
            "customer_id": 9002, "unique_key": str(uuid.uuid4()), "title": "",
            "first_name": "Stranger", "middle_name": "", "last_name": tag,
            "company_name": "Stranger Ltd", "username": stranger_email,
            "date_created": "2024-01-01T09:00:00",
        },
        {  # LAIT holds no email
            "customer_id": 9003, "unique_key": str(uuid.uuid4()), "title": "",
            "first_name": "Nameless", "middle_name": "", "last_name": tag,
            "company_name": "Nameless Ltd", "username": "",
            "date_created": "2024-01-01T09:00:00",
        },
    ]

    state: dict[str, Any] = {"delegates": {}, "fail_delegates_for": None}

    def api(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/GetDelegateManagers":
            return httpx.Response(200, json=managers)
        if path.startswith("/api/GetDelegateManagers/") and path.endswith("/Delegates"):
            cid = int(path.split("/")[3])
            if state["fail_delegates_for"] == cid:
                return httpx.Response(500, json={"error": "upstream"})
            return httpx.Response(200, json=state["delegates"].get(cid, []))
        return httpx.Response(404)

    monkeypatch.setattr(
        mod, "LaitClient",
        lambda s: LaitClient(s, transport=httpx.MockTransport(api)),
    )

    async def build() -> None:
        async with db.session_factory.begin() as session:
            roles = {r.name: r for r in (await session.execute(select(Role))).scalars()}
            people = {}
            for key, email, role in (
                ("known", known_email, "CORPORATE_MANAGER"),
                ("s1", f"{tag}.s1@t.test", "STUDENT"),
                ("s2", f"{tag}.s2@t.test", "STUDENT"),
            ):
                u = User(
                    username=email, slug=f"{tag}-{key}", email=email,
                    first_name=key.title(), last_name=tag,
                    hashed_password=hash_password("Mgr!Test2026xx"),
                    status=UserStatus.ACTIVE, can_login=True, roles=[roles[role]],
                )
                if key in EXT:
                    u.external_student_id = EXT[key]
                session.add(u)
                people[key] = u
            await session.flush()
            for key, u in people.items():
                ids[key] = u.id

    loop.run_until_complete(build())

    def delegates(customer_id: int, student_ids: list[int | None], names: list[str] | None = None) -> None:
        state["delegates"][customer_id] = [
            {
                "customer_id": customer_id, "student_id": sid,
                "unique_key": str(uuid.uuid4()),
                "delegate_name": (names[i] if names else f"Delegate {i}"),
                "status_id": 1, "status_details": "Active",
                "date_added": "2024-01-01T09:00:00",
            }
            for i, sid in enumerate(student_ids)
        ]

    def run(**kwargs: Any):  # noqa: ANN202
        service = ManagerLinkSyncService(db.session_factory, settings)
        return loop.run_until_complete(service.run(**kwargs))

    def count(sql: str, **params: Any) -> int:
        async def go() -> int:
            async with db.session_factory() as session:
                return int((await session.execute(text(sql), params)).scalar_one())

        return loop.run_until_complete(go())

    ns = type(
        "Env", (),
        dict(
            tag=tag, ids=ids, ext=EXT, known_email=known_email, stranger_email=stranger_email,
            state=state, delegates=staticmethod(delegates),
            run=staticmethod(run), count=staticmethod(count), db=db, loop=loop,
        ),
    )
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            # One statement per transaction. A multi-statement teardown aborts
            # wholesale on the first violation and leaves everything behind --
            # which is exactly what happened here when it tried to delete from
            # `audit_logs`, a table a trigger makes append-only.
            p = {"u": f"{tag}.%"}
            for sql in (
                "DELETE FROM manager_students WHERE manager_id IN"
                " (SELECT id FROM users WHERE email LIKE :u)"
                " OR student_id IN (SELECT id FROM users WHERE email LIKE :u)",
                "DELETE FROM user_roles WHERE user_id IN"
                " (SELECT id FROM users WHERE email LIKE :u)",
                "DELETE FROM users WHERE email LIKE :u",
            ):
                async with db.session_factory.begin() as session:
                    await session.execute(text(sql), p)

        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


# -- matching ----------------------------------------------------------------


def test_a_manager_who_is_an_lms_user_is_matched_by_email(env):  # noqa: ANN001, ANN201
    env.delegates(9001, [env.ext['s1'], env.ext['s2']])
    report = env.run()
    assert report.managers_matched == 1
    assert report.links_created == 2
    assert env.count(
        "SELECT count(*) FROM manager_students WHERE manager_id = :m", m=env.ids["known"]
    ) == 2


def test_a_manager_with_no_lms_account_is_skipped_and_never_created(env):  # noqa: ANN001, ANN201
    """The policy. An external directory is not a way to add accounts here."""
    before = env.count("SELECT count(*) FROM users")
    env.delegates(9002, [env.ext['s1']])
    report = env.run()

    assert report.managers_no_account == 1
    assert env.count("SELECT count(*) FROM users") == before, "no account may be created"
    assert env.count(
        "SELECT count(*) FROM users WHERE lower(email) = :e", e=env.stranger_email
    ) == 0
    # And nothing was linked on their behalf.
    assert env.count("SELECT count(*) FROM manager_students WHERE manager_id IN"
                     " (SELECT id FROM users WHERE email = :e)", e=env.stranger_email) == 0


def test_a_manager_with_no_email_upstream_is_skipped(env):  # noqa: ANN001, ANN201
    report = env.run()
    assert report.managers_no_email == 1
    reasons = {s["reason"] for s in report.skipped}
    assert any("no email address" in r for r in reasons)


def test_every_skip_is_recorded_with_a_reason(env):  # noqa: ANN001, ANN201
    report = env.run()
    by_id = {s["customer_id"]: s["reason"] for s in report.skipped}
    assert by_id["9002"] == "no LMS user has this email address"
    assert "no email address" in by_id["9003"]


def test_a_skip_reason_never_carries_the_person(env):  # noqa: ANN001, ANN201
    """These entries are stored on the run and rendered in the console.

    Saying *which* record was passed over is useful; saying who they are is
    publishing a third party's contact details into a sync report.
    """
    report = env.run()
    blob = repr(report.skipped).lower()
    for secret in (env.stranger_email, "stranger", "nameless", "stranger ltd", env.tag.lower()):
        assert secret.lower() not in blob, f"{secret!r} leaked into the skip list"


# -- unmatched records must not fail the run ---------------------------------


def test_skipped_managers_are_not_failures(env):  # noqa: ANN001, ANN201
    """What makes the pipeline report success instead of "finished with
    problems" -- two systems holding different people is not a fault."""
    env.delegates(9001, [env.ext['s1']])
    report = env.run()
    assert report.managers_no_account == 1
    assert report.managers_no_email == 1
    assert report.failed == 0
    assert report.passed_over >= 2


def test_an_upstream_failure_is_a_failure(env):  # noqa: ANN001, ANN201
    """Otherwise the test above would pass against a report that can never
    fail at all, and a dead API would read as a clean run."""
    env.delegates(9001, [env.ext['s1']])
    env.state["fail_delegates_for"] = 9001
    report = env.run()
    assert report.failed == 1
    assert report.errors


def test_one_managers_failure_does_not_stop_the_others(env):  # noqa: ANN001, ANN201
    env.delegates(9001, [env.ext['s1'], env.ext['s2']])
    env.state["fail_delegates_for"] = 9003  # the one with no email anyway
    report = env.run()
    assert report.managers_fetched == 3
    assert report.links_created == 2  # 9001 still processed


# -- idempotence and shape ---------------------------------------------------


def test_running_twice_creates_no_duplicate_links(env):  # noqa: ANN001, ANN201
    env.delegates(9001, [env.ext['s1'], env.ext['s2']])
    first = env.run()
    second = env.run()
    assert first.links_created == 2
    assert second.links_created == 0
    assert second.links_existing == 2
    assert env.count(
        "SELECT count(*) FROM manager_students WHERE manager_id = :m", m=env.ids["known"]
    ) == 2


def test_a_delegate_who_is_not_a_student_here_is_passed_over(env):  # noqa: ANN001, ANN201
    env.delegates(9001, [env.ext['s1'], env.ext['absent']])
    report = env.run()
    assert report.links_created == 1
    assert report.delegates_unmatched == 1
    assert report.failed == 0


def test_a_manager_is_never_linked_to_themselves(env):  # noqa: ANN001, ANN201
    """Real data has managers in their own delegate list."""
    async def give_known_an_external_id() -> None:
        async with env.db.session_factory.begin() as session:
            await session.execute(
                text("UPDATE users SET external_student_id = :e WHERE id = :i"),
                {"i": env.ids["known"], "e": env.ext["self"]},
            )

    env.loop.run_until_complete(give_known_an_external_id())
    env.delegates(9001, [env.ext['self'], env.ext['s1']])
    report = env.run()
    assert report.self_links_skipped == 1
    assert report.links_created == 1
    assert env.count(
        "SELECT count(*) FROM manager_students WHERE manager_id = student_id"
    ) == 0


def test_a_dry_run_writes_nothing(env):  # noqa: ANN001, ANN201
    env.delegates(9001, [env.ext['s1'], env.ext['s2']])
    report = env.run(dry_run=True)
    assert report.links_created == 2  # reported as what *would* happen
    assert env.count(
        "SELECT count(*) FROM manager_students WHERE manager_id = :m", m=env.ids["known"]
    ) == 0


# -- deleted accounts are not matches ----------------------------------------


def test_a_deleted_manager_is_not_matched(env):  # noqa: ANN001, ANN201
    """Users are soft-deleted because `audit_logs` references the row, so a
    deleted person keeps their email. Matching it again re-links them to
    delegates and undoes the deletion -- which is what happened live: 95
    removed accounts were matched again on the very next run.
    """
    async def soft_delete_known() -> None:
        async with env.db.session_factory.begin() as session:
            await session.execute(
                text("UPDATE users SET deleted_at = now() WHERE id = :i"),
                {"i": env.ids["known"]},
            )

    env.delegates(9001, [env.ext["s1"], env.ext["s2"]])
    env.loop.run_until_complete(soft_delete_known())

    report = env.run()
    assert report.managers_matched == 0
    assert report.managers_no_account == 2  # the deleted one, plus the stranger
    assert report.links_created == 0
    assert env.count(
        "SELECT count(*) FROM manager_students WHERE manager_id = :m", m=env.ids["known"]
    ) == 0


def test_a_deleted_delegate_is_not_linked(env):  # noqa: ANN001, ANN201
    async def soft_delete_student() -> None:
        async with env.db.session_factory.begin() as session:
            await session.execute(
                text("UPDATE users SET deleted_at = now() WHERE id = :i"),
                {"i": env.ids["s1"]},
            )

    env.delegates(9001, [env.ext["s1"], env.ext["s2"]])
    env.loop.run_until_complete(soft_delete_student())

    report = env.run()
    assert report.links_created == 1  # s2 only
    assert report.delegates_unmatched == 1
    assert env.count(
        "SELECT count(*) FROM manager_students WHERE student_id = :s", s=env.ids["s1"]
    ) == 0
