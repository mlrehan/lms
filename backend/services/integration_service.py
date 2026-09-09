"""Webhook endpoints, deliveries and calendar feeds (spec §25).

**The event catalogue lists only events the platform actually emits.** It
would be easy to publish a long, impressive list of codes and wire three of
them — and an administrator would then register for `course.archived`,
receive nothing, and have no way to tell a silent integration from a working
one with nothing to report. This codebase has found that shape often enough
to name it: a field that looks configurable and is not. Three events are
emitted, three are offered.

**Delivery is queued, never inline.** A `POST /enrollments` that waits on a
receiver's ten-second timeout has made the institution's enrolment screen as
slow as the slowest integration anyone registered. The row is written in the
same transaction as the event, and `backend/cli/dispatch_webhooks.py` drains
it — so an event that rolled back has no delivery, and a receiver being down
delays nothing.

The one exception is `test_fire`, which is synchronous on purpose: somebody
pressing "test" is asking a question and waiting for the answer.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.core.logging import get_logger
from backend.integrations.delivery import deliver
from backend.integrations.signing import new_secret
from backend.integrations.url_safety import UrlRejected, assert_safe_url
from backend.models.identity.user import User
from backend.models.integration import CalendarFeed, WebhookDelivery, WebhookEndpoint
from backend.schemas.base import PageParams
from backend.schemas.integration import CreateWebhookRequest, UpdateWebhookRequest
from backend.services import audit_service
from backend.services.audit_service import AuditAction

logger = get_logger(__name__)


class WebhookEvent:
    """Events actually emitted. Adding a code here without wiring an emitter
    is the decorative-field pattern; adding an emitter without a code here
    means the event silently reaches nobody."""

    ENROLLMENT_CREATED: Final = "enrollment.created"
    ASSIGNMENT_PUBLISHED: Final = "assignment.published"
    SUBMISSION_GRADED: Final = "submission.graded"


WEBHOOK_EVENTS: Final[tuple[str, ...]] = (
    WebhookEvent.ENROLLMENT_CREATED,
    WebhookEvent.ASSIGNMENT_PUBLISHED,
    WebhookEvent.SUBMISSION_GRADED,
)

# After this many consecutive failures an endpoint stops being dispatched to.
# A receiver that has been dead for a week is not coming back this minute, and
# a queue that retries it for ever is a queue nobody can drain.
MAX_CONSECUTIVE_FAILURES = 20

# Exponential, capped. The cap matters more than the curve: without it the
# thirtieth retry is scheduled for some time next year, which is the same as
# never but harder to notice.
RETRY_BACKOFF_SECONDS = (30, 120, 600, 3600)
MAX_ATTEMPTS = len(RETRY_BACKOFF_SECONDS) + 1


def _now() -> datetime:
    return datetime.now(UTC)


def hash_feed_token(raw: str) -> str:
    """SHA-256, not a password hash.

    A calendar token is 32 bytes of `secrets` output, so there is no
    dictionary to attack and no reason to make verification deliberately
    slow — this runs on every calendar client poll. Argon2 here would cost
    real CPU to defend against a search space that does not exist.
    """
    return hashlib.sha256(raw.encode()).hexdigest()


class WebhookService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- registry ------------------------------------------------------------

    async def list_endpoints(
        self, params: PageParams
    ) -> tuple[Sequence[WebhookEndpoint], int]:
        stmt = select(WebhookEndpoint).order_by(WebhookEndpoint.name)
        count = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = int((await self.session.execute(count)).scalar_one())
        rows = (
            (await self.session.execute(stmt.limit(params.limit).offset(params.offset)))
            .scalars()
            .unique()
            .all()
        )
        return rows, total

    async def get(self, public_id: uuid.UUID) -> WebhookEndpoint:
        stmt = select(WebhookEndpoint).where(WebhookEndpoint.public_id == public_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Webhook endpoint not found.")
        return row

    async def create(
        self, payload: CreateWebhookRequest, *, actor: User
    ) -> tuple[WebhookEndpoint, str]:
        self._assert_events(payload.events)
        url = self._validated_url(payload.target_url)

        existing = await self.session.execute(
            select(WebhookEndpoint).where(
                func.lower(WebhookEndpoint.name) == payload.name.strip().lower()
            )
        )
        if existing.scalars().first() is not None:
            raise ConflictError("A webhook with that name already exists.")

        secret = new_secret()
        endpoint = WebhookEndpoint(
            name=payload.name.strip(),
            target_url=url,
            secret=secret,
            events=sorted(set(payload.events)),
            description=payload.description,
            is_active=True,
            created_by=actor.id,
            # A new instance's collection is unloaded and the flush cascade
            # touches it -- `MissingGreenlet` under asyncio otherwise.
            deliveries=[],
        )
        self.session.add(endpoint)
        await self.session.flush()

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="webhook_endpoint",
            entity_id=endpoint.id,
            # The URL is recorded; the secret is not. An audit trail that
            # copies a credential is a second place to steal it from.
            details={"name": endpoint.name, "url": url, "events": endpoint.events},
        )
        return endpoint, secret

    async def update(
        self, public_id: uuid.UUID, payload: UpdateWebhookRequest, *, actor: User
    ) -> WebhookEndpoint:
        endpoint = await self.get(public_id)
        changes = payload.model_dump(exclude_unset=True)

        if "events" in changes and changes["events"] is not None:
            self._assert_events(changes["events"])
            changes["events"] = sorted(set(changes["events"]))
        if "target_url" in changes and changes["target_url"] is not None:
            changes["target_url"] = self._validated_url(changes["target_url"])
            # A new destination starts with a clean record: the old failures
            # describe a URL that is no longer in use, and leaving the count
            # would disable a healthy endpoint on somebody else's history.
            endpoint.failure_count = 0
            endpoint.last_failure_reason = None

        for field, value in changes.items():
            if value is not None or field == "description":
                setattr(endpoint, field, value)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="webhook_endpoint",
            entity_id=endpoint.id,
            details={"fields": sorted(changes)},
        )
        return endpoint

    async def rotate_secret(self, public_id: uuid.UUID, *, actor: User) -> tuple[WebhookEndpoint, str]:
        endpoint = await self.get(public_id)
        secret = new_secret()
        endpoint.secret = secret
        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="webhook_endpoint",
            entity_id=endpoint.id,
            details={"secret": "rotated"},
        )
        return endpoint, secret

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        endpoint = await self.get(public_id)
        entity_id, name = endpoint.id, endpoint.name
        await self.session.delete(endpoint)
        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="webhook_endpoint",
            entity_id=entity_id,
            details={"name": name},
        )

    # -- dispatch ------------------------------------------------------------

    async def enqueue(self, event: str, payload: dict[str, Any]) -> int:
        """Queue one event for every endpoint subscribed to it.

        Staged in the caller's transaction, so an event whose own write rolls
        back leaves no delivery behind claiming it happened.
        """
        if event not in WEBHOOK_EVENTS:
            raise RuntimeError(f"Unknown webhook event {event!r}.")

        stmt = select(WebhookEndpoint).where(
            WebhookEndpoint.is_active.is_(True),
            WebhookEndpoint.failure_count < MAX_CONSECUTIVE_FAILURES,
        )
        queued = 0
        for endpoint in (await self.session.execute(stmt)).scalars().unique().all():
            if event not in (endpoint.events or []):
                continue
            self.session.add(
                WebhookDelivery(
                    endpoint_id=endpoint.id,
                    event=event,
                    payload=payload,
                    status="queued",
                    next_attempt_at=_now(),
                )
            )
            queued += 1
        return queued

    async def test_fire(self, public_id: uuid.UUID, *, actor: User) -> WebhookDelivery:
        """Send one delivery now and report what happened.

        Synchronous where real events are queued: the person pressing "test"
        is waiting for the answer, and a queued test that reports success
        before anything was sent tells them nothing.
        """
        endpoint = await self.get(public_id)
        delivery = WebhookDelivery(
            endpoint_id=endpoint.id,
            event="webhook.test",
            payload={"event": "webhook.test", "endpoint": endpoint.name,
                     "sent_at": _now().isoformat()},
            status="queued",
        )
        self.session.add(delivery)
        await self.session.flush()

        await self.attempt(delivery, endpoint)
        return delivery

    async def attempt(
        self, delivery: WebhookDelivery, endpoint: WebhookEndpoint
    ) -> bool:
        """One delivery attempt, recording the outcome on both rows."""
        delivery.attempts = (delivery.attempts or 0) + 1
        result = await deliver(
            url=endpoint.target_url,
            secret=endpoint.secret,
            event=delivery.event,
            payload=delivery.payload,
            delivery_id=str(delivery.public_id),
        )

        delivery.response_status = result.status_code
        if result.ok:
            delivery.status = "delivered"
            delivery.delivered_at = _now()
            delivery.error = None
            delivery.next_attempt_at = None
            endpoint.failure_count = 0
            endpoint.last_success_at = _now()
            endpoint.last_failure_reason = None
            return True

        delivery.error = result.error
        endpoint.last_failure_at = _now()
        endpoint.last_failure_reason = (result.error or "")[:255]
        endpoint.failure_count = (endpoint.failure_count or 0) + 1

        if not result.retryable or delivery.attempts >= MAX_ATTEMPTS:
            # A 4xx means the receiver understood and refused. Retrying it is
            # spending both sides' resources to be told the same thing again.
            delivery.status = "failed"
            delivery.next_attempt_at = None
        else:
            delivery.status = "queued"
            backoff = RETRY_BACKOFF_SECONDS[
                min(delivery.attempts - 1, len(RETRY_BACKOFF_SECONDS) - 1)
            ]
            delivery.next_attempt_at = _now() + timedelta(seconds=backoff)
        return False

    async def due_deliveries(self, *, limit: int = 100) -> list[WebhookDelivery]:
        stmt = (
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status == "queued",
                WebhookDelivery.next_attempt_at <= _now(),
            )
            .order_by(WebhookDelivery.next_attempt_at)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def deliveries_for(
        self, public_id: uuid.UUID, params: PageParams, *, status: str | None = None
    ) -> tuple[Sequence[WebhookDelivery], int]:
        endpoint = await self.get(public_id)
        stmt = select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint.id)
        if status:
            stmt = stmt.where(WebhookDelivery.status == status)
        stmt = stmt.order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc())

        count = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = int((await self.session.execute(count)).scalar_one())
        rows = (
            (await self.session.execute(stmt.limit(params.limit).offset(params.offset)))
            .scalars()
            .unique()
            .all()
        )
        return rows, total

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _assert_events(events: Sequence[str]) -> None:
        unknown = sorted(set(events) - set(WEBHOOK_EVENTS))
        if unknown:
            raise ValidationError(
                "Unknown webhook event(s).",
                details={"unknown": unknown, "known": list(WEBHOOK_EVENTS)},
            )

    @staticmethod
    def _validated_url(url: str) -> str:
        try:
            return assert_safe_url(url)
        except UrlRejected as rejected:
            # 422 rather than 400: the field is well-formed and the value is
            # the problem, and the message names the resolved address so the
            # administrator can see *why* rather than guessing.
            raise ValidationError(str(rejected), details={"target_url": url}) from None


class CalendarFeedService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_own(self, *, actor: User) -> Sequence[CalendarFeed]:
        stmt = (
            select(CalendarFeed)
            .where(CalendarFeed.user_id == actor.id)
            .order_by(CalendarFeed.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def create(self, *, actor: User, name: str) -> tuple[CalendarFeed, str]:
        raw = secrets.token_urlsafe(32)
        feed = CalendarFeed(
            user_id=actor.id,
            name=name.strip(),
            token_hash=hash_feed_token(raw),
            is_active=True,
        )
        self.session.add(feed)
        await self.session.flush()

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="calendar_feed",
            entity_id=feed.id,
            details={"name": feed.name},
        )
        return feed, raw

    async def revoke(self, public_id: uuid.UUID, *, actor: User) -> None:
        stmt = select(CalendarFeed).where(
            CalendarFeed.public_id == public_id, CalendarFeed.user_id == actor.id
        )
        feed = (await self.session.execute(stmt)).scalar_one_or_none()
        if feed is None:
            # Scoped to the caller in the query, so somebody else's feed is
            # indistinguishable from one that never existed.
            raise NotFoundError("Calendar feed not found.")

        feed.is_active = False
        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="calendar_feed",
            entity_id=feed.id,
            details={"name": feed.name, "revoked": True},
        )

    async def resolve(self, raw_token: str) -> CalendarFeed | None:
        """Find an active feed by its raw token, and record the access.

        Looked up **by hash**: the stored column is not a working URL, so a
        leaked backup of this table does not hand anyone a set of live feeds.
        """
        if not raw_token or len(raw_token) > 200:
            return None
        stmt = select(CalendarFeed).where(
            CalendarFeed.token_hash == hash_feed_token(raw_token),
            CalendarFeed.is_active.is_(True),
        )
        feed = (await self.session.execute(stmt)).scalar_one_or_none()
        if feed is not None:
            feed.last_accessed_at = _now()
            feed.access_count = (feed.access_count or 0) + 1
        return feed
