"""Reaching somebody whose tab is closed.

The SSE stream covers the case where the console is open. Web Push covers the
one it cannot: the browser is shut, the laptop is asleep, the phone is in a
pocket. The two are deliberately not coordinated on the server -- there is no
"is this person online?" check here, and that is a decision rather than an
omission:

* Server-side presence is wrong often enough to matter. A tab left open in a
  background window holds a live stream and is looked at by nobody, and a
  person reading on their phone has no stream on the laptop that does.
* With several workers, presence would have to live in Redis with a TTL, and
  every edge of that -- a worker killed mid-stream, a clock skew, a missed
  expiry -- turns into a notification somebody never receives.

So every notification is pushed, and **the service worker decides whether to
show it**, using `clients.matchAll()`: it can see whether a window of this app
is open *and focused*, which is the actual question. The browser is the only
party that knows, so the browser is where the decision goes.

Nothing here ever carries the content of a message. A push payload is delivered
to a device that may be unlocked on a desk in a staff room, and it is composed
by whoever performed the write rather than for the person reading it -- so it
says what happened and who it is for, and the app fetches the rest once it is
opened and the reader is known.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.config import PushSettings
from backend.core.errors import ValidationError
from backend.core.logging import get_logger
from backend.models.push import PushSubscription

logger = get_logger(__name__)

#: Status codes a push service returns for an endpoint that no longer exists.
#: These are the *only* reliable signal that a subscription is dead -- a
#: browser that clears its site data tells us nothing -- so they are acted on
#: by deleting the row rather than merely logged.
GONE = frozenset({404, 410})


class PushService:
    def __init__(self, session: AsyncSession, settings: PushSettings) -> None:
        self.session = session
        self.settings = settings

    # -- registration --------------------------------------------------------

    async def register(
        self,
        *,
        user_id: int,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str | None,
    ) -> PushSubscription:
        """Record a device, or move it to this user if it was somebody else's.

        Moving rather than rejecting is the safe direction. An endpoint belongs
        to a browser profile, so the same one arriving under a second account
        means the device changed hands -- and leaving the old row in place would
        keep delivering the previous person's notifications to it.
        """
        if not self.settings.configured:
            raise ValidationError("Push notifications are not configured on this server.")

        existing = (
            await self.session.execute(
                select(PushSubscription).where(PushSubscription.endpoint == endpoint)
            )
        ).scalar_one_or_none()

        if existing is not None:
            existing.user_id = user_id
            existing.p256dh, existing.auth = p256dh, auth
            existing.user_agent = user_agent
            return existing

        await self._enforce_device_cap(user_id)

        row = PushSubscription(
            user_id=user_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=user_agent,
            created_at=datetime.now(UTC),
        )
        self.session.add(row)
        return row

    async def unregister(self, *, user_id: int, endpoint: str) -> bool:
        """Remove one device. Scoped to the caller: an endpoint is not a secret
        (it travels in every subscribe call), so anyone could otherwise
        unsubscribe a device they merely knew the address of."""
        result = await self.session.execute(
            delete(PushSubscription).where(
                PushSubscription.endpoint == endpoint,
                PushSubscription.user_id == user_id,
            )
        )
        return bool(result.rowcount)

    async def list_for(self, user_id: int) -> Sequence[PushSubscription]:
        return list(
            (
                await self.session.execute(
                    select(PushSubscription)
                    .where(PushSubscription.user_id == user_id)
                    .order_by(PushSubscription.created_at.desc())
                )
            ).scalars()
        )

    async def _enforce_device_cap(self, user_id: int) -> None:
        rows = await self.list_for(user_id)
        excess = len(rows) - self.settings.max_devices_per_user + 1
        if excess <= 0:
            return
        # Oldest first: a browser that keeps re-registering leaves a trail of
        # dead endpoints, and the newest is the one actually in use.
        for stale in rows[-excess:]:
            await self.session.delete(stale)

    # -- sending -------------------------------------------------------------

    def payload(self, *, title: str, body: str, url: str, tag: str) -> str:
        return json.dumps(
            {"title": title[:120], "body": body[:200], "url": url, "tag": tag},
            separators=(",", ":"),
        )

    async def send_to_user(self, user_id: int, payload: str) -> int:
        """Push to every device this person has registered. Returns how many
        were delivered.

        Failures are absorbed. This runs after the write it announces has
        already committed and the client already has its response; raising
        would turn a succeeded request into an error nobody can act on, and the
        console's own realtime stream and unread badge still tell the truth.
        """
        if not self.settings.configured:
            return 0

        rows = await self.list_for(user_id)
        if not rows:
            return 0

        delivered = 0
        dead: list[int] = []
        for row in rows:
            status = await asyncio.to_thread(self._send_one, row, payload)
            if status in GONE:
                dead.append(row.id)
            elif status is not None and 200 <= status < 300:
                row.last_used_at = datetime.now(UTC)
                delivered += 1

        if dead:
            await self.session.execute(
                delete(PushSubscription).where(PushSubscription.id.in_(dead))
            )
            logger.info("Removed dead push subscriptions", extra={"count": len(dead)})

        return delivered

    def _send_one(self, row: PushSubscription, payload: str) -> int | None:
        """One blocking send, run on a worker thread.

        `pywebpush` is synchronous and uses `requests`; calling it directly on
        the event loop would stall every other request on this worker for the
        duration of a round trip to a push service that may be slow or down.
        """
        from pywebpush import WebPushException, webpush

        try:
            response = webpush(
                subscription_info={
                    "endpoint": row.endpoint,
                    "keys": {"p256dh": row.p256dh, "auth": row.auth},
                },
                data=payload,
                vapid_private_key=self.settings.vapid_private_key,
                vapid_claims={"sub": self.settings.subject},
                ttl=self.settings.ttl_seconds,
                timeout=10,
            )
            return int(getattr(response, "status_code", 201))
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in GONE:
                return int(status)
            logger.warning(
                "Push send failed",
                extra={"status": status, "subscription_id": row.id},
            )
            return int(status) if status else None
        except Exception:  # noqa: BLE001
            logger.warning("Push send failed", extra={"subscription_id": row.id}, exc_info=True)
            return None


async def push_notifications(
    session_factory: async_sessionmaker[AsyncSession],
    settings: PushSettings,
    items: Sequence[dict[str, Any]],
) -> None:
    """Deliver pushes for already-committed notifications, off the request path.

    Takes a session *factory*, not a session: by the time this runs the
    request's unit of work has closed, and reusing a session past its
    transaction is how a background task ends up writing into nothing.
    """
    if not settings.configured or not items:
        return

    try:
        async with session_factory.begin() as session:
            service = PushService(session, settings)
            for item in items:
                await service.send_to_user(
                    item["user_id"],
                    service.payload(
                        title=item.get("title") or "New activity",
                        body=item.get("body") or "",
                        url=item.get("url") or "/notifications",
                        # Same tag replaces an unread push rather than stacking
                        # a tenth banner for the tenth message in a thread.
                        tag=item.get("tag") or "lms",
                    ),
                )
    except Exception:  # noqa: BLE001
        logger.warning("Push delivery batch failed", exc_info=True)
