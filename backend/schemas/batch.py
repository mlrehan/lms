"""Batch schemas (spec §6)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import Field, model_validator

from backend.schemas.base import APIModel, RequestModel

BatchCode = Annotated[str, Field(min_length=2, max_length=50, pattern=r"^[A-Za-z0-9._\-]+$")]


class BatchSummary(APIModel):
    public_id: uuid.UUID
    batch_code: str
    is_active: bool
    start_date: date | None = None
    end_date: date | None = None
    capacity: int | None = None
    total_enrollments: int = Field(default=0, description="Recounted from enrollments by the LAIT sync.")

    # What an operational list needs without a request per row. Filled by `api/v1/batches.summarise`.
    course_title: str | None = None
    training_days: str | None = None
    training_method: str | None = None
    batch_fee: float | None = None
    class_duration_minutes: int | None = None
    tutor_name: str | None = Field(default=None, description="The tutor teaching most of the batch's sessions.")
    session_count: int = 0
    next_session_start: datetime | None = None


class BatchResponse(BatchSummary):
    course_id: uuid.UUID = Field(description="public_id of the owning course.")
    training_start_day: str | None = None
    training_end_day: str | None = None
    training_start_time: str | None = Field(default=None, description="HH:MM, in `schedule_timezone`.")
    training_end_time: str | None = None
    schedule_timezone: str | None = None
    academic_year_id: uuid.UUID | None = None
    academic_year_label: str | None = None
    semester_id: uuid.UUID | None = None
    semester_name: str | None = None
    duration_hours: int | None = None
    number_of_sessions: int | None = None
    notes: str | None = None
    enrolled_count: int = Field(default=0, description="Enrollments currently occupying a seat.")
    seats_available: int | None = Field(
        default=None, description="Null when the batch has no capacity limit.",
    )


class _BatchDates(RequestModel):
    @model_validator(mode="after")
    def _end_after_start(self):  # type: ignore[no-untyped-def]
        start, end = getattr(self, "start_date", None), getattr(self, "end_date", None)
        if start and end and end < start:
            raise ValueError("end_date cannot be earlier than start_date")
        return self


class BatchCreateRequest(_BatchDates):
    batch_code: BatchCode = Field(description="Unique across the institution, e.g. 'MATH101-A'.")
    capacity: int | None = Field(default=None, ge=1, le=100_000)
    duration_hours: int | None = Field(default=None, ge=0, le=100_000)
    number_of_sessions: int | None = Field(default=None, ge=0, le=10_000)
    start_date: date | None = None
    end_date: date | None = None
    notes: str | None = None
    academic_year_id: uuid.UUID | None = None
    semester_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Must belong to `academic_year_id` when both are given; naming only "
            "the semester implies its year."
        ),
    )


class BatchUpdateRequest(_BatchDates):
    batch_code: BatchCode | None = None
    capacity: int | None = Field(default=None, ge=1, le=100_000)
    duration_hours: int | None = Field(default=None, ge=0, le=100_000)
    number_of_sessions: int | None = Field(default=None, ge=0, le=10_000)
    start_date: date | None = None
    end_date: date | None = None
    notes: str | None = None
    is_active: bool | None = None
    academic_year_id: uuid.UUID | None = None
    semester_id: uuid.UUID | None = None
    clear_academic_year: bool = Field(
        default=False, description="Unschedule from its academic year (and semester)."
    )
    clear_semester: bool = Field(default=False, description="Unschedule from its semester.")
