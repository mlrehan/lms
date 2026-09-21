"""Generating and replacing a batch's sessions."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import Field, field_validator

from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import Platforms


class PlanRequest(RequestModel):
    """Everything is optional except the zone: what is left out comes from the batch (or its existing sessions)."""

    timezone: str = Field(default="UTC", max_length=50, description="The zone the dates, weekdays and clock times are read in.")
    start_date: date | None = None
    end_date: date | None = None
    weekdays: list[int] | None = Field(default=None, description="0 = Monday ... 6 = Sunday.")
    start_time: time | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=24 * 60)
    sessions: int | None = Field(default=None, ge=1, le=200)

    @field_validator("weekdays")
    @classmethod
    def _valid_days(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and any(d < 0 or d > 6 for d in value):
            raise ValueError("weekdays must be 0 (Monday) to 6 (Sunday)")
        return value


class PlanSettingsOut(APIModel):
    timezone: str
    weekdays: list[int]
    training_days: str
    start_time: str | None = None
    duration_minutes: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    sessions: int | None = None
    source: str = Field(description="Where the defaults came from: the batch's schedule, its existing sessions, or nothing.")
    note: str | None = Field(default=None, description="Explains a carry across time zones, when there was one.")


class PlannedSessionOut(APIModel):
    index: int
    start_utc: datetime
    end_utc: datetime
    start_local: str = Field(description="Wall-clock start in the plan's zone, `YYYY-MM-DDTHH:mm`.")
    duration_minutes: int
    weekday: str


class ExistingSessions(APIModel):
    total: int
    protected: int = Field(description="Sessions that hold attendance, a recording or notes, and are never deleted by a re-create.")
    replaceable: int
    protected_reasons: list[str] = Field(default_factory=list)
    first_start: datetime | None = None
    last_start: datetime | None = None


class PlanPerson(APIModel):
    public_id: uuid.UUID
    name: str


class PlanResponse(APIModel):
    settings: PlanSettingsOut
    sessions: list[PlannedSessionOut]
    warnings: list[str]
    existing: ExistingSessions
    default_tutor: PlanPerson | None = None
    default_platform: Platforms | None = None
    batch_code: str
    course_title: str | None = None


class ReplaceRow(RequestModel):
    start_utc: datetime
    end_utc: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=24 * 60)
    tutor_id: uuid.UUID
    platform: Platforms = Platforms.Zoom
    classroom: str | None = Field(default=None, max_length=255)
    meeting_link: str | None = Field(default=None, max_length=2048)


class ScheduleToSave(RequestModel):
    """The schedule these sessions were generated from, kept on the batch so the next re-create starts from it."""

    timezone: str = Field(max_length=50)
    weekdays: list[int] = Field(default_factory=list)
    start_time: time | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=24 * 60)


class ReplaceRequest(RequestModel):
    sessions: list[ReplaceRow] = Field(min_length=1, max_length=200)
    confirm_replace: bool = Field(default=False, description="Required when the batch already has sessions that would be replaced.")
    schedule: ScheduleToSave | None = None


class ReplaceResponse(APIModel):
    created: int
    replaced: int = Field(description="Existing sessions removed to make way for the new ones.")
    kept_protected: int = Field(description="Existing sessions kept because they hold attendance, a recording or notes.")
    skipped: int = Field(description="Proposed sessions not created because a protected session already starts then.")
    total_sessions: int
