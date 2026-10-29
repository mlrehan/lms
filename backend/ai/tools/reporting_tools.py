"""Reporting, Performance & Analytics AI Tools.

Connects to GradeBookService, PerformanceService, and ManagedStudentService.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
import uuid
from sqlalchemy import func, select

from backend.ai.security import RiskLevel, SecurityPolicyEngine, ToolPolicy
from backend.ai.tools.registry import ConfirmationPreview, ToolDefinition, ToolExecutionContext
from backend.core.privacy import visible_email, visible_username
from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.attendance import Attendance
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.guardian import StudentGuardian
from backend.models.identity.user import User as UserModel
from backend.models.organization import ManagedStudent
from backend.models.quiz import Quiz, QuizAttempt
from backend.services.gradebook_service import GradeBookService
from backend.services.scope import ScopeResolver
from backend.utils.enums import AssessmentState, AttendanceStatus, EnrollmentStatus, Roles


async def handle_get_student_academic_summary(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Retrieve grades, weighted performance, and assessment status for an authorized student."""
    user = context.user
    session = context.session
    resolver = ScopeResolver(session)

    target_student_id = arguments.get("student_id")
    student_id_int: int | None = None

    if target_student_id:
        visible = await resolver.visible_student_ids(user)
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
            stmt = select(UserModel.id).where(UserModel.username == str(target_student_id))
        found_student = (await session.execute(stmt)).scalars().first()
        if not found_student:
            raise NotFoundError(f"Student '{target_student_id}' was not found.")
        if not visible.allows(found_student.id):
            raise NotFoundError("Student not found.")  # same answer as one that does not exist
        student_id_int = found_student.id
        student_obj = found_student
    elif any(r.name == Roles.STUDENT.value for r in (user.roles or [])):
        student_id_int = user.id
        student_obj = user
    else:
        raise ValidationError("Student identifier is required.")

    # Query completed quiz attempts
    stmt = (
        select(
            func.count(QuizAttempt.id).label("total_attempts"),
            func.avg(QuizAttempt.score).label("average_score"),
        )
        .where(QuizAttempt.student_id == student_id_int)
    )
    res = (await session.execute(stmt)).first()
    total_attempts = res[0] if res else 0
    # No marked attempt means no average -- never 0%, which reads as "scored nothing".
    avg_score = float(res[1]) if res and res[1] is not None else None

    # Query enrollments
    enrollment_stmt = (
        select(Enrollments)
        .where(
            (Enrollments.student_id == student_id_int)
            & (Enrollments.status.in_([EnrollmentStatus.CONFIRMED, EnrollmentStatus.COMPLETED]))
        )
    )
    enrollments = (await session.execute(enrollment_stmt)).scalars().all()

    return {
        "student_name": f"{student_obj.first_name or ''} {student_obj.last_name or ''}".strip() or "Unnamed account",
        "student_username": visible_username(student_obj),
        "enrolled_cohorts_count": len(enrollments),
        "assessments_completed": total_attempts,
        "average_assessment_score": round(avg_score, 1) if avg_score is not None else None,
        "academic_standing": (
            "NOT_ASSESSED_YET" if avg_score is None else "PASSING" if avg_score >= 70.0 else "NEEDS_SUPPORT"
        ),
    }


