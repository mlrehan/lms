"""Attendance endpoints (spec §9)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.core.privacy import visible_username
from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.attendance import Attendance
from backend.schemas.attendance import (
    AttendanceResponse,
    AttendanceSummaryResponse,
    MarkAttendanceRequest,
)
from backend.schemas.attendance_sheet import QueueItem, SaveSheetRequest, SheetHistory, SheetView
from backend.schemas.base import Page, PageParams
from backend.services.attendance_service import AttendanceService
from backend.services.attendance_sheet_service import AttendanceSheetService
from backend.utils.enums import AttendanceStatus

router = APIRouter(tags=["Attendance"])


def _response(a: Attendance) -> AttendanceResponse:
    return AttendanceResponse(
        public_id=a.public_id,
        session_id=a.session.public_id,
        session_start_time=a.session.session_start_time,
        batch_code=a.session.batch.batch_code if a.session.batch else None,
        student_id=a.student.public_id,
        student_username=visible_username(a.student),
        status=a.status,
        remarks=a.remarks,
        recorded_at=a.recorded_at,
        recorded_by_username=visible_username(a.tutor) if a.tutor else None,
    )


_SHEET = require_permissions(perm(Module.ATTENDANCE, Action.CREATE))


@router.get("/attendance/queue", response_model=Page[QueueItem], summary="Sessions to take or review attendance for")
async def attendance_queue(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(_SHEET)],
    batch_id: Annotated[uuid.UUID | None, Query()] = None,
    tutor_id: Annotated[uuid.UUID | None, Query(description="Narrow to one tutor's sessions (administrators only see other tutors').")] = None,
    state: Annotated[str | None, Query(pattern="^(PENDING|NOT_STARTED|DRAFT|FINALIZED)$")] = None,
    starts_from: Annotated[datetime | None, Query()] = None,
    starts_to: Annotated[datetime | None, Query()] = None,
) -> Page[QueueItem]:
    """A tutor sees only the sessions assigned to them. An administrator or the Super Admin sees every session and can
    narrow by batch and tutor: Batch -> Session -> Tutor -> Attendance."""
    items, total = await AttendanceSheetService(session).queue(
        actor, params, batch_public_id=batch_id, tutor_public_id=tutor_id, state=state, starts_from=starts_from, starts_to=starts_to
    )
    return Page.build(items, total=total, params=params)


@router.get("/attendance/sessions/{session_id}/sheet", response_model=SheetView, summary="The attendance sheet for a session")
async def get_sheet(session_id: uuid.UUID, session: DBSession, actor: Annotated[CurrentUser, Depends(_SHEET)]) -> SheetView:
    return await AttendanceSheetService(session).view(actor, session_id)


@router.put("/attendance/sessions/{session_id}/sheet", response_model=SheetView, summary="Save a draft, submit, or correct a submitted sheet")
async def save_sheet(session_id: uuid.UUID, payload: SaveSheetRequest, session: DBSession, actor: Annotated[CurrentUser, Depends(_SHEET)]) -> SheetView:
    """`submit: false` saves a draft (nothing reaches the attendance record). `submit: true` finalizes it, and on an
    already-submitted sheet records a correction. Only the session's assigned tutor may; the Super Admin may act on
    the tutor's behalf, and that is recorded."""
    return await AttendanceSheetService(session).save(actor, session_id, payload)


@router.get("/attendance/sessions/{session_id}/sheet/history", response_model=SheetHistory, summary="Who did what to this sheet")
async def sheet_history(session_id: uuid.UUID, session: DBSession, actor: Annotated[CurrentUser, Depends(_SHEET)]) -> SheetHistory:
    return SheetHistory(events=await AttendanceSheetService(session).history(actor, session_id))


@router.put(
    "/sessions/{session_id}/attendance",
    response_model=list[AttendanceResponse],
    summary="Mark the register for a session",
)
async def mark_attendance(
    session_id: uuid.UUID,
    payload: MarkAttendanceRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ATTENDANCE, Action.CREATE)))
    ],
) -> list[AttendanceResponse]:
    """Bulk by design — a tutor records the whole class at once, and thirty
    separate requests would leave a half-marked register if one failed.

    Idempotent: re-sending corrects the existing entries rather than adding
    duplicates. Marking a student who is not enrolled in this session's batch
    refuses the *whole* request, since a register that silently drops names
    is worse than one that fails visibly.

    Returns the complete register for the session, not just the rows sent.
    """
    rows = await AttendanceService(session).mark(session_id, payload.entries, actor=actor)
    return [_response(r) for r in rows]


@router.get(
    "/attendance", response_model=Page[AttendanceResponse], summary="List attendance records"
)
async def list_attendance(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ATTENDANCE, Action.READ)))
    ],
    session_id: Annotated[uuid.UUID | None, Query()] = None,
    student_id: Annotated[uuid.UUID | None, Query()] = None,
    batch_id: Annotated[uuid.UUID | None, Query()] = None,
    attendance_status: Annotated[AttendanceStatus | None, Query(alias="status")] = None,
) -> Page[AttendanceResponse]:
    """Row-scoped: a Tutor reaches attendance through the sessions they
    teach, a Guardian or Corporate Manager through the people in their care,
    a Student through their own records."""
    rows, total = await AttendanceService(session).list_attendance(
        params,
        actor=actor,
        session_public_id=session_id,
        student_public_id=student_id,
        batch_public_id=batch_id,
        status=attendance_status,
    )
    return Page.build([_response(r) for r in rows], total=total, params=params)


@router.get(
    "/attendance/summary",
    response_model=AttendanceSummaryResponse,
    summary="Attendance totals and rate",
)
async def attendance_summary(
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ATTENDANCE, Action.READ)))
    ],
    student_id: Annotated[uuid.UUID | None, Query()] = None,
    batch_id: Annotated[uuid.UUID | None, Query()] = None,
) -> AttendanceSummaryResponse:
    """Spec §9's reporting, per student and/or per batch.

    The caller's scope is applied to the aggregate as well as to listings — a
    summary computed over rows they cannot see would leak the same
    information one number at a time.

    `attendance_rate` is (present + late) / (total − excused): an excused
    absence leaves the denominator rather than counting against the student.
    """
    return await AttendanceService(session).summarise(
        actor=actor, student_public_id=student_id, batch_public_id=batch_id
    )
