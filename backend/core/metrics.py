"""In-process request metrics (spec §24).

**Per-process and reset by a restart, and the endpoint says so.** This is not
a substitute for Prometheus or a hosted APM — with two workers behind a load
balancer, each answers about itself. What it is good for is the question an
operator actually asks first: *which route is slow, and which route is
erroring, right now, on this box*. Answering that should not require standing
up a metrics stack, and a deployment that has one can scrape these numbers
into it.

**Latency is kept as buckets plus a running sum, not a list of samples.** A
list would grow without bound on a busy process and would make the metrics
endpoint the biggest allocation in the system. Buckets give the shape —
"most requests are under 50ms, forty were over a second" — which is the part
that changes behaviour; a true p99 needs the sample set and is what the real
metrics stack is for.

Keyed by the **route template** (`/courses/{course_id}`), never the path.
Keying on the path makes every id its own metric, so a thousand courses is a
thousand rows describing one route, and the one number an operator wants —
how slow is fetching a course — is nowhere.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

# Upper bounds in milliseconds. Chosen around the decisions they inform:
# 50ms is "fine", 250ms is "a person notices", 1s is "a person waits", and
# over 2.5s is "something is wrong".
BUCKET_BOUNDS_MS: tuple[float, ...] = (10, 50, 250, 1000, 2500)


@dataclass
class RouteStats:
    requests: int = 0
    errors: int = 0  # 5xx
    client_errors: int = 0  # 4xx
    total_ms: float = 0.0
    max_ms: float = 0.0
    buckets: list[int] = field(
        default_factory=lambda: [0] * (len(BUCKET_BOUNDS_MS) + 1)
    )

    def observe(self, duration_ms: float, status_code: int) -> None:
        self.requests += 1
        self.total_ms += duration_ms
        self.max_ms = max(self.max_ms, duration_ms)
        if status_code >= 500:
            self.errors += 1
        elif status_code >= 400:
            self.client_errors += 1

        for index, bound in enumerate(BUCKET_BOUNDS_MS):
            if duration_ms <= bound:
                self.buckets[index] += 1
                return
        self.buckets[-1] += 1

    @property
    def average_ms(self) -> float:
        return round(self.total_ms / self.requests, 2) if self.requests else 0.0


class MetricsRegistry:
    """Thread-safe counters for the process.

    A lock rather than per-thread accumulation: the write is three integer
    updates, uncontended in an asyncio process that mostly runs on one
    thread, and the alternative is a merge step that has to be right.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._routes: dict[tuple[str, str], RouteStats] = {}
        self.started_at = time.time()

    def observe(
        self, *, method: str, route: str, duration_ms: float, status_code: int
    ) -> None:
        key = (method, route)
        with self._lock:
            stats = self._routes.get(key)
            if stats is None:
                stats = RouteStats()
                self._routes[key] = stats
            stats.observe(duration_ms, status_code)

    def snapshot(self) -> dict:
        with self._lock:
            routes = [
                {
                    "method": method,
                    "route": route,
                    "requests": s.requests,
                    "errors": s.errors,
                    "client_errors": s.client_errors,
                    "average_ms": s.average_ms,
                    "max_ms": round(s.max_ms, 2),
                    "buckets": dict(
                        zip(
                            [f"<={int(b)}ms" for b in BUCKET_BOUNDS_MS] + ["slower"],
                            s.buckets,
                        )
                    ),
                }
                for (method, route), s in self._routes.items()
            ]
        routes.sort(key=lambda r: r["requests"], reverse=True)
        total = sum(r["requests"] for r in routes)
        return {
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "total_requests": total,
            "total_errors": sum(r["errors"] for r in routes),
            "routes": routes,
        }

    def reset(self) -> None:
        with self._lock:
            self._routes.clear()
            self.started_at = time.time()


REGISTRY = MetricsRegistry()
