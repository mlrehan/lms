"""Global search schemas (spec §22)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import Field

from backend.schemas.base import APIModel


class SearchType(str, Enum):
    COURSE = "course"
    USER = "user"
    BATCH = "batch"
    RESOURCE = "resource"
    ASSIGNMENT = "assignment"
    ANNOUNCEMENT = "announcement"
    DISCUSSION = "discussion"


class SearchHit(APIModel):
    type: SearchType
    public_id: uuid.UUID
    label: str = Field(description="The primary name — a course title, a username.")
    subtitle: str | None = Field(
        default=None, description="Enough context to tell two similar hits apart."
    )
    created_at: datetime | None = None


class SearchGroup(APIModel):
    type: SearchType
    total: int = Field(
        description="Matches this caller may see, ignoring the per-group cap."
    )
    items: list[SearchHit]
    truncated: bool = Field(
        default=False, description="More matches exist than the per-group cap returns."
    )


class SearchResponse(APIModel):
    query: str
    generated_at: datetime
    searched: list[SearchType] = Field(
        description="Types actually queried — the caller's permissions decide."
    )
    skipped: list[SearchType] = Field(
        default_factory=list,
        description="Types omitted because the caller cannot read them at all.",
    )
    total: int = Field(description="Sum across every group.")
    groups: list[SearchGroup]
