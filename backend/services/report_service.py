"""Institution reports (spec §18).

Three reports — attendance, enrollment, performance — each grouped several
ways, each scoped to what the caller may already see, and each exportable as
CSV under a separate permission.

**Scoping is not relaxed for reports.** The aggregate goes through the same
`AttendanceVisibility` / `EnrollmentVisibility` / `WorkVisibility` objects the
listings use, so a tutor's "attendance by course" covers the courses they
teach and nothing else. A report that quietly widened would be the most
valuable thing in the API to attack: one request, whole institution, and a
plausible-looking reason to be calling it.

**Reading and exporting are different permissions on purpose.** A tutor holds
`report.read` and not `report.export`: they can see their own numbers on
screen, and cannot walk out with a file. `report.export` is held by
Administrators and Corporate Managers, both of whom have a standing reason to
take figures out of the system.

**A report returns groups, never rows.** See `repositories/reporting.py` —
there is no "every attendance record" query, because that endpoint is a data
dump wearing a report's name, and the paged, scoped row views already exist.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import NotFoundError, ValidationError
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.identity.user import User
from backend.repositories.coursework_reporting import CourseworkReportingRepository
from backend.repositories.reporting import MAX_GROUPS, ReportingRepository
from backend.schemas.reporting import (
    AttendanceGroupBy,
    CourseworkGroupBy,
    EnrollmentGroupBy,
    PerformanceGroupBy,
    ReportResponse,
    ReportRow,
)
from backend.services.metrics import attendance_rate, percentage
from backend.services.scope import ScopeResolver
from backend.utils.enums import AttendanceStatus, EnrollmentStatus

# An unbounded default would let anyone run "every record since the
# institution opened" by omitting a parameter, which is both the slowest
# query in the system and the largest answer. A year is the widest window
# anybody reads at a glance; wider is available by asking for it.
DEFAULT_WINDOW_DAYS = 365
MAX_WINDOW_DAYS = 366 * 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.reports = ReportingRepository(session)
        self.coursework_reports = CourseworkReportingRepository(session)
        self.scopes = ScopeResolver(session)

    # -- attendance ----------------------------------------------------------

    async def attendance(
        self,
        *,
        actor: User,
        group_by: AttendanceGroupBy,
        date_from: date | None,
        date_to: date | None,
        course_id: uuid.UUID | None = None,
        batch_id: uuid.UUID | None = None,
    ) -> ReportResponse:
        start, end = self._window(date_from, date_to)
        visibility = await self.scopes.attendance_visibility(actor)

        groups = await self.reports.attendance_by(
            group_by.value,
            visibility=visibility,
            date_from=start,
            date_to=end,
            course_id=await self._course_pk(course_id),
            batch_id=await self._batch_pk(batch_id),
        )

        rows: list[ReportRow] = []
        for key, label, counts in groups[:MAX_GROUPS]:
            present = counts.get(AttendanceStatus.PRESENT, 0)
            late = counts.get(AttendanceStatus.LATE, 0)
            absent = counts.get(AttendanceStatus.ABSENT, 0)
            excused = counts.get(AttendanceStatus.EXCUSED, 0)
            rows.append(
                ReportRow(
                    key=key,
                    label=label,
                    metrics={
                        "present": present,
                        "late": late,
                        "absent": absent,
                        "excused": excused,
                        "total": present + late + absent + excused,
                        "attendance_rate": attendance_rate(
                            present=present, late=late, absent=absent, excused=excused
                        ),
                    },
                )
            )

        return ReportResponse(
            report="attendance",
            group_by=group_by.value,
            generated_at=_now(),
            date_from=start,
            date_to=end,
            columns=["present", "late", "absent", "excused", "total", "attendance_rate"],
            rows=rows,
            truncated=len(groups) > MAX_GROUPS,
        )

    # -- enrollment ----------------------------------------------------------

    async def enrollment(
        self,
        *,
        actor: User,
        group_by: EnrollmentGroupBy,
        date_from: date | None,
        date_to: date | None,
        course_id: uuid.UUID | None = None,
    ) -> ReportResponse:
        start, end = self._window(date_from, date_to)
        visibility = await self.scopes.enrollment_visibility(actor)

        groups = await self.reports.enrollment_by(
            group_by.value,
            visibility=visibility,
            date_from=start,
            date_to=end,
            course_id=await self._course_pk(course_id),
        )

        statuses = [s.value for s in EnrollmentStatus]
        rows = [
            ReportRow(
                key=key,
                label=label,
                metrics={
                    **{s: counts.get(s, 0) for s in statuses},
                    "total": sum(counts.values()),
                },
            )
            for key, label, counts in groups[:MAX_GROUPS]
        ]

        return ReportResponse(
            report="enrollment",
            group_by=group_by.value,
            generated_at=_now(),
            date_from=start,
            date_to=end,
            # Every status column is emitted even when zero, so a CSV keeps
            # the same shape month to month -- a spreadsheet whose columns
            # appear and disappear cannot be appended to.
            columns=[*statuses, "total"],
            rows=rows,
            truncated=len(groups) > MAX_GROUPS,
        )

    # -- performance ---------------------------------------------------------

    async def performance(
        self,
        *,
        actor: User,
        group_by: PerformanceGroupBy,
        course_id: uuid.UUID | None = None,
        batch_id: uuid.UUID | None = None,
    ) -> ReportResponse:
        visibility = await self.scopes.work_visibility(actor)

        groups = await self.reports.performance_by(
            group_by.value,
            visibility=visibility,
            course_id=await self._course_pk(course_id),
            batch_id=await self._batch_pk(batch_id),
        )

        rows = [
            ReportRow(
                key=key,
                label=label,
                metrics={
                    "students": metrics["students"],
                    "entries": metrics["entries"],
                    "average_percent": percentage(
                        metrics["scored"], metrics["available"]
                    ),
                    "lowest_percent": metrics["lowest_percent"],
                    "median_percent": metrics["median_percent"],
                    "highest_percent": metrics["highest_percent"],
                },
            )
            for key, label, metrics in groups[:MAX_GROUPS]
        ]

        return ReportResponse(
            report="performance",
            group_by=group_by.value,
            generated_at=_now(),
            # Average first because it is what people look for, then the
            # spread that tells them whether the average means anything.
            columns=[
                "students",
                "entries",
                "average_percent",
                "lowest_percent",
                "median_percent",
                "highest_percent",
            ],
            rows=rows,
            truncated=len(groups) > MAX_GROUPS,
        )

    # -- export --------------------------------------------------------------

    async def coursework(
        self,
        *,
        actor: User,
        group_by: CourseworkGroupBy,
        course_id: uuid.UUID | None = None,
        batch_id: uuid.UUID | None = None,
    ) -> ReportResponse:
        """Who has handed work in, who has not, and what is waiting to be marked.

        Scoped through the same `WorkVisibility` the submission listings use,
        so a tutor's chase list covers the courses they teach. A report that
        quietly widened would be the most valuable thing in the API to attack:
        one request, whole institution, and a plausible reason to be calling
        it.
        """
        visibility = await self.scopes.work_visibility(actor)

        groups = await self.coursework_reports.coursework_by(
            group_by.value,
            visibility=visibility,
            course_id=await self._course_pk(course_id),
            batch_id=await self._batch_pk(batch_id),
        )

        rows = [
            ReportRow(key=key, label=label, metrics=metrics)
            for key, label, metrics in groups[:MAX_GROUPS]
        ]

        return ReportResponse(
            report="coursework",
            group_by=group_by.value,
            generated_at=_now(),
            # `missing` sits beside `submitted` rather than at the end: it is
            # the column anybody opening this report is actually here for.
            columns=[
                "expected",
                "submitted",
                "missing",
                "late",
                "awaiting_grading",
                "submission_rate",
                "pass_rate",
            ],
            rows=rows,
            truncated=len(groups) > MAX_GROUPS,
        )

    @staticmethod
    def to_csv(report: ReportResponse) -> str:
        """One writer for every report, which is why the row shape is generic.

        `key` is included alongside `label`: two courses can share a title,
        and a spreadsheet that merges them is wrong in a way nobody notices.
        """
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow([report.group_by, "key", *report.columns])
        for row in report.rows:
            writer.writerow(
                [row.label, row.key, *[_csv_cell(row.metrics.get(c)) for c in report.columns]]
            )
        return buffer.getvalue()

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _window(date_from: date | None, date_to: date | None) -> tuple[date, date]:
        """Resolve the reporting window, half-open `[from, to)`.

        Half-open because a closed range on dates silently drops or
        double-counts the boundary day depending on how the timestamps fall,
        and every month-on-month report then disagrees with itself at the
        seams.
        """
        end = date_to or (_now().date() + timedelta(days=1))
        start = date_from or (end - timedelta(days=DEFAULT_WINDOW_DAYS))
        if end <= start:
            raise ValidationError("date_to must be after date_from.")
        if (end - start).days > MAX_WINDOW_DAYS:
            raise ValidationError(
                f"The reporting window cannot exceed {MAX_WINDOW_DAYS} days.",
                details={"requested_days": (end - start).days},
            )
        return start, end

    async def _course_pk(self, public_id: uuid.UUID | None) -> int | None:
        if public_id is None:
            return None
        row = (
            await self.session.execute(select(Course.id).where(Course.public_id == public_id))
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Course not found.")
        return int(row)

    async def _batch_pk(self, public_id: uuid.UUID | None) -> int | None:
        if public_id is None:
            return None
        row = (
            await self.session.execute(select(Batch.id).where(Batch.public_id == public_id))
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Batch not found.")
        return int(row)


def _csv_cell(value: float | int | None) -> str:
    """`None` becomes an empty cell, never `0`.

    "No assessable sessions yet" and "attended none of them" are different
    facts, and a spreadsheet that renders the first as 0 will average it in
    against students who actually turned up.
    """
    return "" if value is None else str(value)
