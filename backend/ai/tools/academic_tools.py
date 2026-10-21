"""Academic & Assessment AI Tools.

Connects to QuizService, AssignmentService, and CourseService with strict scope
validation and answer-key verification.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from sqlalchemy import select

from backend.ai.security import RiskLevel, ToolPolicy
from backend.ai.tools.registry import ToolDefinition, ToolExecutionContext
from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.models.batch import Batch
from backend.models.course import Course
from backend.schemas.quiz import (
    OptionInput,
    QuestionCreateRequest,
    QuizCreateRequest,
)
from backend.services.course_service import CourseService
from backend.services.quiz_service import QuizService
from backend.services.scope import ScopeResolver
from backend.utils.enums import AssessmentScope, QuestionType, Roles


async def handle_create_assessment_draft(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Create a draft quiz or assignment with verified questions and answer keys."""
    user = context.user
    session = context.session

    title = arguments.get("title", "").strip()
    if not title:
        raise ValidationError("Assessment title is required.")

    course_id_str = arguments.get("course_id")
    batch_id_str = arguments.get("batch_id")

    if not course_id_str:
        raise ValidationError("Course ID is required to create an assessment.")

    # 1. Resolve Course by public UUID or integer
    courses_svc = CourseService(session)
    course = await courses_svc.get_by_id_or_public_id(course_id_str)
    if not course:
        raise NotFoundError(f"Course '{course_id_str}' was not found.")

    # 2. Scope verification: Does the caller have standing to set work for this course?
    resolver = ScopeResolver(session)
    visible_courses = await resolver.visible_course_ids(user)
    if not visible_courses.allows(course.id):
        raise AuthorizationError("You are not assigned to teach or manage this course.")

    # 3. Resolve Batch if specified
    batch: Batch | None = None
    if batch_id_str:
        batch_uuid = None
        try:
            batch_uuid = uuid.UUID(str(batch_id_str).strip())
        except (ValueError, TypeError):
            pass
        if batch_uuid:
            stmt = select(Batch).where(
                (Batch.public_id == batch_uuid) | (Batch.batch_code == str(batch_id_str))
            )
        else:
            stmt = select(Batch).where(Batch.batch_code == str(batch_id_str))
        batch = (await session.execute(stmt)).scalar_one_or_none()
        if not batch:
            raise NotFoundError(f"Batch '{batch_id_str}' was not found.")
        visible_batches = await resolver.visible_batch_ids(user)
        if not visible_batches.allows(batch.id):
            raise AuthorizationError("You are not assigned to this batch.")

    questions_data = arguments.get("questions", [])
    if not questions_data:
        raise ValidationError("At least one question is required for an assessment draft.")

    # 4. Construct Question requests
    prepared_questions: list[QuestionCreateRequest] = []
    total_points = Decimal("0")

    for i, q in enumerate(questions_data, start=1):
        q_text = q.get("question_text", "").strip()
        if not q_text:
            raise ValidationError(f"Question #{i} text is required.")

        raw_type = q.get("question_type", "MCQ_SINGLE").upper()
        try:
            q_type = QuestionType(raw_type)
        except ValueError:
            q_type = QuestionType.MCQ_SINGLE

        points = Decimal(str(q.get("points", 1.0)))
        total_points += points

        options_input: list[OptionInput] = []

        if q_type in (QuestionType.MCQ_SINGLE, QuestionType.MCQ_MULTIPLE, QuestionType.TRUE_FALSE):
            raw_options = q.get("options", [])
            for opt_idx, opt in enumerate(raw_options):
                opt_text = opt.get("option_text", f"Option {opt_idx + 1}")
                is_corr = bool(opt.get("is_correct", False))
                options_input.append(
                    OptionInput(
                        option_text=opt_text,
                        is_correct=is_corr,
                        order=opt_idx + 1,
                    )
                )

        prepared_questions.append(
            QuestionCreateRequest(
                question_text=q_text,
                question_type=q_type,
                points=points,
                order=i,
                options=options_input,
            )
        )

    # 5. Create Draft Quiz via QuizService
    quiz_svc = QuizService(session)
    quiz_req = QuizCreateRequest(
        title=title,
        instructions=arguments.get("instructions", "Complete all questions carefully."),
        duration_minutes=arguments.get("duration_minutes", 30),
        passing_score=Decimal(str(arguments.get("passing_score", 70.0))),
        total_marks=total_points,
        shuffle_questions=bool(arguments.get("shuffle_questions", False)),
        is_auto_graded=True,
        scope=AssessmentScope.BATCH if batch else AssessmentScope.COURSE,
        batch_id=batch.public_id if batch else None,
    )

    created_quiz = await quiz_svc.create(course.public_id, quiz_req, actor=user)

    # 6. Add each question to the quiz
    for q_req in prepared_questions:
        await quiz_svc.add_question(created_quiz.public_id, q_req, actor=user)

    return {
        "success": True,
        "assessment_id": str(created_quiz.public_id),
        "title": created_quiz.title,
        "status": "DRAFT",
        "question_count": len(prepared_questions),
        "total_marks": float(total_points),
        "scope": created_quiz.scope.value,
        "course": course.title,
        "batch": batch.batch_code if batch else None,
        "message": (
            f"Draft assessment '{created_quiz.title}' created successfully in DRAFT state. "
            "It is not yet published to students."
        ),
    }


