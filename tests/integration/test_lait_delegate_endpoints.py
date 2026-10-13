"""The two read-through LAIT endpoints, over real HTTP with a fake upstream.

Two things are being proved, and only the first is obvious:

1. **The permission gate.** `organization.read` opens both routes; a tutor,
   a student and an anonymous caller are refused. That is checked through the
   app rather than against the dependency, because a route that forgets to
   declare the dependency passes every unit test of the dependency.

2. **An external source is not a way around the contact rule.** Upstream, a
   manager's `username` *is* their email address. It reaches the caller as
   `email` only for a holder of `user.view_contact`; for everybody else the
   field is `null` and the address must appear **nowhere** in the body --
   which is why the assertions search the whole response text rather than
   just that one key.

The upstream is a `MockTransport`, so these tests make no network call and do
not depend on LAIT being up. The real service was driven separately; what a
fake can prove and a live call cannot is the behaviour of its failure modes.
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
from sqlalchemy import select, text

from backend.api.v1 import lait_delegates as module
from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.integrations.lait_client import LaitClient
from backend.main import app
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.security.password import hash_password
from backend.utils.enums import UserStatus

PASSWORD = "Delegate!Test2026"

# One manager carries a middle name and a title so `full_name` has something
# to compose; the other has neither, so the composition cannot be a format
# string that only works when every part is present.
MANAGERS: list[dict[str, Any]] = [
    {
        "customer_id": 41,
        "unique_key": str(uuid.uuid4()),
        "title": "Mr",
        "first_name": "Adam",
        "middle_name": "J",
        "last_name": "Copland",
        "company_name": "Axcess Payment Services Ltd",
        "designation": "Integration & Gateway Manager",
        "is_active": True,
        "username": "adam.copland@axcess.test",
        "date_created": "2024-03-13T12:59:02.783000",
        "date_modified": None,
    },
    {
        "customer_id": 42,
        "unique_key": str(uuid.uuid4()),
        "title": "",
        "first_name": "Carla",
        "middle_name": "",
        "last_name": "Gordon",
        "company_name": "Wise Ltd",
        "designation": None,
        "is_active": False,
        "username": "carla.gordon@wise.test",
        "date_created": "2025-01-02T09:00:00",
        "date_modified": "2025-06-02T09:00:00",
    },
]

DELEGATES: dict[int, list[dict[str, Any]]] = {
    41: [
        {
            "customer_id": 41,
            "student_id": 34143,
            "unique_key": str(uuid.uuid4()),
            "delegate_name": "Adam Copland",
            "status_id": 1,
            "status_details": "Active",
            "date_added": "2024-03-13T12:59:02.783000",
        },
        {
            "customer_id": 41,
            "student_id": 34144,
            "unique_key": str(uuid.uuid4()),
            "delegate_name": "Rita Shah",
            "status_id": 2,
            "status_details": "Inactive",
            "date_added": "2024-04-01T08:00:00",
        },
    ],
    # A real manager with nobody under them. The endpoint must say `count: 0`
    # rather than 404: upstream distinguishes "no delegates" from "no such
    # manager", and flattening the two would make an empty company look like
    # a bad id.
    42: [],
}


class Fake:
    """Upstream, as observed: a list, a per-manager list, and a 404 for an id
    it has never heard of."""

    def __init__(self) -> None:
        self.fail_with: int | None = None
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        if self.fail_with:
            return httpx.Response(self.fail_with, json={"error": "upstream detail"})
        if path == "/api/GetDelegateManagers":
            return httpx.Response(200, json=MANAGERS)
        if path.startswith("/api/GetDelegateManagers/") and path.endswith("/Delegates"):
            rows = DELEGATES.get(int(path.split("/")[3]))
            return httpx.Response(404) if rows is None else httpx.Response(200, json=rows)
        return httpx.Response(404)


@pytest.fixture()
def world(monkeypatch):  # noqa: ANN001, ANN201
    tag = f"dlg{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="delegate-tests")
    fake = Fake()
    tokens: dict[str, str] = {}
    people: dict[str, str] = {}

    lait = get_settings().lait.model_copy(
        update={"api_base_url": "https://lait.test", "api_key": SecretStr("fake-key")}
    )
    # A fresh client per request, because the route closes the one it is given.
    monkeypatch.setattr(
        module, "_client", lambda: LaitClient(lait, transport=httpx.MockTransport(fake))
    )

    async def build() -> None:
        async with db.session_factory.begin() as s:
            roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}
            users = []
            for key, role in (
                ("super", "SUPER_ADMIN"),
                ("admin", "ADMIN"),
                ("manager", "CORPORATE_MANAGER"),
                ("tutor", "TUTOR"),
                ("student", "STUDENT"),
            ):
                email = f"{tag}.{key}@t.test"
                people[key] = email
                users.append(
                    User(
                        username=email,
                        slug=f"{tag}-{key}",
                        email=email,
                        first_name=key.title(),
                        last_name=tag,
                        hashed_password=hash_password(PASSWORD),
                        status=UserStatus.ACTIVE,
                        can_login=True,
                        roles=[roles[role]],
                    )
                )
            s.add_all(users)

    loop.run_until_complete(build())
    lifespan = app.router.lifespan_context(app)
    loop.run_until_complete(lifespan.__aenter__())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")

    def get(who: str | None, path: str) -> httpx.Response:
        async def go() -> httpx.Response:
            headers = {}
            if who is not None:
                if who not in tokens:
                    r = await client.post(
                        "/api/v1/auth/login",
                        json={"identifier": people[who], "password": PASSWORD},
                    )
                    assert r.status_code == 200, r.text
                    tokens[who] = r.json()["access_token"]
                headers["Authorization"] = f"Bearer {tokens[who]}"
            return await client.get(f"/api/v1/integrations/lait{path}", headers=headers)

        return loop.run_until_complete(go())

    ns = type("W", (), dict(tag=tag, fake=fake, get=staticmethod(get)))
    try:
        yield ns
    finally:

        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"u": f"{tag}.%"}
                await s.execute(
                    text(
                        "DELETE FROM tokens WHERE user_id IN"
                        " (SELECT id FROM users WHERE email LIKE :u)"
                    ),
                    p,
                )
                await s.execute(
                    text(
                        "DELETE FROM user_roles WHERE user_id IN"
                        " (SELECT id FROM users WHERE email LIKE :u)"
                    ),
                    p,
                )
                await s.execute(text("DELETE FROM users WHERE email LIKE :u"), p)

        loop.run_until_complete(client.aclose())
        loop.run_until_complete(lifespan.__aexit__(None, None, None))
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


# -- who may ask at all ------------------------------------------------------


@pytest.mark.parametrize(
    "who,expected",
    [("super", 200), ("admin", 200), ("manager", 200), ("tutor", 403), ("student", 403), (None, 401)],
)
@pytest.mark.parametrize("path", ["/delegate-managers", "/delegate-managers/41/delegates"])
def test_only_organization_read_opens_these_routes(world, who, expected, path):  # noqa: ANN001, ANN201
    assert world.get(who, path).status_code == expected


def test_a_refused_caller_does_not_reach_the_upstream_service(world):  # noqa: ANN001, ANN201
    """A 403 is decided before the external call, so a tutor hammering the
    route cannot drive traffic (or cost) at LAIT on our key."""
    world.fake.calls.clear()
    assert world.get("student", "/delegate-managers").status_code == 403
    assert world.get("tutor", "/delegate-managers/41/delegates").status_code == 403
    assert world.fake.calls == []


# -- the email decision ------------------------------------------------------


def test_the_contact_holder_sees_the_managers_email(world):  # noqa: ANN001, ANN201
    rows = world.get("super", "/delegate-managers").json()
    by_id = {row["customer_id"]: row for row in rows}
    assert by_id[41]["email"] == "adam.copland@axcess.test"
    assert by_id[42]["email"] == "carla.gordon@wise.test"


@pytest.mark.parametrize("who", ["admin", "manager"])
def test_everybody_else_gets_the_address_withheld_not_renamed(world, who):  # noqa: ANN001, ANN201
    """`email: null` for a caller without `user.view_contact` -- and the
    address itself nowhere in the payload, so it cannot have survived under
    `username` or inside `full_name`."""
    response = world.get(who, "/delegate-managers")
    assert response.status_code == 200
    assert [row["email"] for row in response.json()] == [None, None]
    for address in ("adam.copland@axcess.test", "carla.gordon@wise.test"):
        assert address not in response.text


def test_the_rest_of_the_record_still_arrives_without_the_grant(world):  # noqa: ANN001, ANN201
    """Withholding the address must not empty the row -- otherwise the test
    above would pass against an endpoint that returns nothing useful."""
    rows = world.get("admin", "/delegate-managers").json()
    row = next(r for r in rows if r["customer_id"] == 41)
    assert row["company_name"] == "Axcess Payment Services Ltd"
    assert row["full_name"] == "Mr Adam J Copland"


def test_full_name_is_composed_from_the_parts_that_exist(world):  # noqa: ANN001, ANN201
    rows = {r["customer_id"]: r for r in world.get("super", "/delegate-managers").json()}
    assert rows[41]["full_name"] == "Mr Adam J Copland"
    assert rows[42]["full_name"] == "Carla Gordon"  # no title, no middle name


def test_a_manager_row_carries_what_the_companion_endpoint_needs(world):  # noqa: ANN001, ANN201
    rows = world.get("admin", "/delegate-managers").json()
    assert sorted(r["customer_id"] for r in rows) == [41, 42]
    inactive = next(r for r in rows if r["customer_id"] == 42)
    assert inactive["is_active"] is False  # not coerced to a default


# -- delegates ---------------------------------------------------------------


def test_delegates_arrive_wrapped_with_their_manager_named(world):  # noqa: ANN001, ANN201
    body = world.get("admin", "/delegate-managers/41/delegates").json()
    assert body["customer_id"] == 41
    assert body["count"] == 2
    assert [d["delegate_name"] for d in body["delegates"]] == ["Adam Copland", "Rita Shah"]
    assert body["delegates"][0]["student_id"] == 34143
    assert body["delegates"][1]["status_details"] == "Inactive"


def test_a_manager_with_nobody_is_an_empty_list_not_a_404(world):  # noqa: ANN001, ANN201
    response = world.get("admin", "/delegate-managers/42/delegates")
    assert response.status_code == 200
    assert response.json() == {"customer_id": 42, "count": 0, "delegates": []}


def test_an_id_upstream_has_never_heard_of_is_a_404(world):  # noqa: ANN001, ANN201
    """The distinction the wrapper exists for. Upstream answers 404 and so do
    we, rather than reporting somebody else's empty company."""
    assert world.get("admin", "/delegate-managers/99999999/delegates").status_code == 404


@pytest.mark.parametrize("raw", ["0", "-1", "abc"])
def test_a_customer_id_that_is_not_a_positive_integer_never_reaches_upstream(world, raw):  # noqa: ANN001, ANN201
    """The id is interpolated into an upstream URL path, so it is validated
    here: anything but a positive integer is refused before the call."""
    world.fake.calls.clear()
    assert world.get("admin", f"/delegate-managers/{raw}/delegates").status_code == 422
    assert world.fake.calls == []


# -- failure modes -----------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403, 500, 502])
@pytest.mark.parametrize("path", ["/delegate-managers", "/delegate-managers/41/delegates"])
def test_an_upstream_failure_is_503_and_carries_nothing_from_the_response(world, status, path):  # noqa: ANN001, ANN201
    """A refused key is 503, not 500: the fault is a configuration or an
    outage, not this request. And the upstream body -- which on these routes
    is people's names -- must not be relayed."""
    world.fake.fail_with = status
    response = world.get("admin", path)
    assert response.status_code == 503
    assert "upstream detail" not in response.text
    assert "fake-key" not in response.text
    assert "lait.test" not in response.text
