"""Scheduled "Sync All Data": every synchronisation, in dependency order.

    python -m backend.cli.sync_all --once
    python -m backend.cli.sync_all                 # loop, obeying the console
    python -m backend.cli.sync_all --interval 3600 # loop, ignoring the console

Built in the same shape as `sync_lait_users` and `sync_lait_academic`, which is
this project's existing answer to scheduled work: a separate process, not a
thread inside the API. That is what makes it independent of user sessions --
and of the API process, which can be restarted or scaled without the schedule
skipping a beat.

**The schedule lives in the database, not in this file.** Each pass re-reads
`sync.automatic.enabled` and `sync.automatic.interval_hours` from
`system_settings`, so a Super Admin switching automatic sync off from the
dashboard is obeyed by the next pass, with nothing to restart. `--interval`
overrides the stored frequency for operators who want a fixed cadence; the
*enabled* flag is always obeyed, because an off switch that a command-line
flag could defeat is not an off switch.

**Two of these running is harmless.** The `RUNNING` row is a unique index, so
the second simply reports that one is already in progress -- which is also
what happens when a scheduled pass lands while somebody is pressing the button.

**A deployment that never runs this synchronises nothing**, and the API says
nothing about it, so every pass prints its outcome -- including an idle one --
and `--once` exits non-zero when the pipeline failed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from backend.core.config import get_settings
from backend.core.errors import ConflictError
from backend.core.logging import configure_logging, get_logger
from backend.db.manager import DatabaseManager
from backend.services.sync_pipeline_service import SyncPipelineService
from backend.services.sync_schedule import read_schedule

logger = get_logger("sync.pipeline.cli")

# How often to look at the settings while automatic sync is switched off. Short
# enough that switching it on in the console is picked up promptly, long enough
# that an idle deployment is not polling the database every second.
_IDLE_POLL_SECONDS = 60.0


async def _one_pass(service: SyncPipelineService) -> tuple[bool, str]:
    """Run the pipeline once. Returns (failed, one-line summary)."""
    try:
        run = await service.start(trigger_type="SCHEDULED", triggered_by_user_id=None)
    except ConflictError:
        return False, "skipped: a synchronisation is already running"

    finished = await service.execute(run.id)
    jobs = sorted(finished.jobs, key=lambda j: j.position)
    steps = " ".join(f"{j.step.lower()}={j.status.lower()}" for j in jobs)
    processed = sum(j.processed for j in jobs)
    failed_records = sum(j.failed for j in jobs)
    summary = (
        f"status={finished.status} processed={processed} failed={failed_records} {steps}"
        + (f" failure={finished.failure_reason}" if finished.failure_reason else "")
    )
    return finished.status == "FAILED", summary


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.lait.is_configured:
        print("LAIT_API_KEY / LAIT_API_BASE_URL are not set; nothing to sync.", file=sys.stderr)
        return 2

    db = DatabaseManager(settings.database, application_name="lms-sync-all")
    service = SyncPipelineService(db.session_factory, settings)
    failed = False
    try:
        while True:
            async with db.session_factory() as session:
                schedule = await read_schedule(session)

            if args.once or schedule.enabled:
                failed, summary = await _one_pass(service)
                print(summary, flush=True)
            else:
                print("idle: automatic synchronisation is switched off", flush=True)

            if args.once:
                break

            # An override is a cadence, never a way past the off switch.
            if schedule.enabled:
                delay = args.interval or schedule.interval_seconds
            else:
                delay = _IDLE_POLL_SECONDS
            await asyncio.sleep(delay)
    finally:
        await db.dispose()
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run every LAIT synchronisation in dependency order, on a schedule."
    )
    parser.add_argument("--once", action="store_true", help="One pass, then exit. Ignores the on/off setting.")
    parser.add_argument(
        "--interval", type=float, default=0,
        help="Seconds between passes, overriding the configured frequency (not the on/off setting).",
    )
    args = parser.parse_args()
    configure_logging(get_settings().logging)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
