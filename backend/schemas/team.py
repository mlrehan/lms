"""The "people in my care" view: a corporate manager's employees, or a guardian's wards.

Names only, by design: `core/privacy.py` keeps everybody's email address and phone number out of this view, so
a manager sees how their people are doing without being given a way to contact them outside the platform.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from backend.schemas.base import APIModel


class TeamNextSession(APIModel):
    start: datetime
    batch_code: str
    course_title: str | None = None


class TeamMemberSummary(APIModel):
    public_id: uuid.UUID
    full_name: str
    status: str
    last_login: datetime | None = None

    organization: str | None = None
    department: str | None = None
    employee_code: str | None = None
    relationship: str | None = Field(default=None, description="A guardian's relationship to this ward.")

    enrollments_active: int = 0
    enrollments_completed: int = 0
    courses: list[str] = Field(default_factory=list, description="Titles of the courses they are currently enrolled on.")

    attendance_rate: float | None = Field(default=None, description="Percent of recorded sessions attended (present, late or excused).")
    sessions_recorded: int = 0

    assignments_total: int = 0
    assignments_submitted: int = 0
    assignments_overdue: int = 0

    average_score: float | None = Field(default=None, description="Percent, from the grade book.")
    gpa: float | None = None
    next_session: TeamNextSession | None = None

    needs_attention: bool = False
    attention_reasons: list[str] = Field(default_factory=list)


class TeamOverview(APIModel):
    people: int
    needing_attention: int
    average_attendance_rate: float | None = None
    assignments_overdue: int = 0
    items: list[TeamMemberSummary]


class TeamAttendanceBreakdown(APIModel):
    present: int = 0
    late: int = 0
    absent: int = 0
    excused: int = 0


class TeamEnrollment(APIModel):
    batch_id: uuid.UUID
    batch_code: str
    course_title: str | None = None
    status: str
    enrolled_at: datetime | None = None
    attendance: TeamAttendanceBreakdown
    attendance_rate: float | None = None
    score_percent: float | None = None
    overall_grade: str | None = None
    gpa: float | None = None


class TeamAssignment(APIModel):
    title: str
    course_title: str | None = None
    due_date: datetime
    status: str = Field(description="PENDING, OVERDUE, SUBMITTED or GRADED.")
    submitted_at: datetime | None = None
    grade: float | None = None
    max_score: float | None = None


class TeamAttendanceRecord(APIModel):
    session_start: datetime
    batch_code: str
    course_title: str | None = None
    status: str


class TeamMemberDetail(TeamMemberSummary):
    enrollments: list[TeamEnrollment] = Field(default_factory=list)
    assignments: list[TeamAssignment] = Field(default_factory=list)
    recent_attendance: list[TeamAttendanceRecord] = Field(default_factory=list)
