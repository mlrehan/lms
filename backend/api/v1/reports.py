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
    CourseworkGroupBy,
    GradingQueueGroupBy,
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

    `lowest`, `median` and `highest` are taken across *students*, each first
    reduced to their own weighted percentage, so they will not agree with the
    mark-weighted average — and that disagreement is the useful part. An
    average of 68% over a cohort whose median is 81% is a cohort with a few
    students in serious trouble.

    `group_by=month` keys on when a mark was **recorded**, the only date a
    grade-book entry carries. A term's marking entered in one sitting shows as
    one month; reading that as a sudden improvement would be wrong.
    """
    report = await ReportService(session).performance(
        actor=actor, group_by=group_by, course_id=course_id, batch_id=batch_id
    )
    return _render(report, format, actor)


@router.get(
    "/coursework",
    response_model=ReportResponse,
    summary="Submission, lateness and grading status, grouped",
)
async def coursework_report(
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
    group_by: Annotated[CourseworkGroupBy, Query()] = CourseworkGroupBy.ASSIGNMENT,
    course_id: Annotated[uuid.UUID | None, Query()] = None,
    batch_id: Annotated[uuid.UUID | None, Query()] = None,
    format: Annotated[ReportFormat, Query()] = ReportFormat.JSON,
):  # type: ignore[no-untyped-def]
    """Measured against **eligible students**, not submission rows.

    Counting over submissions gives a submission rate of 100% by
    construction, because a student who never handed anything in has no row
    to count. The population comes from the same scope rule that decides who
    an assignment was set for, so `missing` is a real number and the three
    reports §34 asks for -- submission, missing work, grading status -- are
    three readings of one query rather than three endpoints that can drift.

    Draft assignments are excluded: a draft has been set for nobody, so its
    "missing submissions" would be work nobody was asked to do.

    A rate over an empty population is `null`, never `0` — "no coursework has
    been set" is not "nobody submitted".
    """
    report = await ReportService(session).coursework(
        actor=actor, group_by=group_by, course_id=course_id, batch_id=batch_id
    )
    return _render(report, format, actor)


@router.get(
    "/distribution",
    response_model=ReportResponse,
    summary="Grade distribution across a cohort",
)
async def distribution_report(
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
    course_id: Annotated[uuid.UUID | None, Query()] = None,
    batch_id: Annotated[uuid.UUID | None, Query()] = None,
    format: Annotated[ReportFormat, Query()] = ReportFormat.JSON,
):  # type: ignore[no-untyped-def]
    """The shape an average cannot show.

    A cohort averaging 68% might be thirty students clustered at 68, or
    fifteen at 85 and fifteen at 50 — the same mean, and completely different
    teaching problems.

    **A course or batch is required.** Grade bands belong to a grading scheme
    and a course may override the institution's (§13), so a distribution drawn
    across two schemes would add together bands that do not mean the same
    thing. That is refused rather than rendered.

    Counted against the enrolled roster, so students nobody has assessed
    appear as their own row instead of silently shrinking the cohort the
    shape describes. Bands nobody reached are reported as zero rather than
    omitted — a gap in the middle of a distribution is the interesting part.
    """
    report = await ReportService(session).distribution(
        actor=actor, course_id=course_id, batch_id=batch_id
    )
    return _render(report, format, actor)


@router.get(
    "/grading-queue",
    response_model=ReportResponse,
    summary="What is waiting to be marked, grouped",
)
async def grading_queue_report(
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
    group_by: Annotated[GradingQueueGroupBy, Query()] = GradingQueueGroupBy.COURSE,
    course_id: Annotated[uuid.UUID | None, Query()] = None,
    batch_id: Annotated[uuid.UUID | None, Query()] = None,
    format: Annotated[ReportFormat, Query()] = ReportFormat.JSON,
):  # type: ignore[no-untyped-def]
    """§34's Tutor Grading Status, across assignments, quizzes and exams.

    A queue, not a rate. Each type's definition of "waiting" is its own: a
    submission that arrived without a mark, a *finished* quiz attempt with no
    score (how an auto-graded quiz says something needed a person), and an
    exam result row with no marks entered — the offline case.

    An exam with no result rows at all is not counted: nobody has said those
    students sat it, and a queue that assumed they had would show every future
    exam as outstanding work.

    Groups with nothing outstanding are omitted. An empty queue is the absence
    of work, and listing every course with a zero turns the answer into a
    directory nobody can scan.
    """
    report = await ReportService(session).grading_queue(
        actor=actor, group_by=group_by, course_id=course_id, batch_id=batch_id
    )
    return _render(report, format, actor)
