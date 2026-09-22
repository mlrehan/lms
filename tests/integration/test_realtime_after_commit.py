"""An event is published only if the thing it announces is real.

This is the one property the whole realtime layer rests on. A notification is
staged inside the caller's transaction on purpose, so a tray cannot hold "your
grade was recorded" for a mark whose insert rolled back -- and a chime that beat
the commit would reintroduce exactly that bug, in the form a person actually
notices: a badge, a toast, and nothing there when they look.

Driven against a real session and a real transaction rather than a fake, because
the mechanism *is* SQLAlchemy's `after_commit` firing and `after_rollback` not.
A fake would only assert that I called my own helper.
"""

from __future__ import annotations

import asyncio
import random
import selectors

import pytest
from sqlalchemy import text

from backend.core.config import get_settings
from backend.core.events import EventKind, RealtimeEvent, drain_committed, queue_event
from backend.db.manager import DatabaseManager
from backend.realtime.bus import InProcessBus


@pytest.fixture()
def db():
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    manager = DatabaseManager(get_settings().database, application_name="realtime-tests")
    try:
        yield loop, manager
    finally:
        loop.run_until_complete(manager.dispose())
        loop.close()


def _event(user_id: int = 1) -> RealtimeEvent:
    return RealtimeEvent(kind=EventKind.NOTIFICATION_CREATED, user_id=user_id, data={"type": "t"})


# ---------------------------------------------------------- commit/rollback ---


def test_a_committed_transaction_releases_its_events(db) -> None:
    loop, manager = db

    async def go() -> list[RealtimeEvent]:
        async with manager.session_factory() as session:
            queue_event(session.sync_session, _event())
            # Nothing has committed yet, so nothing may be published yet.
            assert drain_committed(session.sync_session) == []
            await session.execute(text("SELECT 1"))
            await session.commit()
            return drain_committed(session.sync_session)

    released = loop.run_until_complete(go())
    assert [e.kind for e in released] == [EventKind.NOTIFICATION_CREATED]


def test_a_rolled_back_transaction_announces_nothing(db) -> None:
    """The defect this file exists to prevent."""
    loop, manager = db

    async def go() -> list[RealtimeEvent]:
        async with manager.session_factory() as session:
            await session.execute(text("SELECT 1"))
            queue_event(session.sync_session, _event())
            await session.rollback()
            return drain_committed(session.sync_session)

    assert loop.run_until_complete(go()) == []


def test_an_exception_inside_the_unit_of_work_announces_nothing(db) -> None:
    """The shape a real request takes: `session_factory.begin()` rolls back on
    any exception, which is how a failed write reaches the client as a 500."""
    loop, manager = db

    async def go() -> list[RealtimeEvent]:
        session_holder = {}
        with pytest.raises(RuntimeError):
            async with manager.session_factory.begin() as session:
                session_holder["s"] = session
                queue_event(session.sync_session, _event())
                raise RuntimeError("the write failed")
        return drain_committed(session_holder["s"].sync_session)

    assert loop.run_until_complete(go()) == []


def test_draining_twice_does_not_publish_twice(db) -> None:
    """Two drains of one session must not send an event to a person's tabs
    twice; a duplicated hint is a duplicated toast."""
    loop, manager = db

    async def go() -> tuple[int, int]:
        async with manager.session_factory() as session:
            queue_event(session.sync_session, _event())
            await session.commit()
            first = len(drain_committed(session.sync_session))
            second = len(drain_committed(session.sync_session))
            return first, second

    assert loop.run_until_complete(go()) == (1, 0)


# ------------------------------------------------------------ the memory bus ---


def test_an_event_reaches_only_the_person_it_is_addressed_to() -> None:
    """There is no parameter anywhere that selects a channel: it is derived
    from the authenticated user id. This is that guarantee, at the bus."""
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())

    async def go() -> tuple[str | None, str | None]:
        bus = InProcessBus()
        mine, theirs = bus.subscribe(7), bus.subscribe(8)
        await bus.publish(_event(user_id=7))
        got_mine = await mine.next_event(timeout=1.0)
        got_theirs = await theirs.next_event(timeout=0.2)
        await mine.aclose()
        await theirs.aclose()
        return (got_mine.kind if got_mine else None, got_theirs.kind if got_theirs else None)

    try:
        assert loop.run_until_complete(go()) == (EventKind.NOTIFICATION_CREATED, None)
    finally:
        loop.close()


def test_a_quiet_subscription_survives_its_heartbeat() -> None:
    """`next_event` exists instead of an async iterator because `wait_for`
    around a generator's `__anext__` finalises the generator -- which would end
    every connection on its first idle heartbeat."""
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())

    async def go() -> tuple[str | None, str | None]:
        bus = InProcessBus()
        sub = bus.subscribe(3)
        idle = await sub.next_event(timeout=0.05)          # times out
        await bus.publish(_event(user_id=3))
        after = await sub.next_event(timeout=1.0)          # still works
        await sub.aclose()
        return (idle, after.kind if after else None)

    try:
        assert loop.run_until_complete(go()) == (None, EventKind.NOTIFICATION_CREATED)
    finally:
        loop.close()


def test_closing_a_subscription_stops_delivery_and_leaves_nothing_behind() -> None:
    """A per-user dict entry kept after the last tab closed is a slow leak in a
    long-running process."""
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())

    async def go() -> tuple[int, int]:
        bus = InProcessBus()
        sub = bus.subscribe(11)
        before = bus.subscriber_count
        await sub.aclose()
        return before, bus.subscriber_count

    try:
        assert loop.run_until_complete(go()) == (1, 0)
    finally:
        loop.close()


def test_a_subscriber_that_stops_reading_cannot_grow_without_limit() -> None:
    """A suspended tab, or a socket the OS has not yet reaped, must not be able
    to consume memory in proportion to how much happens while it is gone."""
    from backend.realtime.bus import QUEUE_LIMIT

    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())

    async def go() -> int:
        bus = InProcessBus()
        sub = bus.subscribe(5)
        for _ in range(QUEUE_LIMIT + 50):
            await bus.publish(_event(user_id=5))
        return sub._queue.qsize()

    try:
        assert loop.run_until_complete(go()) == QUEUE_LIMIT
    finally:
        loop.close()
