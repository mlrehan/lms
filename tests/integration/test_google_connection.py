"""GoogleConnectionService: the OAuth round-trip, and how the credential is stored.

Every database test runs inside a transaction that is rolled back, so nothing here can touch a
developer's real connection.
"""

from __future__ import annotations

import asyncio
import base64
import json
import selectors
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from backend.core.config import get_settings
from backend.core.errors import AuthorizationError, ServiceUnavailableError, ValidationError
from backend.db.manager import DatabaseManager
from backend.integrations.google_calendar import GoogleApiError
from backend.models.google_connection import GoogleConnection
from backend.models.identity.user import User
from backend.security import token_cipher
from backend.services.google_calendar_service import STATE_TTL_SECONDS, TOKEN_PURPOSE, GoogleConnectionService

REFRESH = "1//refresh-token-must-not-be-readable-at-rest"


def _settings(**over):  # noqa: ANN003, ANN202
    base = get_settings()
    google = base.google.model_copy(update={"client_id": "123456789012-abcdefghijklmnopqrstuvwxyz012345.apps.googleusercontent.com", "client_secret": SecretStr("secret"), "email": "org@lait.test", **over})
    return base.model_copy(update={"google": google})


def _id_token(email: str) -> str:
    return "h." + base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=") + ".s"


def _oauth(email: str, calls: list[str] | None = None) -> httpx.MockTransport:
    def route(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        if "revoke" in str(request.url):
            return httpx.Response(200)
        return httpx.Response(200, json={"refresh_token": REFRESH, "scope": "s1 s2", "id_token": _id_token(email)})
    return httpx.MockTransport(route)


@pytest.fixture()
def env():
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="google-conn-tests")

    def run(fn):  # noqa: ANN001, ANN202
        """Runs `fn(session, actor)` and ALWAYS rolls back."""
        async def go():  # noqa: ANN202
            async with db.session_factory() as s:
                actor = (await s.execute(select(User).where(User.username == "superadmin"))).scalar_one()
                try:
                    return await fn(s, actor)
                finally:
                    await s.rollback()
        return loop.run_until_complete(go())

    try:
        yield run
    finally:
        loop.run_until_complete(db.dispose())
        loop.close()


# --------------------------------------------------------------- state


def _svc(**over):  # noqa: ANN003, ANN202
    return GoogleConnectionService(None, _settings(**over))  # type: ignore[arg-type]


def test_a_state_round_trips_for_the_person_who_started_it() -> None:
    svc = _svc()
    svc.check_state(svc.make_state(7), 7)


def test_a_state_started_by_someone_else_is_refused() -> None:
    svc = _svc()
    with pytest.raises(AuthorizationError):
        svc.check_state(svc.make_state(7), 8)


def test_a_tampered_or_forged_state_is_refused() -> None:
    svc = _svc()
    body, sig = svc.make_state(7).split(".")
    forged = base64.urlsafe_b64encode(json.dumps({"u": 8, "e": int(time.time()) + 999, "n": "x"}).encode()).decode().rstrip("=")
    for bad in (f"{forged}.{sig}", f"{body}.{sig[:-2]}AA", "nonsense", "", f"{body}.", ".x"):
        with pytest.raises(ValidationError):
            svc.check_state(bad, 7)


def test_a_state_signed_with_another_secret_is_refused() -> None:
    a, b = _svc(), GoogleConnectionService(None, _settings().model_copy(update={"security": _settings().security.model_copy(update={"jwt_secret": SecretStr("a-completely-different-secret-value-0123456789")})}))  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        b.check_state(a.make_state(7), 7)


def test_an_expired_state_is_refused() -> None:
    svc = _svc()
    state = svc.make_state(7, now=time.time() - STATE_TTL_SECONDS - 5)
    with pytest.raises(ValidationError, match="too long"):
        svc.check_state(state, 7)


def test_the_consent_url_carries_a_state_that_belongs_to_the_caller() -> None:
    class U:
        id = 7

    svc = _svc()
    q = parse_qs(urlparse(svc.authorize_url(U())).query)  # type: ignore[arg-type]
    svc.check_state(q["state"][0], 7)


def test_connecting_is_refused_when_google_is_not_configured() -> None:
    class U:
        id = 1

    with pytest.raises(ServiceUnavailableError):
        _svc(client_id="", client_secret=SecretStr("")).authorize_url(U())  # type: ignore[arg-type]


# -------------------------------------------------------------- complete


