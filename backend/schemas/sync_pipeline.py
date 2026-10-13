"""What the console is told about a "Sync All Data" run.

The shapes carry counts and statuses only. No part of the LAIT credential
appears here, and nothing from an upstream response body is relayed: a step's
`error` is a short reason written by this codebase, because these feeds are
people's names and addresses.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field, computed_field

from backend.models.sync_pipeline import PIPELINE_STEP_LABELS
from backend.schemas.base import APIModel


class SyncJobResponse(APIModel):
    """One step of one pipeline."""

    public_id: uuid.UUID
    step: str = Field(description="USERS | MANAGERS | COURSES | BATCHES | SESSIONS | ENROLLMENTS")
    position: int = Field(description="Dependency order, as the server ran it.")
    status: str = Field(description="PENDING | RUNNING | COMPLETED | FAILED | SKIPPED")
    started_at: datetime | None = None
    finished_at: datetime | None = None
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    detail: dict[str, Any] | None = Field(
        default=None, description="Per-step counts, as the step reported them."
    )
    error: str | None = Field(
        default=None, description="A short reason. Never an upstream response body."
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def label(self) -> str:
        """The step's name for people, resolved server-side so the console and
        the server cannot disagree about what a step is called."""
        return PIPELINE_STEP_LABELS.get(self.step, self.step.title())


class SyncPipelineResponse(APIModel):
    """One press of the button."""

    public_id: uuid.UUID
    trigger_type: str = Field(description="MANUAL | SCHEDULED")
    status: str = Field(description="RUNNING | COMPLETED | PARTIAL | FAILED")
    started_at: datetime
    finished_at: datetime | None = None
    failure_reason: str | None = None
    jobs: list[SyncJobResponse] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def progress_percent(self) -> int:
        """Overall progress, 0-100.

        Computed from settled steps rather than from records, because the steps
        are wildly different sizes and a record-weighted bar would sit at 4%
        through the whole user import and then jump. A running step counts as
        half, so the bar moves while a long step is in flight.
        """
        if not self.jobs:
            return 0
        settled = sum(1.0 for j in self.jobs if j.status in ("COMPLETED", "FAILED", "SKIPPED"))
        settled += sum(0.5 for j in self.jobs if j.status == "RUNNING")
        return min(100, round(settled / len(self.jobs) * 100))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def processed_total(self) -> int:
        return sum(j.processed for j in self.jobs)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def succeeded_total(self) -> int:
        return sum(j.succeeded for j in self.jobs)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def failed_total(self) -> int:
        return sum(j.failed for j in self.jobs)


class SyncPipelineStatusResponse(APIModel):
    """What the dashboard panel needs in one request."""

    running: SyncPipelineResponse | None = Field(
        default=None, description="The pipeline in flight, if any."
    )
    latest: SyncPipelineResponse | None = Field(
        default=None, description="The most recent pipeline, running or not."
    )
    last_successful_at: datetime | None = Field(
        default=None, description="When a pipeline last completed with every step succeeding."
    )
    schedule_enabled: bool = Field(
        default=False, description="Whether the scheduled worker is switched on."
    )
    schedule_interval_hours: float | None = Field(
        default=None, description="Hours between scheduled runs."
    )
    can_configure_schedule: bool = Field(
        default=False, description="Whether this caller may change the two settings above."
    )


class SyncScheduleRequest(APIModel):
    """Enable, disable or re-time the scheduled synchronisation."""

    enabled: bool
    interval_hours: float = Field(
        default=6, ge=0.25, le=168,
        description="Between 15 minutes and a week. A tighter loop would spend "
                    "the upstream rate limit without importing anything new.",
    )
