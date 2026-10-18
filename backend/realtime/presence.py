"""Who is actually at their desk.

**An unexpired session is not a person.** A token lives for its full life
whether the browser is open, minimised, crashed or thrown in a river, so a
"logged-in users" list built from sessions counts people who left an hour ago.
This counts something narrower and truer: a browser that is still holding its
realtime connection open *now*.

**The heartbeat already exists, so presence is a side effect of it.** Every
signed-in console tab holds an SSE stream, and that stream already wakes on a
fixed interval to write a keep-alive frame. Refreshing presence on the same
tick costs one small write per tab per interval and needs no polling endpoint,
no extra connection and no client code at all.

**Going offline is a timeout, never an event.** A browser that crashes, a
laptop whose lid closes, a network that drops -- none of them send a logout.
So nothing here marks anybody offline: an entry simply stops being refreshed
and falls outside the window. A clean disconnect calls `drop` as a courtesy,
which makes the common case immediate, but correctness never depends on it.

**Memory is refused in a deployed environment**, for the same reason the event
bus refuses it: with several workers behind a load balancer each process would
see only the tabs it happens to be holding, and the active-user count would be
a fraction that changes depending on which worker answered. That is a wrong
number that looks plausible, which is the worst kind.
"""

from __future__ import annotations

import time
from typing import Protocol

from backend.core.config import RealtimeBackend, RealtimeSettings
from backend.core.logging import get_logger

logger = get_logger(__name__)

#: The sorted set every present user is scored into, by last-seen timestamp.
KEY = "presence:online"

#: How long after its last heartbeat an entry still counts as online.
#:
#: Must comfortably exceed the heartbeat interval or an ordinary tab flickers
#: offline between beats; the default is a little over twice 25 seconds, so a
#: single missed beat is survivable and two are not.
DEFAULT_WINDOW_SECONDS = 60


class PresenceStore(Protocol):
    """Who is here, and when each was last seen."""

    async def touch(self, user_id: int) -> bool:
        """Record that this person's browser is still connected.

        Returns True only when this was a *transition* -- they were not counted
        as online a moment ago and now are. Every other heartbeat returns
        False, which is what stops one connected browser publishing an event
        every twenty-five seconds to everybody watching the dashboard.
        """

    async def drop(self, user_id: int) -> bool:
        """A clean disconnect. Correctness does not depend on this arriving.

        Returns True if somebody was actually removed, so a second close for a
        person who had already gone announces nothing.
        """

    async def online(self, *, window_seconds: int = DEFAULT_WINDOW_SECONDS) -> dict[int, float]:
        """Everyone seen within the window, as `user_id -> unix seconds`."""

    async def close(self) -> None: ...


class MemoryPresence:
    """Correct when exactly one process serves every connection.

    Fine in development and during tests; refused in a deployed environment by
    `build_presence_store`.
    """

    def __init__(self) -> None:
        self._seen: dict[int, float] = {}

    async def touch(self, user_id: int) -> bool:
        now = time.time()
        previous = self._seen.get(user_id)
        self._seen[user_id] = now
        # Absent, or last seen so long ago that a reader would already have
        # counted them offline. Both are arrivals as far as anybody watching
        # the list is concerned.
        return previous is None or previous < now - DEFAULT_WINDOW_SECONDS

    async def drop(self, user_id: int) -> bool:
        return self._seen.pop(user_id, None) is not None

    async def online(self, *, window_seconds: int = DEFAULT_WINDOW_SECONDS) -> dict[int, float]:
        cutoff = time.time() - window_seconds
        # Pruning on read rather than on a timer: the only thing that cares
        # about staleness is a reader, and a process with no readers has no
        # reason to be doing work.
        self._seen = {uid: at for uid, at in self._seen.items() if at >= cutoff}
        return dict(self._seen)

    async def close(self) -> None:
        self._seen.clear()


class RedisPresence:
    """One sorted set, scored by last-seen.

    A key-per-user with a TTL is the obvious shape and is wrong for the read
    this serves: finding everyone online would mean `SCAN`, which walks the
    whole keyspace and gets slower as the deployment gets busier -- exactly
    backwards. A sorted set answers "who was seen since T" in one range query
    and keeps the expiry explicit.
    """

    def __init__(self, url: str) -> None:
        import redis.asyncio as redis  # imported here so `memory` needs no redis

        self._redis = redis.from_url(url, decode_responses=True)

    async def touch(self, user_id: int) -> bool:
        now = time.time()
        member = str(user_id)
        # The previous score is read before the write rather than inferred from
        # `ZADD ... CH`, which reports a changed *score* -- true on every
        # heartbeat, and therefore useless for telling an arrival from a
        # still-here. One extra round trip per heartbeat, against one frame to
        # every connected administrator if we got this wrong.
        previous = await self._redis.zscore(KEY, member)
        await self._redis.zadd(KEY, {member: now})
        return previous is None or float(previous) < now - DEFAULT_WINDOW_SECONDS

    async def drop(self, user_id: int) -> bool:
        return bool(await self._redis.zrem(KEY, str(user_id)))

    async def online(self, *, window_seconds: int = DEFAULT_WINDOW_SECONDS) -> dict[int, float]:
        cutoff = time.time() - window_seconds
        # Trimming here, on the read, keeps the set from growing without bound
        # without needing a sweeper process whose own failure would be silent.
        await self._redis.zremrangebyscore(KEY, "-inf", f"({cutoff}")
        rows = await self._redis.zrangebyscore(KEY, cutoff, "+inf", withscores=True)
        return {int(member): float(score) for member, score in rows}

    async def close(self) -> None:
        await self._redis.aclose()


def build_presence_store(settings: RealtimeSettings, *, deployed: bool) -> PresenceStore:
    """Pick an adapter, and refuse the one that would be silently wrong.

    `deployed` is passed rather than read, so a test can exercise both branches
    without pretending to be production.
    """
    if settings.backend is RealtimeBackend.REDIS:
        if not settings.redis_url:
            raise RuntimeError(
                "REALTIME_BACKEND=redis needs REALTIME_REDIS_URL to be set."
            )
        return RedisPresence(settings.redis_url)

    if deployed:
        raise RuntimeError(
            "In-memory presence counts only the tabs this worker happens to hold, "
            "so with more than one worker the active-user count is a fraction that "
            "changes with whichever process answers. Set REALTIME_BACKEND=redis."
        )

    logger.info("Presence is in-memory: correct only while one process serves every tab")
    return MemoryPresence()
