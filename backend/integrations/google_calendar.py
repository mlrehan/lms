"""A small Google Calendar client over httpx (no Google SDK).

Only the calls the LMS needs, so the whole surface is readable here. Properties that matter:

* **Tokens never appear in an error, a log line or a repr.** Errors carry an HTTP status and
  Google's machine-readable `reason`, nothing else -- Google's error bodies can echo request
  details, and a refresh token is the institution's standing access to its calendar.
* **Quota errors are retried, other errors are not.** Google reports "calendar usage limits
  exceeded" as a 403 (`rateLimitExceeded`), not a 429; a 403 for any other reason (no access,
  scope missing) is final and retrying it only delays the real message.
* **Writes are paced.** Creating many events in a burst is what triggers those limits, so a
  short pause between writes is cheaper than the retries it avoids.
* **Access tokens are cached until shortly before they expire**, and a 401 forces one refresh.
* **A revoked grant is a distinct error** (`GoogleAuthRevoked`) so the caller can mark the
  connection as needing to be re-authorised rather than retrying for ever.
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from backend.core.config import GoogleSettings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API_BASE = "https://www.googleapis.com/calendar/v3"

_RETRY_STATUS = {429, 500, 502, 503, 504}
_QUOTA_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "backendError"}
_ATTEMPTS = 4
_BACKOFF = (1.0, 2.5, 6.0)
_EXPIRY_MARGIN = 60


class GoogleApiError(Exception):
    def __init__(self, message: str, *, status: int | None = None, reason: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.reason = reason


class GoogleNotFound(GoogleApiError):
    """404/410: the calendar or event does not exist (any more)."""


class GoogleAuthRevoked(GoogleApiError):
    """The refresh token was revoked or expired: the connection must be re-authorised."""


def build_auth_url(settings: GoogleSettings, state: str) -> str:
    params = {
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "scope": " ".join(settings.scopes),
        # `offline` + `consent` is what makes Google return a refresh token, and return it again
        # when the account has authorised this client before.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
        "state": state,
    }
    if settings.email:
        params["login_hint"] = settings.email
    return f"{AUTH_URL}?{urlencode(params)}"


def _id_token_claims(id_token: str) -> dict[str, Any]:
    """Claims from an id_token received *directly from Google's token endpoint over TLS*.

    Google's documentation allows skipping signature verification in exactly that case, and it
    is only used to check which account signed in -- not to authenticate a request.
    """
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError):
        return {}


class GoogleOAuth:
    def __init__(self, settings: GoogleSettings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._s = settings
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._s.request_timeout_seconds, transport=self._transport, follow_redirects=False)

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Returns `{refresh_token, scope, email}`. Raises GoogleApiError if Google refuses."""
        async with self._client() as http:
            try:
                r = await http.post(TOKEN_URL, data={
                    "code": code, "client_id": self._s.client_id, "client_secret": self._s.client_secret.get_secret_value(),
                    "redirect_uri": self._s.redirect_uri, "grant_type": "authorization_code",
                })
            except httpx.HTTPError as exc:
                raise GoogleApiError(f"token exchange failed ({type(exc).__name__})") from None
        if r.status_code != 200:
            raise GoogleApiError(f"Google refused the authorisation ({_reason(r) or r.status_code}).", status=r.status_code, reason=_reason(r))
        body = r.json()
        if not body.get("refresh_token"):
            raise GoogleApiError("Google did not return a refresh token. Remove this app's access in your Google account and connect again.")
        return {
            "refresh_token": body["refresh_token"],
            "scope": body.get("scope", ""),
            "email": str(_id_token_claims(body.get("id_token", "")).get("email", "")).lower(),
        }

    async def access_token(self, refresh_token: str) -> tuple[str, float]:
        async with self._client() as http:
            try:
                r = await http.post(TOKEN_URL, data={
                    "refresh_token": refresh_token, "client_id": self._s.client_id,
                    "client_secret": self._s.client_secret.get_secret_value(), "grant_type": "refresh_token",
                })
            except httpx.HTTPError as exc:
                raise GoogleApiError(f"token refresh failed ({type(exc).__name__})") from None
        if r.status_code == 400 and _reason(r) in ("invalid_grant", "invalid_request"):
            raise GoogleAuthRevoked("Google no longer accepts this connection; connect it again.", status=400, reason="invalid_grant")
        if r.status_code != 200:
            raise GoogleApiError(f"token refresh failed ({r.status_code}).", status=r.status_code, reason=_reason(r))
        body = r.json()
        return body["access_token"], time.monotonic() + float(body.get("expires_in", 3600)) - _EXPIRY_MARGIN

    async def revoke(self, token: str) -> None:
        async with self._client() as http:
            try:
                await http.post(REVOKE_URL, data={"token": token})
            except httpx.HTTPError:
                pass  # best effort: the local record is what matters


def _reason(response: httpx.Response) -> str | None:
    try:
        data = response.json()
    except ValueError:
        return None
    err = data.get("error")
    if isinstance(err, str):
        return err
    if isinstance(err, dict):
        errors = err.get("errors") or []
        if errors and isinstance(errors[0], dict):
            return errors[0].get("reason")
        return err.get("status")
    return None


