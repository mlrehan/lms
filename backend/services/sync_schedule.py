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

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.errors import ConflictError
from backend.core.logging import get_logger
from backend.models.administration import SystemSetting
from backend.models.sync_pipeline import SyncPipelineRun

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


async def should_run_now(
    session: AsyncSession,
    schedule: SyncSchedule,
    *,
    now: datetime | None = None,
) -> bool:
    """Return True if automatic sync is enabled and the interval has elapsed since the last run."""
    if not schedule.enabled:
        return False

    if now is None:
        now = datetime.now(timezone.utc)

    # Do not start if any pipeline is currently running
    running = (
        await session.execute(
            select(SyncPipelineRun.id).where(SyncPipelineRun.status == "RUNNING").limit(1)
        )
    ).first()
    if running:
        return False

    # Find the most recent finished run
    last_run = (
        await session.execute(
            select(SyncPipelineRun)
            .where(SyncPipelineRun.status.in_(("COMPLETED", "PARTIAL", "FAILED")))
            .order_by(SyncPipelineRun.finished_at.desc().nullslast(), SyncPipelineRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if last_run is None:
        return True

    reference_time = last_run.finished_at or last_run.started_at
    if reference_time is None:
        return True

    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    cutoff = reference_time + timedelta(seconds=schedule.interval_seconds)
    return now >= cutoff


async def run_sync_scheduler(
    factory: async_sessionmaker[AsyncSession],
    service: Any,
    *,
    poll_interval_seconds: float = 15.0,
) -> None:
    """Continuously poll schedule settings and execute pipeline when due."""
    logger.info("Automatic sync scheduler loop started", extra={"poll_interval": poll_interval_seconds})
    try:
        while True:
            try:
                await service.current()
                async with factory() as session:
                    schedule = await read_schedule(session)
                    due = await should_run_now(session, schedule)

                if due:
                    logger.info("Automatic sync is due; starting pipeline run")
                    try:
                        run = await service.start(trigger_type="SCHEDULED", triggered_by_user_id=None)
                        await service.execute(run.id)
                    except ConflictError:
                        logger.info("Automatic sync skipped; another synchronization is already running")
                    except Exception:
                        logger.exception("Automatic sync run failed during execution")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unexpected error in automatic sync scheduler iteration")

            await asyncio.sleep(poll_interval_seconds)
    except asyncio.CancelledError:
        logger.info("Automatic sync scheduler loop stopped")
