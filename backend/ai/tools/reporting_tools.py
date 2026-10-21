"""Reporting, Performance & Analytics AI Tools.

Connects to GradeBookService, PerformanceService, and ManagedStudentService.
"""

from __future__ import annotations

from typing import Any
from sqlalchemy import func, select

from backend.ai.security import RiskLevel, ToolPolicy
from backend.ai.tools.registry import ToolDefinition, ToolExecutionContext
from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.models.batch import Batch
from backend.models.enrollment import Enrollments
from backend.models.identity.user import User as UserModel
from backend.models.organization import ManagedStudent
from backend.models.quiz import QuizAttempt
from backend.services.gradebook_service import GradeBookService
from backend.services.scope import ScopeResolver
from backend.utils.enums import EnrollmentStatus, Roles


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
        stmt = select(UserModel).where(
            (UserModel.public_id == target_student_id) | (UserModel.username == target_student_id)
        )
        found_student = (await session.execute(stmt)).scalars().first()
        if not found_student:
            raise NotFoundError(f"Student '{target_student_id}' was not found.")
        if not visible.allows(found_student.id):
            raise AuthorizationError("You do not have permission to view grades for this student.")
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
            func.coalesce(func.avg(QuizAttempt.score), 0).label("average_score"),
        )
        .where(QuizAttempt.student_id == student_id_int)
    )
    res = (await session.execute(stmt)).first()
    total_attempts = res[0] if res else 0
    avg_score = float(res[1]) if res else 0.0

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
        "student_name": f"{student_obj.first_name or ''} {student_obj.last_name or ''}".strip() or student_obj.username,
        "student_username": student_obj.username,
        "enrolled_cohorts_count": len(enrollments),
        "assessments_completed": total_attempts,
        "average_assessment_score": round(avg_score, 1),
        "academic_standing": "PASSING" if avg_score >= 70.0 or total_attempts == 0 else "NEEDS_SUPPORT",
    }


async def handle_get_corporate_training_progress(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Retrieve training completion and progress metrics for employees linked to the corporate manager."""
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
            "manager": user.username,
            "linked_employee_count": 0,
            "message": "No employee accounts are currently linked to your corporate profile.",
            "employees": [],
        }

    employee_ids = [e.id for e in employees]

    # Query active enrollments for linked employees
    enr_stmt = (
        select(
            Enrollments.student_id,
            func.count(Enrollments.id).label("cohorts"),
        )
        .where(
            (Enrollments.student_id.in_(employee_ids))
            & (Enrollments.status == EnrollmentStatus.CONFIRMED)
        )
        .group_by(Enrollments.student_id)
    )
    enr_counts = dict((await session.execute(enr_stmt)).all())

    roster = []
    for emp in employees:
        roster.append({
            "employee_id": str(emp.public_id),
            "name": f"{emp.first_name or ''} {emp.last_name or ''}".strip() or emp.username,
            "designation": emp.designation or "Employee",
            "active_courses": enr_counts.get(emp.id, 0),
        })

    return {
        "manager": user.username,
        "linked_employee_count": len(employees),
        "employees": roster,
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

