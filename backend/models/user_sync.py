"""History of runs of the LAIT user synchronisation.

One row per run, whether it was started by the Super Admin's "Sync Now" button
or by the scheduled worker. It exists for three reasons, each visible in the
columns:

* **A run must say what it did.** The button would otherwise be a fire-and-
  forget request that answers "started" and never "finished" -- and a
  scheduled job that has been failing for a week would be indistinguishable
  from one that has been succeeding. `stats` and `errors` are the answer.
* **The `RUNNING` row is the lock.** A partial unique index allows at most one
  row in that state, so two syncs cannot race each other -- enforced by the
  database rather than by remembering to check. A process killed mid-run
  leaves a stale `RUNNING` row; the service reaps those before starting.
* **Per-record failures are data, not a stack trace.** `errors` holds one
  small entry per skipped record (which LAIT id, and why), because "3 of 40
  tutors could not be created" is only actionable if you can see which three.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, PublicIdMixin

from .helpers import bool_column


class UserSyncRun(Base, PublicIdMixin):
    __tablename__ = "user_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    kind: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'USERS'"),
        comment="USERS | ACADEMIC. One RUNNING row across both kinds is the lock: an academic run can create users.",
    )
    trigger_type: Mapped[str] = mapped_column(String(10), nullable=False)  # MANUAL | SCHEDULED
    triggered_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    dry_run: Mapped[bool] = bool_column(default=False, nullable=False)

    status: Mapped[str] = mapped_column(
        String(10), nullable=False, index=True
    )  # RUNNING | SUCCEEDED | PARTIAL | FAILED

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # {"students": {"fetched": n, "created": n, ...}, "tutors": {...}, "geo": {...}}
    stats: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # [{"source": "student", "external_id": "...", "reason": "..."}]
    errors: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    # A whole-run failure (API unreachable, bad key) -- distinct from per-record errors.
    failure_reason: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    __table_args__ = (
        # At most one RUNNING row, ever. `((true))` indexes a constant, so any
        # two qualifying rows collide.
        Index(
            "ux_user_sync_runs_one_running",
            text("(true)"),
            unique=True,
            postgresql_where=text("status = 'RUNNING'"),
        ),
        Index("ix_user_sync_runs_started_at", "started_at"),
    )
