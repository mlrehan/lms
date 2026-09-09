"""Announcement schemas (spec §16).

Targeting is three explicit, independently-nullable columns -- course, batch,
role -- rather than a free-form audience blob. NULL on a dimension means "not
narrowed by it", so all three NULL is an institution-wide notice. That shape
is what makes the feed query indexable; a JSON audience would have to be
deserialised per row to answer "is this for me?".
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field, model_validator

from backend.schemas.base import APIModel, RequestModel
from backend.schemas.messaging import PartyRef
from backend.utils.enums import Roles


class AnnouncementResponse(APIModel):
    public_id: uuid.UUID
    title: str
    content: str
    author: PartyRef | None = None
    course_id: uuid.UUID | None = None
    course_title: str | None = None
    batch_id: uuid.UUID | None = None
    batch_code: str | None = None
    role_scope: Roles | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    pinned: bool = False
    is_live: bool = Field(
        default=False, description="Whether the display window currently includes now."
    )


class CreateAnnouncementRequest(RequestModel):
    title: Annotated[str, Field(min_length=1, max_length=255)]
    content: Annotated[str, Field(min_length=1, max_length=20_000)]
    course_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    role_scope: Roles | None = Field(
        default=None, description="Narrow to one role. Omit for every role."
    )
    start_at: datetime | None = Field(
        default=None, description="Defaults to now, i.e. publish immediately."
    )
    end_at: datetime | None = Field(
        default=None, description="Omit for an announcement that never expires."
    )
    pinned: bool = False

    @model_validator(mode="after")
    def _window_is_ordered(self) -> "CreateAnnouncementRequest":
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at.")
        return self


class UpdateAnnouncementRequest(RequestModel):
    title: Annotated[str | None, Field(min_length=1, max_length=255)] = None
    content: Annotated[str | None, Field(min_length=1, max_length=20_000)] = None
    role_scope: Roles | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    pinned: bool | None = None

    @model_validator(mode="after")
    def _window_is_ordered(self) -> "UpdateAnnouncementRequest":
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at.")
        return self
