"""Scheduled LAIT user synchronisation.

    python -m backend.cli.sync_lait_users --once
    python -m backend.cli.sync_lait_users --interval 900
    python -m backend.cli.sync_lait_users --once --dry-run

**A deployment that never runs this syncs nothing** and the API says nothing --
the same failure shape as an undrained webhook queue -- so every pass prints
its counts, including an empty one, and `--once` exits non-zero on failure.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from backend.core.config import get_settings
from backend.core.errors import ConflictError
from backend.core.logging import configure_logging, get_logger
from backend.db.manager import DatabaseManager
from backend.services.lait_sync_service import LaitSyncService

logger = get_logger("lait.sync.cli")


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.lait.is_configured:
        print("LAIT_API_KEY / LAIT_API_BASE_URL are not set; nothing to sync.", file=sys.stderr)
        return 2
    interval = args.interval or settings.lait.sync_interval_seconds
    db = DatabaseManager(settings.database, application_name="lms-lait-sync")
    service = LaitSyncService(db.session_factory, settings)
    failed = False
    try:
        while True:
            try:
                run = await service.run(trigger_type="SCHEDULED", triggered_by_user_id=None, dry_run=args.dry_run)
                s = run.stats or {}
                failed = run.status == "FAILED"
                print(
                    f"status={run.status} dry_run={run.dry_run} "
                    f"students={s.get('students')} tutors={s.get('tutors')} errors={len(run.errors or [])}"
                    + (f" failure={run.failure_reason}" if run.failure_reason else ""),
                    flush=True,
                )
            except ConflictError:
                print("skipped: another synchronisation is running", flush=True)
            if args.once:
                break
            await asyncio.sleep(interval)
    finally:
        await db.dispose()
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronise users from the LAIT API.")
    parser.add_argument("--once", action="store_true", help="One pass, then exit.")
    parser.add_argument("--interval", type=float, default=0, help="Seconds between passes (default from settings).")
    parser.add_argument("--dry-run", action="store_true", help="Do everything, then roll back.")
    args = parser.parse_args()
    configure_logging(get_settings().logging)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
