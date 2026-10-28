"""Per-person request limits for the AI endpoints.

A rolling one-minute window per (person, bucket), held in this process.

**In process, deliberately, and that is its limit.** The API runs as a single
uvicorn process (`backend/main.py`), so one counter is the whole truth today.
Run several workers and each keeps its own window, so a person gets the limit
once per worker -- still a bound, just a looser one. Moving the window into
Redis is the fix when that day comes; it is not worth a network round trip per
chat turn before then.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock

from backend.core.errors import RateLimitError

_WINDOW_SECONDS = 60.0


class RequestLimiter:
    """Counts requests per key over a rolling window and refuses past `limit`."""

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[tuple[int, str], deque[float]] = {}
        self._lock = Lock()

    def check(self, *, user_id: int, bucket: str, limit: int) -> None:
        """Record one request, or raise RateLimitError if the window is full.

        A refused request is not recorded: retrying after the wait must work,
        and counting refusals would let a retry loop lock itself out for ever.
        """
        now = self._clock()
        key = (user_id, bucket)
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= _WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = max(1, int(_WINDOW_SECONDS - (now - hits[0])) + 1)
                raise RateLimitError(
                    f"Too many assistant requests. Try again in {retry_after} seconds.",
                    details={"retry_after_seconds": retry_after},
                )
            hits.append(now)


_limiter = RequestLimiter()


def get_request_limiter() -> RequestLimiter:
    return _limiter
