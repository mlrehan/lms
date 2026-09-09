"""Attendance schemas (spec §9)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field, field_validator

from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import AttendanceStatus


class AttendanceResponse(APIModel):
    public_id: uuid.UUID
    session_id: uuid.UUID
    session_start_time: datetime | None = None
    batch_code: str | None = None
    student_id: uuid.UUID
    student_username: str | None = None
    status: AttendanceStatus
    remarks: str | None = None
    recorded_at: datetime | None = None
    recorded_by_username: str | None = None


class AttendanceEntry(RequestModel):
    student_id: uuid.UUID
    status: AttendanceStatus
    remarks: Annotated[str | None, Field(max_length=1000)] = None


class MarkAttendanceRequest(RequestModel):
    """Marking a register is inherently a bulk act -- a tutor records the
    whole class at once. A one-student-at-a-time API would mean thirty
    requests to take one register, and a half-finished register if the
    fifteenth failed."""

    entries: list[AttendanceEntry] = Field(min_length=1, max_length=500)

    @field_validator("entries")
    @classmethod
    def _no_duplicate_students(cls, entries: list[AttendanceEntry]) -> list[AttendanceEntry]:
        seen = {e.student_id for e in entries}
        if len(seen) != len(entries):
            # Two entries for one student in a single request have no
            # defined winner; refusing is better than silently picking one.
            raise ValueError("each student may appear only once per request")
        return entries


class AttendanceSummaryResponse(APIModel):
    """Spec §9's attendance reporting."""

    present: int = 0
    late: int = 0
    absent: int = 0
    excused: int = 0
    total: int = 0
    attendance_rate: float | None = Field(
        default=None,
        description=(
            "(present + late) / (total - excused), as a percentage. Excused "
            "absences leave the denominator rather than counting against the "
            "student. Null when there is nothing to divide by."
        ),
    )
