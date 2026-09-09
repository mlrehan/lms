"""Attendance endpoints (spec §9)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.attendance import Attendance
from backend.schemas.attendance import (
    AttendanceResponse,
    AttendanceSummaryResponse,
    MarkAttendanceRequest,
)
from backend.schemas.base import Page, PageParams
from backend.services.attendance_service import AttendanceService
from backend.utils.enums import AttendanceStatus

router = APIRouter(tags=["Attendance"])


def _response(a: Attendance) -> AttendanceResponse:
    return AttendanceResponse(
        public_id=a.public_id,
        session_id=a.session.public_id,
        session_start_time=a.session.session_start_time,
        batch_code=a.session.batch.batch_code if a.session.batch else None,
        student_id=a.student.public_id,
        student_username=a.student.username,
        status=a.status,
        remarks=a.remarks,
        recorded_at=a.recorded_at,
        recorded_by_username=a.tutor.username if a.tutor else None,
    )


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
