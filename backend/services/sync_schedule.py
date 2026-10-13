"""Whether automatic synchronisation is on, and how often.

Stored in `system_settings` rather than in a new table or in `.env`, for three
reasons: the Super Admin can change it without a deploy, the System settings
screen keeps showing every setting this deployment has, and the worker reads
it on each pass so a change takes effect without restarting anything.

**One reader, used by both sides.** The API reports the schedule and the
worker obeys it; if each parsed the settings its own way they would eventually
disagree about what `"True"` or `"6h"` means, and the symptom would be a
worker that quietly never runs.

**An unreadable or nonsensical value means off.** A sync that writes to
hundreds of records is not something to start because a string failed to
parse -- the safe reading of a broken setting is "do nothing and let somebody
look", not "run every minute".
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logging import get_logger
from backend.models.administration import SystemSetting

logger = get_logger("sync.schedule")

SETTING_ENABLED = "sync.automatic.enabled"
SETTING_INTERVAL_HOURS = "sync.automatic.interval_hours"

DEFAULT_INTERVAL_HOURS = 6.0
MIN_INTERVAL_HOURS = 0.25
MAX_INTERVAL_HOURS = 168.0

_TRUE = {"true", "1", "yes", "on"}


@dataclass(frozen=True)
class SyncSchedule:
    enabled: bool
    interval_hours: float

    @property
    def interval_seconds(self) -> float:
        return self.interval_hours * 3600.0


async def read_schedule(session: AsyncSession) -> SyncSchedule:
    """The stored schedule, or the off-by-default one."""
    rows = (
        await session.execute(
            select(SystemSetting.key, SystemSetting.value).where(
                SystemSetting.key.in_((SETTING_ENABLED, SETTING_INTERVAL_HOURS))
            )
        )
    ).all()
    values = {key: (value or "").strip() for key, value in rows}

    enabled = values.get(SETTING_ENABLED, "").lower() in _TRUE

    interval = DEFAULT_INTERVAL_HOURS
    raw = values.get(SETTING_INTERVAL_HOURS)
    if raw:
        try:
            interval = float(raw)
        except ValueError:
            logger.warning(
                "Automatic sync interval is not a number; automatic sync is off.",
                extra={"setting": SETTING_INTERVAL_HOURS},
            )
            return SyncSchedule(enabled=False, interval_hours=DEFAULT_INTERVAL_HOURS)
        if not (MIN_INTERVAL_HOURS <= interval <= MAX_INTERVAL_HOURS):
            logger.warning(
                "Automatic sync interval is out of range; automatic sync is off.",
                extra={"setting": SETTING_INTERVAL_HOURS, "hours": interval},
            )
            return SyncSchedule(enabled=False, interval_hours=DEFAULT_INTERVAL_HOURS)

    return SyncSchedule(enabled=enabled, interval_hours=interval)