def test_the_refresh_token_is_stored_encrypted_and_never_in_plaintext(env) -> None:
    async def go(s, actor):  # noqa: ANN001, ANN202
        svc = GoogleConnectionService(s, _settings(), oauth_transport=_oauth("org@lait.test"))
        conn = await svc.complete("CODE", svc.make_state(actor.id), actor)
        assert REFRESH not in conn.refresh_token_enc and conn.refresh_token_enc.startswith("v1:")
        assert token_cipher.decrypt(conn.refresh_token_enc, purpose=TOKEN_PURPOSE) == REFRESH
        assert (conn.account_email, conn.status, conn.connected_by_user_id) == ("org@lait.test", "ACTIVE", actor.id)
        with pytest.raises(token_cipher.TokenCipherError):
            token_cipher.decrypt(conn.refresh_token_enc, purpose="another-purpose")  # bound to its purpose

    env(go)


def test_signing_in_as_the_wrong_google_account_is_refused_and_stores_nothing(env) -> None:
    async def go(s, actor):  # noqa: ANN001, ANN202
        before = (await s.execute(select(GoogleConnection))).scalars().all()
        svc = GoogleConnectionService(s, _settings(), oauth_transport=_oauth("someone.else@gmail.com"))
        with pytest.raises(ValidationError, match="org@lait.test"):
            await svc.complete("CODE", svc.make_state(actor.id), actor)
        assert len((await s.execute(select(GoogleConnection))).scalars().all()) == len(before)

    env(go)


def test_a_forged_state_stops_the_flow_before_anything_is_sent_to_google(env) -> None:
    calls: list[str] = []

    async def go(s, actor):  # noqa: ANN001, ANN202
        svc = GoogleConnectionService(s, _settings(), oauth_transport=_oauth("org@lait.test", calls))
        with pytest.raises(ValidationError):
            await svc.complete("CODE", "forged.state", actor)
        assert calls == []  # the authorisation code was never exchanged

    env(go)


def test_connecting_again_replaces_the_active_connection_leaving_exactly_one(env) -> None:
    async def go(s, actor):  # noqa: ANN001, ANN202
        svc = GoogleConnectionService(s, _settings(), oauth_transport=_oauth("org@lait.test"))
        first = await svc.complete("C1", svc.make_state(actor.id), actor)
        second = await svc.complete("C2", svc.make_state(actor.id), actor)
        active = (await s.execute(select(GoogleConnection).where(GoogleConnection.status == "ACTIVE"))).scalars().all()
        assert [c.id for c in active] == [second.id] and first.status == "REVOKED"

    env(go)


def test_a_missing_refresh_token_is_reported_clearly(env) -> None:
    async def go(s, actor):  # noqa: ANN001, ANN202
        svc = GoogleConnectionService(s, _settings(), oauth_transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"access_token": "x"})))
        with pytest.raises(GoogleApiError, match="refresh token"):
            await svc.complete("CODE", svc.make_state(actor.id), actor)

    env(go)


# ------------------------------------------------------- disconnect, status


def test_disconnecting_revokes_at_google_and_marks_the_row(env) -> None:
    calls: list[str] = []

    async def go(s, actor):  # noqa: ANN001, ANN202
        svc = GoogleConnectionService(s, _settings(), oauth_transport=_oauth("org@lait.test", calls))
        await svc.complete("CODE", svc.make_state(actor.id), actor)
        assert await svc.disconnect(actor) is True
        assert any("revoke" in c for c in calls) and await svc.active() is None
        assert await svc.disconnect(actor) is False  # nothing left to disconnect

    env(go)


def test_the_status_exposes_no_secret_and_no_token(env) -> None:
    async def go(s, actor):  # noqa: ANN001, ANN202
        svc = GoogleConnectionService(s, _settings(), oauth_transport=_oauth("org@lait.test"))
        await svc.complete("CODE", svc.make_state(actor.id), actor)
        status = await svc.status()
        blob = json.dumps(status, default=str)
        assert REFRESH not in blob and "secret" not in blob.lower().replace("client_secret", "") and "refresh_token" not in blob
        assert status["connected"] and status["account_email"] == "org@lait.test" and status["redirect_uri"].endswith("/integrations/google/callback")

    env(go)


def test_connecting_with_a_wrong_client_id_explains_how_to_fix_it_instead_of_sending_the_user_to_google() -> None:
    class U:
        id = 1

    with pytest.raises(ServiceUnavailableError, match="does not look like a Google OAuth client ID"):
        _svc(client_id="x" * 80).authorize_url(U())  # type: ignore[arg-type]
