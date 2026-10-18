"""What the permanent-deletion endpoints send and accept."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from backend.schemas.base import APIModel


class PurgeEntityOption(APIModel):
    key: str
    label: str
    singular: str = Field(description="For counts of one; \"1 people\" reads as a bug.")
    consequence: str = Field(description="What else goes, in plain words.")


class PurgeBlockedEntity(APIModel):
    """Something a caller may reasonably look for and will not find here.

    Returned so the screen can show it greyed out with the reason. A screen
    that silently omits what somebody asked for teaches them the feature is
    broken; one that explains teaches them the rule.
    """

    key: str
    label: str
    reason: str


class PurgeEntitiesResponse(APIModel):
    entities: list[PurgeEntityOption]
    blocked: list[PurgeBlockedEntity]
    unsupported_constraints: list[str] = Field(
        default_factory=list,
        description=(
            "Multi-column foreign keys, which the dependency walk cannot follow. "
            "Expected to be empty; listed so that 'none' is a measurement rather "
            "than an assumption."
        ),
    )


class PurgeTarget(APIModel):
    id: int
    label: str | None = None


class PurgeDependencyRow(APIModel):
    table: str
    column: str
    effect: str = Field(description="'cascade', 'blocks' or 'detach'.")
    rows: int
    depth: int


class PurgePreviewRequest(APIModel):
    entity: str
    ids: list[int] = Field(min_length=1, max_length=500)


class PurgeExecuteRequest(PurgePreviewRequest):
    confirmation: str = Field(
        description=(
            "The exact phrase returned by the preview as `confirmation_phrase`. "
            "It carries the real record count, so a preview that has gone stale "
            "cannot be confirmed."
        )
    )


class PurgePreviewResponse(APIModel):
    entity: str
    label: str
    singular: str
    consequence: str
    requested: int
    found: int = Field(description="How many of the requested ids still exist.")
    targets: list[PurgeTarget]
    deleted_rows: int = Field(description="Rows that will cease to exist, targets included.")
    detached_rows: int = Field(description="Rows that survive with a reference cleared.")
    breakdown: list[PurgeDependencyRow]
    detached_breakdown: list[PurgeDependencyRow]
    truncated: bool = Field(
        description=(
            "True if the dependency walk hit its depth limit. The counts are then "
            "a floor rather than a total."
        )
    )
    blockers: list[str] = Field(
        default_factory=list,
        description="Reasons this deletion will be refused. Empty means it may proceed.",
    )
    confirmation_phrase: str


class EmptyBatchRow(APIModel):
    id: int
    batch_code: str | None = None
    start_date: str | None = None
    sessions: int


class EmptyBatchesResponse(APIModel):
    batches: list[EmptyBatchRow]


class SystemResetImpact(APIModel):
    table: str
    label: str
    rows: int


class SystemResetPreviewResponse(APIModel):
    database: str
    environment: str
    enabled: bool = Field(
        description=(
            "Whether this installation will carry a reset out at all. False means "
            "the endpoint exists and is gated shut by configuration."
        )
    )
    blockers: list[str] = Field(
        default_factory=list,
        description="Why a reset cannot proceed here. Empty means it would run.",
    )
    impact: list[SystemResetImpact]
    total_rows: int
    preserved: list[str] = Field(
        description="What a reset keeps: reference data, the schema, and the audit trail."
    )
    confirmation_phrase: str


class SystemResetRequest(APIModel):
    confirmation: str = Field(
        description="The exact phrase from the preview, which names this database."
    )
    # There is deliberately no "clear the audit trail too" option. The database
    # keeps `audit_logs` append-only with a trigger covering DELETE, UPDATE and
    # TRUNCATE, so the field could only ever have been a request that failed --
    # and an append-only guarantee an endpoint can switch off is not one.


class SystemResetResponse(APIModel):
    database: str
    rows_deleted: int
    cleared: list[SystemResetImpact]
    seeded: dict[str, Any]
    bootstrap_username: str
    bootstrap_password: str = Field(
        description=(
            "Shown exactly once, in this response, and never stored in readable "
            "form or written to a log. If it is lost, the only way back is the "
            "bootstrap command with shell access."
        )
    )
    sessions_invalidated: int
    warnings: list[str] = Field(default_factory=list)
