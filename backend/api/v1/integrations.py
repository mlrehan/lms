"""Integration endpoints (spec §25): webhooks and calendar feeds."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import CurrentUser, require_permissions
from backend.core.errors import NotFoundError
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession, commit_before_responding
from backend.integrations.icalendar import build_calendar
from backend.core.config import get_settings
from backend.models.assignment import Assignment
from backend.models.batch import Batch, BatchSession
from backend.models.exam import Exam
from backend.models.quiz import Quiz
from backend.utils.enums import AssessmentScope, AssessmentState
from backend.models.enrollment import Enrollments
from backend.models.course import Course
from backend.schemas.base import Page, PageParams
from backend.schemas.integration import (
    CalendarFeedCreatedResponse,
    CalendarFeedResponse,
    CreateCalendarFeedRequest,
    CreateWebhookRequest,
    RotateSecretResponse,
    TestDeliveryResponse,
    UpdateWebhookRequest,
    WebhookCreatedResponse,
    WebhookDeliveryResponse,
    WebhookEndpointResponse,
    WebhookEventCatalogResponse,
)
from backend.services.integration_service import (
    WEBHOOK_EVENTS,
    CalendarFeedService,
    WebhookService,
)

router = APIRouter(prefix="/integrations", tags=["Integrations"])

_READ = require_permissions(perm(Module.INTEGRATION, Action.READ))
_CREATE = require_permissions(perm(Module.INTEGRATION, Action.CREATE))
_UPDATE = require_permissions(perm(Module.INTEGRATION, Action.UPDATE))
_DELETE = require_permissions(perm(Module.INTEGRATION, Action.DELETE))

# How far a timetable feed looks in each direction. A calendar client re-polls
# constantly, so an unbounded feed would re-serialise every session the
# institution has ever run on each request.
FEED_PAST_DAYS = 30
FEED_FUTURE_DAYS = 180


def _endpoint(row) -> WebhookEndpointResponse:  # type: ignore[no-untyped-def]
    return WebhookEndpointResponse(
        public_id=row.public_id,
        name=row.name,
        target_url=row.target_url,
        events=list(row.events or []),
        is_active=row.is_active,
        description=row.description,
        failure_count=row.failure_count or 0,
        last_success_at=row.last_success_at,
        last_failure_at=row.last_failure_at,
        last_failure_reason=row.last_failure_reason,
        created_at=row.created_at,
    )


def _delivery(row) -> WebhookDeliveryResponse:  # type: ignore[no-untyped-def]
    return WebhookDeliveryResponse(
        public_id=row.public_id,
        event=row.event,
        status=row.status,
        attempts=row.attempts or 0,
        response_status=row.response_status,
        error=row.error,
        created_at=row.created_at,
        delivered_at=row.delivered_at,
        next_attempt_at=row.next_attempt_at,
        payload=row.payload,
    )


# =============================================================================
# WEBHOOKS
# =============================================================================


@router.get(
    "/webhooks/events",
    response_model=WebhookEventCatalogResponse,
    summary="Events you can subscribe to",
)
async def webhook_events(
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> WebhookEventCatalogResponse:
    """Only events the platform actually emits are listed.

    Publishing a longer, more impressive list and wiring three of them would
    let somebody subscribe to `course.archived`, receive nothing, and have no
    way to tell a broken integration from a quiet one.
    """
    return WebhookEventCatalogResponse(events=list(WEBHOOK_EVENTS))


@router.get(
    "/webhooks", response_model=Page[WebhookEndpointResponse], summary="List webhooks"
)
async def list_webhooks(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> Page[WebhookEndpointResponse]:
    rows, total = await WebhookService(session).list_endpoints(params)
    return Page.build([_endpoint(r) for r in rows], total=total, params=params)


@router.post(
    "/webhooks",
    response_model=WebhookCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a webhook",
)
async def create_webhook(
    payload: CreateWebhookRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_CREATE)],
) -> WebhookCreatedResponse:
    """**The only response that ever carries the signing secret.** Every other
    route returns a model with no field capable of holding it.

    The target URL is refused with 422 if the server should not connect to it
    — a private address, the cloud metadata service, a non-HTTP scheme — and
    the message names the address it resolved to, because "invalid URL" sends
    an administrator looking at their typing rather than their DNS.
    """
    endpoint, secret = await WebhookService(session).create(payload, actor=actor)
    base = _endpoint(endpoint)
    return WebhookCreatedResponse(**base.model_dump(), secret=secret)


@router.get(
    "/webhooks/{webhook_id}",
    response_model=WebhookEndpointResponse,
    summary="Get one webhook",
)
async def get_webhook(
    webhook_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> WebhookEndpointResponse:
    return _endpoint(await WebhookService(session).get(webhook_id))


@router.patch(
    "/webhooks/{webhook_id}",
    response_model=WebhookEndpointResponse,
    summary="Update a webhook",
)
async def update_webhook(
    webhook_id: uuid.UUID,
    payload: UpdateWebhookRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_UPDATE)],
) -> WebhookEndpointResponse:
    """Changing the target URL clears the failure count: the old failures
    describe a destination that is no longer in use, and carrying them over
    would disable a healthy endpoint on somebody else's history."""
    return _endpoint(await WebhookService(session).update(webhook_id, payload, actor=actor))


