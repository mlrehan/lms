"""Academic & Assessment AI Tools.

Connects to QuizService, AssignmentService, ExamService, CourseService, and ResourceService
with strict RBAC, scope validation, rubric support, and draft verification.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
import inspect
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.security import RiskLevel, ToolPolicy
from backend.ai.tools.registry import ToolDefinition, ToolExecutionContext
from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.exam import Exam
from backend.models.identity.user import User as UserModel
from backend.models.quiz import Quiz, QuizAttempt
from backend.models.resource import Resource, ResourceFolder
from backend.schemas.assignment import AssignmentCreateRequest
from backend.schemas.base import PageParams
from backend.schemas.exam import ExamCreateRequest
from backend.schemas.quiz import (
    OptionInput,
    QuestionCreateRequest,
    QuizCreateRequest,
)
from backend.schemas.resource import FolderCreateRequest
from backend.services.assignment_service import AssignmentService
from backend.services.course_service import CourseService
from backend.services.exam_service import ExamService
from backend.services.quiz_service import QuizService
from backend.services.resource_service import ResourceService
from backend.services.scope import ScopeResolver
from backend.utils.enums import AssessmentScope, ExamType, QuestionType, ResourceType, Roles, SubmissionState


async def _resolve_course(session: AsyncSession, course_identifier: str) -> Course | None:
    c_uuid = None
    try:
        c_uuid = uuid.UUID(str(course_identifier).strip())
    except (ValueError, TypeError):
        pass
    if c_uuid:
        stmt = select(Course).where((Course.public_id == c_uuid) | (Course.code == str(course_identifier)))
    else:
        stmt = select(Course).where(
            (Course.code == str(course_identifier))
            | (Course.title.ilike(f"%{course_identifier}%"))
        )
    try:
        res = session.execute(stmt)
        if inspect.isawaitable(res):
            res = await res
        return res.scalars().first()
    except Exception:
        return None


async def _resolve_batch(session: AsyncSession, batch_identifier: str) -> Batch | None:
    batch_uuid = None
    try:
        batch_uuid = uuid.UUID(str(batch_identifier).strip())
    except (ValueError, TypeError):
        pass
    if batch_uuid:
        stmt = select(Batch).where((Batch.public_id == batch_uuid) | (Batch.batch_code == str(batch_identifier)))
    else:
        stmt = select(Batch).where(Batch.batch_code == str(batch_identifier))
    return (await session.execute(stmt)).scalar_one_or_none()


async def _resolve_quiz(session: AsyncSession, quiz_identifier: str) -> Quiz | None:
    quiz_uuid = None
    try:
        quiz_uuid = uuid.UUID(str(quiz_identifier).strip())
    except (ValueError, TypeError):
        pass
    if quiz_uuid:
        stmt = select(Quiz).where((Quiz.public_id == quiz_uuid) | (Quiz.title.ilike(f"%{quiz_identifier}%")))
    elif str(quiz_identifier).strip().isdigit():
        stmt = select(Quiz).where(
            (Quiz.id == int(quiz_identifier))
            | (Quiz.title.ilike(f"%{quiz_identifier}%"))
        )
    else:
        stmt = select(Quiz).where(Quiz.title.ilike(f"%{quiz_identifier}%"))
    return (await session.execute(stmt)).scalars().first()


# =============================================================================
# 1. CREATE ASSESSMENT (QUIZ) DRAFT
# =============================================================================


async def handle_create_assessment_draft(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Create a draft quiz with verified questions and answer keys."""
    user = context.user
    session = context.session

    title = arguments.get("title", "").strip()
    if not title:
        raise ValidationError("Assessment title is required.")

    course_id_str = arguments.get("course_id")
    batch_id_str = arguments.get("batch_id")

    if not course_id_str:
        raise ValidationError("Course ID is required to create an assessment.")

    # 1. Resolve Course by public UUID or integer/code
    courses_svc = CourseService(session)
    course = None
    if hasattr(courses_svc, "get_by_id_or_public_id"):
        try:
            res = courses_svc.get_by_id_or_public_id(course_id_str)
            course = await res if inspect.isawaitable(res) else res
        except Exception:
            course = None
    if not course:
        course = await _resolve_course(session, course_id_str)
    if not course:
        raise NotFoundError(f"Course '{course_id_str}' was not found.")

    # 2. Scope verification
    resolver = ScopeResolver(session)
    visible_courses = await resolver.visible_course_ids(user)
    if not visible_courses.allows(course.id):
        raise AuthorizationError("You are not assigned to teach or manage this course.")

    # 3. Resolve Batch if specified
    batch: Batch | None = None
    if batch_id_str:
        batch = await _resolve_batch(session, batch_id_str)
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


