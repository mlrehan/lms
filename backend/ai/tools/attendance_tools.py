"""Scheduling & Attendance AI Tools.

Connects to SessionService and AttendanceService with strict row-scoping.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
import uuid
from sqlalchemy import func, or_, select

from backend.ai.orchestrator import AIOrchestrator
from backend.ai.security import RiskLevel, ToolPolicy
from backend.ai.tools.registry import ToolDefinition, ToolExecutionContext
from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.models.attendance import Attendance
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.services.scope import ScopeResolver
from backend.services.session_service import SessionService
from backend.utils.enums import AttendanceStatus, Roles


async def handle_get_my_schedule(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Retrieve schedule of classes for the caller within the requested time window."""
    user = context.user
    session = context.session

    time_phrase = arguments.get("timeframe", "this week")
    start, end = AIOrchestrator.resolve_date_window(
        phrase=time_phrase,
        user_timezone=user.timezone,
    )

    batch_id_str = arguments.get("batch_identifier")
    batch_public_id = None
    if batch_id_str:
        batch_uuid = None
        try:
            batch_uuid = uuid.UUID(str(batch_id_str).strip())
        except (ValueError, TypeError):
            pass

        if batch_uuid:
            stmt = select(Batch.public_id).where(
                (Batch.public_id == batch_uuid) | (Batch.batch_code == str(batch_id_str))
            )
        else:
            stmt = select(Batch.public_id).where(Batch.batch_code == str(batch_id_str))
        batch_public_id = (await session.execute(stmt)).scalar_one_or_none()

    session_svc = SessionService(session)
    sessions = await session_svc.calendar(
        actor=user,
        start=start,
        end=end,
        batch_public_id=batch_public_id,
        limit=50,
    )

    formatted_sessions = []
    for s in sessions:
        course_name = "Unknown"
        if s.batch and hasattr(s.batch, "course") and s.batch.course:
            course_name = getattr(s.batch.course, "title", "Unknown")
        batch_name = s.batch.batch_code if s.batch else "Unknown"

        formatted_sessions.append({
            "session_id": str(s.public_id),
            "batch_code": batch_name,
            "course_title": course_name,
            "title": getattr(s, "title", None) or f"{course_name} Session",
            "start_time": s.session_start_time.isoformat() if s.session_start_time else "",
            "end_time": s.session_end_time.isoformat() if s.session_end_time else "",
            "classroom": s.classroom or s.meeting_link or "Standard Classroom",
            "is_cancelled": s.cancelled_at is not None,
        })

    return {
        "timeframe": time_phrase,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "session_count": len(formatted_sessions),
        "classes": formatted_sessions,
    }