async def handle_get_corporate_training_progress(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Retrieve comprehensive training completion, attendance, and skill gap metrics for corporate employees."""
    user = context.user
    session = context.session

    # Corporate manager scoping: students linked via ManagedStudent
    stmt = (
        select(UserModel)
        .join(ManagedStudent, ManagedStudent.student_id == UserModel.id)
        .where(ManagedStudent.manager_id == user.id)
    )
    employees = (await session.execute(stmt)).scalars().all()

    if not employees:
        return {
            "manager": visible_username(user),
            "linked_employee_count": 0,
            "message": "No employee accounts are currently linked to your corporate profile.",
            "employees": [],
            "team_metrics": {
                "total_active_enrollments": 0,
                "total_completed_modules": 0,
                "overall_team_attendance_rate": None,
                "team_average_assessment_score": None,
            },
        }

    roster = []
    total_active_courses = 0
    total_completed_courses = 0
    total_sessions_all = 0
    total_sessions_attended = 0
    scores_collected = []

    for emp in employees:
        # Query employee enrollments
        e_stmt = select(Enrollments).where(Enrollments.student_id == emp.id)
        emp_enrs = (await session.execute(e_stmt)).scalars().all()
        confirmed_count = sum(1 for e in emp_enrs if e.status == EnrollmentStatus.CONFIRMED)
        completed_count = sum(1 for e in emp_enrs if e.status == EnrollmentStatus.COMPLETED)
        total_active_courses += confirmed_count
        total_completed_courses += completed_count

        # Attendance counts
        att_cnt = (await session.execute(
            select(func.count(Attendance.id)).where(Attendance.student_id == emp.id)
        )).scalar_one() or 0
        pres_cnt = (await session.execute(
            select(func.count(Attendance.id)).where(
                Attendance.student_id == emp.id,
                Attendance.status.in_([AttendanceStatus.PRESENT, AttendanceStatus.LATE]),
            )
        )).scalar_one() or 0
        total_sessions_all += att_cnt
        total_sessions_attended += pres_cnt
        att_rate = round(pres_cnt / att_cnt * 100, 1) if att_cnt > 0 else None

        # Assessment score average: None when nothing is marked. A real 0 counts --
        # dropping it (as `> 0` used to) hid exactly the employee who most needs a look.
        avg_score = (await session.execute(
            select(func.avg(QuizAttempt.score)).where(QuizAttempt.student_id == emp.id, QuizAttempt.score.is_not(None))
        )).scalar_one()
        if avg_score is not None:
            scores_collected.append(float(avg_score))

        skill_gaps = []
        if att_rate is not None and att_rate < 80.0:
            skill_gaps.append(f"Low training attendance ({att_rate}%)")
        if avg_score is not None and float(avg_score) < 70.0:
            skill_gaps.append(f"Assessment performance below passing benchmark ({round(float(avg_score), 1)}/100)")
        if confirmed_count == 0 and completed_count == 0:
            skill_gaps.append("No active training courses enrolled")

        roster.append({
            "employee_id": str(emp.public_id),
            "name": f"{emp.first_name or ''} {emp.last_name or ''}".strip() or "Unnamed account",
            "email": visible_email(emp),
            "designation": emp.designation or "Employee",
            "active_courses": confirmed_count,
            "completed_courses": completed_count,
            "attendance_rate": att_rate,
            "average_score": round(float(avg_score), 1) if avg_score is not None else None,
            "skill_gaps": skill_gaps if skill_gaps else ["On track - no gaps detected"],
            "training_status": "NEEDS_ATTENTION" if skill_gaps else "COMPLIANT",
        })

    team_att_rate = round(total_sessions_attended / total_sessions_all * 100, 1) if total_sessions_all > 0 else None
    team_avg_score = round(sum(scores_collected) / len(scores_collected), 1) if scores_collected else None

    return {
        "manager": visible_username(user),
        "linked_employee_count": len(employees),
        "team_metrics": {
            "total_active_enrollments": total_active_courses,
            "total_completed_modules": total_completed_courses,
            "overall_team_attendance_rate": team_att_rate,
            "team_average_assessment_score": team_avg_score,
        },
        "employees": roster,
        "summary": (
            f"Corporate workforce training status: {len(employees)} employee(s) tracked. "
            f"Team attendance: {team_att_rate}%, Average assessment score: {team_avg_score}%. "
            f"Active enrollments: {total_active_courses}, Completed: {total_completed_courses}."
        ),
    }


get_student_academic_summary_tool = ToolDefinition(
    name="get_student_academic_summary",
    description="Retrieve grade averages, assessment scores, and academic standing for an authorized student.",
    policy=ToolPolicy(
        name="get_student_academic_summary",
        description="View student academic summary",
        required_permissions=("grade.read",),
        risk_level=RiskLevel.LOW,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "student_id": {
                "type": "string",
                "description": "Student UUID or username (optional for students)",
            },
        },
    },
    handler=handle_get_student_academic_summary,
)


get_corporate_training_progress_tool = ToolDefinition(
    name="get_corporate_training_progress",
    description="Retrieve training progress, enrolled courses, and completion summaries for linked corporate employees.",
    policy=ToolPolicy(
        name="get_corporate_training_progress",
        description="View corporate training progress",
        required_permissions=("team.read",),
        allowed_roles=(Roles.CORPORATE_MANAGER.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value),
        risk_level=RiskLevel.LOW,
    ),
    parameters_schema={
        "type": "object",
        "properties": {},
    },
    handler=handle_get_corporate_training_progress,
)


async def handle_get_batch_student_performance_and_gaps(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Analyze student performance, attendance rates, learning gaps, and identify at-risk students for a batch."""
    user = context.user
    session = context.session
    resolver = ScopeResolver(session)

    batch_id_str = arguments.get("batch_identifier")
    if not batch_id_str:
        raise ValidationError("Batch identifier is required.")

    batch_uuid = None
    try:
        batch_uuid = uuid.UUID(str(batch_id_str).strip())
    except Exception:
        pass

    if batch_uuid:
        stmt = select(Batch).where((Batch.public_id == batch_uuid) | (Batch.batch_code == str(batch_id_str)))
    else:
        stmt = select(Batch).where(Batch.batch_code == str(batch_id_str))

    batch = (await session.execute(stmt)).scalar_one_or_none()
    if not batch:
        raise NotFoundError(f"Batch '{batch_id_str}' was not found.")

    visible_batches = await resolver.visible_batch_ids(user)
    if not visible_batches.allows(batch.id):
        raise NotFoundError("Batch not found.")  # same answer as one that does not exist

    enrollment_stmt = (
        select(Enrollments, UserModel)
        .join(UserModel, UserModel.id == Enrollments.student_id)
        .where(Enrollments.batch_id == batch.id, Enrollments.status.in_([EnrollmentStatus.CONFIRMED, EnrollmentStatus.COMPLETED]))
    )
    enrolled_students = (await session.execute(enrollment_stmt)).all()

    sess_count = (await session.execute(
        select(func.count(BatchSession.id)).where(BatchSession.batch_id == batch.id, BatchSession.cancelled_at.is_(None))
    )).scalar_one() or 0

    student_summaries = []
    at_risk_students = []

    for enr, student in enrolled_students:
        s_name = f"{student.first_name or ''} {student.last_name or ''}".strip() or "Unnamed account"

        attended = (await session.execute(
            select(func.count(Attendance.id))
            .join(BatchSession, BatchSession.id == Attendance.session_id)
            .where(
                BatchSession.batch_id == batch.id,
                Attendance.student_id == student.id,
                Attendance.status.in_([AttendanceStatus.PRESENT, AttendanceStatus.LATE])
            )
        )).scalar_one() or 0

        att_pct = round((attended / sess_count * 100.0), 1) if sess_count > 0 else None

        quiz_avg = (await session.execute(
            select(func.avg(QuizAttempt.score))
            .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
            .where(Quiz.batch_id == batch.id, QuizAttempt.student_id == student.id, QuizAttempt.score.is_not(None))
        )).scalar_one()

        quiz_score = round(float(quiz_avg), 1) if quiz_avg is not None else None

        low_attendance = att_pct is not None and att_pct < 80.0
        needs_support = low_attendance or (quiz_score is not None and quiz_score < 60.0)
        reasons = []
        if low_attendance:
            reasons.append(f"Low attendance ({att_pct}%)")
        if quiz_score is not None and quiz_score < 60.0:
            reasons.append(f"Low assessment score ({quiz_score}%)")

        item = {
            "student_username": visible_username(student),
            "student_name": s_name,
            "attendance_percentage": att_pct,
            "average_quiz_score": quiz_score,
            "status": "AT_RISK" if needs_support else "GOOD_STANDING",
            "support_reasons": reasons,
        }
        student_summaries.append(item)
        if needs_support:
            at_risk_students.append(item)

    return {
        "batch_code": batch.batch_code,
        "total_students": len(enrolled_students),
        "total_scheduled_sessions": sess_count,
        "students": student_summaries,
        "at_risk_count": len(at_risk_students),
        "at_risk_students": at_risk_students,
        "summary": (
            f"Batch {batch.batch_code}: {len(enrolled_students)} enrolled students. "
            f"{len(at_risk_students)} student(s) identified needing additional support."
        ),
    }


get_batch_student_performance_and_gaps_tool = ToolDefinition(
    name="get_batch_student_performance_and_gaps",
    description="Analyze student attendance, grades, learning gaps, and identify at-risk students who need support in a batch.",
    policy=ToolPolicy(
        name="get_batch_student_performance_and_gaps",
        description="View batch performance and student gaps",
        required_permissions=("grade.read",),
        allowed_roles=(Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value),
        risk_level=RiskLevel.LOW,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "batch_identifier": {"type": "string", "description": "Batch code or UUID to analyze"},
        },
        "required": ["batch_identifier"],
    },
    handler=handle_get_batch_student_performance_and_gaps,
)