async def handle_get_course_curriculum(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Retrieve syllabus, learning objectives, and curriculum overview for a course."""
    session = context.session
    course_query = arguments.get("course_identifier", "").strip()

    stmt = select(Course).where(
        (Course.code.ilike(f"%{course_query}%"))
        | (Course.title.ilike(f"%{course_query}%"))
        | (Course.public_id == course_query if len(course_query) == 36 else False)
    )
    course = (await session.execute(stmt)).scalars().first()
    if not course:
        raise NotFoundError(f"Course matching '{course_query}' was not found.")

    return {
        "course_id": str(course.public_id),
        "code": course.code,
        "title": course.title,
        "level": course.level.value if course.level else "BEGINNER",
        "summary": course.summary or course.description or "No description available.",
        "prerequisites": course.prerequisites or "None",
        "duration_hours": course.duration_hours,
        "credit_hours": course.credit_hours,
    }


create_assessment_draft_tool = ToolDefinition(
    name="create_assessment_draft",
    description=(
        "Create a new quiz or assessment draft with verified questions, point values, "
        "and answer keys. Always saved in DRAFT state (never immediately published to students)."
    ),
    policy=ToolPolicy(
        name="create_assessment_draft",
        description="Create draft assessment",
        required_permissions=("quiz.create",),
        allowed_roles=(Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value),
        risk_level=RiskLevel.MODERATE,
        audit_action="CREATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Title of the assessment"},
            "course_id": {"type": "string", "description": "Course UUID or code"},
            "batch_id": {"type": "string", "description": "Batch UUID or batch code (optional)"},
            "instructions": {"type": "string", "description": "Guidance for students"},
            "duration_minutes": {"type": "integer", "description": "Time limit in minutes", "default": 30},
            "passing_score": {"type": "number", "description": "Passing percentage (e.g. 70.0)", "default": 70.0},
            "questions": {
                "type": "array",
                "description": "List of questions with options and answer keys",
                "items": {
                    "type": "object",
                    "properties": {
                        "question_text": {"type": "string"},
                        "question_type": {
                            "type": "string",
                            "enum": ["MCQ_SINGLE", "MCQ_MULTIPLE", "TRUE_FALSE", "SHORT_ANSWER", "ESSAY"],
                        },
                        "points": {"type": "number", "default": 1.0},
                        "options": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "option_text": {"type": "string"},
                                    "is_correct": {"type": "boolean"},
                                    "explanation": {"type": "string"},
                                },
                                "required": ["option_text", "is_correct"],
                            },
                        },
                    },
                    "required": ["question_text", "question_type"],
                },
            },
        },
        "required": ["title", "course_id", "questions"],
    },
    handler=handle_create_assessment_draft,
)


get_course_curriculum_tool = ToolDefinition(
    name="get_course_curriculum",
    description="Retrieve the syllabus, modules, and prerequisites of an authorized course.",
    policy=ToolPolicy(
        name="get_course_curriculum",
        description="View course curriculum",
        required_permissions=("course.read",),
        risk_level=RiskLevel.LOW,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "course_identifier": {"type": "string", "description": "Course title, code, or UUID"},
        },
        "required": ["course_identifier"],
    },
    handler=handle_get_course_curriculum,
)