@router.post(
    "/webhooks/{webhook_id}/rotate-secret",
    response_model=RotateSecretResponse,
    summary="Issue a new signing secret",
)
async def rotate_secret(
    webhook_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_UPDATE)],
) -> RotateSecretResponse:
    """The previous secret stops working immediately — there is deliberately
    no overlap window. Two valid secrets means a leaked one keeps working
    while somebody decides, and the whole reason to rotate is that it may
    have leaked."""
    endpoint, secret = await WebhookService(session).rotate_secret(webhook_id, actor=actor)
    return RotateSecretResponse(public_id=endpoint.public_id, secret=secret)


@router.post(
    "/webhooks/{webhook_id}/test",
    response_model=TestDeliveryResponse,
    summary="Send a test delivery now",
)
async def test_webhook(
    webhook_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_UPDATE)],
) -> TestDeliveryResponse:
    """Synchronous, where real events are queued: somebody pressing "test" is
    waiting for the answer, and a queued test reporting success before
    anything was sent tells them nothing."""
    delivery = await WebhookService(session).test_fire(webhook_id, actor=actor)
    await commit_before_responding(session)
    return TestDeliveryResponse(
        delivered=delivery.status == "delivered",
        response_status=delivery.response_status,
        error=delivery.error,
        delivery_id=delivery.public_id,
    )


@router.get(
    "/webhooks/{webhook_id}/deliveries",
    response_model=Page[WebhookDeliveryResponse],
    summary="Delivery attempts",
)
async def webhook_deliveries(
    webhook_id: uuid.UUID,
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(_READ)],
    delivery_status: Annotated[
        str | None, Query(alias="status", pattern="^(queued|delivered|failed)$")
    ] = None,
) -> Page[WebhookDeliveryResponse]:
    """Successes are kept, not only failures: "did the grade reach the finance
    system?" is asked far more often than it is planned for."""
    rows, total = await WebhookService(session).deliveries_for(
        webhook_id, params, status=delivery_status
    )
    return Page.build([_delivery(r) for r in rows], total=total, params=params)


