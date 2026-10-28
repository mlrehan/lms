"""Approximate location of an IP address, from a local MaxMind GeoLite2-City file.

**Local, never a network call.** An audit row is written on every sign-in and
every change; asking a web service each time would send every user's address
to a third party, add latency to the action being audited, and fail exactly
when the service rate-limits. A memory-mapped database file answers in
microseconds and keeps the address on this server.

**Never raises.** `locate()` returns a `GeoResult` with a status for every
outcome -- no file, unreadable file, address not in the database, an address
that has no location by nature (private, loopback) -- because a geolocation
problem must never cost an audit event.

**An estimate, labelled as one.** The result is where the address's network is
registered or routed, to within `accuracy_km` at best. A VPN exit, a mobile
carrier or a corporate gateway puts everybody behind it at one place. Nothing
here is a person's physical location, and the UI says so.

**The file is replaced in place by `geoipupdate`**, so the reader is reopened
when the file's modification time changes; the cache is cleared with it,
because a cached answer from last month's database is last month's answer.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from backend.core.client_ip import IpScope
from backend.core.config import GeoIPSettings, get_settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class GeoStatus:
    OK = "OK"                          # located
    NOT_FOUND = "NOT_FOUND"            # a public address the database has no record for
    NOT_APPLICABLE = "NOT_APPLICABLE"  # private, loopback, reserved or unknown: nothing to locate
    UNAVAILABLE = "UNAVAILABLE"        # lookups disabled, or no database file installed
    ERROR = "ERROR"                    # the file could not be read


@dataclass(frozen=True)
class GeoResult:
    status: str
    source: str | None = None
    country_code: str | None = None
    country: str | None = None
    region: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    accuracy_km: int | None = None

    def as_columns(self) -> dict[str, Any]:
        return {f"geo_{k}": v for k, v in asdict(self).items()}


def _name(node: Any) -> str | None:
    if not isinstance(node, dict):
        return None
    names = node.get("names") or {}
    return names.get("en") or next(iter(names.values()), None)


def _from_record(record: dict[str, Any], source: str) -> GeoResult:
    country = record.get("country") or record.get("registered_country") or {}
    subdivisions = record.get("subdivisions") or []
    location = record.get("location") or {}
    return GeoResult(
        status=GeoStatus.OK,
        source=source,
        country_code=country.get("iso_code"),
        country=_name(country),
        # The largest subdivision: a US state, an English region, a Bangladeshi division.
        region=_name(subdivisions[0]) if subdivisions else None,
        city=_name(record.get("city")),
        latitude=location.get("latitude"),
        longitude=location.get("longitude"),
        accuracy_km=location.get("accuracy_radius"),
    )


class GeoLocator:
    def __init__(self, settings: GeoIPSettings, reader: Any | None = None, source: str | None = None) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._reader = reader
        self._source = source
        self._mtime: float | None = None
        self._injected = reader is not None
        self._cache: OrderedDict[str, GeoResult] = OrderedDict()
        self._warned = False

    def _open(self) -> Any | None:
        """The reader for the current file, reopening it after an update. None when absent."""
        if self._injected:
            return self._reader
        path = self._settings.city_db_path
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            if not self._warned:
                logger.warning("GeoIP database not found at %s; audit locations will be recorded as unavailable", path)
                self._warned = True
            self._close()
            return None
        if self._reader is not None and mtime == self._mtime:
            return self._reader
        import maxminddb

        self._close()
        self._reader = maxminddb.open_database(path)
        self._mtime = mtime
        meta = self._reader.metadata()
        built = datetime.fromtimestamp(meta.build_epoch, UTC).date().isoformat()
        self._source = f"{meta.database_type} {built}"[:64]
        self._cache.clear()
        self._warned = False
        return self._reader

    def _close(self) -> None:
        if self._reader is not None and not self._injected:
            try:
                self._reader.close()
            except Exception:  # noqa: BLE001
                pass
            self._reader = None
            self._mtime = None

    def locate(self, ip: str | None, scope: str | None) -> GeoResult:
        if not ip or scope != IpScope.PUBLIC.value:
            return GeoResult(status=GeoStatus.NOT_APPLICABLE)
        if not self._settings.enabled:
            return GeoResult(status=GeoStatus.UNAVAILABLE)
        try:
            with self._lock:
                reader = self._open()
                if reader is None:
                    return GeoResult(status=GeoStatus.UNAVAILABLE)
                cached = self._cache.get(ip)
                if cached is not None:
                    self._cache.move_to_end(ip)
                    return cached
                record = reader.get(ip)
                result = (
                    _from_record(record, self._source or "MaxMind GeoLite2")
                    if isinstance(record, dict)
                    else GeoResult(status=GeoStatus.NOT_FOUND, source=self._source)
                )
                if self._settings.cache_size:
                    self._cache[ip] = result
                    while len(self._cache) > self._settings.cache_size:
                        self._cache.popitem(last=False)
                return result
        except Exception as exc:  # noqa: BLE001 -- a broken file must never cost an audit event
            logger.warning("GeoIP lookup failed: %s", exc)
            return GeoResult(status=GeoStatus.ERROR, source=self._source)


_locator: GeoLocator | None = None
_locator_lock = threading.Lock()


def get_locator() -> GeoLocator:
    global _locator
    if _locator is None:
        with _locator_lock:
            if _locator is None:
                _locator = GeoLocator(get_settings().geoip)
    return _locator


def set_locator(locator: GeoLocator | None) -> None:
    """Replace the process-wide locator (tests; or None to rebuild from settings)."""
    global _locator
    _locator = locator
