"""The address and location on a real audit row, through the real application.

A sign-in with an unknown identifier is driven over ASGI with a chosen socket
peer, so the whole path runs: the middleware resolves the address, the auth
service writes LOGIN_FAILED in its own transaction, and the row lands in
Postgres. The location database is a stand-in reader (the real GeoLite2 file
needs a MaxMind account); everything else is the production code.

Audit rows cannot be deleted (append-only by trigger), so each run leaves its
few LOGIN_FAILED rows behind, tagged with a unique identifier.
"""

from __future__ import annotations

import asyncio
import selectors
import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text

from backend.api import middleware
from backend.core.config import GeoIPSettings, get_settings
from backend.db.manager import DatabaseManager
from backend.integrations.geoip import GeoLocator, set_locator
from backend.main import app

DHAKA = {
    "city": {"names": {"en": "Dhaka"}},
    "country": {"iso_code": "BD", "names": {"en": "Bangladesh"}},
    "subdivisions": [{"names": {"en": "Dhaka Division"}}],
    "location": {"latitude": 23.7104, "longitude": 90.4074, "accuracy_radius": 20},
}


class Reader:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def get(self, ip):  # noqa: ANN001, ANN201
        if self.fail:
            raise OSError("corrupt database")
        return {"103.170.173.46": DHAKA}.get(ip)


@pytest.fixture()
def env(monkeypatch):  # noqa: ANN001, ANN201
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="audit-client-ip-tests")
    # The deployment's trust list, independent of this machine's .env (settings are frozen,
    # so the middleware's lookup is what is replaced).
    trusted = SimpleNamespace(server=SimpleNamespace(forwarded_allow_ips="127.0.0.1,::1,172.16.0.0/12"))
    monkeypatch.setattr(middleware, "get_settings", lambda: trusted)
    lifespan = app.router.lifespan_context(app)
    loop.run_until_complete(lifespan.__aenter__())

    def attempt(peer: str, headers: dict[str, str] | None = None, reader: Reader | None = None):  # noqa: ANN202
        set_locator(GeoLocator(GeoIPSettings(), reader=reader or Reader(), source="GeoLite2-City test"))
        tag = f"ipaudit-{uuid.uuid4().hex[:10]}@t.test"

        async def go():  # noqa: ANN202
            transport = httpx.ASGITransport(app=app, client=(peer, 50123))
            async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
                r = await client.post("/api/v1/auth/login", json={"identifier": tag, "password": "wrong-password-123"},
                                      headers=headers or {})
                assert r.status_code == 401
            async with db.session_factory() as s:
                return (await s.execute(text(
                    "SELECT ip_address, ip_scope, geo_status, geo_city, geo_region, geo_country, geo_country_code, "
                    "geo_latitude, geo_longitude, geo_accuracy_km, geo_source "
                    "FROM audit_logs WHERE actor_email = :e AND action = 'LOGIN_FAILED'"), {"e": tag})).mappings().one()
        return loop.run_until_complete(go())

    try:
        yield attempt
    finally:
        set_locator(None)
        loop.run_until_complete(lifespan.__aexit__(None, None, None))
        loop.run_until_complete(db.dispose())
        loop.close()


def test_the_browser_address_the_proxy_appended_is_recorded_and_located(env):  # noqa: ANN001
    row = env("127.0.0.1", {"X-Forwarded-For": "6.6.6.6, 103.170.173.46"})
    assert (row["ip_address"], row["ip_scope"]) == ("103.170.173.46", "PUBLIC")
    assert row["geo_status"] == "OK"
    assert (row["geo_city"], row["geo_region"], row["geo_country"], row["geo_country_code"]) == (
        "Dhaka", "Dhaka Division", "Bangladesh", "BD",
    )
    assert (row["geo_latitude"], row["geo_longitude"], row["geo_accuracy_km"]) == (23.7104, 90.4074, 20)
    assert row["geo_source"] == "GeoLite2-City test"


def test_a_proxy_that_passes_no_address_is_recorded_as_unknown_not_as_itself(env):  # noqa: ANN001
    row = env("127.0.0.1")
    assert (row["ip_address"], row["ip_scope"], row["geo_status"]) == (None, "UNAVAILABLE", "NOT_APPLICABLE")


def test_a_direct_caller_cannot_forge_its_address(env):  # noqa: ANN001
    row = env("81.2.69.142", {"X-Forwarded-For": "103.170.173.46", "X-Real-IP": "103.170.173.46"})
    assert (row["ip_address"], row["ip_scope"]) == ("81.2.69.142", "PUBLIC")
    assert row["geo_status"] == "NOT_FOUND"  # the stand-in database does not know it


def test_ipv6_through_the_proxy(env):  # noqa: ANN001
    row = env("::1", {"X-Forwarded-For": "2a02:c204:2110:73::99"})
    assert (row["ip_address"], row["ip_scope"]) == ("2a02:c204:2110:73::99", "PUBLIC")


def test_a_private_address_is_recorded_without_a_location(env):  # noqa: ANN001
    row = env("172.18.0.4", {"X-Forwarded-For": "192.168.10.196"})
    assert (row["ip_address"], row["ip_scope"], row["geo_status"], row["geo_city"]) == (
        "192.168.10.196", "PRIVATE", "NOT_APPLICABLE", None,
    )


def test_a_failing_location_database_still_writes_the_audit_row(env):  # noqa: ANN001
    row = env("127.0.0.1", {"X-Forwarded-For": "103.170.173.46"}, reader=Reader(fail=True))
    assert (row["ip_address"], row["geo_status"], row["geo_city"]) == ("103.170.173.46", "ERROR", None)