class GoogleCalendarClient:
    def __init__(
        self,
        settings: GoogleSettings,
        refresh_token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        oauth_transport: httpx.AsyncBaseTransport | None = None,
        pace_seconds: float = 0.12,
    ) -> None:
        self._s = settings
        self._refresh_token = refresh_token
        self._oauth = GoogleOAuth(settings, transport=oauth_transport or transport)
        self._http = httpx.AsyncClient(base_url=API_BASE, timeout=settings.request_timeout_seconds, follow_redirects=False, transport=transport)
        self._token: str | None = None
        self._expires = 0.0
        self._pace = pace_seconds

    async def __aenter__(self) -> "GoogleCalendarClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._http.aclose()

    def __repr__(self) -> str:  # never show the token
        return "<GoogleCalendarClient>"

    async def _bearer(self, *, force: bool = False) -> str:
        if force or self._token is None or time.monotonic() >= self._expires:
            self._token, self._expires = await self._oauth.access_token(self._refresh_token)
        return self._token

    async def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: Any = None, write: bool = False) -> dict[str, Any] | None:
        if write and self._pace:
            await asyncio.sleep(self._pace)
        refreshed = False
        last: GoogleApiError | None = None
        for attempt in range(_ATTEMPTS):
            try:
                response = await self._http.request(
                    method, path, params=params, json=json_body,
                    headers={"Authorization": f"Bearer {await self._bearer()}"},
                )
            except httpx.TimeoutException:
                last = GoogleApiError(f"{method} {path}: timed out")
            except httpx.HTTPError as exc:
                last = GoogleApiError(f"{method} {path}: transport error ({type(exc).__name__})")
            else:
                status = response.status_code
                if status in (200, 201):
                    return response.json()
                if status == 204:
                    return None
                reason = _reason(response)
                if status == 401 and not refreshed:
                    refreshed = True
                    await self._bearer(force=True)
                    continue
                if status in (404, 410):
                    raise GoogleNotFound(f"{method} {path}: not found", status=status, reason=reason)
                retryable = status in _RETRY_STATUS or (status == 403 and reason in _QUOTA_REASONS)
                last = GoogleApiError(f"{method} {path}: HTTP {status} ({reason or 'no reason'})", status=status, reason=reason)
                if not retryable:
                    raise last
            if attempt < _ATTEMPTS - 1:
                await asyncio.sleep(_BACKOFF[attempt] * (0.75 + random.random() / 2))
        assert last is not None
        raise last

    # ------------------------------------------------------------- calendars

    async def create_calendar(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/calendars", json_body=body, write=True) or {}

    async def patch_calendar(self, calendar_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", f"/calendars/{_q(calendar_id)}", json_body=body, write=True) or {}

    async def get_calendar(self, calendar_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/calendars/{_q(calendar_id)}") or {}

    async def delete_calendar(self, calendar_id: str) -> None:
        await self._request("DELETE", f"/calendars/{_q(calendar_id)}", write=True)

    async def share_calendar(self, calendar_id: str, email: str, role: str = "writer") -> None:
        """Idempotent: an existing rule for this person is not an error."""
        try:
            await self._request(
                "POST", f"/calendars/{_q(calendar_id)}/acl", params={"sendNotifications": "false"},
                json_body={"role": role, "scope": {"type": "user", "value": email}}, write=True,
            )
        except GoogleApiError as exc:
            if exc.status != 409:
                raise

    # ---------------------------------------------------------------- events

    async def create_event(self, calendar_id: str, body: dict[str, Any], *, send_updates: str) -> dict[str, Any]:
        return await self._request("POST", f"/calendars/{_q(calendar_id)}/events", params={"sendUpdates": send_updates}, json_body=body, write=True) or {}

    async def patch_event(self, calendar_id: str, event_id: str, body: dict[str, Any], *, send_updates: str) -> dict[str, Any]:
        return await self._request("PATCH", f"/calendars/{_q(calendar_id)}/events/{_q(event_id)}", params={"sendUpdates": send_updates}, json_body=body, write=True) or {}

    async def delete_event(self, calendar_id: str, event_id: str, *, send_updates: str) -> None:
        await self._request("DELETE", f"/calendars/{_q(calendar_id)}/events/{_q(event_id)}", params={"sendUpdates": send_updates}, write=True)

    async def list_events(
        self, calendar_id: str, *, updated_min: str | None = None, show_deleted: bool = False
    ) -> list[dict[str, Any]]:
        """Every page. `singleEvents` is off on purpose: the LMS creates plain, non-recurring events."""
        events: list[dict[str, Any]] = []
        token: str | None = None
        while True:
            params: dict[str, Any] = {"maxResults": 250, "showDeleted": str(show_deleted).lower()}
            if updated_min:
                params["updatedMin"] = updated_min
            if token:
                params["pageToken"] = token
            page = await self._request("GET", f"/calendars/{_q(calendar_id)}/events", params=params) or {}
            events.extend(page.get("items", []))
            token = page.get("nextPageToken")
            if not token:
                return events


def _q(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")
