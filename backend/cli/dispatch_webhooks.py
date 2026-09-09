"""Drain the webhook delivery queue.

**A separate process, and that is the design.** Delivery is queued rather
than sent inline because a `POST /enrollments` that waits on a receiver's
ten-second timeout has made the enrolment screen as slow as the slowest
integration anybody registered. The row is written in the same transaction as
the event — so an event that rolled back leaves no delivery claiming it
happened — and this drains it afterwards.

Run it on a timer:

    python -m backend.cli.dispatch_webhooks --once
    python -m backend.cli.dispatch_webhooks --interval 30

**A deployment that never runs this will queue deliveries for ever and send
nothing**, with the API reporting success throughout — the same failure shape
as a worker-less job queue. `--once` exits non-zero if anything failed, so a
scheduler surfaces it rather than logging into a void.

Each delivery gets **its own transaction**. One batch in one transaction
would hold every row's lock for the length of the slowest receiver, and a
failure at the end would discard the record of the successes that preceded
it — which is the one thing this table exists to remember.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from backend.core.config import get_settings
from backend.core.logging import configure_logging, get_logger
from backend.db.manager import DatabaseManager
from backend.models.integration import WebhookDelivery, WebhookEndpoint
from backend.services.integration_service import WebhookService

logger = get_logger("webhooks.dispatch")


async def _drain_once(db: DatabaseManager, *, batch: int) -> tuple[int, int]:
    """Returns `(delivered, failed)` for one pass."""
    async with db.session_factory() as session:
        due = await WebhookService(session).due_deliveries(limit=batch)
        ids = [d.id for d in due]

    delivered = failed = 0
    for delivery_id in ids:
        # One transaction per delivery: a slow receiver must not hold locks
        # for the rest of the batch, and an error must not roll back the
        # successes recorded before it.
        async with db.session_factory.begin() as session:
            row = (
                await session.execute(
                    select(WebhookDelivery).where(WebhookDelivery.id == delivery_id)
                )
            ).scalar_one_or_none()
            if row is None or row.status != "queued":
                # Another dispatcher took it, or it was cancelled. Not an
                # error: at-least-once delivery means two dispatchers racing
                # is expected, and the loser simply skips.
                continue

            endpoint = (
                await session.execute(
                    select(WebhookEndpoint).where(WebhookEndpoint.id == row.endpoint_id)
                )
            ).scalar_one_or_none()
            if endpoint is None or not endpoint.is_active:
                row.status = "failed"
                row.error = "Endpoint removed or disabled."
                row.next_attempt_at = None
                failed += 1
                continue

            ok = await WebhookService(session).attempt(row, endpoint)
            if ok:
                delivered += 1
            elif row.status == "failed":
                failed += 1

    return delivered, failed


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    db = DatabaseManager(settings.database, application_name="lms-webhook-dispatch")
    total_failed = 0
    try:
        while True:
            delivered, failed = await _drain_once(db, batch=args.batch)
            total_failed += failed
            # Printed on every pass, including an empty one. A dispatcher
            # that is silent when it finds nothing looks exactly like a
            # dispatcher nobody is running -- which is the failure this
            # command exists to make visible.
            logger.info(
                "Webhook batch complete",
                extra={"delivered": delivered, "failed": failed},
            )
            print(f"delivered={delivered} failed={failed}", flush=True)
            if args.once:
                break
            await asyncio.sleep(args.interval)
    finally:
        await db.dispose()

    # Non-zero on failure so a scheduler notices. A dispatcher that always
    # exits 0 is indistinguishable from one that is not running.
    return 1 if total_failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Deliver queued webhooks.")
    parser.add_argument("--once", action="store_true", help="One pass, then exit.")
    parser.add_argument("--interval", type=float, default=30.0, help="Seconds between passes.")
    parser.add_argument("--batch", type=int, default=100, help="Deliveries per pass.")
    args = parser.parse_args()

    configure_logging(get_settings().logging)

    if sys.platform == "win32":
        # psycopg's async path cannot run on a ProactorEventLoop -- the same
        # constraint `backend/main.py` documents for the server.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
