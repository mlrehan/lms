"""Scheduled Google Calendar synchronisation.

    python -m backend.cli.sync_google_calendar --once
    python -m backend.cli.sync_google_calendar --interval 300
    python -m backend.cli.sync_google_calendar --once --dry-run

Pushes LMS changes to Google and pulls session-time edits made in Google. A Super Admin must
connect Google first (Integrations -> Google Calendar). Every pass prints its counts,
including an empty one, and `--once` exits non-zero on failure -- a worker that is silent when
it finds nothing looks exactly like a worker nobody is running.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from backend.core.config import get_settings
from backend.core.errors import ConflictError, ServiceUnavailableError
from backend.core.logging import configure_logging
from backend.db.manager import DatabaseManager
from backend.services.google_calendar_service import GoogleCalendarSyncService


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    db = DatabaseManager(settings.database, application_name="lms-google-sync")
    service = GoogleCalendarSyncService(db.session_factory, settings)
    interval = args.interval or settings.google.sync_interval_seconds
    failed = False
    try:
        while True:
            try:
                run = await service.run(trigger_type="SCHEDULED", triggered_by_user_id=None, dry_run=args.dry_run)
                s = run.stats or {}
                failed = run.status == "FAILED"
                print(f"status={run.status} dry_run={run.dry_run} batches={s.get('batches')} calendars={s.get('calendars')} events={s.get('events')} "
                      f"pulled={s.get('pulled')} errors={len(run.errors or [])}" + (f" failure={run.failure_reason}" if run.failure_reason else ""), flush=True)
            except ConflictError:
                print("skipped: another synchronisation is running", flush=True)
            except ServiceUnavailableError as exc:
                print(f"not run: {exc}", file=sys.stderr, flush=True)
                failed = True
            if args.once:
                break
            await asyncio.sleep(interval)
    finally:
        await db.dispose()
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronise batches, sessions and enrolments with Google Calendar.")
    parser.add_argument("--once", action="store_true", help="One pass, then exit.")
    parser.add_argument("--interval", type=float, default=0, help="Seconds between passes (default from settings).")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change; write nothing.")
    args = parser.parse_args()
    configure_logging(get_settings().logging)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
