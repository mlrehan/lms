"""backend/integrations/google_calendar.py against httpx.MockTransport: no network, no Google."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Callable
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from pydantic import SecretStr

from backend.core.config import GoogleSettings
from backend.integrations import google_calendar as gc

SECRET = "client-secret-that-must-never-leak"
REFRESH = "refresh-token-that-must-never-leak"
CODE = "auth-code-1234567890"


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gc, "_BACKOFF", (0.0, 0.0, 0.0))


def settings(**over: object) -> GoogleSettings:
    values = dict(email="org@x.test", client_id="123456789012-abcdefghijklmnopqrstuvwxyz012345.apps.googleusercontent.com", client_secret=SecretStr(SECRET),
                  redirect_uri="http://localhost:3000/integrations/google/callback")
    values.update(over)
    return GoogleSettings(**values)  # type: ignore[arg-type]


def run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


def token_response(**over: object) -> httpx.Response:
    body = {"access_token": "AT-1", "expires_in": 3600}
    body.update(over)
    return httpx.Response(200, json=body)


def api(handler: Callable[[httpx.Request], httpx.Response]) -> gc.GoogleCalendarClient:
    """A client whose token endpoint always succeeds and whose API is `handler`."""
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return token_response()
        return handler(request)

    return gc.GoogleCalendarClient(settings(), REFRESH, transport=httpx.MockTransport(route), pace_seconds=0)


def err(status: int, reason: str, message: str = "boom SENSITIVE-BODY") -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": status, "message": message, "errors": [{"reason": reason}]}})


# ---------------------------------------------------------------- consent URL


def test_the_consent_url_asks_for_offline_access_and_only_the_calendar_scopes() -> None:
    url = gc.build_auth_url(settings(), "STATE123")
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert q["access_type"] == "offline" and q["prompt"] == "consent" and q["state"] == "STATE123"
    assert q["redirect_uri"] == "http://localhost:3000/integrations/google/callback" and q["login_hint"] == "org@x.test"
    scopes = set(q["scope"].split())
    assert "https://www.googleapis.com/auth/calendar.app.created" in scopes
    assert not any(x for x in scopes if "classroom" in x or "meet" in x or "youtube" in x)  # calendar only
    assert "https://www.googleapis.com/auth/calendar" not in scopes  # the broad scope is not requested
    assert SECRET not in url  # the secret is never part of a browser URL


# -------------------------------------------------------------- code exchange


def _id_token(email: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    return f"h.{payload}.s"


def test_the_code_exchange_returns_the_refresh_token_and_which_account_signed_in() -> None:
    def route(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert form["code"] == [CODE] and form["grant_type"] == ["authorization_code"]
        return httpx.Response(200, json={"refresh_token": REFRESH, "scope": "a b", "id_token": _id_token("Org@X.test")})

    result = run(gc.GoogleOAuth(settings(), transport=httpx.MockTransport(route)).exchange_code(CODE))
    assert result == {"refresh_token": REFRESH, "scope": "a b", "email": "org@x.test"}


def test_no_refresh_token_is_a_clear_error() -> None:
    oauth = gc.GoogleOAuth(settings(), transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"access_token": "x"})))
    with pytest.raises(gc.GoogleApiError, match="refresh token"):
        run(oauth.exchange_code(CODE))


def test_a_refused_exchange_leaks_neither_the_code_nor_the_secret_nor_the_body() -> None:
    oauth = gc.GoogleOAuth(settings(), transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "invalid_grant", "error_description": f"bad code {CODE} SENSITIVE"})))
    with pytest.raises(gc.GoogleApiError) as info:
        run(oauth.exchange_code(CODE))
    text = str(info.value) + repr(info.value)
    assert CODE not in text and SECRET not in text and "SENSITIVE" not in text


def test_a_revoked_grant_is_its_own_error() -> None:
    oauth = gc.GoogleOAuth(settings(), transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "invalid_grant"})))
    with pytest.raises(gc.GoogleAuthRevoked):
        run(oauth.access_token(REFRESH))


# --------------------------------------------------------------------- calls


def test_requests_carry_the_bearer_token_and_the_token_is_cached() -> None:
    seen: list[str] = []
    refreshes = 0

    def route(request: httpx.Request) -> httpx.Response:
        nonlocal refreshes
        if request.url.host == "oauth2.googleapis.com":
            refreshes += 1
            return token_response()
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json={"id": "cal"})

    async def go() -> None:
        async with gc.GoogleCalendarClient(settings(), REFRESH, transport=httpx.MockTransport(route), pace_seconds=0) as c:
            await c.get_calendar("a")
            await c.get_calendar("b")

    run(go())
    assert seen == ["Bearer AT-1", "Bearer AT-1"] and refreshes == 1


def test_a_401_refreshes_once_and_retries() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": {"errors": [{"reason": "authError"}]}}) if calls == 1 else httpx.Response(200, json={"id": "x"})

    async def go() -> dict:
        async with api(handler) as c:
            return await c.get_calendar("a")

    assert run(go()) == {"id": "x"} and calls == 2


def test_a_persistent_401_gives_up() -> None:
    async def go() -> None:
        async with api(lambda r: httpx.Response(401, json={})) as c:
            await c.get_calendar("a")

    with pytest.raises(gc.GoogleApiError):
        run(go())


def test_usage_limit_403s_are_retried_but_other_403s_are_not() -> None:
    calls = 0

    def limited(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return err(403, "rateLimitExceeded") if calls < 3 else httpx.Response(200, json={"id": "ok"})

    async def go(handler) -> dict:  # noqa: ANN001
        async with api(handler) as c:
            return await c.create_event("cal", {}, send_updates="none")

    assert run(go(limited)) == {"id": "ok"} and calls == 3

    forbidden = 0

    def no_access(request: httpx.Request) -> httpx.Response:
        nonlocal forbidden
        forbidden += 1
        return err(403, "forbidden")

    with pytest.raises(gc.GoogleApiError) as info:
        run(go(no_access))
    assert forbidden == 1 and info.value.status == 403  # a final answer is not retried


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_statuses_are_retried_up_to_the_limit(status: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={})

    async def go() -> None:
        async with api(handler) as c:
            await c.get_calendar("a")

    with pytest.raises(gc.GoogleApiError):
        run(go())
    assert calls == 4


@pytest.mark.parametrize("status", [404, 410])
def test_missing_things_are_a_distinct_error(status: int) -> None:
    async def go() -> None:
        async with api(lambda r: err(status, "notFound")) as c:
            await c.delete_event("cal", "ev", send_updates="none")

    with pytest.raises(gc.GoogleNotFound):
        run(go())


def test_a_delete_returns_nothing_on_204() -> None:
    async def go() -> object:
        async with api(lambda r: httpx.Response(204)) as c:
            return await c.delete_event("cal", "ev", send_updates="none")

    assert run(go()) is None


def test_errors_never_contain_the_response_body_or_any_token() -> None:
    async def go() -> None:
        async with api(lambda r: err(400, "invalid", f"echo {REFRESH} SENSITIVE-BODY")) as c:
            await c.create_calendar({})

    with pytest.raises(gc.GoogleApiError) as info:
        run(go())
    text = str(info.value) + repr(info.value)
    assert REFRESH not in text and SECRET not in text and "SENSITIVE-BODY" not in text and "AT-1" not in text


def test_the_client_repr_hides_the_token() -> None:
    c = gc.GoogleCalendarClient(settings(), REFRESH, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    assert REFRESH not in repr(c) and SECRET not in repr(c)


def test_ids_are_percent_encoded_into_the_path() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path.decode())
        return httpx.Response(200, json={})

    async def go() -> None:
        async with api(handler) as c:
            await c.get_calendar("a/../b@group.calendar.google.com")

    run(go())
    assert seen == ["/calendar/v3/calendars/a%2F..%2Fb%40group.calendar.google.com"]  # cannot escape the calendar path


def test_list_events_follows_every_page_and_passes_updated_min() -> None:
    pages = {None: {"items": [{"id": "1"}], "nextPageToken": "T"}, "T": {"items": [{"id": "2"}]}}
    queries: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        q = dict(request.url.params)
        queries.append(q)
        return httpx.Response(200, json=pages[q.get("pageToken")])

    async def go() -> list:
        async with api(handler) as c:
            return await c.list_events("cal", updated_min="2026-09-20T00:00:00Z", show_deleted=True)

    assert [e["id"] for e in run(go())] == ["1", "2"]
    assert queries[0]["updatedMin"] == "2026-09-20T00:00:00Z" and queries[0]["showDeleted"] == "true"


def test_sharing_never_notifies_by_email() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={})

    async def go() -> None:
        async with api(handler) as c:
            await c.share_calendar("cal", "admin@x.test")

    run(go())
    assert seen[0]["sendNotifications"] == "false"


# ------------------------------------------------------- configuration check

VALID_ID = "123456789012-abcdefghijklmnopqrstuvwxyz012345.apps.googleusercontent.com"


@pytest.mark.parametrize("client_id", [
    "",                                    # not set
    "abcdefghijklmnopqrstuvwxyz" * 3,      # the wrong kind of value entirely (a long token)
    "AIzaSyD-not-a-client-id-it-is-an-api-key-0123456789",
    "123456789012.apps.googleusercontent.com",           # no middle part
    "abc-123456789012.apps.googleusercontent.com",       # must start with the project number
    VALID_ID.replace(".apps.googleusercontent.com", ""), # suffix missing
    VALID_ID + "x",                                       # trailing junk
])
def test_a_value_that_is_not_a_google_client_id_is_reported_with_a_fix(client_id: str) -> None:
    problem = settings(client_id=client_id).configuration_problem
    assert problem is not None and "GOOGLE_CLIENT_ID" in problem
    assert settings(client_id=client_id).is_configured is False


def test_a_real_looking_client_id_and_secret_are_accepted() -> None:
    assert settings(client_id=VALID_ID).configuration_problem is None and settings(client_id=VALID_ID).is_configured


def test_a_missing_secret_is_reported() -> None:
    assert "GOOGLE_CLIENT_SECRET" in (settings(client_secret=SecretStr("")).configuration_problem or "")


def test_the_problem_message_never_contains_the_value_it_rejected() -> None:
    bad = "supersecretvalue-that-was-pasted-by-mistake"
    assert bad not in (settings(client_id=bad).configuration_problem or "")


@pytest.mark.parametrize("pasted", [
    f"http://{VALID_ID}/",       # a link-ified paste, as found in a real .env
    f"https://{VALID_ID}",
    f'"{VALID_ID}"', f"'{VALID_ID}'", f"  {VALID_ID}  ", f"{VALID_ID}/",
])
def test_a_client_id_pasted_as_a_link_or_with_quotes_is_tidied(pasted: str) -> None:
    s = settings(client_id=pasted)
    assert s.client_id == VALID_ID and s.is_configured


def test_tidying_never_turns_a_wrong_value_into_an_accepted_one() -> None:
    for bad in ("http://not-a-client-id/", "https://example.com/" + VALID_ID.split("-")[1], "'garbage'"):
        assert settings(client_id=bad).is_configured is False
