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
from backend.ai.tools.registry import (
    BOUND_PREFIX,
    ConfirmationPreview,
    ToolDefinition,
    ToolExecutionContext,
)
from backend.core.privacy import visible_email, visible_username
from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.models.attendance import Attendance
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.services import audit_service
from backend.services.scope import ScopeResolver
from backend.services.session_service import SessionService
from backend.utils.enums import AttendanceStatus, EnrollmentStatus, Roles


async def handle_get_my_schedule(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Retrieve schedule of classes for the caller within the requested time window."""
    user = context.user
    session = context.session
    now_utc = datetime.now(UTC)

    time_phrase = arguments.get("timeframe", "this week")
    lowered_phrase = str(time_phrase).strip().lower()
    is_next_or_first = any(w in lowered_phrase for w in ("first", "next", "upcoming", "soon", "nearest"))

    if is_next_or_first:
        start = now_utc
        end = now_utc + timedelta(days=90)
    else:
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

    # Identify the next upcoming non-cancelled class after now
    upcoming_classes = [
        s for s in formatted_sessions
        if s.get("start_time") and datetime.fromisoformat(s["start_time"]) >= now_utc and not s.get("is_cancelled")
    ]
    upcoming_classes.sort(key=lambda x: x["start_time"])
    next_session = upcoming_classes[0] if upcoming_classes else None

    # If no upcoming session in the immediate window, run a forward lookup up to 120 days
    if not next_session and not is_next_or_first:
        forward_sessions = await session_svc.calendar(
            actor=user,
            start=now_utc,
            end=now_utc + timedelta(days=120),
            batch_public_id=batch_public_id,
            limit=20,
        )
        for s in forward_sessions:
            if s.cancelled_at is not None or not s.session_start_time or s.session_start_time < now_utc:
                continue
            c_name = getattr(s.batch.course, "title", "Unknown") if s.batch and hasattr(s.batch, "course") and s.batch.course else "Unknown"
            b_name = s.batch.batch_code if s.batch else "Unknown"
            next_session = {
                "session_id": str(s.public_id),
                "batch_code": b_name,
                "course_title": c_name,
                "title": getattr(s, "title", None) or f"{c_name} Session",
                "start_time": s.session_start_time.isoformat() if s.session_start_time else "",
                "end_time": s.session_end_time.isoformat() if s.session_end_time else "",
                "classroom": s.classroom or s.meeting_link or "Standard Classroom",
                "is_cancelled": False,
            }
            break

    message = (
        f"Next upcoming class: {next_session['course_title']} (Batch {next_session['batch_code']}), "
        f"starting at {next_session['start_time']} ({next_session['classroom']})."
        if next_session
        else "No upcoming classes are scheduled for your assigned batches."
    )

    return {
        "timeframe": time_phrase,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "session_count": len(formatted_sessions),
        "classes": formatted_sessions,
        "next_upcoming_class": next_session,
        "has_upcoming_class": next_session is not None,
        "summary": message,
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
            raise NotFoundError("Batch not found.")  # same answer as one that does not exist
        target_batch_id = batch_row.id

    # If student is specified, check visibility
    student_id_int: int | None = None
    target_student_obj = None
    user_roles = {r.name.upper() for r in (user.roles or [])}

    if target_student_id:
        visible_students = await resolver.visible_student_ids(user)
        from backend.models.identity.user import User as UserModel
        user_uuid = None
        try:
            user_uuid = uuid.UUID(str(target_student_id).strip())
        except (ValueError, TypeError):
            pass
        if user_uuid:
            stmt = select(UserModel).where(
                (UserModel.public_id == user_uuid) | (UserModel.username == str(target_student_id))
            )
        else:
            stmt = select(UserModel).where(
                (UserModel.username == str(target_student_id))
                | (UserModel.email == str(target_student_id))
            )
        found_student = (await session.execute(stmt)).scalar_one_or_none()
        if not found_student:
            raise NotFoundError(f"Student '{target_student_id}' was not found.")
        if not visible_students.allows(found_student.id):
            raise NotFoundError("Student not found.")  # same answer as one that does not exist
        student_id_int = found_student.id
        target_student_obj = found_student
    elif Roles.STUDENT.value.upper() in user_roles:
        # Default to caller if student
        student_id_int = user.id
        target_student_obj = user
    elif Roles.GUARDIAN.value.upper() in user_roles:
        # Default to guardian wards
        ward_ids = list(await resolver._guardian_student_ids(user.id))
        if not ward_ids:
            return {
                "scope": "GUARDIAN_WARDS",
                "ward_count": 0,
                "total_records": 0,
                "wards": [],
                "summary": "No verified student dependents found for your guardian account.",
            }
        from backend.models.identity.user import User as UserModel
        ward_users = (await session.execute(
            select(UserModel).where(UserModel.id.in_(ward_ids))
        )).scalars().all()
        ward_summaries = []
        total_all = 0
        present_all = 0
        for w in ward_users:
            stmt = (
                select(Attendance.status, func.count(Attendance.id))
                .where(Attendance.student_id == w.id)
                .group_by(Attendance.status)
            )
            rows = (await session.execute(stmt)).all()
            counts = {r[0].value if hasattr(r[0], "value") else str(r[0]): r[1] for r in rows}
            w_tot = sum(counts.values())
            w_pres = counts.get(AttendanceStatus.PRESENT.value, 0)
            total_all += w_tot
            present_all += w_pres
            pct = round((w_pres / w_tot * 100), 1) if w_tot > 0 else 100.0
            ward_summaries.append({
                "student_id": str(w.public_id),
                "name": f"{w.first_name or ''} {w.last_name or ''}".strip() or "Unnamed account",
                "email": visible_email(w),
                "total_classes": w_tot,
                "present_count": w_pres,
                "absent_count": counts.get(AttendanceStatus.ABSENT.value, 0),
                "late_count": counts.get(AttendanceStatus.LATE.value, 0),
                "excused_count": counts.get(AttendanceStatus.EXCUSED.value, 0),
                "attendance_rate": pct,
                "standing": "GOOD" if (w_tot == 0 or (w_pres / w_tot) >= 0.8) else "AT_RISK",
            })
        ovr_rate = round((present_all / total_all * 100), 1) if total_all > 0 else 100.0
        return {
            "scope": "GUARDIAN_WARDS",
            "ward_count": len(ward_summaries),
            "total_classes_across_wards": total_all,
            "overall_attendance_rate": ovr_rate,
            "wards": ward_summaries,
            "summary": f"Retrieved attendance for {len(ward_summaries)} dependent(s). Overall attendance rate: {ovr_rate}%.",
        }
    elif Roles.CORPORATE_MANAGER.value.upper() in user_roles:
        # Default to corporate managed employees
        emp_ids = list(await resolver._managed_student_ids(user.id))
        if not emp_ids:
            return {
                "scope": "CORPORATE_EMPLOYEES",
                "employee_count": 0,
                "total_records": 0,
                "employees": [],
                "summary": "No managed employees found for your corporate account.",
            }
        from backend.models.identity.user import User as UserModel
        emp_users = (await session.execute(
            select(UserModel).where(UserModel.id.in_(emp_ids))
        )).scalars().all()
        emp_summaries = []
        total_all = 0
        present_all = 0
        for emp in emp_users:
            stmt = (
                select(Attendance.status, func.count(Attendance.id))
                .where(Attendance.student_id == emp.id)
                .group_by(Attendance.status)
            )
            rows = (await session.execute(stmt)).all()
            counts = {r[0].value if hasattr(r[0], "value") else str(r[0]): r[1] for r in rows}
            e_tot = sum(counts.values())
            e_pres = counts.get(AttendanceStatus.PRESENT.value, 0)
            total_all += e_tot
            present_all += e_pres
            pct = round((e_pres / e_tot * 100), 1) if e_tot > 0 else 100.0
            emp_summaries.append({
                "student_id": str(emp.public_id),
                "name": f"{emp.first_name or ''} {emp.last_name or ''}".strip() or "Unnamed account",
                "email": visible_email(emp),
                "total_classes": e_tot,
                "present_count": e_pres,
                "absent_count": counts.get(AttendanceStatus.ABSENT.value, 0),
                "late_count": counts.get(AttendanceStatus.LATE.value, 0),
                "attendance_rate": pct,
            })
        ovr_rate = round((present_all / total_all * 100), 1) if total_all > 0 else 100.0
        return {
            "scope": "CORPORATE_EMPLOYEES",
            "employee_count": len(emp_summaries),
            "total_classes_across_team": total_all,
            "team_attendance_rate": ovr_rate,
            "employees": emp_summaries,
            "summary": f"Retrieved attendance for {len(emp_summaries)} team member(s). Team attendance rate: {ovr_rate}%.",
        }

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

    student_display = (
        f"{target_student_obj.first_name or ''} {target_student_obj.last_name or ''}".strip()
        or "Unnamed account"
        if target_student_obj
        else (target_student_id or str(user.public_id))
    )

    return {
        "student_id": target_student_id or str(user.public_id),
        "student_name": student_display,
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
        "Supports timeframes such as 'today', 'tomorrow', 'this week', 'this month', "
        "'next month', 'last month', or specific month-year like 'December 2026', 'January 2027'."
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
                "description": (
                    "Natural language window: 'today', 'tomorrow', 'this week', 'next week', "
                    "'this month', 'next month', 'last month', or specific month/year like "
                    "'December 2026', 'January 2027'. Pass the user's exact time reference."
                ),
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


async def _resolve_register(
    arguments: dict[str, Any], context: ToolExecutionContext
) -> tuple[BatchSession, list[tuple[Any, AttendanceStatus, str | None]]]:
    """The session and the exact register to record, or a refusal naming why.

    Students are matched by name or id **within the session's enrolled roster
    only** -- a tutor cannot see email addresses, so matching on them (as this
    tool used to) could never succeed, and matching across the whole user
    table could pick a namesake in somebody else's class. A name that matches
    nobody, or more than one person, refuses the whole register rather than
    being skipped: a register that silently drops a name is worse than one
    that fails visibly.
    """
    user = context.user
    session = context.session
    session_ident = arguments.get("session_id")
    batch_code = arguments.get("batch_code")

    session_row: BatchSession | None = None
    if session_ident:
        try:
            suuid = uuid.UUID(str(session_ident).strip())
        except (ValueError, TypeError) as exc:
            raise ValidationError("session_id must be a session's id as returned by get_my_schedule.") from exc
        session_row = (
            await session.execute(select(BatchSession).where(BatchSession.public_id == suuid))
        ).scalar_one_or_none()
    if not session_row and batch_code:
        # The batch's most recent class that has started (or starts within the
        # hour) -- never a future one. Ordering by start time alone picked the
        # last session on the timetable, so "today's class" was recorded
        # against a class weeks away.
        session_row = (
            await session.execute(
                select(BatchSession)
                .join(Batch, Batch.id == BatchSession.batch_id)
                .where(
                    Batch.batch_code == str(batch_code).strip(),
                    BatchSession.cancelled_at.is_(None),
                    BatchSession.session_start_time <= datetime.now(UTC) + timedelta(hours=1),
                )
                .order_by(BatchSession.session_start_time.desc())
            )
        ).scalars().first()
    if not session_row:
        raise NotFoundError("Session not found.")

    is_admin = any(r.name in (Roles.SUPER_ADMIN.value, Roles.ADMIN.value) for r in (user.roles or []))
    if not is_admin and session_row.tutor_id != user.id:
        raise NotFoundError("Session not found.")  # same answer as one that does not exist

    from backend.models.identity.user import User as UserModel

    roster = (
        await session.execute(
            select(UserModel)
            .join(Enrollments, Enrollments.student_id == UserModel.id)
            .where(
                Enrollments.batch_id == session_row.batch_id,
                Enrollments.status == EnrollmentStatus.CONFIRMED,
            )
        )
    ).scalars().all()

    def full(u: Any) -> str:
        return " ".join(f"{u.first_name or ''} {u.last_name or ''}".split()).lower()

    def status_of(raw: Any) -> AttendanceStatus:
        try:
            return AttendanceStatus[str(raw or "").strip().upper()]
        except KeyError as exc:
            raise ValidationError(
                f"'{raw}' is not an attendance status; use PRESENT, LATE, ABSENT or EXCUSED."
            ) from exc

    register: dict[int, tuple[Any, AttendanceStatus, str | None]] = {}
    if arguments.get("everyone_else"):
        default = status_of(arguments["everyone_else"])
        register = {u.id: (u, default, None) for u in roster}

    problems: list[str] = []
    for item in arguments.get("entries") or []:
        ident = str(item.get("student") or "").strip()
        if not ident:
            continue
        try:
            as_id = uuid.UUID(ident)
            matches = [u for u in roster if u.public_id == as_id]
        except ValueError:
            wanted = " ".join(ident.split()).lower()
            matches = [u for u in roster if full(u) == wanted]
        if len(matches) != 1:
            problems.append(
                f"'{ident}' is not enrolled in this class" if not matches else f"'{ident}' matches more than one student"
            )
            continue
        register[matches[0].id] = (matches[0], status_of(item.get("status")), item.get("remarks") or None)

    if problems:
        raise ValidationError("Nothing was recorded: " + "; ".join(problems) + ".")
    if not register:
        raise ValidationError("Name the students, or say what status everyone else should get.")
    return session_row, sorted(register.values(), key=lambda e: full(e[0]))


def _register_name(u: Any) -> str:
    return " ".join(f"{u.first_name or ''} {u.last_name or ''}".split()) or "Unnamed student"


async def preview_mark_session_attendance(
    arguments: dict[str, Any], context: ToolExecutionContext
) -> ConfirmationPreview:
    session_row, register = await _resolve_register(arguments, context)
    from zoneinfo import ZoneInfo

    try:
        zone = ZoneInfo(context.user.timezone or "UTC")
    except Exception:  # noqa: BLE001 -- an unknown zone name shows UTC
        zone = ZoneInfo("UTC")
    start = session_row.session_start_time
    when = start.astimezone(zone).strftime("%d %b %Y %H:%M %Z") if start else "?"
    listing = ", ".join(f"{_register_name(u)}: {st.value}" for u, st, _ in register)
    return ConfirmationPreview(
        summary=f"Record attendance for {session_row.batch.course.title} ({session_row.batch.batch_code}), {when}: {listing}.",
        affected_records_count=len(register),
        bound_parameters={
            "session_id": str(session_row.public_id),
            "entries": [[str(u.public_id), st.value] for u, st, _ in register],
        },
    )


async def handle_mark_session_attendance(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Record the confirmed register through AttendanceService."""
    from backend.schemas.attendance import AttendanceEntry
    from backend.services.attendance_service import AttendanceService

    session_row, register = await _resolve_register(arguments, context)
    if (
        str(session_row.public_id) != str(arguments.get(f"{BOUND_PREFIX}session_id"))
        or [[str(u.public_id), st.value] for u, st, _ in register] != arguments.get(f"{BOUND_PREFIX}entries")
    ):
        raise ValidationError("The register no longer matches what was confirmed; ask again.")

    await AttendanceService(context.session).mark(
        session_public_id=session_row.public_id,
        entries=[AttendanceEntry(student_id=u.public_id, status=st, remarks=r) for u, st, r in register],
        actor=context.user,
    )
    return {
        "success": True,
        "session_id": str(session_row.public_id),
        "marked_count": len(register),
        "entries": [{"student": _register_name(u), "status": st.value} for u, st, _ in register],
        "message": f"Recorded attendance for {len(register)} student(s).",
    }



# Each action needs the permission the console's own route needs for it.
# Scheduling is the administration's (tutors hold `session.update`, not
# `session.create`), and taking a class off the timetable is a removal
# (`session.delete`). Gating the whole tool on `session.update` let a tutor
# schedule and cancel classes through the assistant that the console refuses.
_SESSION_ACTION_PERMISSION = {
    "create": "session.create",
    "update": "session.update",
    "cancel": "session.delete",
}


def _require_session_permission(user: Any, action: str) -> None:
    from backend.ai.security import SecurityPolicyEngine

    needed = _SESSION_ACTION_PERMISSION.get(action)
    if needed is None:
        raise ValidationError(f"Unknown session action: '{action}'.")
    if needed not in SecurityPolicyEngine.caller_permissions(user):
        raise AuthorizationError(f"You do not hold permission to {action} class sessions.")


async def preview_manage_batch_session(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> ConfirmationPreview:
    """Only `cancel` is staged; show which class, at what time."""
    _require_session_permission(context.user, "cancel")
    session_id = arguments.get("session_id")
    if not session_id:
        raise ValidationError("session_id is required to cancel a session.")
    row = await SessionService(context.session).get(uuid.UUID(str(session_id).strip()), actor=context.user)
    if row.cancelled_at is not None:
        raise ValidationError("That class is already cancelled.")
    when = row.session_start_time.isoformat() if row.session_start_time else "an unscheduled time"
    return ConfirmationPreview(
        summary=f"Cancel the class at {when} (UTC)? Its students will no longer be able to join it.",
        bound_parameters={"session_public_id": str(row.public_id)},
    )


async def handle_manage_batch_session(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Create, update, or cancel class sessions for authorized tutors and administrators."""
    user = context.user
    session = context.session
    action = str(arguments.get("action", "create")).lower().strip()

    is_admin = any(
        r.name in (Roles.SUPER_ADMIN.value, Roles.ADMIN.value)
        for r in (user.roles or [])
    )
    is_tutor = any(r.name == Roles.TUTOR.value for r in (user.roles or []))
    if not (is_admin or is_tutor):
        raise AuthorizationError("Only tutors and administrators can manage class sessions.")
    _require_session_permission(user, action)

    session_svc = SessionService(session)

    if action == "create":
        batch_code = arguments.get("batch_code")
        if not batch_code:
            raise ValidationError("batch_code is required to schedule a class session.")

        b_stmt = select(Batch).where(Batch.batch_code == str(batch_code).strip())
        batch_row = (await session.execute(b_stmt)).scalar_one_or_none()
        if not batch_row:
            raise NotFoundError(f"Batch '{batch_code}' not found.")

        start_str = arguments.get("start_time")
        if not start_str:
            raise ValidationError("start_time is required.")
        start_dt = datetime.fromisoformat(str(start_str))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=UTC)

        duration = arguments.get("duration_minutes") or 60
        end_str = arguments.get("end_time")
        if end_str:
            end_dt = datetime.fromisoformat(str(end_str))
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=UTC)
        else:
            end_dt = start_dt + timedelta(minutes=int(duration))

        from backend.schemas.session import SessionCreateRequest

        req = SessionCreateRequest(
            tutor_id=user.public_id,
            session_start_time=start_dt,
            session_end_time=end_dt,
            duration_minutes=int(duration),
            classroom=arguments.get("classroom", "Standard Classroom"),
            meeting_link=arguments.get("meeting_link"),
            tutor_notes=arguments.get("tutor_notes"),
        )
        new_sess = await session_svc.create(
            batch_public_id=batch_row.public_id,
            payload=req,
            actor=user,
        )
        return {
            "success": True,
            "action": "create",
            "session_id": str(new_sess.public_id),
            "batch_code": batch_row.batch_code,
            "start_time": new_sess.session_start_time.isoformat(),
            "end_time": new_sess.session_end_time.isoformat() if new_sess.session_end_time else None,
            "classroom": new_sess.classroom,
            "message": f"Class session scheduled for batch {batch_row.batch_code} at {new_sess.session_start_time.isoformat()}.",
        }

    elif action == "cancel":
        session_id = arguments.get("session_id")
        if not session_id:
            raise ValidationError("session_id is required to cancel a session.")
        suuid = uuid.UUID(str(session_id).strip())
        if str(suuid) != str(arguments.get(f"{BOUND_PREFIX}session_public_id")):
            raise ValidationError("The class no longer matches the one confirmed; ask again.")
        reason = arguments.get("cancelled_reason", "Cancelled by tutor")
        row = await session_svc.get(suuid, actor=user)
        row.cancelled_at = datetime.now(UTC)
        row.cancelled_reason = reason
        audit_service.record(
            session,
            action=audit_service.AuditAction.UPDATE,
            actor_user_id=user.id,
            actor_email=user.email,
            entity_type="batch_session",
            entity_id=row.id,
            details={"operation": "AI_CANCEL_SESSION", "cancelled_reason": reason},
        )
        await session.flush()
        return {
            "success": True,
            "action": "cancel",
            "session_id": str(row.public_id),
            "cancelled_reason": reason,
            "message": f"Class session {row.public_id} has been cancelled ({reason}).",
        }

    elif action == "update":
        session_id = arguments.get("session_id")
        if not session_id:
            raise ValidationError("session_id is required to update a session.")
        suuid = uuid.UUID(str(session_id).strip())
        from backend.schemas.session import SessionUpdateRequest

        up_params: dict[str, Any] = {}
        if arguments.get("classroom"):
            up_params["classroom"] = arguments["classroom"]
        if arguments.get("meeting_link"):
            up_params["meeting_link"] = arguments["meeting_link"]
        if arguments.get("tutor_notes"):
            up_params["tutor_notes"] = arguments["tutor_notes"]
        if arguments.get("start_time"):
            sdt = datetime.fromisoformat(str(arguments["start_time"]))
            up_params["session_start_time"] = sdt if sdt.tzinfo else sdt.replace(tzinfo=UTC)
        if arguments.get("end_time"):
            edt = datetime.fromisoformat(str(arguments["end_time"]))
            up_params["session_end_time"] = edt if edt.tzinfo else edt.replace(tzinfo=UTC)

        req = SessionUpdateRequest(**up_params)
        updated = await session_svc.update(suuid, payload=req, actor=user)
        return {
            "success": True,
            "action": "update",
            "session_id": str(updated.public_id),
            "message": f"Class session {updated.public_id} updated successfully.",
        }

    raise ValidationError(f"Unknown session action: '{action}'.")


mark_session_attendance_tool = ToolDefinition(
    name="mark_session_attendance",
    description=(
        "Record or correct the register for one class you teach. Name students exactly as enrolled (or by id); "
        "use everyone_else for 'everyone present except ...'. The tutor confirms the full register before it is saved."
    ),
    policy=ToolPolicy(
        name="mark_session_attendance",
        description="Record attendance",
        required_permissions=("attendance.update",),
        allowed_roles=(Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value),
        risk_level=RiskLevel.HIGH,
        requires_confirmation=True,
        audit_action="UPDATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Session id from get_my_schedule (preferred)"},
            "batch_code": {"type": "string", "description": "Batch code: its most recent class that has started"},
            "everyone_else": {
                "type": "string",
                "enum": ["PRESENT", "LATE", "ABSENT", "EXCUSED"],
                "description": "Status for every enrolled student not listed in entries",
            },
            "entries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "student": {"type": "string", "description": "Student's full name as enrolled, or id"},
                        "status": {"type": "string", "enum": ["PRESENT", "LATE", "ABSENT", "EXCUSED"]},
                        "remarks": {"type": "string"},
                    },
                    "required": ["student", "status"],
                },
            },
        },
    },
    handler=handle_mark_session_attendance,
    preview=preview_mark_session_attendance,
)


manage_batch_session_tool = ToolDefinition(
    name="manage_batch_session",
    description="Schedule, update, or cancel class sessions for assigned batches.",
    policy=ToolPolicy(
        name="manage_batch_session",
        description="Schedule, update, or cancel class sessions",
        required_permissions=("session.update",),
        allowed_roles=(Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value),
        risk_level=RiskLevel.MODERATE,
        requires_confirmation=True,
        confirm_actions=("cancel",),
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "update", "cancel"],
                "description": "Action to perform: 'create' to schedule, 'update' to edit details, 'cancel' to cancel class",
            },
            "batch_code": {
                "type": "string",
                "description": "Batch code (required for 'create')",
            },
            "session_id": {
                "type": "string",
                "description": "UUID of the session (required for 'update' or 'cancel')",
            },
            "start_time": {
                "type": "string",
                "description": "ISO start time e.g. '2026-10-30T10:00:00'",
            },
            "end_time": {
                "type": "string",
                "description": "ISO end time",
            },
            "duration_minutes": {
                "type": "integer",
                "description": "Class duration in minutes (default 60)",
            },
            "classroom": {
                "type": "string",
                "description": "Physical room or 'Online Classroom'",
            },
            "meeting_link": {
                "type": "string",
                "description": "Online meeting link (Zoom, Google Meet)",
            },
            "cancelled_reason": {
                "type": "string",
                "description": "Reason for cancellation when action='cancel'",
            },
        },
        "required": ["action"],
    },
    handler=handle_manage_batch_session,
    preview=preview_manage_batch_session,
)