async def handle_get_attendance_summary(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Retrieve attendance metrics and absence rates within the caller's authorized scope."""
    user = context.user
    session = context.session
    resolver = ScopeResolver(session)

    target_student_id = arguments.get("student_id")
    batch_identifier = arguments.get("batch_identifier") or arguments.get("batch_code") or arguments.get("batch_id")
    target_batch_id: int | None = None

    if batch_identifier:
        batch_conditions = [Batch.batch_code == str(batch_identifier)]
        try:
            val_uuid = uuid.UUID(str(batch_identifier))
            batch_conditions.append(Batch.public_id == val_uuid)
        except (ValueError, TypeError):
            pass
        batch_stmt = select(Batch).where(or_(*batch_conditions))
        batch_row = (await session.execute(batch_stmt)).scalar_one_or_none()
        if not batch_row:
            raise NotFoundError(f"Batch '{batch_identifier}' was not found.")
        visible_batches = await resolver.visible_batch_ids(user)
        if not visible_batches.allows(batch_row.id):
            raise AuthorizationError("You are not assigned to this batch.")
        target_batch_id = batch_row.id

    # If student is specified, check visibility
    student_id_int: int | None = None
    if target_student_id:
        visible_students = await resolver.visible_student_ids(user)
        # Find student
        from backend.models.identity.user import User as UserModel
        user_uuid = None
        try:
            user_uuid = uuid.UUID(str(target_student_id).strip())
        except (ValueError, TypeError):
            pass
        if user_uuid:
            stmt = select(UserModel.id).where(
                (UserModel.public_id == user_uuid) | (UserModel.username == str(target_student_id))
            )
        else:
            stmt = select(UserModel.id).where(UserModel.username == str(target_student_id))
        found_id = (await session.execute(stmt)).scalar_one_or_none()
        if not found_id:
            raise NotFoundError(f"Student '{target_student_id}' was not found.")
        if not visible_students.allows(found_id):
            raise AuthorizationError("You do not have permission to view attendance for this student.")
        student_id_int = found_id
    elif any(r.name == Roles.STUDENT.value for r in (user.roles or [])):
        # Default to caller if student
        student_id_int = user.id

    if not student_id_int:
        # Aggregate across taught batches for tutor
        visible_batches = await resolver.visible_batch_ids(user)
        stmt = (
            select(
                Attendance.status,
                func.count(Attendance.id).label("count"),
            )
            .join(BatchSession, BatchSession.id == Attendance.session_id)
            .where(visible_batches.apply(select(Batch.id), Batch.id).subquery().c.id == BatchSession.batch_id)
            .group_by(Attendance.status)
        )
        rows = (await session.execute(stmt)).all()
        counts = {r[0].value if hasattr(r[0], "value") else str(r[0]): r[1] for r in rows}
        total = sum(counts.values())
        present = counts.get(AttendanceStatus.PRESENT.value, 0)
        return {
            "scope": "TEACHING_COHORTS",
            "total_records": total,
            "present_count": present,
            "late_count": counts.get(AttendanceStatus.LATE.value, 0),
            "absent_count": counts.get(AttendanceStatus.ABSENT.value, 0),
            "excused_count": counts.get(AttendanceStatus.EXCUSED.value, 0),
            "overall_attendance_rate": round((present / total * 100), 1) if total > 0 else 100.0,
        }

    # Specific student record
    stmt = (
        select(Attendance.status, func.count(Attendance.id))
        .where(Attendance.student_id == student_id_int)
        .group_by(Attendance.status)
    )
    rows = (await session.execute(stmt)).all()
    counts = {r[0].value if hasattr(r[0], "value") else str(r[0]): r[1] for r in rows}
    total = sum(counts.values())
    present = counts.get(AttendanceStatus.PRESENT.value, 0)

    return {
        "student_id": target_student_id or str(user.public_id),
        "total_classes": total,
        "present_count": present,
        "late_count": counts.get(AttendanceStatus.LATE.value, 0),
        "absent_count": counts.get(AttendanceStatus.ABSENT.value, 0),
        "excused_count": counts.get(AttendanceStatus.EXCUSED.value, 0),
        "attendance_percentage": round((present / total * 100), 1) if total > 0 else 100.0,
        "standing": "GOOD" if (total == 0 or (present / total) >= 0.8) else "AT_RISK",
    }


get_my_schedule_tool = ToolDefinition(
    name="get_my_schedule",
    description=(
        "Retrieve class schedule, dates, times, and classrooms for the caller. "
        "Supports timeframes such as 'today', 'tomorrow', 'this week', or 'this month'."
    ),
    policy=ToolPolicy(
        name="get_my_schedule",
        description="View class schedule",
        required_permissions=("session.read",),
        risk_level=RiskLevel.LOW,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "timeframe": {
                "type": "string",
                "description": "Natural language window: 'today', 'tomorrow', 'this week', 'next week', 'this month'",
                "default": "this week",
            },
            "batch_identifier": {
                "type": "string",
                "description": "Specific batch code or UUID to narrow down (optional)",
            },
        },
    },
    handler=handle_get_my_schedule,
)


get_attendance_summary_tool = ToolDefinition(
    name="get_attendance_summary",
    description=(
        "Retrieve attendance rates, present/absent counts, and flags for missed classes. "
        "Scoped to the caller's assigned students or self."
    ),
    policy=ToolPolicy(
        name="get_attendance_summary",
        description="View attendance summary",
        required_permissions=("attendance.read",),
        risk_level=RiskLevel.LOW,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "student_id": {
                "type": "string",
                "description": "Student UUID or username (optional, defaults to self for students)",
            },
            "batch_code": {
                "type": "string",
                "description": "Specific batch code to filter (optional)",
            },
        },
    },
    handler=handle_get_attendance_summary,
)

