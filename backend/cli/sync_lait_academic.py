"""Scheduled LAIT course / batch / enrolment synchronisation.

    python -m backend.cli.sync_lait_academic --once
    python -m backend.cli.sync_lait_academic --interval 900
    python -m backend.cli.sync_lait_academic --once --dry-run
    python -m backend.cli.sync_lait_academic --status-only      # just recompute course status

Run the *user* sync first if you can (`sync_lait_users`), but it is not required:
this one creates any tutor or student it needs on demand.

A deployment that never runs this syncs nothing and the API says nothing, so every
pass prints its counts, including an empty one, and `--once` exits non-zero on
failure. Course status (PUBLISHED <-> RUNNING) is recomputed on every pass even
when the fetch fails, so it follows the calendar rather than the feed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from backend.core.config import get_settings
from backend.core.errors import ConflictError
from backend.core.logging import configure_logging
from backend.db.manager import DatabaseManager
from backend.services.lait_academic_sync_service import LaitAcademicSyncService, refresh_course_statuses


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    db = DatabaseManager(settings.database, application_name="lms-lait-academic-sync")
    failed = False
    try:
        if args.status_only:
            print(f"course_status={await refresh_course_statuses(db.session_factory)}", flush=True)
            return 0
        if not settings.lait.is_configured:
            print("LAIT_API_KEY / LAIT_API_BASE_URL are not set; nothing to sync.", file=sys.stderr)
            return 2
        interval = args.interval or settings.lait.sync_interval_seconds
        service = LaitAcademicSyncService(db.session_factory, settings)
        while True:
            try:
                run = await service.run(trigger_type="SCHEDULED", triggered_by_user_id=None, dry_run=args.dry_run)
                s = run.stats or {}
                failed = run.status == "FAILED"
                print(
                    f"status={run.status} dry_run={run.dry_run} courses={s.get('courses')} batches={s.get('batches')} "
                    f"sessions={s.get('sessions')} enrollments={s.get('enrollments')} errors={len(run.errors or [])}"
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
    parser = argparse.ArgumentParser(description="Synchronise courses, batches, sessions and enrolments from LAIT.")
    parser.add_argument("--once", action="store_true", help="One pass, then exit.")
    parser.add_argument("--interval", type=float, default=0, help="Seconds between passes (default from settings).")
    parser.add_argument("--dry-run", action="store_true", help="Do everything, then roll back.")
    parser.add_argument("--status-only", action="store_true", help="Only recompute course status from the calendar.")
    args = parser.parse_args()
    configure_logging(get_settings().logging)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