@router.delete(
    "/webhooks/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a webhook",
)
async def delete_webhook(
    webhook_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_DELETE)],
) -> Response:
    await WebhookService(session).delete(webhook_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# CALENDAR FEEDS
# =============================================================================


@router.get(
    "/calendar-feeds",
    response_model=list[CalendarFeedResponse],
    summary="Your calendar subscriptions",
)
async def list_calendar_feeds(
    session: DBSession,
    actor: CurrentUser,
) -> list[CalendarFeedResponse]:
    """Authentication only, and scoped to the caller in the query: a calendar
    feed is a personal subscription, not something an administrator manages
    on somebody's behalf."""
    rows = await CalendarFeedService(session).list_own(actor=actor)
    return [
        CalendarFeedResponse(
            public_id=r.public_id,
            name=r.name,
            is_active=r.is_active,
            created_at=r.created_at,
            last_accessed_at=r.last_accessed_at,
            access_count=r.access_count or 0,
        )
        for r in rows
    ]


@router.post(
    "/calendar-feeds",
    response_model=CalendarFeedCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a calendar subscription link",
)
async def create_calendar_feed(
    payload: CreateCalendarFeedRequest,
    session: DBSession,
    actor: CurrentUser,
    request: Request,
) -> CalendarFeedCreatedResponse:
    """**The link is the credential**, and the response says so.

    Calendar clients cannot send an `Authorization` header, so a subscribable
    feed has to carry its secret in the URL. The token is 32 random bytes,
    stored **hashed** so this table is not a list of working links, and
    revocable in one call. The feed carries only session times, titles and
    locations — never grades or messages — so the blast radius of a leaked
    link is a timetable.
    """
    feed, raw = await CalendarFeedService(session).create(actor=actor, name=payload.name)
    url = str(request.url_for("calendar_feed", token=raw))
    # The response hands back a link the caller will click immediately, so
    # the row has to exist by the time they read it. Without this the feed
    # 404s until the transaction lands -- found by a mutation run whose
    # *unrelated* failures were all this race.
    await commit_before_responding(session)
    return CalendarFeedCreatedResponse(
        public_id=feed.public_id,
        name=feed.name,
        is_active=feed.is_active,
        created_at=feed.created_at,
        access_count=0,
        url=url,
    )


@router.delete(
    "/calendar-feeds/{feed_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a calendar link",
)
async def revoke_calendar_feed(
    feed_id: uuid.UUID,
    session: DBSession,
    actor: CurrentUser,
) -> Response:
    await CalendarFeedService(session).revoke(feed_id, actor=actor)
    await commit_before_responding(session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/calendar/{token}.ics",
    name="calendar_feed",
    response_class=Response,
    summary="Subscribe to a timetable (unauthenticated, token in the URL)",
)
async def calendar_feed(
    token: Annotated[str, Path(min_length=16, max_length=200)],
    session: DBSession,
) -> Response:
    """The one unauthenticated route in the API, and the token is what
    authorises it.

    A wrong or revoked token is a **404**, identical to a token that never
    existed — a 401 here would confirm that some link was once valid, which
    is the only fact an attacker guessing tokens could learn.
    """
    feeds = CalendarFeedService(session)
    feed = await feeds.resolve(token)
    if feed is None:
        raise NotFoundError("Calendar feed not found.")

    now = datetime.now(UTC)
    window_start = now - timedelta(days=FEED_PAST_DAYS)
    window_end = now + timedelta(days=FEED_FUTURE_DAYS)

    # Sessions this person is party to: the ones they teach, plus the ones
    # for batches they are enrolled in. Built here rather than through
    # `ScopeResolver` because the caller is a token, not a request actor --
    # and widening it to "everything this user may see" would put another
    # student's timetable in a link they can forward.
    taught = select(BatchSession.id).where(BatchSession.tutor_id == feed.user_id)
    enrolled = (
        select(BatchSession.id)
        .join(Enrollments, Enrollments.batch_id == BatchSession.batch_id)
        .where(Enrollments.student_id == feed.user_id)
    )
    stmt = (
        select(BatchSession, Batch, Course)
        .join(Batch, BatchSession.batch_id == Batch.id)
        .join(Course, Batch.course_id == Course.id)
        .where(
            BatchSession.id.in_(taught.union(enrolled)),
            BatchSession.cancelled_at.is_(None),
            BatchSession.session_start_time >= window_start,
            BatchSession.session_start_time <= window_end,
        )
        .order_by(BatchSession.session_start_time)
    )

    events = [
        {
            "uid": f"{s.public_id}@lms",
            "start": s.session_start_time,
            "end": s.session_end_time or s.session_start_time,
            "summary": f"{c.title} ({b.batch_code})",
            "description": s.student_notes or None,
            "location": s.classroom or None,
            "url": s.meeting_link or None,
        }
        for s, b, c in (await session.execute(stmt)).all()
        if s.session_start_time is not None
    ]

    events.extend(
        await _assessment_events(
            session,
            user_id=feed.user_id,
            window_start=window_start,
            window_end=window_end,
        )
    )
    events.sort(key=lambda e: e["start"])

    body = build_calendar(name=feed.name, events=events)
    await commit_before_responding(session)  # the access counter
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="timetable.ics"',
            # A calendar client polls constantly; without this it is told
            # nothing about freshness and some will cache aggressively.
            "Cache-Control": "private, max-age=300",
        },
    )


