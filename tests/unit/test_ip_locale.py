"""The IP lookup client: validation, parsing, caching and never raising."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.core.config import LocaleSettings
from backend.integrations.ip_locale import IpLocaleClient, is_public, parse_ip

SAMPLE = {
    "ip": "103.170.173.113", "city": "Dhaka", "region": "Dhaka Division", "country": "BD", "country_name": "Bangladesh",
    "timezone": "Asia/Dhaka", "utc_offset": "+0600", "latitude": 23.71, "longitude": 90.40, "currency": "BDT", "org": "AG Communication",
    "country_population": 161356039,
}


def _client(handler, **overrides):  # noqa: ANN001, ANN202
    calls: list[str] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return handler(request)

    settings = LocaleSettings(**overrides)
    return IpLocaleClient(settings, transport=httpx.MockTransport(wrapped)), calls


def run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


@pytest.mark.parametrize("raw, expected", [
    ("103.170.173.113", "103.170.173.113"), (" 8.8.8.8 ", "8.8.8.8"), ("8.8.8.8:5555", "8.8.8.8"), ("[2001:4860:4860::8888]:443", "2001:4860:4860::8888"),
    ("2001:4860:4860::8888", "2001:4860:4860::8888"), ("", None), (None, None), ("not-an-ip", None), ("8.8.8.8/../../admin", None), ("1.2.3", None),
])
def test_parse_ip_accepts_only_real_addresses(raw, expected) -> None:  # noqa: ANN001
    assert parse_ip(raw) == expected


@pytest.mark.parametrize("ip, public", [("8.8.8.8", True), ("103.170.173.113", True), ("127.0.0.1", False), ("10.0.0.5", False), ("192.168.1.9", False),
                                          ("172.16.0.1", False), ("169.254.169.254", False), ("::1", False), (None, False), ("", False)])
def test_only_public_addresses_are_worth_looking_up(ip, public) -> None:  # noqa: ANN001
    assert is_public(ip) is public


def test_a_lookup_returns_the_zone_and_keeps_only_what_is_useful() -> None:
    client, calls = _client(lambda r: httpx.Response(200, json=SAMPLE))
    result = run(client.lookup("103.170.173.113"))
    assert result and result.timezone == "Asia/Dhaka" and result.info["city"] == "Dhaka" and result.info["country_name"] == "Bangladesh"
    assert "country_population" not in result.info and "currency" not in result.info
    assert calls == ["https://ipapi.co/103.170.173.113/json/"]


def test_the_same_address_is_looked_up_once() -> None:
    client, calls = _client(lambda r: httpx.Response(200, json=SAMPLE))

    async def twice() -> None:
        await client.lookup("103.170.173.113")
        await client.lookup("103.170.173.113")

    run(twice())
    assert len(calls) == 1


def test_a_private_address_is_never_sent_anywhere() -> None:
    client, calls = _client(lambda r: httpx.Response(200, json=SAMPLE))
    assert run(client.lookup("192.168.0.4")) is None and run(client.lookup("garbage")) is None
    assert calls == []


def test_a_zone_that_is_not_a_real_one_is_dropped_rather_than_stored() -> None:
    client, _ = _client(lambda r: httpx.Response(200, json={**SAMPLE, "timezone": "Mars/Olympus"}))
    result = run(client.lookup("103.170.173.113"))
    assert result is not None and result.timezone is None and result.info["city"] == "Dhaka"


@pytest.mark.parametrize("response", [httpx.Response(429, json={"error": True}), httpx.Response(500), httpx.Response(200, json={"error": True, "reason": "RateLimited"}),
                                      httpx.Response(200, text="<html>nope</html>")])
def test_a_refusal_or_garbage_is_no_answer_not_an_exception(response) -> None:  # noqa: ANN001
    client, _ = _client(lambda r: response)
    assert run(client.lookup("103.170.173.113")) is None


def test_a_network_failure_is_no_answer_and_is_not_retried_at_once() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client, calls = _client(boom)

    async def twice() -> None:
        assert await client.lookup("103.170.173.113") is None
        assert await client.lookup("103.170.173.113") is None

    run(twice())
    assert len(calls) == 1  # the failure is remembered for the back-off period


def test_the_servers_own_public_address_is_read_and_validated() -> None:
    client, calls = _client(lambda r: httpx.Response(200, text="103.170.173.113\n"))
    assert run(client.public_ip()) == "103.170.173.113" and calls == ["https://icanhazip.com"]
    bad, _ = _client(lambda r: httpx.Response(200, text="<html>captcha</html>"))
    assert run(bad.public_ip()) is None
