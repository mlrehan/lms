"""Sign-in address -> time zone: when it is looked up, when it changes the zone, and when it must not."""

from __future__ import annotations

import asyncio
import random
import selectors

import pytest
from sqlalchemy import select, text

from backend.core.config import LocaleSettings
from backend.db.manager import DatabaseManager
from backend.core.config import get_settings
from backend.integrations.ip_locale import IpLocale
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.services.locale_service import UserLocaleService
from backend.utils.enums import UserStatus


class FakeClient:
    """Stands in for the network: a table of address -> answer, and a count of how often it was asked."""

    def __init__(self, table: dict[str, tuple[str | None, str]], server_ip: str | None = "103.170.173.113") -> None:
        self.table, self.server_ip, self.lookups, self.public_calls = table, server_ip, [], 0

    async def lookup(self, ip: str):  # noqa: ANN202
        self.lookups.append(ip)
        if ip not in self.table:
            return None
        zone, city = self.table[ip]
        return IpLocale(ip=ip, timezone=zone, info={"city": city, "timezone": zone, "country_name": "X"})

    async def public_ip(self):  # noqa: ANN202
        self.public_calls += 1
        return self.server_ip


DHAKA, LONDON = "103.170.173.113", "81.2.69.142"
TABLE = {DHAKA: ("Asia/Dhaka", "Dhaka"), LONDON: ("Europe/London", "London")}


@pytest.fixture()
def env():
    tag = f"loc{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="locale-tests")

    async def build() -> None:
        async with db.session_factory.begin() as s:
            role = (await s.execute(select(Role).where(Role.name == "STUDENT"))).scalar_one()
            s.add(User(username=f"{tag}.u", slug=f"{tag}-u", email=f"{tag}.u@t.test", hashed_password="x", status=UserStatus.ACTIVE, roles=[role]))

    loop.run_until_complete(build())

    def refresh(client: FakeClient, ip: str | None, *, timezone: str | None = "keep", is_auto: bool | None = None, **settings):  # noqa: ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                user = (await s.execute(select(User).where(User.username == f"{tag}.u"))).scalar_one()
                if timezone != "keep":
                    user.timezone = timezone
                if is_auto is not None:
                    user.timezone_is_auto = is_auto
                result = await UserLocaleService(s, settings=LocaleSettings(**settings), client=client).refresh(user, client_ip=ip)  # type: ignore[arg-type]
                return result
        return loop.run_until_complete(go())

    def stored():  # noqa: ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory() as s:
                u = (await s.execute(select(User).where(User.username == f"{tag}.u"))).scalar_one()
                return u.timezone, u.timezone_is_auto, u.locale_ip, (u.locale_info or {}).get("city")
        return loop.run_until_complete(go())

    ns = type("E", (), dict(refresh=staticmethod(refresh), stored=staticmethod(stored)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                await s.execute(text("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), {"u": f"{tag}.%"})
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), {"u": f"{tag}.%"})
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def test_a_first_sign_in_records_the_place_and_fills_in_the_time_zone(env) -> None:
    client = FakeClient(TABLE)
    result = env.refresh(client, DHAKA)
    assert result.ip_changed and result.timezone_changed and result.timezone == "Asia/Dhaka"
    assert env.stored() == ("Asia/Dhaka", True, DHAKA, "Dhaka")


def test_the_same_address_again_costs_no_lookup_at_all(env) -> None:
    client = FakeClient(TABLE)
    env.refresh(client, DHAKA)
    result = env.refresh(client, DHAKA)
    assert client.lookups == [DHAKA] and not result.ip_changed  # one lookup across both sign-ins


def test_a_new_address_is_looked_up_and_moves_an_automatic_time_zone(env) -> None:
    client = FakeClient(TABLE)
    env.refresh(client, DHAKA)
    result = env.refresh(client, LONDON)
    assert client.lookups == [DHAKA, LONDON] and result.ip_changed and result.timezone_changed
    assert env.stored() == ("Europe/London", True, LONDON, "London")


def test_a_time_zone_the_person_chose_is_never_overwritten(env) -> None:
    client = FakeClient(TABLE)
    result = env.refresh(client, LONDON, timezone="Asia/Tokyo", is_auto=False)
    assert result.ip_changed and not result.timezone_changed
    assert env.stored() == ("Asia/Tokyo", False, LONDON, "London")     # the place is recorded; the zone is left alone


def test_a_private_address_uses_the_servers_public_one(env) -> None:
    client = FakeClient(TABLE)
    result = env.refresh(client, "127.0.0.1")
    assert client.public_calls == 1 and client.lookups == [DHAKA] and result.timezone == "Asia/Dhaka"


def test_with_the_fallback_off_a_private_address_does_nothing(env) -> None:
    client = FakeClient(TABLE)
    result = env.refresh(client, "10.1.2.3", use_server_ip_fallback=False)
    assert client.public_calls == 0 and client.lookups == [] and not result.ip_changed and env.stored()[0] is None


def test_a_failed_lookup_changes_nothing(env) -> None:
    client = FakeClient({})
    result = env.refresh(client, DHAKA)
    assert not result.ip_changed and env.stored() == (None, False, None, None)


def test_switched_off_means_no_network_at_all(env) -> None:
    client = FakeClient(TABLE)
    env.refresh(client, DHAKA, enabled=False)
    assert client.lookups == [] and client.public_calls == 0


def test_a_lookup_that_raises_cannot_break_a_sign_in(env) -> None:
    class Exploding(FakeClient):
        async def lookup(self, ip: str):  # noqa: ANN202
            raise RuntimeError("boom")

    async def go() -> None:
        async with DatabaseManager(get_settings().database, application_name="x").session_factory() as s:
            user = User(username="ghost", slug="ghost", email="g@t.test", hashed_password="x", status=UserStatus.ACTIVE)
            result = await UserLocaleService(s, settings=LocaleSettings(), client=Exploding(TABLE)).refresh_quietly(user, client_ip=DHAKA)  # type: ignore[arg-type]
            assert not result.ip_changed

    asyncio.run(go(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