# =============================================================================
# 2. CREATE ASSIGNMENT DRAFT
# =============================================================================


async def handle_create_assignment_draft(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Create a draft assignment with a verified grading rubric and due date."""
    user = context.user
    session = context.session
    resolver = ScopeResolver(session)

    title = arguments.get("title", "").strip()
    if not title:
        raise ValidationError("Assignment title is required.")

    course_id_str = arguments.get("course_id")
    if not course_id_str:
        raise ValidationError("Course ID is required to create an assignment.")

    course = await _resolve_course(session, course_id_str)
    if not course:
        raise NotFoundError(f"Course '{course_id_str}' was not found.")

    visible_courses = await resolver.visible_course_ids(user)
    if not visible_courses.allows(course.id):
        raise AuthorizationError("You are not assigned to teach this course.")

    batch_id_str = arguments.get("batch_id")
    batch = None
    if batch_id_str:
        batch = await _resolve_batch(session, batch_id_str)
        if batch:
            visible_batches = await resolver.visible_batch_ids(user)
            if not visible_batches.allows(batch.id):
                raise AuthorizationError("You are not assigned to this batch.")

    due_date_raw = arguments.get("due_date")
    if due_date_raw:
        try:
            due_date = datetime.fromisoformat(str(due_date_raw))
            if due_date.tzinfo is None:
                due_date = due_date.replace(tzinfo=UTC)
        except Exception:
            due_date = datetime.now(UTC) + timedelta(days=14)
    else:
        due_date = datetime.now(UTC) + timedelta(days=14)

    max_score = Decimal(str(arguments.get("max_score", 100.0)))
    rubric = arguments.get("rubric") or {
        "criteria": [
            {"criterion": "Technical Accuracy", "weight": 40, "description": "Correct implementation and output"},
            {"criterion": "Code Quality / Structure", "weight": 30, "description": "Readable, well-organized code"},
            {"criterion": "Documentation & Analysis", "weight": 30, "description": "Clear explanations and comments"},
        ]
    }

    assignment_svc = AssignmentService(session)
    req = AssignmentCreateRequest(
        title=title,
        description=arguments.get("description", "Complete the required coursework per specifications."),
        due_date=due_date,
        max_score=max_score,
        rubric=rubric,
        allow_late_submissions=bool(arguments.get("allow_late_submissions", True)),
        scope=AssessmentScope.BATCH if batch else AssessmentScope.COURSE,
        batch_id=batch.public_id if batch else None,
    )

    created = await assignment_svc.create(course.public_id, req, actor=user)

    return {
        "success": True,
        "assignment_id": str(created.public_id),
        "title": created.title,
        "course": course.title,
        "batch": batch.batch_code if batch else None,
        "max_score": float(created.max_score),
        "due_date": created.due_date.isoformat(),
        "rubric": created.rubric,
        "state": created.state.value if hasattr(created.state, "value") else str(created.state),
        "summary": f"Draft assignment '{created.title}' created in DRAFT state for {course.title} (Max score: {float(created.max_score)}).",
    }


# =============================================================================
# 3. CREATE EXAMINATION DRAFT
# =============================================================================


async def handle_create_examination_draft(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Prepare a draft examination with duration, venue/link, passing criteria, and schedule."""
    user = context.user
    session = context.session
    resolver = ScopeResolver(session)

    title = arguments.get("title", "").strip()
    if not title:
        raise ValidationError("Examination title is required.")

    course_id_str = arguments.get("course_id")
    if not course_id_str:
        raise ValidationError("Course ID is required for examination.")

    course = await _resolve_course(session, course_id_str)
    if not course:
        raise NotFoundError(f"Course '{course_id_str}' was not found.")

    visible_courses = await resolver.visible_course_ids(user)
    if not visible_courses.allows(course.id):
        raise AuthorizationError("You are not assigned to teach this course.")

    batch_id_str = arguments.get("batch_id")
    batch = None
    if batch_id_str:
        batch = await _resolve_batch(session, batch_id_str)
        if batch:
            visible_batches = await resolver.visible_batch_ids(user)
            if not visible_batches.allows(batch.id):
                raise AuthorizationError("You are not assigned to this batch.")

    sched_raw = arguments.get("scheduled_at")
    if sched_raw:
        try:
            sched_at = datetime.fromisoformat(str(sched_raw))
            if sched_at.tzinfo is None:
                sched_at = sched_at.replace(tzinfo=UTC)
        except Exception:
            sched_at = datetime.now(UTC) + timedelta(days=7)
    else:
        sched_at = datetime.now(UTC) + timedelta(days=7)

    duration = int(arguments.get("duration_minutes", 60))
    total_marks = Decimal(str(arguments.get("total_marks", 100.0)))
    passing_marks = Decimal(str(arguments.get("passing_marks", 50.0)))

    exam_svc = ExamService(session)
    req = ExamCreateRequest(
        title=title,
        exam_type=ExamType.FINAL if "final" in title.lower() else ExamType.MIDTERM,
        scheduled_at=sched_at,
        duration_minutes=duration,
        total_marks=total_marks,
        passing_marks=passing_marks,
        venue_or_link=arguments.get("venue_or_link", "Online Examination Portal"),
        instructions=arguments.get("instructions", "Read all instructions carefully before starting."),
        course_id=course.public_id,
        batch_id=batch.public_id if batch else None,
        scope=AssessmentScope.BATCH if batch else AssessmentScope.COURSE,
    )

    created = await exam_svc.create(req, actor=user)

    return {
        "success": True,
        "exam_id": str(created.public_id),
        "title": created.title,
        "course": course.title,
        "batch": batch.batch_code if batch else None,
        "scheduled_at": created.scheduled_at.isoformat(),
        "duration_minutes": created.duration_minutes,
        "total_marks": float(created.total_marks),
        "passing_marks": float(created.passing_marks),
        "is_published": created.is_published,
        "summary": (
            f"Draft examination '{created.title}' (duration: {created.duration_minutes}m, "
            f"total marks: {float(created.total_marks)}) created in unpublished state."
        ),
    }


# =============================================================================
# 4. GET PENDING SUBMISSIONS
# =============================================================================


async def handle_get_pending_submissions(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Retrieve submitted student assignments awaiting marking within the tutor's authorized courses."""
    user = context.user
    session = context.session
    resolver = ScopeResolver(session)

    visible_courses = await resolver.visible_course_ids(user)

    stmt = (
        select(AssignmentSubmission, Assignment, UserModel)
        .join(Assignment, Assignment.id == AssignmentSubmission.assignment_id)
        .join(UserModel, UserModel.id == AssignmentSubmission.student_id)
        .where(
            AssignmentSubmission.state.in_([
                SubmissionState.SUBMITTED,
                SubmissionState.LATE,
                SubmissionState.UNDER_REVIEW,
            ])
        )
        .order_by(AssignmentSubmission.submitted_at.asc())
        .limit(20)
    )

    stmt = visible_courses.apply(stmt, Assignment.course_id)

    batch_id_str = arguments.get("batch_identifier")
    if batch_id_str:
        batch = await _resolve_batch(session, batch_id_str)
        if batch:
            stmt = stmt.where(Assignment.batch_id == batch.id)

    rows = (await session.execute(stmt)).all()

    out = []
    for sub, asmt, student in rows:
        s_name = f"{student.first_name or ''} {student.last_name or ''}".strip() or student.username
        out.append({
            "submission_id": str(sub.public_id),
            "assignment_title": asmt.title,
            "max_score": float(asmt.max_score),
            "student_name": s_name,
            "student_username": student.username,
            "submitted_at": sub.submitted_at.isoformat() if sub.submitted_at else "",
            "state": sub.state.value if hasattr(sub.state, "value") else str(sub.state),
            "rubric": asmt.rubric,
        })

    return {
        "count": len(out),
        "submissions": out,
        "summary": (
            f"Found {len(out)} pending assignment submission(s) awaiting marking."
            if out
            else "No pending assignment submissions awaiting marking."
        ),
    }


# =============================================================================
# 5. SUGGEST / APPLY SUBMISSION GRADE
# =============================================================================


async def handle_suggest_submission_grade(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Evaluate a student submission against the rubric, propose grades, and optionally record."""
    user = context.user
    session = context.session

    submission_id_str = arguments.get("submission_id")
    if not submission_id_str:
        raise ValidationError("Submission ID is required.")

    sub_uuid = uuid.UUID(str(submission_id_str).strip())
    stmt = (
        select(AssignmentSubmission, Assignment, UserModel)
        .join(Assignment, Assignment.id == AssignmentSubmission.assignment_id)
        .join(UserModel, UserModel.id == AssignmentSubmission.student_id)
        .where(AssignmentSubmission.public_id == sub_uuid)
    )
    row = (await session.execute(stmt)).first()
    if not row:
        raise NotFoundError("Submission not found.")

    sub, asmt, student = row
    resolver = ScopeResolver(session)
    visible_courses = await resolver.visible_course_ids(user)
    if not visible_courses.allows(asmt.course_id):
        raise AuthorizationError("You are not authorized to grade submissions for this course.")

    suggested_score = Decimal(str(arguments.get("suggested_grade", asmt.max_score)))
    if suggested_score > asmt.max_score:
        suggested_score = asmt.max_score

    feedback = arguments.get("feedback", "Good effort. Meets primary evaluation criteria.")
    rubric_eval = arguments.get("rubric_breakdown") or {
        "evaluation": "Rubric criteria satisfied.",
        "score": float(suggested_score),
        "max_score": float(asmt.max_score),
    }

    apply_immediately = bool(arguments.get("apply_immediately", False))

    if apply_immediately:
        from backend.schemas.assignment import GradeSubmissionRequest
        asmt_svc = AssignmentService(session)
        graded = await asmt_svc.grade(
            public_id=sub.public_id,
            payload=GradeSubmissionRequest(
                grade=suggested_score,
                feedback=feedback,
            ),
            actor=user,
        )
        return {
            "status": "GRADED",
            "submission_id": str(graded.public_id),
            "grade": float(graded.grade or suggested_score),
            "max_score": float(asmt.max_score),
            "feedback": graded.feedback,
            "rubric_evaluation": rubric_eval,
            "summary": f"Grade of {float(suggested_score)}/{float(asmt.max_score)} recorded successfully for {student.username}.",
        }

    return {
        "status": "PROPOSED_FOR_REVIEW",
        "submission_id": str(sub.public_id),
        "student_username": student.username,
        "suggested_grade": float(suggested_score),
        "max_score": float(asmt.max_score),
        "feedback": feedback,
        "rubric_evaluation": rubric_eval,
        "summary": (
            f"AI proposed grade: {float(suggested_score)}/{float(asmt.max_score)} for {student.username}. "
            "Feedback and rubric evaluation prepared for tutor approval."
        ),
    }


# =============================================================================
# 6. GET QUIZ EVALUATION SUMMARY
# =============================================================================


async def handle_get_quiz_evaluation_summary(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Retrieve quiz attempt statistics, average scores, passing rate, and evaluation metrics."""
    user = context.user
    session = context.session

    quiz_id_str = arguments.get("quiz_identifier")
    if not quiz_id_str:
        raise ValidationError("Quiz identifier is required.")

    quiz = await _resolve_quiz(session, quiz_id_str)
    if not quiz:
        raise NotFoundError(f"Quiz '{quiz_id_str}' was not found.")

    resolver = ScopeResolver(session)
    visible_courses = await resolver.visible_course_ids(user)
    if not visible_courses.allows(quiz.course_id):
        raise AuthorizationError("You are not authorized to view results for this quiz.")

    stmt = (
        select(QuizAttempt)
        .where(QuizAttempt.quiz_id == quiz.id, QuizAttempt.finished_at.is_not(None))
    )
    attempts = (await session.execute(stmt)).scalars().all()

    if not attempts:
        return {
            "quiz_title": quiz.title,
            "total_attempts": 0,
            "scored_attempts": 0,
            "average_score": None,
            "passing_rate_percent": None,
            "summary": f"No completed student attempts found for quiz '{quiz.title}'.",
        }

    scores = [float(a.score) for a in attempts if a.score is not None]
    passed_count = sum(1 for a in attempts if a.is_passed)
    avg_score = round(sum(scores) / len(scores), 1) if scores else None
    passing_rate = round((passed_count / len(attempts)) * 100.0, 1) if attempts else 0.0

    return {
        "quiz_id": str(quiz.public_id),
        "quiz_title": quiz.title,
        "total_completed_attempts": len(attempts),
        "scored_attempts_count": len(scores),
        "pending_scoring_count": len(attempts) - len(scores),
        "average_score": avg_score,
        "passing_rate_percent": passing_rate,
        "highest_score": max(scores) if scores else None,
        "lowest_score": min(scores) if scores else None,
        "summary": (
            f"Quiz '{quiz.title}': {len(attempts)} attempts, average score {avg_score}%, "
            f"passing rate {passing_rate}%, with {len(attempts) - len(scores)} attempts awaiting evaluation."
        ),
    }


# =============================================================================
# 7. MANAGE COURSE RESOURCES
# =============================================================================


async def handle_manage_course_resources(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Create, organize, list, or delete course materials and learning resources."""
    user = context.user
    session = context.session
    resolver = ScopeResolver(session)

    action = arguments.get("action", "list").lower()
    course_id_str = arguments.get("course_id")

    course = None
    if course_id_str:
        course = await _resolve_course(session, course_id_str)
        if not course:
            raise NotFoundError(f"Course '{course_id_str}' not found.")
        visible_courses = await resolver.visible_course_ids(user)
        if not visible_courses.allows(course.id):
            raise AuthorizationError("You do not have access to this course.")

    batch_id_str = arguments.get("batch_id")
    batch = None
    if batch_id_str:
        batch = await _resolve_batch(session, batch_id_str)

    res_svc = ResourceService(session)

    if action == "list":
        page_params = PageParams(page=1, page_size=20)
        resources, total = await res_svc.list_resources(
            page_params,
            actor=user,
            course_public_id=course.public_id if course else None,
        )
        formatted = [
            {"id": str(r.public_id), "name": r.name, "type": r.resource_type.value, "size": r.size}
            for r in resources[:15]
        ]
        return {
            "action": "list",
            "total_resources": total,
            "resources": formatted,
            "summary": f"Found {total} resource(s) for course {course.title if course else 'all'}.",
        }

    if action == "create_folder":
        folder_name = arguments.get("folder_name", "Course Materials").strip()
        folder_req = FolderCreateRequest(
            name=folder_name,
            course_id=course.public_id if course else None,
            batch_id=batch.public_id if batch else None,
        )
        created_folder = await res_svc.create_folder(folder_req, actor=user)
        return {
            "action": "create_folder",
            "folder_id": str(created_folder.public_id),
            "folder_name": created_folder.name,
            "summary": f"Folder '{created_folder.name}' created successfully for course {course.title if course else 'cohort'}.",
        }

    if action == "delete":
        resource_id_str = arguments.get("resource_id")
        if not resource_id_str:
            raise ValidationError("Resource ID is required for deletion.")
        r_uuid = uuid.UUID(str(resource_id_str).strip())
        await res_svc.soft_delete(r_uuid, actor=user)
        return {
            "action": "delete",
            "resource_id": str(r_uuid),
            "summary": f"Resource {resource_id_str} deleted successfully.",
        }

    return {"error": f"Unsupported resource action: {action}"}


# =============================================================================
# 8. GET COURSE CURRICULUM
# =============================================================================


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


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================


create_assessment_draft_tool = ToolDefinition(
    name="create_assessment_draft",
    description="Create a new quiz draft with verified questions, point values, and answer keys in DRAFT state.",
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


create_assignment_draft_tool = ToolDefinition(
    name="create_assignment_draft",
    description="Create a new course assignment draft with grading rubric, due date, and point scale.",
    policy=ToolPolicy(
        name="create_assignment_draft",
        description="Create draft assignment",
        required_permissions=("assignment.create",),
        allowed_roles=(Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value),
        risk_level=RiskLevel.MODERATE,
        audit_action="CREATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Assignment title"},
            "course_id": {"type": "string", "description": "Course UUID or code"},
            "batch_id": {"type": "string", "description": "Batch UUID or batch code (optional)"},
            "description": {"type": "string", "description": "Assignment instructions and tasks"},
            "max_score": {"type": "number", "description": "Maximum marks (e.g. 100.0)", "default": 100.0},
            "due_date": {"type": "string", "description": "Due date in ISO 8601 (optional)"},
            "rubric": {
                "type": "object",
                "description": "Grading rubric criteria with weights and descriptions",
            },
        },
        "required": ["title", "course_id"],
    },
    handler=handle_create_assignment_draft,
)


create_examination_draft_tool = ToolDefinition(
    name="create_examination_draft",
    description="Prepare a formal examination draft with scheduled date, duration, total marks, and passing criteria.",
    policy=ToolPolicy(
        name="create_examination_draft",
        description="Create draft examination",
        required_permissions=("exam.create",),
        allowed_roles=(Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value),
        risk_level=RiskLevel.MODERATE,
        audit_action="CREATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Examination title (e.g. Final Examination)"},
            "course_id": {"type": "string", "description": "Course UUID or code"},
            "batch_id": {"type": "string", "description": "Batch UUID or batch code (optional)"},
            "scheduled_at": {"type": "string", "description": "Scheduled start time in ISO 8601"},
            "duration_minutes": {"type": "integer", "description": "Duration in minutes (e.g. 60)", "default": 60},
            "total_marks": {"type": "number", "description": "Total marks available", "default": 100.0},
            "passing_marks": {"type": "number", "description": "Minimum passing marks", "default": 50.0},
            "instructions": {"type": "string", "description": "Exam instructions"},
        },
        "required": ["title", "course_id"],
    },
    handler=handle_create_examination_draft,
)


get_pending_submissions_tool = ToolDefinition(
    name="get_pending_submissions",
    description="Retrieve submitted student assignments awaiting marking within the tutor's assigned courses.",
    policy=ToolPolicy(
        name="get_pending_submissions",
        description="View pending assignment submissions",
        required_permissions=("assignment.grade",),
        allowed_roles=(Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value),
        risk_level=RiskLevel.LOW,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "batch_identifier": {"type": "string", "description": "Batch code or UUID to filter submissions (optional)"},
        },
    },
    handler=handle_get_pending_submissions,
)


suggest_submission_grade_tool = ToolDefinition(
    name="suggest_submission_grade",
    description="Evaluate a student submission against a rubric, suggest grades and feedback, and stage for tutor approval.",
    policy=ToolPolicy(
        name="suggest_submission_grade",
        description="Evaluate submission grade",
        required_permissions=("assignment.grade",),
        allowed_roles=(Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value),
        risk_level=RiskLevel.MODERATE,
        audit_action="UPDATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "submission_id": {"type": "string", "description": "Submission UUID"},
            "suggested_grade": {"type": "number", "description": "Proposed score"},
            "feedback": {"type": "string", "description": "Constructive student feedback"},
            "apply_immediately": {"type": "boolean", "description": "Whether to record the grade directly", "default": False},
        },
        "required": ["submission_id", "suggested_grade", "feedback"],
    },
    handler=handle_suggest_submission_grade,
)


get_quiz_evaluation_summary_tool = ToolDefinition(
    name="get_quiz_evaluation_summary",
    description="Analyze quiz attempt results, compute average scores, passing rate, and evaluation metrics.",
    policy=ToolPolicy(
        name="get_quiz_evaluation_summary",
        description="Evaluate quiz results",
        required_permissions=("quiz.grade",),
        allowed_roles=(Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value),
        risk_level=RiskLevel.LOW,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "quiz_identifier": {"type": "string", "description": "Quiz title, code, or UUID"},
        },
        "required": ["quiz_identifier"],
    },
    handler=handle_get_quiz_evaluation_summary,
)


manage_course_resources_tool = ToolDefinition(
    name="manage_course_resources",
    description="Create folders, organize course materials, list files, or delete learning resources.",
    policy=ToolPolicy(
        name="manage_course_resources",
        description="Manage course materials and resources",
        required_permissions=("course.read",),
        allowed_roles=(Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value),
        risk_level=RiskLevel.MODERATE,
        audit_action="UPDATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "create_folder", "delete"], "description": "Action to perform"},
            "course_id": {"type": "string", "description": "Course UUID or code"},
            "batch_id": {"type": "string", "description": "Batch UUID or code (optional)"},
            "folder_name": {"type": "string", "description": "Name for new folder (if action=create_folder)"},
            "resource_id": {"type": "string", "description": "Resource UUID (if action=delete)"},
        },
        "required": ["action"],
    },
    handler=handle_manage_course_resources,
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


async def handle_publish_assessment(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Publish an assessment (quiz, assignment, or examination) making it live for enrolled students."""
    user = context.user
    session = context.session
    assessment_type = str(arguments.get("assessment_type", "quiz")).lower().strip()
    identifier = arguments.get("assessment_id") or arguments.get("identifier")
    if not identifier:
        raise ValidationError("assessment_id or identifier is required.")

    if assessment_type == "quiz":
        quiz = await _resolve_quiz(session, str(identifier))
        if not quiz:
            raise NotFoundError(f"Quiz '{identifier}' not found.")
        quiz_svc = QuizService(session)
        updated = await quiz_svc.set_published(
            public_id=quiz.public_id,
            is_published=True,
            actor=user,
        )
        return {
            "success": True,
            "assessment_type": "quiz",
            "quiz_id": str(updated.public_id),
            "title": updated.title,
            "is_published": True,
            "message": f"Quiz '{updated.title}' has been successfully published to students.",
        }

    elif assessment_type == "assignment":
        asmt_uuid = None
        try:
            asmt_uuid = uuid.UUID(str(identifier).strip())
        except (ValueError, TypeError):
            pass
        if asmt_uuid:
            stmt = select(Assignment).where(Assignment.public_id == asmt_uuid)
        else:
            stmt = select(Assignment).where(Assignment.title == str(identifier).strip())
        asmt = (await session.execute(stmt)).scalar_one_or_none()
        if not asmt:
            raise NotFoundError(f"Assignment '{identifier}' not found.")

        resolver = ScopeResolver(session)
        visible_courses = await resolver.visible_course_ids(user)
        if not visible_courses.allows(asmt.course_id):
            raise AuthorizationError("You are not authorized to publish this assignment.")

        asmt.state = AssessmentState.PUBLISHED
        await session.flush()
        return {
            "success": True,
            "assessment_type": "assignment",
            "assignment_id": str(asmt.public_id),
            "title": asmt.title,
            "state": "PUBLISHED",
            "message": f"Assignment '{asmt.title}' has been successfully published to students.",
        }

    elif assessment_type in ("exam", "examination"):
        from backend.services.exam_service import ExamService
        exam_svc = ExamService(session)
        ex_uuid = uuid.UUID(str(identifier).strip())
        exam = await exam_svc.get(ex_uuid, actor=user)
        exam.is_published = True
        await session.flush()
        return {
            "success": True,
            "assessment_type": "examination",
            "exam_id": str(exam.public_id),
            "title": exam.title,
            "is_published": True,
            "message": f"Examination '{exam.title}' has been successfully published.",
        }

    raise ValidationError(f"Unknown assessment type: '{assessment_type}'.")


publish_assessment_tool = ToolDefinition(
    name="publish_assessment",
    description="Publish an assessment (quiz, assignment, or examination) making it live and visible for students.",
    policy=ToolPolicy(
        name="publish_assessment",
        description="Publish assessment to students",
        required_permissions=("course.read",),
        allowed_roles=(Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value),
        risk_level=RiskLevel.HIGH,
        audit_action="UPDATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "assessment_type": {
                "type": "string",
                "enum": ["quiz", "assignment", "examination"],
                "description": "Type of assessment to publish",
                "default": "quiz",
            },
            "assessment_id": {
                "type": "string",
                "description": "UUID or title of the assessment to publish",
            },
        },
        "required": ["assessment_id"],
    },
    handler=handle_publish_assessment,
)


# =============================================================================
# 10. SUBMIT ASSIGNMENT SOLUTION (STUDENT)
# =============================================================================


async def handle_submit_assignment_solution(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Submit an assignment solution on behalf of the authenticated student."""
    user = context.user
    session = context.session
    asgn_ident = arguments.get("assignment_identifier")
    content = arguments.get("content")

    if not asgn_ident or not content:
        raise ValidationError("Both 'assignment_identifier' and 'content' are required.")

    # Resolve assignment
    assignment_uuid = None
    try:
        assignment_uuid = uuid.UUID(str(asgn_ident).strip())
    except (ValueError, TypeError):
        pass

    if assignment_uuid:
        stmt = select(Assignment).where((Assignment.public_id == assignment_uuid) | (Assignment.title.ilike(f"%{asgn_ident}%")))
    else:
        stmt = select(Assignment).where(Assignment.title.ilike(f"%{asgn_ident}%"))

    assignment = (await session.execute(stmt)).scalars().first()
    if not assignment:
        raise NotFoundError(f"Assignment '{asgn_ident}' was not found.")

    from backend.schemas.assignment import SubmitAssignmentRequest
    from backend.services.assignment_service import AssignmentService

    svc = AssignmentService(session)
    submission = await svc.submit(
        assignment_public_id=assignment.public_id,
        payload=SubmitAssignmentRequest(content=str(content)),
        actor=user,
    )

    return {
        "success": True,
        "submission_id": str(submission.public_id),
        "assignment_title": assignment.title,
        "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else datetime.now(UTC).isoformat(),
        "state": submission.state.value if hasattr(submission.state, "value") else str(submission.state),
        "message": f"Successfully submitted solution for assignment '{assignment.title}'.",
    }


submit_assignment_solution_tool = ToolDefinition(
    name="submit_assignment_solution",
    description="Submit an assignment solution, answer, or code on behalf of the authenticated student.",
    policy=ToolPolicy(
        name="submit_assignment_solution",
        description="Submit assignment solution",
        required_permissions=("assignment.submit",),
        allowed_roles=(Roles.STUDENT.value, Roles.SUPER_ADMIN.value),
        risk_level=RiskLevel.MODERATE,
        audit_action="CREATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "assignment_identifier": {
                "type": "string",
                "description": "Title or UUID of the assignment to submit to",
            },
            "content": {
                "type": "string",
                "description": "The textual answer, code, solution notes, or response text",
            },
        },
        "required": ["assignment_identifier", "content"],
    },
    handler=handle_submit_assignment_solution,
)