async def handle_generate_institution_report(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Generate structured analytical reports across attendance, performance, or coursework."""
    user = context.user
    session = context.session
    report_type = str(arguments.get("report_type", "attendance")).lower().strip()

    from datetime import date
    from backend.services.report_service import ReportService
    from backend.schemas.reporting import AttendanceGroupBy, PerformanceGroupBy

    report_svc = ReportService(session)

    date_from_str = arguments.get("date_from")
    date_to_str = arguments.get("date_to")
    d_from = date.fromisoformat(date_from_str) if date_from_str else None
    d_to = date.fromisoformat(date_to_str) if date_to_str else None

    if report_type == "attendance":
        res = await report_svc.attendance(
            actor=user,
            group_by=AttendanceGroupBy.BATCH,
            date_from=d_from,
            date_to=d_to,
        )
        return {
            "success": True,
            "report_type": "attendance",
            "date_from": str(d_from) if d_from else "30_days_ago",
            "date_to": str(d_to) if d_to else "today",
            "rows_count": len(res.rows),
            "data": [
                {
                    "group": r.label,
                    "attendance_rate": float(r.metric) if r.metric is not None else None,
                    "counts": r.counts,
                }
                for r in res.rows[:15]
            ],
            "summary": f"Attendance report generated across {len(res.rows)} cohort group(s).",
        }
    elif report_type == "performance":
        res = await report_svc.performance(
            actor=user,
            group_by=PerformanceGroupBy.BATCH,
            date_from=d_from,
            date_to=d_to,
        )
        return {
            "success": True,
            "report_type": "performance",
            "rows_count": len(res.rows),
            "data": [
                {
                    "group": r.label,
                    "average_score": float(r.metric) if r.metric is not None else None,
                    "counts": r.counts,
                }
                for r in res.rows[:15]
            ],
            "summary": f"Performance report generated across {len(res.rows)} cohort(s).",
        }

    return {
        "success": True,
        "report_type": report_type,
        "message": f"Report of type '{report_type}' executed for authorized scope.",
    }


generate_institution_report_tool = ToolDefinition(
    name="generate_institution_report",
    description="Generate analytical reports on attendance or performance across courses and batches.",
    policy=ToolPolicy(
        name="generate_institution_report",
        description="Generate institution analytical reports",
        required_permissions=("report.read",),
        allowed_roles=(Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value, Roles.CORPORATE_MANAGER.value),
        risk_level=RiskLevel.LOW,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "report_type": {
                "type": "string",
                "enum": ["attendance", "performance"],
                "description": "Type of report to generate",
                "default": "attendance",
            },
            "date_from": {"type": "string", "description": "Start date YYYY-MM-DD"},
            "date_to": {"type": "string", "description": "End date YYYY-MM-DD"},
        },
    },
    handler=handle_generate_institution_report,
)


# =============================================================================
# GUARDIAN DEPENDENTS TOOL
# =============================================================================


async def handle_get_guardian_dependents(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Retrieve verified student dependents / wards linked to the authenticated guardian."""
    user = context.user
    session = context.session

    stmt = (
        select(StudentGuardian, UserModel)
        .join(UserModel, UserModel.id == StudentGuardian.student_id)
        .where(StudentGuardian.guardian_id == user.id)
    )
    rows = (await session.execute(stmt)).all()

    dependents = []
    for sg, student in rows:
        enr_count = (await session.execute(
            select(func.count(Enrollments.enrollment_id))
            .where(
                Enrollments.student_id == student.id,
                Enrollments.status.in_([EnrollmentStatus.CONFIRMED, EnrollmentStatus.COMPLETED]),
            )
        )).scalar_one() or 0

        att_total = (await session.execute(
            select(func.count(Attendance.id)).where(Attendance.student_id == student.id)
        )).scalar_one() or 0
        att_present = (await session.execute(
            select(func.count(Attendance.id)).where(
                Attendance.student_id == student.id,
                Attendance.status.in_([AttendanceStatus.PRESENT, AttendanceStatus.LATE]),
            )
        )).scalar_one() or 0
        att_pct = round((att_present / att_total * 100), 1) if att_total > 0 else None

        avg_score = (await session.execute(
            select(func.avg(QuizAttempt.score)).where(QuizAttempt.student_id == student.id, QuizAttempt.score.is_not(None))
        )).scalar_one()

        dependents.append({
            "student_id": str(student.public_id),
            "name": f"{student.first_name or ''} {student.last_name or ''}".strip() or "Unnamed account",
            "username": visible_username(student),
            "email": visible_email(student),
            "relationship_type": sg.relationship_type or "Dependent",
            "is_primary": sg.is_primary,
            "active_enrollments": enr_count,
            "overall_attendance_rate": att_pct,
            "average_assessment_score": round(float(avg_score), 1) if avg_score is not None else None,
            "academic_standing": (
                "NOT_ENOUGH_DATA" if att_pct is None and avg_score is None
                else "NEEDS_ATTENTION" if (att_pct is not None and att_pct < 80.0)
                or (avg_score is not None and float(avg_score) < 70.0)
                else "GOOD"
            ),
        })

    return {
        "guardian_username": visible_username(user),
        "dependents_count": len(dependents),
        "dependents": dependents,
        "message": (
            f"Retrieved {len(dependents)} verified student dependent(s)."
            if dependents
            else "No student dependents are currently linked to your guardian account."
        ),
    }


get_guardian_dependents_tool = ToolDefinition(
    name="get_guardian_dependents",
    description="Retrieve the verified list of student dependents (wards) linked to the authenticated guardian.",
    policy=ToolPolicy(
        name="get_guardian_dependents",
        description="View guardian linked student dependents",
        required_permissions=("guardian.read",),
        allowed_roles=(Roles.GUARDIAN.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value),
        risk_level=RiskLevel.LOW,
    ),
    parameters_schema={
        "type": "object",
        "properties": {},
    },
    handler=handle_get_guardian_dependents,
)


# =============================================================================
# STUDENT ASSESSMENTS AND DEADLINES TOOL
# =============================================================================


def _reaches_batches(model: Any, batch_ids: list[int]) -> Any:
    """An assessment set for one of these batches, by the same rule eligibility uses everywhere else."""
    from sqlalchemy import exists

    from backend.services.assessment_scope import covers_batch

    return exists(select(Batch.id).where(Batch.id.in_(batch_ids), covers_batch(model)))


async def handle_get_student_assessments_and_deadlines(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Retrieve upcoming and published quizzes, assignments, examinations, due dates, and scores."""
    user = context.user
    session = context.session
    resolver = ScopeResolver(session)
    held_roles = SecurityPolicyEngine.caller_roles(user)

    target_student_id = arguments.get("student_identifier") or arguments.get("student_id")
    status_filter = str(arguments.get("status_filter", "ALL")).upper()

    student_id_int: int | None = None
    student_obj: UserModel | None = None

    if target_student_id:
        visible = await resolver.visible_student_ids(user)
        user_uuid = None
        try:
            user_uuid = uuid.UUID(str(target_student_id).strip())
        except (ValueError, TypeError):
            pass
        if user_uuid:
            stmt = select(UserModel).where((UserModel.public_id == user_uuid) | (UserModel.username == str(target_student_id)))
        else:
            stmt = select(UserModel).where((UserModel.email == str(target_student_id)) | (UserModel.username == str(target_student_id)))
        found = (await session.execute(stmt)).scalar_one_or_none()
        if not found:
            raise NotFoundError(f"Student '{target_student_id}' not found.")
        if not visible.allows(found.id):
            raise NotFoundError("Student not found.")  # same answer as one that does not exist
        student_id_int = found.id
        student_obj = found
    elif Roles.STUDENT.value in held_roles:
        student_id_int = user.id
        student_obj = user
    elif Roles.GUARDIAN.value in held_roles:
        wards = list(await resolver._guardian_student_ids(user.id))
        if wards:
            student_id_int = wards[0]
            student_obj = (await session.execute(select(UserModel).where(UserModel.id == student_id_int))).scalar_one_or_none()
        else:
            return {"assessments": [], "total": 0, "message": "No student dependents linked to your guardian account."}
    elif Roles.CORPORATE_MANAGER.value in held_roles:
        managed = list(await resolver._managed_student_ids(user.id))
        if managed:
            student_id_int = managed[0]
            student_obj = (await session.execute(select(UserModel).where(UserModel.id == student_id_int))).scalar_one_or_none()
        else:
            return {"assessments": [], "total": 0, "message": "No employees linked to your corporate account."}
    else:
        raise ValidationError("Student identifier is required.")

    if not student_obj or not student_id_int:
        raise NotFoundError("Could not resolve student record.")

    # Find active batches for this student
    b_stmt = (
        select(Batch.id, Batch.batch_code, Course.title.label("course_title"))
        .join(Enrollments, Enrollments.batch_id == Batch.id)
        .join(Course, Course.id == Batch.course_id)
        .where(
            Enrollments.student_id == student_id_int,
            Enrollments.status.in_([EnrollmentStatus.CONFIRMED, EnrollmentStatus.COMPLETED]),
        )
    )
    enrolled_batches = (await session.execute(b_stmt)).all()
    batch_ids = [b[0] for b in enrolled_batches]
    batch_map = {b[0]: {"batch_code": b[1], "course_title": b[2]} for b in enrolled_batches}

    assessments_list = []
    now_utc = datetime.now(UTC)

    if batch_ids:
        # 1. Quizzes
        q_stmt = (
            select(Quiz)
            .where(
                # The shared eligibility rule. "No batch" used to mean "everyone":
                # every course-wide quiz in the institution reached every student.
                _reaches_batches(Quiz, batch_ids),
                Quiz.is_published.is_(True),
            )
            .order_by(Quiz.available_until.asc().nulls_last())
        )
        quizzes = (await session.execute(q_stmt)).scalars().all()

        for q in quizzes:
            att_stmt = select(QuizAttempt).where(
                QuizAttempt.quiz_id == q.id,
                QuizAttempt.student_id == student_id_int,
            ).order_by(QuizAttempt.score.desc().nulls_last())
            attempt = (await session.execute(att_stmt)).scalars().first()

            status = "UPCOMING"
            if attempt and attempt.finished_at:
                status = "COMPLETED"
            elif q.available_until and q.available_until < now_utc:
                status = "OVERDUE"

            if status_filter != "ALL" and status != status_filter:
                continue

            course_title = "General"
            if q.batch_id and q.batch_id in batch_map:
                course_title = batch_map[q.batch_id]["course_title"]
            elif q.course_id:
                c_stmt = select(Course.title).where(Course.id == q.course_id)
                course_title = (await session.execute(c_stmt)).scalar_one_or_none() or "General"

            assessments_list.append({
                "type": "QUIZ",
                "id": str(q.public_id),
                "title": q.title,
                "course": course_title,
                "total_marks": float(q.total_marks) if q.total_marks is not None else None,
                "passing_score": float(q.passing_score) if q.passing_score is not None else None,
                "available_from": q.available_from.isoformat() if q.available_from else None,
                "available_until": q.available_until.isoformat() if q.available_until else None,
                "status": status,
                "score_obtained": float(attempt.score) if attempt and attempt.score is not None else None,
                "is_passed": attempt.is_passed if attempt else None,
            })

        # 2. Assignments
        asgn_stmt = (
            select(Assignment)
            .where(
                _reaches_batches(Assignment, batch_ids),
                Assignment.state == AssessmentState.PUBLISHED,
            )
            .order_by(Assignment.due_date.asc().nulls_last())
        )
        assignments = (await session.execute(asgn_stmt)).scalars().all()

        for a in assignments:
            sub_stmt = select(AssignmentSubmission).where(
                AssignmentSubmission.assignment_id == a.id,
                AssignmentSubmission.student_id == student_id_int,
            )
            submission = (await session.execute(sub_stmt)).scalar_one_or_none()

            status = "PENDING"
            if submission:
                status = "GRADED" if submission.grade is not None else "SUBMITTED"
            elif a.due_date and a.due_date < now_utc:
                status = "OVERDUE"

            if status_filter != "ALL" and status != status_filter:
                continue

            course_title = "General"
            if a.batch_id and a.batch_id in batch_map:
                course_title = batch_map[a.batch_id]["course_title"]
            elif a.course_id:
                c_stmt = select(Course.title).where(Course.id == a.course_id)
                course_title = (await session.execute(c_stmt)).scalar_one_or_none() or "General"

            assessments_list.append({
                "type": "ASSIGNMENT",
                "id": str(a.public_id),
                "title": a.title,
                "course": course_title,
                "max_score": float(a.max_score),
                "passing_score": float(a.passing_score) if a.passing_score else None,
                "due_date": a.due_date.isoformat() if a.due_date else None,
                "status": status,
                "grade_obtained": float(submission.grade) if submission and submission.grade is not None else None,
                "feedback": submission.feedback if submission else None,
            })

    return {
        "student": f"{student_obj.first_name or ''} {student_obj.last_name or ''}".strip() or "Unnamed account",
        "total_assessments": len(assessments_list),
        "assessments": assessments_list,
        "summary": f"Found {len(assessments_list)} assessment(s) matching filter '{status_filter}' for {visible_username(student_obj)}.",
    }


get_student_assessments_and_deadlines_tool = ToolDefinition(
    name="get_student_assessments_and_deadlines",
    description="Retrieve upcoming and published quizzes, assignments, examinations, deadlines, and submission scores for an authorized student or ward.",
    policy=ToolPolicy(
        name="get_student_assessments_and_deadlines",
        description="View student assessments and deadlines",
        required_permissions=("academic.read",),
        allowed_roles=(
            Roles.STUDENT.value,
            Roles.GUARDIAN.value,
            Roles.CORPORATE_MANAGER.value,
            Roles.TUTOR.value,
            Roles.ADMIN.value,
            Roles.SUPER_ADMIN.value,
        ),
        risk_level=RiskLevel.LOW,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "student_identifier": {
                "type": "string",
                "description": "Student UUID, username, or email (optional for student self-query)",
            },
            "status_filter": {
                "type": "string",
                "enum": ["ALL", "UPCOMING", "COMPLETED", "OVERDUE"],
                "default": "ALL",
                "description": "Filter by assessment status",
            },
        },
    },
    handler=handle_get_student_assessments_and_deadlines,
)


# =============================================================================
# STUDENT ENROLLED COURSES TOOL
# =============================================================================


async def handle_get_student_enrolled_courses(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Retrieve enrolled courses, batches, schedules, and progress for an authorized student."""
    user = context.user
    session = context.session
    resolver = ScopeResolver(session)
    held_roles = SecurityPolicyEngine.caller_roles(user)

    target_student_id = arguments.get("student_identifier") or arguments.get("student_id")
    student_id_int: int | None = None
    student_obj: UserModel | None = None

    if target_student_id:
        visible = await resolver.visible_student_ids(user)
        user_uuid = None
        try:
            user_uuid = uuid.UUID(str(target_student_id).strip())
        except (ValueError, TypeError):
            pass
        if user_uuid:
            stmt = select(UserModel).where((UserModel.public_id == user_uuid) | (UserModel.username == str(target_student_id)))
        else:
            stmt = select(UserModel).where((UserModel.email == str(target_student_id)) | (UserModel.username == str(target_student_id)))
        found = (await session.execute(stmt)).scalar_one_or_none()
        if not found:
            raise NotFoundError(f"Student '{target_student_id}' not found.")
        if not visible.allows(found.id):
            raise NotFoundError("Student not found.")  # same answer as one that does not exist
        student_id_int = found.id
        student_obj = found
    elif Roles.STUDENT.value in held_roles:
        student_id_int = user.id
        student_obj = user
    elif Roles.GUARDIAN.value in held_roles:
        wards = list(await resolver._guardian_student_ids(user.id))
        if wards:
            student_id_int = wards[0]
            student_obj = (await session.execute(select(UserModel).where(UserModel.id == student_id_int))).scalar_one_or_none()
        else:
            return {"courses": [], "enrolled_courses_count": 0, "message": "No student dependents linked to your guardian account."}
    elif Roles.CORPORATE_MANAGER.value in held_roles:
        managed = list(await resolver._managed_student_ids(user.id))
        if managed:
            student_id_int = managed[0]
            student_obj = (await session.execute(select(UserModel).where(UserModel.id == student_id_int))).scalar_one_or_none()
        else:
            return {"courses": [], "enrolled_courses_count": 0, "message": "No employees linked to your corporate account."}

    if not student_obj or not student_id_int:
        raise ValidationError("Could not resolve student record.")

    stmt = (
        select(Enrollments, Batch, Course)
        .join(Batch, Batch.id == Enrollments.batch_id)
        .join(Course, Course.id == Batch.course_id)
        .where(Enrollments.student_id == student_id_int)
        .order_by(Enrollments.enrollment_date.desc())
    )
    rows = (await session.execute(stmt)).all()

    enrolled = []
    for enr, batch, course in rows:
        total_sessions = (await session.execute(
            select(func.count(BatchSession.id)).where(BatchSession.batch_id == batch.id, BatchSession.cancelled_at.is_(None))
        )).scalar_one() or 0
        # The rate is over the classes whose register recorded this student --
        # never over every scheduled session, which counts classes that have not
        # happened yet as absences. One rule for the whole platform:
        # services/metrics.attendance_rate (late counts as attended, excused
        # leaves the denominator, nothing recorded is None).
        from backend.services.metrics import attendance_rate

        by_status = dict((await session.execute(
            select(Attendance.status, func.count(Attendance.id))
            .join(BatchSession, BatchSession.id == Attendance.session_id)
            .where(BatchSession.batch_id == batch.id, Attendance.student_id == student_id_int)
            .group_by(Attendance.status)
        )).all())
        attended_sessions = by_status.get(AttendanceStatus.PRESENT, 0) + by_status.get(AttendanceStatus.LATE, 0)
        rate = attendance_rate(
            present=by_status.get(AttendanceStatus.PRESENT, 0), late=by_status.get(AttendanceStatus.LATE, 0),
            absent=by_status.get(AttendanceStatus.ABSENT, 0), excused=by_status.get(AttendanceStatus.EXCUSED, 0),
        )

        enrolled.append({
            "course_id": str(course.public_id),
            "course_title": course.title,
            "course_code": course.code,
            "batch_code": batch.batch_code,
            "enrollment_status": enr.status.value,
            "start_date": batch.start_date.isoformat() if batch.start_date else None,
            "end_date": batch.end_date.isoformat() if batch.end_date else None,
            "training_days": batch.training_days,
            "training_time": f"{batch.training_start_time} - {batch.training_end_time}" if batch.training_start_time else None,
            "sessions_total": total_sessions,
            "sessions_attended": attended_sessions,
            "attendance_rate": rate,
        })

    return {
        "student": f"{student_obj.first_name or ''} {student_obj.last_name or ''}".strip() or "Unnamed account",
        "enrolled_courses_count": len(enrolled),
        "courses": enrolled,
    }


get_student_enrolled_courses_tool = ToolDefinition(
    name="get_student_enrolled_courses",
    description="Retrieve enrolled courses, cohorts, training schedules, and completion progress for an authorized student or ward.",
    policy=ToolPolicy(
        name="get_student_enrolled_courses",
        description="View enrolled courses and batches",
        required_permissions=("enrollment.read",),
        allowed_roles=(
            Roles.STUDENT.value,
            Roles.GUARDIAN.value,
            Roles.CORPORATE_MANAGER.value,
            Roles.TUTOR.value,
            Roles.ADMIN.value,
            Roles.SUPER_ADMIN.value,
        ),
        risk_level=RiskLevel.LOW,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "student_identifier": {
                "type": "string",
                "description": "Student UUID, username, or email (optional for student self-query)",
            },
        },
    },
    handler=handle_get_student_enrolled_courses,
)


# =============================================================================
# ENROLL CORPORATE EMPLOYEE TOOL
# =============================================================================


def _person_name(person: UserModel) -> str:
    return f"{person.first_name or ''} {person.last_name or ''}".strip() or "Unnamed account"


async def _resolve_enrolment(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> tuple[UserModel, Batch, str]:
    """Find the employee and batch, refusing anything outside the caller's reach.

    Someone not on the manager's roster gets the **same** "not found" as
    someone who does not exist. Two different refusals would tell a manager
    which addresses belong to accounts here -- the enumeration this platform
    already closed once in EnrollmentService.
    """
    user = context.user
    session = context.session

    emp_ident = str(arguments.get("employee_identifier") or "").strip()
    batch_code = str(arguments.get("batch_code") or "").strip()
    if not emp_ident or not batch_code:
        raise ValidationError("employee_identifier and batch_code are both required.")

    not_found = NotFoundError(f"No employee '{emp_ident}' was found on your roster.")
    try:
        u_stmt = select(UserModel).where(UserModel.public_id == uuid.UUID(emp_ident))
    except ValueError:
        u_stmt = select(UserModel).where((UserModel.email == emp_ident) | (UserModel.username == emp_ident))
    employee = (await session.execute(u_stmt.where(UserModel.deleted_at.is_(None)))).scalars().first()
    if employee is None:
        raise not_found

    if not ScopeResolver.is_unrestricted(user):
        managed_ids = await ScopeResolver(session)._managed_student_ids(user.id)
        if employee.id not in managed_ids:
            raise not_found

    batch = (await session.execute(select(Batch).where(Batch.batch_code == batch_code))).scalar_one_or_none()
    if batch is None:
        raise NotFoundError(f"Batch '{batch_code}' not found.")
    course_title = (
        await session.execute(select(Course.title).where(Course.id == batch.course_id))
    ).scalar_one_or_none() or "Course"
    return employee, batch, course_title


async def preview_enroll_corporate_employee(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> ConfirmationPreview:
    employee, batch, course_title = await _resolve_enrolment(arguments, context)
    return ConfirmationPreview(
        summary=f"Enrol {_person_name(employee)} in batch {batch.batch_code} ({course_title})?",
        bound_parameters={"employee_public_id": str(employee.public_id), "batch_public_id": str(batch.public_id)},
    )


async def handle_enroll_corporate_employee(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Enrol a person from the caller's roster (runs only after confirmation)."""
    from backend.ai.tools.registry import BOUND_PREFIX
    from backend.services.enrollment_service import EnrollmentService

    user = context.user
    employee, batch, course_title = await _resolve_enrolment(arguments, context)
    if (
        str(employee.public_id) != str(arguments.get(f"{BOUND_PREFIX}employee_public_id"))
        or str(batch.public_id) != str(arguments.get(f"{BOUND_PREFIX}batch_public_id"))
    ):
        raise ValidationError("The person or batch no longer matches what was confirmed; ask again.")

    name = _person_name(employee)
    existing = (
        await context.session.execute(
            select(Enrollments).where(
                Enrollments.student_id == employee.id,
                Enrollments.batch_id == batch.id,
                Enrollments.status.in_([EnrollmentStatus.CONFIRMED, EnrollmentStatus.PENDING]),
            )
        )
    ).scalars().first()
    if existing is not None:
        return {
            "success": True,
            "status": existing.status.value,
            "enrollment_id": str(existing.public_id),
            "message": f"{name} is already enrolled in batch {batch.batch_code}; nothing was changed.",
        }

    # EnrollmentService applies capacity, batch state, the sponsoring
    # organisation and the roster rule again, and emits the notifications.
    enrollment = await EnrollmentService(context.session).enroll(
        student_public_id=employee.public_id,
        batch_public_id=batch.public_id,
        confirmed=True,
        actor=user,
    )
    return {
        "success": True,
        "enrollment_id": str(enrollment.public_id),
        "employee_name": name,
        "batch_code": batch.batch_code,
        "course_title": course_title,
        "status": enrollment.status.value,
        "message": f"{name} is now enrolled in batch {batch.batch_code} ({course_title}).",
    }


enroll_corporate_employee_tool = ToolDefinition(
    name="enroll_corporate_employee",
    description=(
        "Enrol a person on your corporate roster into a course batch. "
        "Requires the user's confirmation."
    ),
    policy=ToolPolicy(
        name="enroll_corporate_employee",
        description="Enroll corporate employee into batch",
        required_permissions=("enrollment.create", "organization.enroll"),
        allowed_roles=(Roles.CORPORATE_MANAGER.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value),
        # An enrolment carries fees, notifications and a place in a cohort, and
        # is undone by dropping it, not deleting it: a consequential write.
        risk_level=RiskLevel.HIGH,
        requires_confirmation=True,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "employee_identifier": {
                "type": "string",
                "description": "Employee email, username, or UUID",
            },
            "batch_code": {
                "type": "string",
                "description": "Batch code to enroll into (e.g. '11405')",
            },
        },
        "required": ["employee_identifier", "batch_code"],
    },
    handler=handle_enroll_corporate_employee,
    preview=preview_enroll_corporate_employee,
)



