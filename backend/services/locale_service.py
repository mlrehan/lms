"""Where a signed-in person is, and the time zone that follows from it.

Called at every sign-in and, while the console is open, periodically. It is cheap when nothing has changed:
the person's current address is compared with the one stored against their account, and only a *different*
address costs a lookup. The rules, all deliberate:

* The address is the caller's own (`get_client_ip`, first hop of `X-Forwarded-For` else the socket). When that
  is private -- local development, where the browser and the API share a machine -- the server's public address
  is used instead, which is then also the person's.
* A time zone a person chose (`timezone_is_auto = false`) is never overwritten. Only a zone that was itself
  filled in from an address, or none at all, follows the address.
* A failed lookup changes nothing and never breaks the sign-in it rides on.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import LocaleSettings, get_settings
from backend.core.logging import get_logger
from backend.integrations.ip_locale import IpLocaleClient, is_public, parse_ip, shared_client
from backend.models.identity.user import User

logger = get_logger(__name__)


@dataclass(frozen=True)
class LocaleResult:
    ip_changed: bool = False
    timezone_changed: bool = False
    timezone: str | None = None


class UserLocaleService:
    def __init__(self, session: AsyncSession, *, settings: LocaleSettings | None = None, client: IpLocaleClient | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings().locale
        self.client = client or shared_client(self.settings)

    async def refresh(self, user: User, *, client_ip: str | None) -> LocaleResult:
        if not self.settings.enabled:
            return LocaleResult(timezone=user.timezone)

        ip = parse_ip(client_ip)
        if not is_public(ip):
            ip = await self.client.public_ip() if self.settings.use_server_ip_fallback else None
        if ip is None:
            return LocaleResult(timezone=user.timezone)

        if user.locale_ip == ip and user.locale_info:
            return LocaleResult(timezone=user.timezone)  # same place as last time: no lookup at all

        locale = await self.client.lookup(ip)
        if locale is None:
            return LocaleResult(timezone=user.timezone)

        user.locale_ip = ip
        user.locale_info = locale.info
        user.locale_checked_at = datetime.now(timezone.utc)

        zone_changed = False
        if locale.timezone and (user.timezone is None or user.timezone_is_auto):
            zone_changed = user.timezone != locale.timezone
            user.timezone = locale.timezone
            user.timezone_is_auto = True
        return LocaleResult(ip_changed=True, timezone_changed=zone_changed, timezone=user.timezone)

    async def refresh_quietly(self, user: User, *, client_ip: str | None) -> LocaleResult:
        """For a sign-in: bounded in time and incapable of raising, so it can never cost anyone their session."""
        try:
            return await asyncio.wait_for(self.refresh(user, client_ip=client_ip), timeout=self.settings.timeout_seconds * 2 + 1)
        except Exception as exc:  # noqa: BLE001 -- see docstring
            logger.warning("Locale refresh skipped", extra={"error": type(exc).__name__})
            return LocaleResult(timezone=user.timezone)
