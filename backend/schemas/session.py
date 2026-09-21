"""Class session schemas (spec §8)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
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


class CalendarSession(APIModel):
    """One block on the calendar: enough to draw and filter it without a request per session."""

    public_id: uuid.UUID
    batch_id: uuid.UUID
    batch_code: str
    course_title: str | None = None
    tutor_id: uuid.UUID
    tutor_name: str | None = None
    session_start_time: datetime
    session_end_time: datetime = Field(description="Start plus duration (an hour if neither is stored) when no end was saved.")
    platform: Platforms
    classroom: str | None = None
    meeting_link: str | None = None
    origin: str | None = None


class CalendarResponse(APIModel):
    items: list[CalendarSession]
    truncated: bool = Field(description="True when the window held more sessions than the cap; narrow it.")


class OverviewPerson(APIModel):
    public_id: uuid.UUID
    name: str
    email: str | None = Field(default=None, description="Only for administrators and the batch's tutors.")
    phone: str | None = None
    detail: str | None = Field(default=None, description="A guardian's relationship, or a manager's job title.")


class OverviewRosterEntry(APIModel):
    student: OverviewPerson
    enrollment_status: str
    attendance: str | None = None
    organization: str | None = None
    guardians: list[OverviewPerson] = []
    managers: list[OverviewPerson] = []


class OverviewCourse(APIModel):
    public_id: uuid.UUID
    title: str
    code: str | None = None
    level: str | None = None


class OverviewBatch(APIModel):
    public_id: uuid.UUID
    batch_code: str
    capacity: int | None = None
    enrolled: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_active: bool


class SessionOverview(APIModel):
    public_id: uuid.UUID
    number: int
    total: int
    session_start_time: datetime
    session_end_time: datetime | None = None
    duration_minutes: int | None = None
    platform: Platforms
    classroom: str | None = None
    meeting_link: str | None = None
    recording_link: str | None = None
    student_notes: str | None = None
    tutor_notes: str | None = None
    origin: str | None = None
    in_google: bool
    course: OverviewCourse
    batch: OverviewBatch
    tutor: OverviewPerson
    roster: list[OverviewRosterEntry]
    roster_is_partial: bool = Field(description="True when the caller sees only their own people, not the whole batch.")
    attendance_counts: dict[str, int]
    can_see_contacts: bool
