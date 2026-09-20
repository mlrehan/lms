"""The LAIT API client (backend/integrations/lait_client.py).

Runs against `httpx.MockTransport`: no network, no key.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Callable

import httpx
import pytest
from pydantic import SecretStr

from backend.core.config import LaitSettings
from backend.integrations import lait_client as lc
from backend.integrations.lait_client import LaitApiError, LaitClient

KEY = "k3y-that-must-never-leak-0123456789"
GUID = "e078ac1b-2d30-45ad-9d95-93b443e980cb"


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lc, "_BACKOFF_SECONDS", (0.0, 0.0))


def settings(**overrides: object) -> LaitSettings:
    values = dict(api_base_url="https://lait.test", api_key=SecretStr(KEY))
    values.update(overrides)
    return LaitSettings(**values)  # type: ignore[arg-type]


def client_for(handler: Callable[[httpx.Request], httpx.Response], **kw: object) -> LaitClient:
    return LaitClient(settings(**kw), transport=httpx.MockTransport(handler))


def run(coro):  # noqa: ANN001
    return asyncio.run(coro)


# --------------------------------------------------------------------- headers


def test_the_key_is_sent_as_x_api_key_and_not_as_a_bearer_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    async def go() -> None:
        async with client_for(handler) as c:
            await c.students_latest()

    run(go())
    assert seen[0].headers["X-API-Key"] == KEY
    assert "authorization" not in seen[0].headers  # Bearer is refused with 401 by LAIT
    assert seen[0].headers["User-Agent"].startswith("lms-lait-sync")  # ipapi-style UA lesson
    assert str(seen[0].url) == "https://lait.test/api/Students/latest"


def test_the_header_name_is_configurable() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    async def go() -> None:
        async with client_for(handler, api_key_header="X-Other") as c:
            await c.tutors()

    run(go())
    assert seen[0].headers["X-Other"] == KEY and "x-api-key" not in seen[0].headers


# -------------------------------------------------------------------- base url


@pytest.mark.parametrize("url", ["http://api.example.com", "ftp://x", "not a url", ""])
def test_a_cleartext_or_invalid_base_url_is_refused(url: str) -> None:
    with pytest.raises(LaitApiError):
        LaitClient(settings(api_base_url=url))


@pytest.mark.parametrize("url", ["http://127.0.0.1:9911", "http://localhost:8080", "https://api.example.com/"])
def test_https_and_loopback_are_accepted(url: str) -> None:
    async def go() -> None:
        async with LaitClient(settings(api_base_url=url), transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))):
            pass

    run(go())


def test_a_missing_key_is_refused_before_any_request() -> None:
    with pytest.raises(LaitApiError):
        LaitClient(settings(api_key=SecretStr("")))


# ------------------------------------------------------------------- redirects


def test_a_redirect_is_never_followed_so_the_key_cannot_be_forwarded() -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(302, headers={"Location": "https://attacker.test/steal"})

    async def go() -> None:
        async with client_for(handler) as c:
            await c.students_latest()

    with pytest.raises(LaitApiError):
        run(go())
    assert hosts == ["lait.test"]  # the second host was never contacted


# ------------------------------------------------------------- errors and retry


def test_a_refused_key_fails_at_once_without_retrying() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, text="nope")

    async def go() -> None:
        async with client_for(handler) as c:
            await c.students_latest()

    with pytest.raises(LaitApiError) as info:
        run(go())
    assert info.value.status == 401
    assert calls == 1  # retrying a refused key only invites a lockout


def test_a_server_error_is_retried_and_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503) if calls < 3 else httpx.Response(200, json=[{"a": 1}])

    async def go() -> list:
        async with client_for(handler) as c:
            return await c.tutors()

    assert run(go()) == [{"a": 1}]
    assert calls == 3


def test_a_persistent_server_error_gives_up_after_three_attempts() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async def go() -> None:
        async with client_for(handler) as c:
            await c.tutors()

    with pytest.raises(LaitApiError):
        run(go())
    assert calls == 3


def test_a_timeout_is_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json=[])

    async def go() -> None:
        async with client_for(handler) as c:
            await c.tutors()

    run(go())
    assert calls == 2


def test_error_messages_never_contain_the_response_body_or_the_key() -> None:
    """The bodies are people's personal data; the key is the credential."""
    pii = "Katie Suleiman 4 Chestnut Walk SG4 7SS"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=pii)

    async def go() -> None:
        async with client_for(handler) as c:
            await c.students_latest()

    with pytest.raises(LaitApiError) as info:
        run(go())
    text = str(info.value) + repr(info.value)
    assert "Katie" not in text and "Chestnut" not in text and KEY not in text


def test_a_body_that_is_not_json_is_an_error_without_echoing_it() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>Katie Suleiman</html>")

    async def go() -> None:
        async with client_for(handler) as c:
            await c.students_latest()

    with pytest.raises(LaitApiError) as info:
        run(go())
    assert "Katie" not in str(info.value)


def test_a_list_endpoint_that_returns_an_object_is_an_error() -> None:
    async def go() -> None:
        async with client_for(lambda r: httpx.Response(200, json={"a": 1})) as c:
            await c.students_latest()

    with pytest.raises(LaitApiError):
        run(go())


# --------------------------------------------------------------- by-guid lookups


def test_a_missing_record_is_none_not_an_error() -> None:
    async def go() -> object:
        async with client_for(lambda r: httpx.Response(404)) as c:
            return await c.tutor_by_guid(GUID)

    assert run(go()) is None


def test_by_guid_accepts_an_object_or_a_one_element_list() -> None:
    async def fetch(payload: object) -> object:
        async with client_for(lambda r: httpx.Response(200, json=payload)) as c:
            return await c.student_by_guid(uuid.UUID(GUID))

    assert run(fetch({"UserID": GUID})) == {"UserID": GUID}
    assert run(fetch([{"UserID": GUID}])) == {"UserID": GUID}
    assert run(fetch([])) is None


@pytest.mark.parametrize("bad", ["../../admin", "x?y=1", "", "e078ac1b/../x"])
def test_a_guid_is_validated_before_it_reaches_the_url(bad: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    async def go() -> None:
        async with client_for(handler) as c:
            await c.student_by_guid(bad)

    with pytest.raises(LaitApiError):
        run(go())
    assert requests == []  # nothing was sent


def test_the_guid_path_is_built_from_the_canonical_form() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={})

    async def go() -> None:
        async with client_for(handler) as c:
            await c.tutor_by_guid(GUID.upper())

    run(go())
    assert seen == [f"/api/Tutors/guid/{GUID}"]
