"""Client for the LAIT external API.

Read-only: it fetches student and tutor records and does nothing else. The
four endpoints, as observed against the live service:

    GET /api/Students/latest        recent registrations only (see below)
    GET /api/Tutors                 the tutor list
    GET /api/Students/guid/{id}     one student, same shape as the list row
    GET /api/Tutors/guid/{id}       one tutor, plus `email_id`

**`/api/Students/latest` is a recent-registrations feed, not the roster.** It
returned 18 students whose ids ran 34951-34978, all registered inside the
last few weeks, while the highest id is in the tens of thousands. A record
that is absent from it has not been deleted -- it has simply not registered
recently. Nothing in this client, or in the sync built on it, infers a
removal from absence.

Security notes, each of which is a decision rather than an accident:

* **Redirects are never followed.** httpx strips `Authorization` when a
  redirect crosses origins but *not* a custom header like `X-API-Key`, so
  following one would hand the key to whichever host the response named.
* **https only, except loopback.** The key travels on every request; sending
  it in cleartext is not a configuration option. Loopback is allowed so the
  client can be exercised against a local stand-in without a certificate.
* **Errors carry a status and a path, never a body.** These responses are
  people's names, addresses and phone numbers; they must not end up in a log
  line or in `user_sync_runs.errors` because a parse failed.
* **The key is read from a `SecretStr` at the last moment** and only placed in
  a request header. It is never logged and never part of an exception.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from urllib.parse import urlsplit

import httpx

from backend.core.config import LaitSettings

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_USER_AGENT = "lms-lait-sync/1.0"
_ATTEMPTS = 3
_BACKOFF_SECONDS = (0.5, 1.5)


class LaitApiError(Exception):
    """A LAIT request failed. `status` is the HTTP status, or None for a
    transport failure. The message never contains a response body."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def validated_base_url(raw: str) -> str:
    parts = urlsplit(raw.strip())
    host = (parts.hostname or "").lower()
    if not host:
        raise LaitApiError("LAIT_API_BASE_URL is not a valid URL.")
    if parts.scheme != "https" and not (parts.scheme == "http" and host in _LOOPBACK_HOSTS):
        raise LaitApiError(
            "LAIT_API_BASE_URL must use https (http is accepted only for loopback)."
        )
    return raw.strip().rstrip("/")


def parse_guid(value: uuid.UUID | str) -> str:
    """A GUID is interpolated into a URL path, so it is parsed first: anything
    that is not a UUID -- `../`, a query string -- is refused rather than sent."""
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise LaitApiError("Not a valid GUID.") from exc


class LaitClient:
    def __init__(
        self,
        settings: LaitSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not settings.is_configured:
            raise LaitApiError("LAIT_API_KEY and LAIT_API_BASE_URL must both be set.")
        self._base_url = validated_base_url(settings.api_base_url)
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=settings.request_timeout_seconds,
            follow_redirects=False,
            transport=transport,
            headers={
                settings.api_key_header: settings.api_key.get_secret_value(),
                "Accept": "application/json",
                "User-Agent": _USER_AGENT,
            },
        )

    async def __aenter__(self) -> "LaitClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- endpoints -------------------------------------------------------------

    async def students_latest(self) -> list[dict[str, Any]]:
        return await self._get_list("/api/Students/latest")

    async def tutors(self) -> list[dict[str, Any]]:
        return await self._get_list("/api/Tutors")

    async def student_by_guid(self, guid: uuid.UUID | str) -> dict[str, Any] | None:
        return await self._get_one(f"/api/Students/guid/{parse_guid(guid)}")

    async def tutor_by_guid(self, guid: uuid.UUID | str) -> dict[str, Any] | None:
        return await self._get_one(f"/api/Tutors/guid/{parse_guid(guid)}")

    async def courses(self) -> list[dict[str, Any]]:
        return await self._get_list("/api/Courses?status=1")

    async def batches_upcoming(self) -> list[dict[str, Any]]:
        return await self._get_list("/api/Batches/Upcoming")

    async def batch_students(self, batch_id: int) -> list[dict[str, Any]]:
        # `int()` is the guard: only digits can ever reach the URL path.
        return await self._get_list(f"/api/Batches/{int(batch_id)}/Students")

    # -- transport ---------------------------------------------------------------

    async def _get_list(self, path: str) -> list[dict[str, Any]]:
        data = await self._get_json(path)
        if not isinstance(data, list):
            raise LaitApiError(f"{path}: expected a JSON list.")
        return [item for item in data if isinstance(item, dict)]

    async def _get_one(self, path: str) -> dict[str, Any] | None:
        data = await self._get_json(path, allow_404=True)
        if data is None:
            return None
        # The by-guid endpoints return a single object; tolerate a one-element list.
        if isinstance(data, list):
            data = data[0] if data else None
        return data if isinstance(data, dict) else None

    async def _get_json(self, path: str, *, allow_404: bool = False) -> Any:
        last: LaitApiError | None = None
        for attempt in range(_ATTEMPTS):
            try:
                response = await self._http.get(path)
            except httpx.TimeoutException:
                last = LaitApiError(f"{path}: timed out.")
            except httpx.HTTPError as exc:
                # The exception type only -- `str(exc)` can embed the URL.
                last = LaitApiError(f"{path}: transport error ({type(exc).__name__}).")
            else:
                status = response.status_code
                if status == 200:
                    try:
                        return response.json()
                    except ValueError:
                        raise LaitApiError(f"{path}: response was not valid JSON.", status=status)
                if status == 404 and allow_404:
                    return None
                if status in (401, 403):
                    # Retrying a refused key only invites a lockout.
                    raise LaitApiError(f"{path}: the API refused the key ({status}).", status=status)
                if 300 <= status < 400:
                    raise LaitApiError(f"{path}: unexpected redirect ({status}).", status=status)
                if status < 500:
                    raise LaitApiError(f"{path}: HTTP {status}.", status=status)
                last = LaitApiError(f"{path}: HTTP {status}.", status=status)

            if attempt < _ATTEMPTS - 1:
                await asyncio.sleep(_BACKOFF_SECONDS[attempt])

        assert last is not None
        raise last
