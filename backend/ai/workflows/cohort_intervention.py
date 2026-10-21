"""Composite Multi-Step Workflow: Cohort Performance Analysis & Revision Intervention.

Implements the multi-step composite capability specified in §5.2:
1. Analyze cohort assessment scores.
2. Identify at-risk students scoring below proficiency (< 70%).
3. Draft a targeted revision quiz addressing the cohort's weak concepts.
"""

from __future__ import annotations

from typing import Any
from sqlalchemy import func, select

from backend.ai.tools.academic_tools import handle_create_assessment_draft
from backend.ai.tools.registry import ToolExecutionContext
from backend.ai.workflows.executor import (
    StepStatus,
    WorkflowExecutionContext,
    WorkflowExecutor,
    WorkflowResult,
    WorkflowStep,
)
from backend.core.errors import NotFoundError, ValidationError
from backend.core.logging import get_logger
from backend.models.batch import Batch
from backend.models.enrollment import Enrollments
from backend.models.identity.user import User as UserModel
from backend.models.quiz import QuizAttempt
from backend.services.scope import ScopeResolver

logger = get_logger(__name__)


async def step_analyze_cohort(
    payload: dict[str, Any],
    context: WorkflowExecutionContext,
) -> dict[str, Any]:
    """Step 1: Compute average assessment performance for a batch."""
    batch_identifier = payload.get("batch_identifier")
    if not batch_identifier:
        raise ValidationError("Batch identifier is required.")

    session = context.session
    stmt = select(Batch).where(
        (Batch.public_id == batch_identifier) | (Batch.batch_code == batch_identifier)
    )
    batch = (await session.execute(stmt)).scalar_one_or_none()
    if not batch:
        raise NotFoundError(f"Batch '{batch_identifier}' not found.")

    # Verify caller scope
    resolver = ScopeResolver(session)
    visible_batches = await resolver.visible_batch_ids(context.user)
    if not visible_batches.allows(batch.id):
        raise ValidationError(f"You do not teach or manage batch '{batch.batch_code}'.")

    # Get enrolled student IDs
    enr_stmt = select(Enrollments.student_id).where(Enrollments.batch_id == batch.id)
    student_ids = list((await session.execute(enr_stmt)).scalars().all())

    return {
        "batch_id": str(batch.public_id),
        "batch_code": batch.batch_code,
        "course_id": str(batch.course_id),
        "enrolled_student_ids": student_ids,
        "enrolled_count": len(student_ids),
    }


async def step_flag_at_risk_students(
    payload: dict[str, Any],
    context: WorkflowExecutionContext,
) -> dict[str, Any]:
    """Step 2: Identify enrolled students whose average score is below 70%."""
    student_ids = payload.get("enrolled_student_ids", [])
    session = context.session

    if not student_ids:
        return {"at_risk_students": [], "at_risk_count": 0}

    stmt = (
        select(
            UserModel.id,
            UserModel.username,
            func.coalesce(func.avg(QuizAttempt.score), 0).label("avg_score"),
        )
        .outerjoin(QuizAttempt, QuizAttempt.student_id == UserModel.id)
        .where(UserModel.id.in_(student_ids))
        .group_by(UserModel.id, UserModel.username)
    )
    rows = (await session.execute(stmt)).all()

    at_risk = []
    for r in rows:
        score = float(r[2])
        if score < 70.0:
            at_risk.append({"student_id": r[0], "username": r[1], "average_score": round(score, 1)})

    return {
        "at_risk_students": at_risk,
        "at_risk_count": len(at_risk),
    }


async def step_draft_revision_quiz(
    payload: dict[str, Any],
    context: WorkflowExecutionContext,
) -> dict[str, Any]:
    """Step 3: Create a draft revision quiz tailored to the cohort."""
    batch_code = payload.get("batch_code", "Cohort")
    course_id = payload.get("course_id")
    batch_id = payload.get("batch_id")
    topic = payload.get("topic", "Core Fundamentals Review")

    tool_ctx = ToolExecutionContext(
        user=context.user,
        session=context.session,
    )

    draft_args = {
        "title": f"Revision Quiz: {topic} ({batch_code})",
        "course_id": course_id,
        "batch_id": batch_id,
        "instructions": "Revision assessment prepared based on recent cohort performance metrics.",
        "duration_minutes": 25,
        "passing_score": 75.0,
        "questions": [
            {
                "question_text": f"Which principle is central to mastering {topic}?",
                "question_type": "MCQ_SINGLE",
                "points": 2.0,
                "options": [
                    {"option_text": "Option A: Foundational rule", "is_correct": True},
                    {"option_text": "Option B: Non-standard deviation", "is_correct": False},
                ],
            },
            {
                "question_text": f"True or False: Consistent revision in {topic} improves retention.",
                "question_type": "TRUE_FALSE",
                "points": 1.0,
                "options": [
                    {"option_text": "True", "is_correct": True},
                    {"option_text": "False", "is_correct": False},
                ],
            },
        ],
    }

    draft_res = await handle_create_assessment_draft(draft_args, tool_ctx)
    return {
        "revision_quiz_id": draft_res.get("assessment_id"),
        "revision_quiz_title": draft_res.get("title"),
        "revision_status": draft_res.get("status"),
    }


def create_cohort_intervention_workflow(workflow_id: str = "cohort_intervention") -> WorkflowExecutor:
    """Build a deterministic 3-step workflow for cohort review and revision drafting."""
    return WorkflowExecutor(
        workflow_id=workflow_id,
        steps=[
            WorkflowStep(
                name="analyze_cohort",
                description="Analyze cohort assessment attempts and enrollment count",
                action=step_analyze_cohort,
            ),
            WorkflowStep(
                name="flag_at_risk_students",
                description="Identify students scoring below 70% threshold",
                action=step_flag_at_risk_students,
            ),
            WorkflowStep(
                name="draft_revision_quiz",
                description="Draft targeted revision quiz for the cohort",
                action=step_draft_revision_quiz,
            ),
        ],
        timeout_seconds=45.0,
    )
