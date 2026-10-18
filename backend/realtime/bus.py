"""Getting an event from the process that wrote it to the process holding the
browser's connection.

Those are usually the same process in development and usually *not* the same
process in production, where several workers sit behind a load balancer and a
person's SSE connection lands on whichever one the balancer chose. An in-memory
fan-out is completely correct in the first case and silently broken in the
second: messages simply never arrive for some users, intermittently, with
nothing in the logs. That is the worst failure shape available, so `memory` is
refused outright in a deployed environment rather than left as a default
somebody inherits.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Protocol

from backend.core.config import RealtimeBackend, RealtimeSettings
from backend.core.events import RealtimeEvent
from backend.core.logging import get_logger

logger = get_logger(__name__)

#: How long a subscriber's queue may fall behind before it is dropped.
#: A browser that has stopped reading (a suspended tab, a dead connection the
#: OS has not reaped) must not be able to grow a queue without limit; losing a
#: hint is recoverable because the client re-reads on reconnect, and running
#: the server out of memory is not.
QUEUE_LIMIT = 100


def channel_for(user_id: int) -> str:
    return f"rt:user:{user_id}"


def channel_for_topic(topic: str) -> str:
    """A channel several connections share.

    Distinct prefix from the per-user channels so the two namespaces cannot
    collide: a topic named `7` must never land on user 7's channel.
    """
    return f"rt:topic:{topic}"


def _channels(evt: RealtimeEvent) -> str:
    """Where one event goes. Exactly one of topic / user is meaningful."""
    return channel_for_topic(evt.topic) if evt.topic else channel_for(evt.user_id)


class EventBus(Protocol):
    """Publish to one person; subscribe as one person."""

    async def publish(self, evt: RealtimeEvent) -> None: ...

    def subscribe(
        self, user_id: int, topics: "tuple[str, ...]" = ()
    ) -> "Subscription": ...

    async def close(self) -> None: ...


class Subscription(Protocol):
    """One reader's view of one person's events.

    Deliberately a `next_event(timeout)` call rather than an async iterator.
    The caller needs to wake up on a heartbeat interval whether or not anything
    arrived, and `asyncio.wait_for` around an async generator's `__anext__`
    *finalises the generator* when it times out -- so an iterator-shaped API
    would end the subscription on the first quiet heartbeat, which is every
    connection, almost always.
    """

    async def next_event(self, timeout: float) -> RealtimeEvent | None:
        """The next event, or `None` if `timeout` elapsed first."""
        ...

    async def aclose(self) -> None: ...


# --------------------------------------------------------------- in-process ---


class _MemorySubscription:
    def __init__(
        self, bus: "InProcessBus", user_id: int, topics: tuple[str, ...] = ()
    ) -> None:
        self.topics = topics
        self._bus = bus
        self._user_id = user_id
        self._queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=QUEUE_LIMIT)
        self._closed = False

    def offer(self, evt: RealtimeEvent) -> None:
        try:
            self._queue.put_nowait(evt)
        except asyncio.QueueFull:
            # Dropping the oldest would be worse: the newest event is the one
            # that reflects the current unread count, and a client that missed
            # a hint re-reads anyway.
            logger.warning(
                "Realtime subscriber is not keeping up; dropping event",
                extra={"user_id": self._user_id, "kind": evt.kind},
            )

    async def next_event(self, timeout: float) -> RealtimeEvent | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError):
            return None

    async def aclose(self) -> None:
        self._closed = True
        self._bus._remove(self._user_id, self)


class InProcessBus:
    """Correct when exactly one process serves every connection.

    Used in development and in tests, where it is not a compromise: it removes
    a network dependency from the thing under test without changing what the
    thing under test does.
    """

    def __init__(self) -> None:
        self._subscribers: dict[int, set[_MemorySubscription]] = {}
        #: Keyed by topic name. Separate from `_subscribers` rather than
        #: sharing one dict keyed by channel string, so the per-user path --
        #: the hot one, and the one carrying personal events -- keeps its
        #: integer key and cannot be reached by a crafted topic name.
        self._topics: dict[str, set[_MemorySubscription]] = {}

    async def publish(self, evt: RealtimeEvent) -> None:
        if evt.topic:
            for sub in tuple(self._topics.get(evt.topic, ())):
                sub.offer(evt)
            return
        for sub in tuple(self._subscribers.get(evt.user_id, ())):
            sub.offer(evt)

    def subscribe(self, user_id: int, topics: tuple[str, ...] = ()) -> _MemorySubscription:
        sub = _MemorySubscription(self, user_id, topics)
        self._subscribers.setdefault(user_id, set()).add(sub)
        for topic in topics:
            self._topics.setdefault(topic, set()).add(sub)
        return sub

    def _remove(self, user_id: int, sub: _MemorySubscription) -> None:
        holders = self._subscribers.get(user_id)
        if holders:
            holders.discard(sub)
            if not holders:
                # Otherwise the dict grows one empty set per user who ever
                # connected, for the life of the process.
                self._subscribers.pop(user_id, None)
        for topic in sub.topics:
            members = self._topics.get(topic)
            if not members:
                continue
            members.discard(sub)
            if not members:
                self._topics.pop(topic, None)

    async def close(self) -> None:
        self._subscribers.clear()
        self._topics.clear()

    # Introspection for `/readyz` and tests; never used to make a decision.
    @property
    def subscriber_count(self) -> int:
        return sum(len(s) for s in self._subscribers.values())

    @property
    def topic_subscriber_count(self) -> int:
        return sum(len(s) for s in self._topics.values())


# -------------------------------------------------------------------- redis ---


class _RedisSubscription:
    def __init__(self, pubsub, channels: tuple[str, ...]) -> None:  # noqa: ANN001
        self._pubsub = pubsub
        self._channels = channels
        self._subscribed = False

    async def next_event(self, timeout: float) -> RealtimeEvent | None:
        if not self._subscribed:
            # Subscribing here rather than in `EventBus.subscribe` keeps that
            # method synchronous, so both adapters share one shape instead of
            # the port going async for redis's convenience alone.
            # One `SUBSCRIBE` carrying every channel, not one call each: a
            # connection holding five topics would otherwise cost five round
            # trips before it can read its first event.
            await self._pubsub.subscribe(*self._channels)
            self._subscribed = True

        message = await self._pubsub.get_message(
            ignore_subscribe_messages=True, timeout=timeout
        )
        if not message or message.get("type") != "message":
            return None

        raw = message["data"]
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            return RealtimeEvent.from_json(raw)
        except Exception:  # noqa: BLE001
            # A malformed frame is somebody else's bug, or a stale format from
            # a half-deployed rollout. Dropping one beats tearing down a live
            # connection for every subscriber on this worker.
            logger.warning(
                "Discarding malformed realtime frame",
                extra={"channels": ",".join(self._channels)},
            )
            return None

    async def aclose(self) -> None:
        with suppress(Exception):
            if self._subscribed:
                await self._pubsub.unsubscribe(*self._channels)
        with suppress(Exception):
            await self._pubsub.aclose()


class RedisBus:
    """Fan-out across workers.

    Pub/sub rather than a stream, deliberately: an event is a hint that
    something changed, and a subscriber who was disconnected re-reads the truth
    from the database on reconnect. Durable delivery would mean storing a
    per-user backlog to replay hints that are already stale by the time anyone
    reads them.
    """

    def __init__(self, url: str) -> None:
        import redis.asyncio as redis  # imported here so `memory` needs no redis at all

        self._redis = redis.from_url(url, decode_responses=True)

    async def publish(self, evt: RealtimeEvent) -> None:
        await self._redis.publish(_channels(evt), evt.to_json())

    def subscribe(self, user_id: int, topics: tuple[str, ...] = ()) -> _RedisSubscription:
        return _RedisSubscription(
            self._redis.pubsub(ignore_subscribe_messages=True),
            (channel_for(user_id), *(channel_for_topic(t) for t in topics)),
        )

    async def close(self) -> None:
        with suppress(Exception):
            await self._redis.aclose()

    async def ping(self) -> bool:
        return bool(await self._redis.ping())


# ------------------------------------------------------------------ factory ---


def build_bus(settings: RealtimeSettings, *, deployed: bool) -> EventBus:
    """Choose an adapter, and refuse the combination that fails silently."""
    if settings.backend is RealtimeBackend.REDIS:
        if not settings.redis_url:
            raise RuntimeError(
                "REALTIME_BACKEND=redis requires REALTIME_REDIS_URL. Refusing to "
                "start rather than falling back to an in-memory bus, which would "
                "deliver events only to whichever worker happened to write them."
            )
        return RedisBus(settings.redis_url)

    if deployed:
        raise RuntimeError(
            "REALTIME_BACKEND=memory cannot be used in a deployed environment: "
            "each worker would only ever reach the browsers connected to itself, "
            "so realtime delivery would appear to work and fail for most users. "
            "Set REALTIME_BACKEND=redis and REALTIME_REDIS_URL."
        )
    return InProcessBus()
