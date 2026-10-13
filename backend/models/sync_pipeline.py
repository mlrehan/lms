"""One "Sync All Data" press, and the ordered jobs it runs.

`user_sync_runs` already records *one* synchronisation of *one* kind. What it
cannot express is the thing the Super Admin actually presses: six steps that
must happen in dependency order, where a batch is meaningless before its
course exists and an enrolment is meaningless before both. These two tables
are that pipeline -- the parent is the press, the children are the steps.

Three properties are enforced here rather than remembered:

* **One pipeline at a time.** A partial unique index allows at most one row in
  `RUNNING`, exactly as `user_sync_runs` does for a single run, so two presses
  (or a press racing the scheduler) cannot both start. The database refuses the
  second; nothing depends on a service checking first.
* **A step's place in the order is data, not code.** `position` is stored, so
  the console renders the order the server actually ran rather than a list
  hard-coded in the UI that could drift from it.
* **A step says what it did.** `processed`, `succeeded` and `failed` are
  separate columns because "ran" and "worked" are different claims, and a step
  that processed 400 records and failed 400 of them must not read as success.

`sync_run_id` points at the `user_sync_runs` row for the steps backed by an
existing service, so the detailed per-record errors those services already
record stay reachable instead of being copied.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, PublicIdMixin

# The six steps, in the only order that can work: a batch needs its course, a
# session needs its batch, an enrolment needs the student, course and batch.
# Managers come second because linking a manager to a delegate needs both
# accounts to exist, and step one is what creates them.
PIPELINE_STEPS: tuple[str, ...] = (
    "USERS",
    "MANAGERS",
    "COURSES",
    "BATCHES",
    "SESSIONS",
    "ENROLLMENTS",
)

PIPELINE_STEP_LABELS: dict[str, str] = {
    "USERS": "Sync users",
    "MANAGERS": "Assign managers",
    "COURSES": "Sync courses",
    "BATCHES": "Sync batches",
    "SESSIONS": "Sync sessions",
    "ENROLLMENTS": "Sync enrollments",
}


class SyncPipelineRun(Base, PublicIdMixin):
    """One press of "Sync All Data", or one scheduled equivalent."""

    __tablename__ = "sync_pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    trigger_type: Mapped[str] = mapped_column(String(10), nullable=False)  # MANUAL | SCHEDULED
    triggered_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        comment="Null for a scheduled run: nobody pressed it.",
    )

    # PENDING | RUNNING | COMPLETED | PARTIAL | FAILED
    status: Mapped[str] = mapped_column(String(10), nullable=False, index=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # A whole-pipeline failure (the API unreachable, a bad key) as distinct
    # from a step's own failure, which lives on the step.
    failure_reason: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    jobs: Mapped[list["SyncPipelineJob"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="SyncPipelineJob.position",
        lazy="selectin",
    )

    __table_args__ = (
        # At most one RUNNING pipeline, ever. `((true))` indexes a constant, so
        # any two qualifying rows collide. This is the duplicate-run guard; no
        # service is trusted to check first.
        Index(
            "ux_sync_pipeline_runs_one_running",
            text("(true)"),
            unique=True,
            postgresql_where=text("status = 'RUNNING'"),
        ),
        Index("ix_sync_pipeline_runs_started_at", "started_at"),
    )


class SyncPipelineJob(Base, PublicIdMixin):
    """One step of one pipeline."""

    __tablename__ = "sync_pipeline_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sync_pipeline_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    step: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Dependency order, stored so the console cannot disagree with the server."
    )

    # PENDING | RUNNING | COMPLETED | FAILED | SKIPPED
    status: Mapped[str] = mapped_column(String(10), nullable=False)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    processed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    succeeded: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    # Free-form per-step detail: {"created": n, "updated": n, ...}. Kept as the
    # step reported it rather than flattened, so a step can describe itself.
    detail: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # The `user_sync_runs` row this step drove, where one exists. The detailed
    # per-record errors stay there; copying them would be two sources of truth.
    sync_run_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user_sync_runs.id", ondelete="SET NULL"), nullable=True
    )

    run: Mapped["SyncPipelineRun"] = relationship(back_populates="jobs")

    __table_args__ = (
        # A pipeline has each step exactly once; a retry re-runs the row rather
        # than adding a second one, so history stays one row per step per press.
        UniqueConstraint("pipeline_run_id", "step", name="uq_sync_pipeline_jobs_run_step"),
    )
