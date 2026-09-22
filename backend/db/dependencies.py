import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.core.events import EventKind, drain_committed
from backend.core.logging import get_logger
from backend.db.manager import DatabaseManager

logger = get_logger(__name__)


async def get_db_session(
    request: Request,
) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session with a real commit/rollback boundary.

    `async_sessionmaker.begin()` opens the session *and* starts a
    transaction: a clean exit from the `async with` block commits, an
    exception rolls back -- automatically, on every path. The previous
    version of this dependency only ever rolled back on exception and never
    committed on success at all, silently discarding every write a caller
    made unless that caller remembered to call `session.commit()` itself.
    """

    db: DatabaseManager = request.app.state.db

    async with db.session_factory.begin() as session:
        yield session

    # Past this line the transaction has committed -- the `async with` exit is
    # what commits it, and an exception would have propagated instead of
    # reaching here. Events staged during the request are published now, and
    # only now: announcing a notification whose insert then rolled back would
    # put a chime and a badge in front of something that does not exist.
    await _publish_committed(request, session)


async def _publish_committed(request: Request, session: AsyncSession) -> None:
    events = drain_committed(session.sync_session)
    if not events:
        return

    bus = getattr(request.app.state, "event_bus", None)
    if bus is None:
        return

    for evt in events:
        try:
            await bus.publish(evt)
        except Exception:  # noqa: BLE001
            # The write succeeded and the client already has its response. A
            # failed hint costs a delayed badge -- the client polls and
            # re-reads on reconnect -- and raising here would turn a working
            # request into a 500 after the fact.
            logger.warning(
                "Realtime publish failed", extra={"kind": evt.kind}, exc_info=True
            )

    _spawn_push(request, events)


#: Fire-and-forget tasks are garbage-collected mid-flight unless something
#: holds a reference; the same pattern guards outbound mail in `api/v1/messages`.
_push_tasks: set[asyncio.Task[None]] = set()


def _spawn_push(request: Request, events: list) -> None:  # noqa: ANN001
    """Send Web Push for the notifications this request created.

    Detached from the request on purpose. A fan-out of forty recipients with
    two devices each is eighty round trips to a third-party push service, and
    the person who published the assignment should not be the one waiting for
    them. The write has already committed, so nothing is at risk if this task
    never finishes.

    Only `notification.created` is pushed. A message also raises
    `message.received`, but it raises a notification too -- pushing both would
    buzz twice for one message.
    """
    settings = get_settings()
    if not settings.push.configured:
        return

    items = [
        {
            "user_id": e.user_id,
            "title": (e.data or {}).get("title") or "New activity",
            # Deliberately no body. A push banner lands on a device that may be
            # unlocked on a desk, and the payload was composed at write time --
            # before the reader, and therefore the privacy rules that apply to
            # them, were known. The title says what happened; the app says the
            # rest once it is opened.
            "body": "Open the LMS to read it.",
            "url": "/notifications",
            "tag": (e.data or {}).get("type") or "lms",
        }
        for e in events
        if e.kind == EventKind.NOTIFICATION_CREATED
    ]
    if not items:
        return

    from backend.services.push_service import push_notifications

    db: DatabaseManager = request.app.state.db
    task = asyncio.create_task(push_notifications(db.session_factory, settings.push, items))
    _push_tasks.add(task)
    task.add_done_callback(_push_tasks.discard)


DBSession = Annotated[
    AsyncSession,
    Depends(get_db_session),
]


async def commit_before_responding(session: AsyncSession) -> None:
    """Commit now, rather than in this dependency's teardown.

    **Measured, because it is counter-intuitive:** FastAPI sends the response
    *before* exiting a `yield` dependency here, so the commit in
    `get_db_session` lands after the client already holds its `200`. Proved by
    sleeping two seconds in the teardown -- the client received its response
    in 0.92s, while the commit was still pending.

    For almost every endpoint that is harmless: nobody reads their own write
    back within milliseconds. For an incident-response action it is not. An
    administrator unlocking an account and immediately telling somebody "try
    now" hit a still-locked login **3 times in 40** measured runs, because the
    unlock had returned success before it was visible.

    Committing inside `session_factory.begin()` is safe: the context manager's
    exit is a no-op once the transaction has already ended (verified, not
    assumed). Calling this is a statement that the endpoint's contract is
    "effective when you read this response", not merely "accepted".

    The general fix -- a unit-of-work boundary that closes before the response
    is produced, for all ~145 routes -- is an architectural change worth
    making deliberately rather than as a side effect of this phase, and is
    recorded as such.
    """
    await session.commit()
