"""Asking where an IP address is: a public-IP echo service and a geolocation service.

Two calls, both optional and both best effort: `public_ip()` (icanhazip) for the case where the caller's own
address is private, and `lookup(ip)` (ipapi.co) for what an address implies (city, country, time zone).

The address is validated with `ipaddress` before it is put into a URL, so a header cannot steer the request
anywhere but the configured service. Results are cached in process for the same address (a whole office shares
one), and a failure is remembered for a while, because the usual failure is a rate limit and retrying it on
every sign-in only prolongs it. Nothing here ever raises: no answer is `None`, and the caller carries on.
"""

from __future__ import annotations

import ipaddress
import time
from dataclasses import dataclass
from typing import Any
from zoneinfo import available_timezones

import httpx

from backend.core.config import LocaleSettings
from backend.core.logging import get_logger

logger = get_logger(__name__)

_VALID_ZONES = available_timezones()
# Only these fields are kept from the lookup; the rest of the payload (currency, population...) is noise here.
_KEEP = ("ip", "city", "region", "country", "country_name", "country_code", "timezone", "utc_offset", "latitude", "longitude", "org")


@dataclass(frozen=True)
class IpLocale:
    ip: str
    timezone: str | None
    info: dict[str, Any]


def parse_ip(value: str | None) -> str | None:
    """A clean, canonical address, or None. Strips a port and brackets; refuses anything else."""
    if not value:
        return None
    text = value.strip()
    if text.startswith("[") and "]" in text:  # [::1]:8080
        text = text[1 : text.index("]")]
    elif text.count(":") == 1 and "." in text:  # 1.2.3.4:5678
        text = text.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return None


def is_public(ip: str | None) -> bool:
    """False for loopback, private, link-local and reserved space: nothing a geolocation service can place."""
    if not ip:
        return False
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


class _Cache:
    def __init__(self) -> None:
        self._items: dict[str, tuple[float, IpLocale | None]] = {}

    def get(self, key: str) -> tuple[bool, IpLocale | None]:
        entry = self._items.get(key)
        if entry is None or entry[0] < time.monotonic():
            self._items.pop(key, None)
            return False, None
        return True, entry[1]

    def put(self, key: str, value: IpLocale | None, ttl: float) -> None:
        if len(self._items) > 5000:  # bounded: drop everything rather than track ages
            self._items.clear()
        self._items[key] = (time.monotonic() + ttl, value)


class IpLocaleClient:
    def __init__(self, settings: LocaleSettings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._s = settings
        self._transport = transport
        self._cache = _Cache()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._s.timeout_seconds, transport=self._transport, follow_redirects=False,
                                 headers={"User-Agent": "lms-locale/1.0", "Accept": "application/json"})

    async def public_ip(self) -> str | None:
        """This machine's public address, as an outside service sees it."""
        cached, value = self._cache.get("__self__")
        if cached:
            return value.ip if value else None
        try:
            async with self._client() as client:
                response = await client.get(self._s.public_ip_url)
            ip = parse_ip(response.text) if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Public IP lookup failed", extra={"error": type(exc).__name__})
            ip = None
        self._cache.put("__self__", IpLocale(ip, None, {}) if ip else None, self._s.cache_ttl_seconds if ip else self._s.failure_backoff_seconds)
        return ip

    async def lookup(self, ip: str) -> IpLocale | None:
        """What the geolocation service says about `ip`; None if it will not say."""
        clean = parse_ip(ip)
        if clean is None or not is_public(clean):
            return None
        cached, value = self._cache.get(clean)
        if cached:
            return value
        result: IpLocale | None = None
        try:
            async with self._client() as client:
                response = await client.get(self._s.lookup_url.replace("{ip}", clean))
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and not data.get("error"):
                    zone = data.get("timezone")
                    info = {k: data.get(k) for k in _KEEP if data.get(k) is not None}
                    result = IpLocale(ip=clean, timezone=zone if isinstance(zone, str) and zone in _VALID_ZONES else None, info=info)
            else:
                logger.warning("IP lookup refused", extra={"status": response.status_code})
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("IP lookup failed", extra={"error": type(exc).__name__})
        self._cache.put(clean, result, self._s.cache_ttl_seconds if result else self._s.failure_backoff_seconds)
        return result


_shared: IpLocaleClient | None = None


def shared_client(settings: LocaleSettings) -> IpLocaleClient:
    """One process-wide client, so the cache is shared by every request."""
    global _shared
    if _shared is None:
        _shared = IpLocaleClient(settings)
    return _shared
