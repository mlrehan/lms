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
from backend.ai.tools.registry import ConfirmationPreview, ToolDefinition, ToolExecutionContext
from backend.core.privacy import visible_email, visible_username
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
from backend.utils.enums import AssessmentScope, AssessmentState, ExamType, QuestionType, ResourceType, Roles, SubmissionState, SubmissionType


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
            raise NotFoundError("Batch not found.")  # same answer as one that does not exist

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
        settings: dict[str, Any] | None = None

        if q_type in (
            QuestionType.MCQ_SINGLE, QuestionType.MCQ_MULTIPLE, QuestionType.TRUE_FALSE,
            QuestionType.ORDERING, QuestionType.MATCHING,
        ):
            # For ORDERING the list is given in the correct order, so the
            # position written here *is* the answer key.
            for opt_idx, opt in enumerate(q.get("options", [])):
                options_input.append(
                    OptionInput(
                        option_text=opt.get("option_text", f"Option {opt_idx + 1}"),
                        is_correct=bool(opt.get("is_correct", False)),
                        order=opt_idx + 1,
                        match_text=opt.get("match_text") if q_type is QuestionType.MATCHING else None,
                    )
                )
        elif q_type is QuestionType.FILL_BLANK:
            settings = {"accepted": [str(a) for a in (q.get("accepted_answers") or []) if str(a).strip()]}
            if q.get("case_sensitive"):
                settings["case_sensitive"] = True
        elif q_type is QuestionType.NUMERIC:
            settings = {"answer": q.get("numeric_answer")}
            if q.get("tolerance") is not None:
                settings["tolerance"] = q.get("tolerance")

        try:
            prepared_questions.append(
                QuestionCreateRequest(
                    question_text=q_text,
                    question_type=q_type,
                    points=points,
                    order=i,
                    options=options_input,
                    settings=settings,
                    explanation=(q.get("explanation") or None),
                )
            )
        except ValueError as exc:
            # Raised before anything is saved, so a bad question leaves no
            # half-built quiz behind; the message says which one to fix.
            raise ValidationError(f"Question #{i} cannot be saved: {exc}") from exc

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
                raise NotFoundError("Batch not found.")  # same answer as one that does not exist

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
        submission_type=SubmissionType(str(arguments.get("submission_type") or "FILE_UPLOAD").upper())
        if str(arguments.get("submission_type") or "FILE_UPLOAD").upper() in SubmissionType.__members__
        else SubmissionType.FILE_UPLOAD,
        scope=AssessmentScope.BATCH if batch else AssessmentScope.COURSE,
        batch_id=batch.public_id if batch else None,
        # Stated explicitly: the request schema defaults to PUBLISHED, which
        # notified every student the moment the assistant "drafted" one.
        # Publishing is a separate, confirmed step (publish_assessment).
        state=AssessmentState.DRAFT,
    )

    created = await assignment_svc.create(course.public_id, req, actor=user)
    state = created.state.value if hasattr(created.state, "value") else str(created.state)

    return {
        "success": True,
        "assignment_id": str(created.public_id),
        "title": created.title,
        "course": course.title,
        "batch": batch.batch_code if batch else None,
        "max_score": float(created.max_score),
        "due_date": created.due_date.isoformat(),
        "rubric": created.rubric,
        "state": state,
        "summary": (
            f"Assignment '{created.title}' saved in {state} state for {course.title} "
            f"(max score {float(created.max_score)}). Students cannot see it until it is published."
            if state == AssessmentState.DRAFT.value
            else f"Assignment '{created.title}' is {state} for {course.title}."
        ),
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
                raise NotFoundError("Batch not found.")  # same answer as one that does not exist

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
        s_name = f"{student.first_name or ''} {student.last_name or ''}".strip() or "Unnamed account"
        out.append({
            "submission_id": str(sub.public_id),
            "assignment_title": asmt.title,
            "max_score": float(asmt.max_score),
            "student_name": s_name,
            "student_username": visible_username(student),
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
    """Evaluate a student submission against the rubric and propose a grade (records nothing)."""
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

    # A missing score is refused, never defaulted: the previous default was
    # full marks, which is a grade nobody decided.
    raw_grade = arguments.get("suggested_grade")
    if raw_grade is None:
        raise ValidationError("A suggested grade is required.")
    suggested_score = Decimal(str(raw_grade))
    if suggested_score < 0:
        raise ValidationError("A suggested grade cannot be negative.")
    if suggested_score > asmt.max_score:
        suggested_score = asmt.max_score

    feedback = arguments.get("feedback")
    rubric_eval = arguments.get("rubric_breakdown") or {
        "evaluation": "Rubric criteria satisfied.",
        "score": float(suggested_score),
        "max_score": float(asmt.max_score),
    }

    # Suggest only. Recording a mark is the tutor's act, on the marking screen;
    # an `apply_immediately` switch here let a model-chosen number become a
    # student's grade with no confirmation at all.
    student_name = f"{student.first_name or ''} {student.last_name or ''}".strip() or "this student"

    return {
        "status": "PROPOSED_FOR_REVIEW",
        "submission_id": str(sub.public_id),
        "student_name": student_name,
        "suggested_grade": float(suggested_score),
        "max_score": float(asmt.max_score),
        "feedback": feedback,
        "rubric_evaluation": rubric_eval,
        "summary": (
            f"Suggested grade: {float(suggested_score)}/{float(asmt.max_score)} for {student_name}. "
            "Nothing has been recorded; the tutor records the mark on the marking screen."
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
    """A course's published content: description, outline, overview, prerequisites.

    Candidates are found by id, code or title, and each is admitted through
    `CourseService.get` -- the catalogue's own rule, so a draft course is
    visible only to the tutors assigned to it, exactly as on the Courses screen.
    The schema has no module or lesson tables: the outline, from the
    institution's course page, is the curriculum, and is said to be missing
    when it is.
    """
    session = context.session
    course_query = str(arguments.get("course_identifier") or "").strip()
    if not course_query:
        raise ValidationError("Name the course by its title, code or id.")

    try:
        by_id = uuid.UUID(course_query)
    except ValueError:
        by_id = None
    if by_id is not None:
        stmt = select(Course.public_id).where(Course.public_id == by_id)
    else:
        stmt = (
            select(Course.public_id)
            .where(
                Course.deleted_at.is_(None),
                (func.lower(Course.code) == course_query.lower()) | Course.title.ilike(f"%{course_query}%"),
            )
            # An exact code or title outranks a partial title match.
            .order_by(
                (func.lower(Course.code) == course_query.lower()).desc(),
                (func.lower(Course.title) == course_query.lower()).desc(),
                Course.title,
            )
            .limit(10)
        )
    courses = CourseService(session)
    course = None
    for public_id in (await session.execute(stmt)).scalars():
        try:
            course = await courses.get(public_id, actor=context.user)
            break
        except NotFoundError:
            continue
    if course is None:
        raise NotFoundError(f"Course matching '{course_query}' was not found.")

    return {
        "course_id": str(course.public_id),
        "code": course.code,
        "title": course.title,
        "level": course.level.value if course.level else None,
        "description": course.description,
        "prerequisites": course.prerequisites,
        "duration_hours": course.duration_hours,
        "official_outline": course.outline,
        "overview": course.overview,
        "course_page": course.course_link,
        "sources": {
            "official_outline": "verified_lms" if course.outline else "missing",
            "description": "verified_lms" if course.description else "missing",
        },
    }


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================


create_assessment_draft_tool = ToolDefinition(
    name="create_assessment_draft",
    description=(
        "Create an unpublished quiz with questions, points, answer keys and explanations. Students see nothing "
        "until it is published with publish_assessment."
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
                            "enum": [
                                "MCQ_SINGLE", "MCQ_MULTIPLE", "TRUE_FALSE", "FILL_BLANK", "NUMERIC",
                                "MATCHING", "ORDERING", "SHORT_ANSWER", "ESSAY",
                            ],
                        },
                        "points": {"type": "number", "default": 1.0},
                        "explanation": {
                            "type": "string",
                            "description": "Why the answer is correct; also the marking guide for SHORT_ANSWER/ESSAY",
                        },
                        "options": {
                            "type": "array",
                            "description": (
                                "MCQ/TRUE_FALSE: choices with is_correct. ORDERING: items in the CORRECT order. "
                                "MATCHING: each item with its match_text."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "option_text": {"type": "string"},
                                    "is_correct": {"type": "boolean"},
                                    "match_text": {"type": "string"},
                                },
                                "required": ["option_text"],
                            },
                        },
                        "accepted_answers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "FILL_BLANK: every answer that counts as correct",
                        },
                        "case_sensitive": {"type": "boolean"},
                        "numeric_answer": {"type": "number", "description": "NUMERIC: the correct value"},
                        "tolerance": {"type": "number", "description": "NUMERIC: allowed +/- difference"},
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
            "submission_type": {
                "type": "string",
                "enum": ["FILE_UPLOAD", "TEXT", "LINK"],
                "description": "How students hand it in: a file (default), typed text, or a link",
            },
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
        # Records nothing, so it audits nothing: an UPDATE row here would put a
        # write into the trail that never happened.
        risk_level=RiskLevel.MODERATE,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "submission_id": {"type": "string", "description": "Submission UUID"},
            "suggested_grade": {"type": "number", "description": "Proposed score"},
            "feedback": {"type": "string", "description": "Constructive student feedback"},
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
    description=(
        "Retrieve a course's published description, official outline, overview and prerequisites. "
        "For preparing a class the caller teaches, prefer get_teaching_context."
    ),
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


# Publishing an assessment needs the same permission the console's own route
# needs for that type -- `exam.publish` for a schedule, `quiz.publish` for a
# quiz, `assignment.update` for an assignment (its publish is a state change on
# the ordinary update route). The tool used to accept `course.read` plus a role
# list, so whether it agreed with the console depended on how roles happened to
# be granted rather than on the permission the console actually checks.
_PUBLISH_PERMISSION = {
    "quiz": "quiz.publish",
    "assignment": "assignment.update",
    "examination": "exam.publish",
}


def _publish_type(arguments: dict[str, Any]) -> str:
    raw = str(arguments.get("assessment_type", "quiz")).lower().strip()
    kind = "examination" if raw == "exam" else raw
    if kind not in _PUBLISH_PERMISSION:
        raise ValidationError(f"Unknown assessment type: '{raw}'.")
    return kind


async def _resolve_for_publish(session: AsyncSession, model: Any, identifier: str) -> Any:
    """An exact id, or an exact title that names one row -- never a fuzzy match.

    Publishing the first title that merely contains the words typed would make
    a near-namesake live for a whole class.
    """
    ident = str(identifier).strip()
    try:
        return (
            await session.execute(select(model).where(model.public_id == uuid.UUID(ident)))
        ).scalar_one_or_none()
    except (ValueError, TypeError):
        pass
    rows = (
        await session.execute(select(model).where(func.lower(model.title) == ident.lower()).limit(2))
    ).scalars().all()
    if len(rows) > 1:
        raise ValidationError(f"More than one assessment is titled '{ident}'. Give its id instead.")
    return rows[0] if rows else None


async def _load_for_publish(arguments: dict[str, Any], context: ToolExecutionContext) -> tuple[str, Any]:
    """Resolve the assessment through its own service, so its scope rules apply."""
    from backend.ai.security import SecurityPolicyEngine

    kind = _publish_type(arguments)
    if _PUBLISH_PERMISSION[kind] not in SecurityPolicyEngine.caller_permissions(context.user):
        raise AuthorizationError(f"You do not hold permission to publish this {kind}.")

    identifier = arguments.get("assessment_id") or arguments.get("identifier")
    if not identifier:
        raise ValidationError("assessment_id or identifier is required.")

    model = {"quiz": Quiz, "assignment": Assignment, "examination": Exam}[kind]
    row = await _resolve_for_publish(context.session, model, str(identifier))
    if row is None:
        raise NotFoundError(f"{kind.capitalize()} '{identifier}' not found.")

    service = {"quiz": QuizService, "assignment": AssignmentService, "examination": ExamService}[kind]
    # `get` applies the same visibility the console applies: 404 if outside scope.
    row = await service(context.session).get(row.public_id, actor=context.user)
    return kind, row


async def preview_publish_assessment(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> ConfirmationPreview:
    kind, row = await _load_for_publish(arguments, context)
    return ConfirmationPreview(
        summary=f"Publish the {kind} '{row.title}' to its students?",
        bound_parameters={"assessment_public_id": str(row.public_id)},
    )


async def handle_publish_assessment(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Publish an assessment through its service (runs only after confirmation)."""
    from backend.ai.tools.registry import BOUND_PREFIX
    from backend.schemas.assignment import AssignmentUpdateRequest
    from backend.utils.enums import AssessmentState

    kind, row = await _load_for_publish(arguments, context)
    if str(row.public_id) != str(arguments.get(f"{BOUND_PREFIX}assessment_public_id")):
        raise ValidationError("The assessment no longer matches the one confirmed; ask again.")

    user = context.user
    if kind == "quiz":
        updated = await QuizService(context.session).set_published(row.public_id, True, actor=user)
        published = bool(updated.is_published)
    elif kind == "assignment":
        updated = await AssignmentService(context.session).update(
            row.public_id, AssignmentUpdateRequest(state=AssessmentState.PUBLISHED), actor=user
        )
        published = updated.state is AssessmentState.PUBLISHED
    else:
        updated = await ExamService(context.session).set_published(row.public_id, True, actor=user)
        published = bool(updated.is_published)

    # Reported from the row the service returned, not assumed from the call.
    return {
        "success": published,
        "assessment_type": kind,
        "assessment_id": str(updated.public_id),
        "title": updated.title,
        "is_published": published,
        "message": (
            f"The {kind} '{updated.title}' is now published."
            if published
            else f"The {kind} '{updated.title}' could not be published."
        ),
    }


publish_assessment_tool = ToolDefinition(
    name="publish_assessment",
    description=(
        "Publish an assessment (quiz, assignment, or examination) so its students can see it. "
        "Requires the user's confirmation."
    ),
    policy=ToolPolicy(
        name="publish_assessment",
        description="Publish assessment to students",
        required_permissions=("course.read",),
        allowed_roles=(Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value),
        risk_level=RiskLevel.HIGH,
        requires_confirmation=True,
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
                "description": "UUID or exact title of the assessment to publish",
            },
        },
        "required": ["assessment_id"],
    },
    handler=handle_publish_assessment,
    preview=preview_publish_assessment,
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

