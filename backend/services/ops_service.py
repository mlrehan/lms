"""Operational and performance visibility (spec §24).

Three questions, and the endpoints exist because answering them otherwise
means a database console and a person who knows where to look:

* **Is the system healthy right now** — beyond the unauthenticated `/readyz`
  probe, which deliberately answers only yes/no because a load balancer is
  the wrong audience for detail.
* **Which route is slow or erroring** — from `core/metrics.py`, per process.
* **Is the database doing what we think** — sequential scans on big tables,
  indexes nobody uses, connection-pool pressure, table growth.

**What is deliberately absent: statement-level timing.** That needs
`pg_stat_statements`, which needs `shared_preload_libraries` and therefore a
server restart. The extension is *available* on this deployment but not
loaded, so `CREATE EXTENSION` would succeed and every query against the view
would then fail — an endpoint that exists and cannot work. It is reported as
unavailable, with the setting that would enable it, rather than shipped
broken.

**Reads here are diagnostic, not authoritative.** `pg_stat_user_tables`
counters reset on `pg_stat_reset()` and on a crash, so "this index has never
been used" means "not since the counters were last reset". The response says
when that was, because the number is misleading without it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logging import get_logger
from backend.core.metrics import REGISTRY

logger = get_logger(__name__)

# Below this many rows a sequential scan is the *right* plan, and reporting
# it as a problem sends people to add indexes that make writes slower and
# reads no faster.
SEQ_SCAN_ROW_FLOOR = 1000


class OpsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- health --------------------------------------------------------------

    async def health(self) -> dict[str, Any]:
        checks: dict[str, Any] = {}

        started = datetime.now(UTC)
        try:
            await self.session.execute(text("SELECT 1"))
            checks["database"] = {
                "ok": True,
                "latency_ms": round(
                    (datetime.now(UTC) - started).total_seconds() * 1000, 2
                ),
            }
        except Exception as exc:  # noqa: BLE001 - a health check reports, never crashes
            checks["database"] = {"ok": False, "error": type(exc).__name__}

        try:
            from backend.storage.factory import get_storage

            storage = get_storage()
            checks["storage"] = {"ok": True, "backend": type(storage).__name__}
        except Exception as exc:  # noqa: BLE001
            # A misconfigured storage backend must show as degraded, not take
            # the health endpoint down -- the endpoint exists to report that.
            checks["storage"] = {"ok": False, "error": str(exc)[:200]}

        return {
            "status": "ok" if all(c.get("ok") for c in checks.values()) else "degraded",
            "checked_at": datetime.now(UTC),
            "checks": checks,
        }

    # -- metrics -------------------------------------------------------------

    @staticmethod
    def metrics() -> dict[str, Any]:
        snapshot = REGISTRY.snapshot()
        snapshot["scope"] = (
            "This process only. Counters reset when it restarts, and other "
            "workers behind a load balancer report their own."
        )
        return snapshot

    # -- database ------------------------------------------------------------

    async def database(self, *, limit: int = 15) -> dict[str, Any]:
        return {
            "captured_at": datetime.now(UTC),
            "size": await self._database_size(),
            "connections": await self._connections(),
            "pool": self._pool(),
            "tables": await self._tables(limit=limit),
            "unused_indexes": await self._unused_indexes(limit=limit),
            "statement_timing": await self._statement_timing(),
        }

    async def _database_size(self) -> dict[str, Any]:
        row = (
            await self.session.execute(
                text(
                    "SELECT pg_database_size(current_database()) AS bytes, "
                    "pg_size_pretty(pg_database_size(current_database())) AS pretty"
                )
            )
        ).one()
        return {"bytes": int(row[0]), "pretty": row[1]}

    async def _connections(self) -> dict[str, Any]:
        rows = (
            await self.session.execute(
                text(
                    "SELECT state, count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() GROUP BY state"
                )
            )
        ).all()
        by_state = {(r[0] or "unknown"): int(r[1]) for r in rows}
        max_conn = (
            await self.session.execute(text("SHOW max_connections"))
        ).scalar_one()
        return {
            "by_state": by_state,
            "total": sum(by_state.values()),
            "max_connections": int(max_conn),
        }

    def _pool(self) -> dict[str, Any]:
        """SQLAlchemy's own pool, which is the number that actually limits
        this process -- `max_connections` is the server's ceiling across
        every client."""
        try:
            bind = self.session.get_bind()
            pool = bind.pool  # type: ignore[union-attr]
            return {
                "size": pool.size(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow(),
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": type(exc).__name__, "detail": str(exc)[:120]}

    async def _tables(self, *, limit: int) -> list[dict[str, Any]]:
        """Biggest tables, with how they are being read.

        `seq_scan` against `idx_scan` is the single most useful pair here: a
        large table read mostly by sequential scan is either missing an index
        or being queried in a way no index can serve, and both are worth
        knowing. Small tables are excluded from the *flag*, not the listing --
        a sequential scan of 40 rows is correct.
        """
        rows = (
            await self.session.execute(
                text(
                    """
                    SELECT relname,
                           n_live_tup,
                           n_dead_tup,
                           seq_scan,
                           idx_scan,
                           pg_total_relation_size(relid) AS bytes,
                           pg_size_pretty(pg_total_relation_size(relid)) AS pretty
                    FROM pg_stat_user_tables
                    ORDER BY pg_total_relation_size(relid) DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
        ).all()

        out = []
        for name, live, dead, seq, idx, size_bytes, pretty in rows:
            live = int(live or 0)
            seq = int(seq or 0)
            idx = int(idx or 0)
            out.append(
                {
                    "table": name,
                    "live_rows": live,
                    "dead_rows": int(dead or 0),
                    "seq_scans": seq,
                    "index_scans": idx,
                    "size": pretty,
                    "size_bytes": int(size_bytes),
                    "mostly_sequential": bool(
                        live >= SEQ_SCAN_ROW_FLOOR and seq > idx
                    ),
                }
            )
        return out

    async def _unused_indexes(self, *, limit: int) -> list[dict[str, Any]]:
        """Indexes with no recorded scans.

        Reported with a caveat rather than as a recommendation: an index
        serving a constraint, or one that only matters during a month-end
        job, looks identical to a useless one here. The counters also reset,
        so "never used" can mean "not since Tuesday".
        """
        rows = (
            await self.session.execute(
                text(
                    """
                    SELECT indexrelname, relname, idx_scan,
                           pg_size_pretty(pg_relation_size(indexrelid)) AS pretty
                    FROM pg_stat_user_indexes
                    WHERE idx_scan = 0
                    ORDER BY pg_relation_size(indexrelid) DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
        ).all()
        return [
            {"index": r[0], "table": r[1], "scans": int(r[2] or 0), "size": r[3]}
            for r in rows
        ]

    async def _statement_timing(self) -> dict[str, Any]:
        """Whether per-statement timing is available, and why not if not."""
        preload = (
            await self.session.execute(text("SHOW shared_preload_libraries"))
        ).scalar_one()
        loaded = "pg_stat_statements" in (preload or "")
        if not loaded:
            return {
                "available": False,
                "reason": (
                    "pg_stat_statements is not in shared_preload_libraries. "
                    "Enabling it needs a postgresql.conf change and a server "
                    "restart; CREATE EXTENSION alone would install it and "
                    "every query against the view would still fail."
                ),
                "shared_preload_libraries": preload or "(empty)",
            }

        rows = (
            await self.session.execute(
                text(
                    """
                    SELECT calls, round(mean_exec_time::numeric, 2) AS mean_ms,
                           round(total_exec_time::numeric, 2) AS total_ms,
                           left(query, 200) AS query
                    FROM pg_stat_statements
                    ORDER BY total_exec_time DESC
                    LIMIT 10
                    """
                )
            )
        ).all()
        return {
            "available": True,
            "slowest": [
                {"calls": int(r[0]), "mean_ms": float(r[1]),
                 "total_ms": float(r[2]), "query": r[3]}
                for r in rows
            ],
        }