async def _assessment_events(
    db: AsyncSession,
    *,
    user_id: int,
    window_start: datetime,
    window_end: datetime,
) -> list[dict]:
    """Assignment deadlines, quiz windows and exam sittings for this person (§26).

    **Scoped the same way the sessions above are, and for the same reason.**
    The caller is a token in a URL, not a request actor, so `ScopeResolver` is
    the wrong tool: it answers "everything this user may see", which for a
    tutor or an administrator would put other people's cohorts into a link
    that can be forwarded. The population here is exactly "batches I am
    enrolled in or teach", and an assessment is included only when its own
    scope lands inside it.

    **Unpublished assessments are never included.** A calendar feed is read by
    software the institution does not control, cached by it, and often mirrored
    to a phone -- so a draft leaking here leaks further than a draft leaking on
    a screen, and cannot be withdrawn.

    One query per assessment type with `IN` clauses, not a scope resolution per
    row: a 90-day window on a busy course is hundreds of assessments, and
    asking the eligibility resolver about each would be the N+1 §33 forbids.
    """
    # The two memberships this person has, resolved once.
    enrolled_batches = select(Enrollments.batch_id).where(Enrollments.student_id == user_id)
    taught_batches = select(BatchSession.batch_id).where(BatchSession.tutor_id == user_id)
    my_batches = enrolled_batches.union(taught_batches).subquery()
    batch_ids = select(my_batches.c[0])

    my_courses = select(Batch.course_id).where(Batch.id.in_(batch_ids))
    my_sessions = select(BatchSession.id).where(BatchSession.batch_id.in_(batch_ids))

    def in_scope(model) -> object:  # type: ignore[no-untyped-def]
        """`scope` decides which id to match, rather than which id is non-null.

        A batch-scoped assessment also carries its course id, so matching on
        "whichever column is populated" would hand a course-wide audience
        something set for one batch -- the exact confusion `AssessmentScope`
        exists to remove.
        """
        return or_(
            and_(model.scope == AssessmentScope.COURSE, model.course_id.in_(my_courses)),
            and_(model.scope == AssessmentScope.BATCH, model.batch_id.in_(batch_ids)),
            and_(model.scope == AssessmentScope.SESSION, model.session_id.in_(my_sessions)),
        )

    base = get_settings().mail.app_url.rstrip("/")

    def link(path: str) -> str | None:
        # No invented host. Without a configured console URL the event simply
        # carries no link, which is what the email templates already do.
        return f"{base}{path}" if base else None

    out: list[dict] = []

    # -- assignments: a deadline is a moment, drawn as a short event ---------
    assignments = (
        await db.execute(
            select(Assignment)
            .where(
                Assignment.state == AssessmentState.PUBLISHED,
                Assignment.due_date >= window_start,
                Assignment.due_date <= window_end,
                in_scope(Assignment),
            )
            .order_by(Assignment.due_date)
        )
    ).scalars().all()
    for a in assignments:
        out.append(
            {
                "uid": f"assignment-{a.public_id}@lms",
                "start": a.due_date,
                "end": a.due_date,
                "summary": f"Assignment due: {a.title}",
                # No description, instructions or venue free-text anywhere in
                # this helper. The feed is a capability URL -- the link *is*
                # the credential -- so it carries what a calendar needs to
                # show an entry (a title and a time) and nothing a forwarded
                # link should not disclose. Anyone needing the detail follows
                # `url` and authenticates.
                "description": None,
                "location": None,
                "url": link(f"/assignments/{a.public_id}"),
            }
        )

    # -- quizzes: the window it is open for, when one is set ----------------
    quizzes = (
        await db.execute(
            select(Quiz)
            .where(
                Quiz.is_published.is_(True),
                Quiz.available_from.is_not(None),
                Quiz.available_from >= window_start,
                Quiz.available_from <= window_end,
                in_scope(Quiz),
            )
            .order_by(Quiz.available_from)
        )
    ).scalars().all()
    for q in quizzes:
        start = q.available_from
        if start is None:  # pragma: no cover - excluded by the query above
            continue
        out.append(
            {
                "uid": f"quiz-{q.public_id}@lms",
                "start": start,
                # An always-open quiz has no close time; a zero-length event
                # says "available from here" rather than inventing a deadline.
                "end": q.available_until or start,
                "summary": f"Quiz opens: {q.title}",
                "description": None,
                "location": None,
                "url": link(f"/quizzes/{q.public_id}"),
            }
        )

    # -- exams: a real sitting, with a duration -----------------------------
    exams = (
        await db.execute(
            select(Exam)
            .where(
                Exam.is_published.is_(True),
                Exam.scheduled_at >= window_start,
                Exam.scheduled_at <= window_end,
                in_scope(Exam),
            )
            .order_by(Exam.scheduled_at)
        )
    ).scalars().all()
    for e in exams:
        end = (
            e.scheduled_at + timedelta(minutes=e.duration_minutes)
            if e.duration_minutes
            else e.scheduled_at
        )
        out.append(
            {
                "uid": f"exam-{e.public_id}@lms",
                "start": e.scheduled_at,
                "end": end,
                "summary": f"Exam: {e.title}",
                "description": None,
                # A venue is an address a person must travel to, so it stays;
                # an online exam's joining link does not, because it is a way
                # *in* and this link can be forwarded.
                "location": e.venue_or_link if not e.is_online else None,
                "url": link(f"/exams/{e.public_id}"),
            }
        )

    return out
