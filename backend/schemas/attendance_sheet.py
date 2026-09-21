"""Attendance as a workflow: the queue of sessions to do, and the sheet for one of them.

People are names only (`core/privacy.py`): a tutor sees who is in their class, not how to contact them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import Field, field_validator

from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import AttendanceStatus, Platforms


class SheetState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class SheetPerson(APIModel):
    public_id: uuid.UUID
    name: str


class SheetRow(APIModel):
    student: SheetPerson
    status: AttendanceStatus | None = Field(default=None, description="Null until somebody has marked this student.")
    remarks: str | None = None


class SheetSummary(APIModel):
    present: int = 0
    late: int = 0
    absent: int = 0
    excused: int = 0
    unmarked: int = 0
    total: int = 0
    rate: float | None = Field(default=None, description="(present + late) / (marked - excused), as a percentage.")


class SheetSession(APIModel):
    public_id: uuid.UUID
    start_time: datetime | None = None
    end_time: datetime | None = None
    platform: Platforms | None = None
    classroom: str | None = None
    cancelled: bool = False


class SheetBatch(APIModel):
    public_id: uuid.UUID
    batch_code: str
    course_title: str | None = None
    enrolled: int = 0


class SheetMeta(APIModel):
    state: SheetState
    assigned_tutor: SheetPerson
    started_by: SheetPerson | None = None
    started_at: datetime | None = None
    last_saved_by: SheetPerson | None = None
    last_saved_at: datetime | None = None
    finalized_by: SheetPerson | None = None
    finalized_at: datetime | None = None
    submitted_on_behalf: bool = False
    legacy: bool = Field(default=False, description="Marked before sheets existed: finalized, with no record of who started it.")


class SheetPermissions(APIModel):
    can_edit: bool
    is_assigned_tutor: bool
    would_be_on_behalf: bool = Field(description="True when the caller may edit only because they may act for the assigned tutor.")


class SheetView(APIModel):
    session: SheetSession
    batch: SheetBatch
    meta: SheetMeta
    permissions: SheetPermissions
    notes: str | None = None
    roster: list[SheetRow]
    summary: SheetSummary


class SheetEntry(RequestModel):
    student_id: uuid.UUID
    status: AttendanceStatus | None = Field(default=None, description="Null clears a mark (draft only).")
    remarks: Annotated[str | None, Field(max_length=1000)] = None


class SaveSheetRequest(RequestModel):
    entries: list[SheetEntry] = Field(default_factory=list, max_length=500)
    notes: Annotated[str | None, Field(max_length=2000)] = None
    submit: bool = Field(default=False, description="False saves a draft. True finalizes (or, on a finalized sheet, records an edit).")

    @field_validator("entries")
    @classmethod
    def _one_entry_per_student(cls, entries: list[SheetEntry]) -> list[SheetEntry]:
        if len({e.student_id for e in entries}) != len(entries):
            raise ValueError("each student may appear only once per request")
        return entries


class SheetChange(APIModel):
    student: str
    was: str | None = None
    now: str | None = None
    remarks_changed: bool = False


class SheetEvent(APIModel):
    action: str
    at: datetime
    actor: SheetPerson
    assigned_tutor: SheetPerson
    on_behalf: bool
    counts: dict[str, int] = Field(default_factory=dict)
    changes: list[SheetChange] = Field(default_factory=list)
    notes_changed: bool = False


class SheetHistory(APIModel):
    events: list[SheetEvent]


class QueueItem(APIModel):
    session_id: uuid.UUID
    start_time: datetime | None = None
    end_time: datetime | None = None
    batch_id: uuid.UUID
    batch_code: str
    course_title: str | None = None
    tutor: SheetPerson
    enrolled: int
    state: SheetState
    marked: int = 0
    submitted_on_behalf: bool = False
    finalized_at: datetime | None = None
    can_edit: bool = False
