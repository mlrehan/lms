"""Class session schemas (spec §8)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field, model_validator

from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import Platforms


class SessionSummary(APIModel):
    public_id: uuid.UUID
    session_start_time: datetime | None = None
    session_end_time: datetime | None = None
    duration_minutes: int | None = None
    platform: Platforms
    classroom: str | None = None


class SessionResponse(SessionSummary):
    batch_id: uuid.UUID
    batch_code: str | None = None
    course_title: str | None = None
    tutor_id: uuid.UUID
    tutor_username: str | None = None
    meeting_link: str | None = None
    recording_link: str | None = None
    tutor_notes: str | None = None
    student_notes: str | None = None
    attendance_recorded: bool = Field(
        default=False, description="True once a register has been marked for this session."
    )


class _SessionTimes(RequestModel):
    @model_validator(mode="after")
    def _end_after_start(self):  # type: ignore[no-untyped-def]
        start = getattr(self, "session_start_time", None)
        end = getattr(self, "session_end_time", None)
        if start and end and end <= start:
            raise ValueError("session_end_time must be after session_start_time")
        return self


class SessionCreateRequest(_SessionTimes):
    tutor_id: uuid.UUID = Field(
        description=(
            "The tutor taking this session. Assigning one grants them access to "
            "the batch's students, so it must be a user holding the TUTOR role."
        )
    )
    session_start_time: datetime
    session_end_time: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    platform: Platforms = Platforms.Zoom
    classroom: Annotated[str | None, Field(max_length=255)] = None
    meeting_link: Annotated[str | None, Field(max_length=2048)] = None
    tutor_notes: str | None = None


class SessionUpdateRequest(_SessionTimes):
    tutor_id: uuid.UUID | None = None
    session_start_time: datetime | None = None
    session_end_time: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    platform: Platforms | None = None
    classroom: Annotated[str | None, Field(max_length=255)] = None
    meeting_link: Annotated[str | None, Field(max_length=2048)] = None
    recording_link: Annotated[str | None, Field(max_length=2048)] = None
    tutor_notes: str | None = None
    student_notes: str | None = None
