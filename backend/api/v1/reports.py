"""Institution report endpoints (spec §18).

Three reports, each grouped several ways and each available as JSON or CSV.
`?format=csv` is checked against `report.export` **inside** the handler rather
than by a second dependency, because it is one report with two renderings and
splitting it into `/reports/attendance` and `/reports/attendance.csv` would
duplicate every filter parameter twice over.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from backend.api.deps import CurrentUser, require_permissions, resolve_permissions
from backend.core.errors import AuthorizationError
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.identity.user import User
from backend.schemas.reporting import (
    AttendanceGroupBy,
    EnrollmentGroupBy,
    PerformanceGroupBy,
    ReportFormat,
    ReportResponse,
)
from backend.services.report_service import ReportService

router = APIRouter(prefix="/reports", tags=["Reports"])

_READ = require_permissions(perm(Module.REPORT, Action.READ))
_EXPORT = perm(Module.REPORT, Action.EXPORT)


def _render(report: ReportResponse, fmt: ReportFormat, actor: User) -> Response | ReportResponse:
    if fmt is ReportFormat.JSON:
        return report

    if _EXPORT not in resolve_permissions(actor):
        # Seeing the numbers and taking them away are different acts. A tutor
        # holds `report.read` and not `report.export` on purpose: the figures
        # for their own batches are theirs to consult, and a file is theirs
        # to keep after their account is closed.
        raise AuthorizationError(
            "You do not have permission to export reports.",
            details={"required": [_EXPORT]},
        )

    filename = f"{report.report}-by-{report.group_by}.csv"
    return Response(
        content=ReportService.to_csv(report),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/attendance",
    response_model=ReportResponse,
    summary="Attendance, grouped",
)
async def attendance_report(
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
    group_by: Annotated[AttendanceGroupBy, Query()] = AttendanceGroupBy.BATCH,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query(description="Exclusive upper bound.")] = None,
    course_id: Annotated[uuid.UUID | None, Query()] = None,
    batch_id: Annotated[uuid.UUID | None, Query()] = None,
    format: Annotated[ReportFormat, Query()] = ReportFormat.JSON,
):  # type: ignore[no-untyped-def]
    """Spec §9's per-tutor, per-course and monthly views, which the existing
    `/attendance/summary` (a single scalar) could not express.

    Ranged on the **session's** scheduled time, not on when the register was
    filled in: a mark recorded late still belongs to the class it describes.
    The window is half-open and defaults to the last year — an unbounded
    default is the slowest query in the system and the largest answer, run by
    accident.

    Scoped like every listing: a tutor sees the batches they teach, a guardian
    their wards, an Administrator the institution.
    """
    report = await ReportService(session).attendance(
        actor=actor,
        group_by=group_by,
        date_from=date_from,
        date_to=date_to,
        course_id=course_id,
        batch_id=batch_id,
    )
    return _render(report, format, actor)


@router.get(
    "/enrollment",
    response_model=ReportResponse,
    summary="Enrollments, grouped",
)
async def enrollment_report(
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
    group_by: Annotated[EnrollmentGroupBy, Query()] = EnrollmentGroupBy.COURSE,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query(description="Exclusive upper bound.")] = None,
    course_id: Annotated[uuid.UUID | None, Query()] = None,
    format: Annotated[ReportFormat, Query()] = ReportFormat.JSON,
):  # type: ignore[no-untyped-def]
    """Every enrollment status gets a column even when it is zero, so a CSV
    keeps the same shape month to month — a spreadsheet whose columns appear
    and disappear cannot be appended to."""
    report = await ReportService(session).enrollment(
        actor=actor,
        group_by=group_by,
        date_from=date_from,
        date_to=date_to,
        course_id=course_id,
    )
    return _render(report, format, actor)


@router.get(
    "/performance",
    response_model=ReportResponse,
    summary="Grade performance, grouped",
)
async def performance_report(
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
    group_by: Annotated[PerformanceGroupBy, Query()] = PerformanceGroupBy.BATCH,
    course_id: Annotated[uuid.UUID | None, Query()] = None,
    batch_id: Annotated[uuid.UUID | None, Query()] = None,
    format: Annotated[ReportFormat, Query()] = ReportFormat.JSON,
):  # type: ignore[no-untyped-def]
    """Averaged as `SUM(score) / SUM(max_score)`, not as the mean of each
    row's percentage — a 1-mark quiz and a 100-mark exam are not equal halves
    of a student's performance, and averaging percentages would make them so.

    A group with no assessable marks reports `average_percent: null`, never
    `0`: "nothing graded yet" and "scored nothing" are different facts and
    only one of them belongs at the bottom of a distribution.
    """
    report = await ReportService(session).performance(
        actor=actor, group_by=group_by, course_id=course_id, batch_id=batch_id
    )
    return _render(report, format, actor)
