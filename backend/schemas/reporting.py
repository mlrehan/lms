"""Dashboard and report schemas (spec §17–§18).

**Report rows are deliberately generic.** Every report returns
`{key, label, metrics}` plus a `columns` list naming the metrics in order,
rather than a bespoke row model per report. Three reports with three row
shapes would need three CSV writers and three client renderers; one shape
needs one of each, and the metric *names* are what differ, not the structure.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum

from pydantic import Field

from backend.schemas.base import APIModel


# =============================================================================
# REPORTS
# =============================================================================


class ReportFormat(str, Enum):
    JSON = "json"
    CSV = "csv"


class AttendanceGroupBy(str, Enum):
    COURSE = "course"
    BATCH = "batch"
    TUTOR = "tutor"
    STUDENT = "student"
    MONTH = "month"


class EnrollmentGroupBy(str, Enum):
    COURSE = "course"
    BATCH = "batch"
    STATUS = "status"
    MONTH = "month"


class PerformanceGroupBy(str, Enum):
    COURSE = "course"
    BATCH = "batch"
    COMPONENT = "component"
    STUDENT = "student"


class CourseworkGroupBy(str, Enum):
    """How the coursework report is cut.

    `assignment` and `student` are the two that drive action -- which piece of
    work is not coming in, and which person is not handing it in -- so both
    are offered rather than only the management cuts.
    """

    COURSE = "course"
    BATCH = "batch"
    ASSIGNMENT = "assignment"
    STUDENT = "student"


class ReportRow(APIModel):
    key: str = Field(description="Stable identifier for the group (a public_id, a status, or a month).")
    label: str
    metrics: dict[str, float | int | None]


class ReportResponse(APIModel):
    report: str
    group_by: str
    generated_at: datetime
    date_from: date | None = None
    date_to: date | None = None
    columns: list[str] = Field(description="Metric names, in display order.")
    rows: list[ReportRow]
    truncated: bool = Field(
        default=False,
        description="True when the result hit the group cap and is incomplete.",
    )


# =============================================================================
# DASHBOARD
# =============================================================================


class SessionBrief(APIModel):
    public_id: uuid.UUID
    batch_code: str
    course_title: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    classroom: str | None = None
    # No `meeting_link`. This panel is drawn for every role including students,
    # and a link here would have been the third payload carrying it past the
    # join window. The dashboard shows whether the door is open; the door is
    # opened by POST /sessions/{id}/join.
    join_opens_at: datetime | None = None
    join_closes_at: datetime | None = None
    can_join_now: bool = False


class AssignmentBrief(APIModel):
    public_id: uuid.UUID
    title: str
    course_title: str
    due_date: datetime | None = None
    is_overdue: bool = False


class PersonalPanel(APIModel):
    unread_messages: int = 0
    unread_notifications: int = 0
    live_announcements: int = 0


class StudentPanel(APIModel):
    enrolled_batches: int = 0
    active_courses: int = 0
    attendance_rate: float | None = Field(
        default=None, description="Percentage; null when there is nothing assessable yet."
    )
    average_score: float | None = Field(
        default=None, description="Mean percentage across recorded grade components."
    )
    assignments_outstanding: int = 0
    assignments_overdue: int = 0
    upcoming_sessions: list[SessionBrief] = Field(default_factory=list)
    next_deadlines: list[AssignmentBrief] = Field(default_factory=list)


class TeachingPanel(APIModel):
    batches_taught: int = 0
    courses_taught: int = 0
    students_taught: int = 0
    sessions_next_7_days: int = 0
    submissions_awaiting_grading: int = 0
    quiz_attempts_awaiting_grading: int = 0
    upcoming_sessions: list[SessionBrief] = Field(default_factory=list)


class CarePanel(APIModel):
    """Guardians and corporate managers: the people in their care."""

    people: int = 0
    attendance_rate: float | None = None
    assignments_overdue: int = 0
    upcoming_sessions: list[SessionBrief] = Field(default_factory=list)


class InstitutionPanel(APIModel):
    active_users: int = 0
    suspended_users: int = 0
    courses_published: int = 0
    courses_draft: int = 0
    active_batches: int = 0
    enrollments_confirmed: int = 0
    attendance_rate_30d: float | None = None
    submissions_awaiting_grading: int = 0


class DashboardResponse(APIModel):
    generated_at: datetime
    panels: list[str] = Field(
        description="Which panels are populated for this caller, in display order."
    )
    personal: PersonalPanel
    student: StudentPanel | None = None
    teaching: TeachingPanel | None = None
    care: CarePanel | None = None
    institution: InstitutionPanel | None = None
