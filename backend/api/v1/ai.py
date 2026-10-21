"""AI Assistant API Endpoints.

Provides role-aware conversational interface, two-phase confirmation ticket workflows,
voice transcription, and user-scoped conversation state management.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any, AsyncIterator
from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from backend.ai.client import get_openai_client
from backend.ai.orchestrator import create_role_agent
from backend.ai.security import AISecurityError, SecurityError, SecurityPolicyEngine
from backend.ai.state import ConversationStateManager
from backend.ai.tickets import get_ticket_manager
from backend.ai.workflows.confirmation_service import ConfirmationExecutionService
from backend.api.deps import CurrentUser
from backend.core.errors import (
    AppError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from backend.core.logging import get_logger
from backend.db.dependencies import DBSession
from backend.models.enrollment import Enrollments
from backend.models.identity.user import User
from backend.models.quiz import Quiz
from backend.services import audit_service
from backend.services.quiz_service import QuizService
from backend.utils.enums import EnrollmentStatus

router = APIRouter(prefix="/ai", tags=["AI Assistant"])
logger = get_logger(__name__)


# =============================================================================
# SCHEMAS
# =============================================================================


class AIChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=10000, description="User prompt or instruction")
    stream: bool = Field(default=False, description="Whether to stream the response via SSE")


class AIChatResponse(BaseModel):
    message: str
    role: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    draft_assessments: list[dict[str, Any]] = Field(default_factory=list)
    confirmation_ticket: dict[str, Any] | None = None
    success: bool = True


class CreatePublishAssessmentTicketRequest(BaseModel):
    quiz_id: str = Field(..., description="Public ID or UUID of the quiz to publish")


class ConfirmationTicketResponse(BaseModel):
    ticket_id: str
    action_name: str
    parameters: dict[str, Any]
    parameters_hash: str
    affected_records_count: int
    preview_summary: str
    expires_at: str
    status: str


class ConfirmationExecuteRequest(BaseModel):
    ticket_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ConfirmationExecuteResponse(BaseModel):
    success: bool
    result: dict[str, Any]


class AudioTranscriptionResponse(BaseModel):
    text: str


class ConversationMessageItem(BaseModel):
    message_id: str
    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    created_at: str | None = None


class ConversationHistoryResponse(BaseModel):
    messages: list[ConversationMessageItem]
    total: int


class ClearHistoryResponse(BaseModel):
    success: bool
    deleted_count: int


# =============================================================================
# CHAT ENDPOINT
# =============================================================================


@router.post("/chat", response_model=AIChatResponse, summary="Send a prompt to the role-bound AI assistant")
async def chat_with_agent(
    payload: AIChatRequest,
    current_user: CurrentUser,
    session: DBSession,
    request: Request,
) -> Any:
    """Send a conversational prompt to the caller's role-bound AI assistant."""
    # 1. Prompt Injection & Jailbreak Defense
    try:
        sanitized_prompt = SecurityPolicyEngine.sanitize_user_input(payload.prompt)
    except (SecurityError, AISecurityError) as exc:
        logger.warning("Prompt injection blocked for user %s: %s", current_user.public_id, exc)
        try:
            audit_service.record(
                session,
                action=audit_service.AuditAction.AI_SECURITY_ALERT,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                entity_type="ai_prompt",
                success=False,
                details={
                    "event": "PROMPT_INJECTION_BLOCKED",
                    "reason": str(exc),
                },
            )
        except Exception:
            pass

        return AIChatResponse(
            message=(
                "Request blocked by AI safety policy. Malicious prompt patterns or "
                "unauthorized instruction overrides were detected."
            ),
            role="SAFETY_SYSTEM",
            success=False,
        )

    # 2. Scoped Conversation History
    state_mgr = ConversationStateManager(session)
    recent_history = await state_mgr.get_recent_history(user_id=current_user.id, limit=10)

    # Fast-path for conversational confirmation (e.g. SuperAdmin answering "Yes" or "No" to confirmation prompt)
    lowered_cmd = sanitized_prompt.lower().strip()
    ticket_mgr = get_ticket_manager()

    if lowered_cmd in ("yes", "y", "confirm", "proceed", "yes, please", "do it"):
        pending_ticket = ticket_mgr.get_latest_pending_for_user(current_user.id)
        if pending_ticket:
            exec_svc = ConfirmationExecutionService(session)
            client_ip = request.client.host if request.client else None
            try:
                res = await exec_svc.execute_ticket(
                    ticket_id=pending_ticket.ticket_id,
                    actor=current_user,
                    client_ip=client_ip,
                )
                msg = res.get("message", "Action completed successfully.")
                await state_mgr.append_message(user_id=current_user.id, role="user", content=payload.prompt)
                await state_mgr.append_message(user_id=current_user.id, role="assistant", content=msg)
                return AIChatResponse(
                    message=msg,
                    role=Roles.SUPER_ADMIN.value,
                    tool_calls=[{"tool": pending_ticket.action_name, "result": res}],
                    success=True,
                )
            except Exception as exc:
                err_msg = f"Operation failed: {str(exc)}"
                return AIChatResponse(
                    message=err_msg,
                    role=Roles.SUPER_ADMIN.value,
                    success=False,
                )

    if lowered_cmd in ("no", "n", "cancel", "abort", "stop", "nevermind", "no, cancel"):
        cancelled_ticket = ticket_mgr.cancel_pending_for_user(current_user.id)
        if cancelled_ticket:
            action_name = cancelled_ticket.action_name
            cancel_msg = "Synchronization cancelled." if "sync" in action_name else "Operation cancelled."
            await state_mgr.append_message(user_id=current_user.id, role="user", content=payload.prompt)
            await state_mgr.append_message(user_id=current_user.id, role="assistant", content=cancel_msg)
            return AIChatResponse(
                message=cancel_msg,
                role=Roles.SUPER_ADMIN.value,
                success=True,
            )

    # Convert to standard role/content list for agent
    formatted_history = [
        {"role": item["role"], "content": item["content"]}
        for item in recent_history
        if item.get("role") in ("user", "assistant")
    ]

    client_ip = request.client.host if request.client else None
    request_id = request.headers.get("x-request-id")

    # 3. Instantiate Role-Bound Agent
    agent = create_role_agent(
        user=current_user,
        session=session,
        client_ip=client_ip,
        request_id=request_id,
    )

    # 4. Handle Streaming vs Synchronous Turn
    if payload.stream:
        return _handle_chat_stream(
            agent=agent,
            prompt=sanitized_prompt,
            history=formatted_history,
            current_user=current_user,
            state_mgr=state_mgr,
        )

    # Synchronous turn
    turn_response = await agent.execute_turn(
        prompt=sanitized_prompt,
        conversation_history=formatted_history,
    )

    # 5. Extract draft assessments created during execution
    draft_assessments: list[dict[str, Any]] = []
    for tc in turn_response.tool_calls_made:
        res = tc.get("result")
        if tc.get("tool") == "create_assessment_draft" and isinstance(res, dict) and res.get("success"):
            draft_assessments.append(res)

    # 6. Persist Conversation Turn in Database
    try:
        await state_mgr.append_message(
            user_id=current_user.id,
            role="user",
            content=payload.prompt,
        )
        await state_mgr.append_message(
            user_id=current_user.id,
            role="assistant",
            content=turn_response.text,
            tool_calls=turn_response.tool_calls_made or None,
        )
    except Exception as exc:
        logger.warning("Failed to persist AI conversation turn: %s", exc)

    return AIChatResponse(
        message=turn_response.text,
        role=turn_response.role,
        tool_calls=turn_response.tool_calls_made,
        draft_assessments=draft_assessments,
        confirmation_ticket=turn_response.confirmation_ticket,
        success=turn_response.success,
    )


def _handle_chat_stream(
    *,
    agent: Any,
    prompt: str,
    history: list[dict[str, str]],
    current_user: User,
    state_mgr: ConversationStateManager,
) -> StreamingResponse:
    """Stream AI agent response via Server-Sent Events (SSE)."""

    async def sse_generator() -> AsyncIterator[bytes]:
        try:
            # Yield initial status
            yield f"data: {json.dumps({'type': 'status', 'content': 'Analyzing intent and planning actions...'})}\n\n".encode()

            turn_response = await agent.execute_turn(
                prompt=prompt,
                conversation_history=history,
            )

            # Yield tool calls notification if any occurred
            if turn_response.tool_calls_made:
                for tc in turn_response.tool_calls_made:
                    yield f"data: {json.dumps({'type': 'tool', 'tool': tc.get('tool'), 'result': tc.get('result')})}\n\n".encode()

            # Stream message chunks
            full_text = turn_response.text
            words = full_text.split(" ")
            chunk = []
            for word in words:
                chunk.append(word)
                if len(chunk) >= 4:
                    yield f"data: {json.dumps({'type': 'delta', 'delta': ' '.join(chunk) + ' '})}\n\n".encode()
                    chunk = []
            if chunk:
                yield f"data: {json.dumps({'type': 'delta', 'delta': ' '.join(chunk)})}\n\n".encode()

            draft_assessments: list[dict[str, Any]] = []
            for tc in turn_response.tool_calls_made:
                res = tc.get("result")
                if tc.get("tool") == "create_assessment_draft" and isinstance(res, dict) and res.get("success"):
                    draft_assessments.append(res)

            # Persist state
            try:
                await state_mgr.append_message(
                    user_id=current_user.id,
                    role="user",
                    content=prompt,
                )
                await state_mgr.append_message(
                    user_id=current_user.id,
                    role="assistant",
                    content=turn_response.text,
                    tool_calls=turn_response.tool_calls_made or None,
                )
            except Exception as exc:
                logger.warning("Stream state persistence failed: %s", exc)

            # Yield done payload
            done_payload = {
                "type": "done",
                "message": turn_response.text,
                "role": turn_response.role,
                "tool_calls": turn_response.tool_calls_made,
                "draft_assessments": draft_assessments,
                "confirmation_ticket": turn_response.confirmation_ticket,
                "success": turn_response.success,
            }
            yield f"data: {json.dumps(done_payload)}\n\n".encode()
        except Exception as exc:
            logger.error("SSE stream error: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n".encode()

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(sse_generator(), headers=headers)


# =============================================================================
# CONFIRMATION TICKETS
# =============================================================================


@router.post(
    "/tickets/publish-assessment",
    response_model=ConfirmationTicketResponse,
    summary="Generate a confirmation ticket for publishing an assessment",
)
async def create_publish_assessment_ticket(
    payload: CreatePublishAssessmentTicketRequest,
    current_user: CurrentUser,
    session: DBSession,
) -> ConfirmationTicketResponse:
    """Generate a cryptographically fingerprinted ticket to publish a draft assessment."""
    held_perms = SecurityPolicyEngine.caller_permissions(current_user)
    if "quiz.publish" not in held_perms and "assignment.publish" not in held_perms and "institution.view_all" not in held_perms:
        raise AuthorizationError("You do not hold permission to publish assessments.")

    # 1. Resolve Quiz
    try:
        quiz_uuid = uuid.UUID(payload.quiz_id)
        stmt = select(Quiz).where(Quiz.public_id == quiz_uuid)
    except ValueError:
        stmt = select(Quiz).where(Quiz.public_id == payload.quiz_id)

    quiz = (await session.execute(stmt)).scalar_one_or_none()
    if not quiz:
        raise NotFoundError(f"Assessment '{payload.quiz_id}' not found.")

    if quiz.is_published:
        raise ConflictError(f"Assessment '{quiz.title}' is already published.")

    # Check question count
    quiz_svc = QuizService(session)
    q_count, _ = await quiz_svc.quizzes.question_stats(quiz.id)
    if q_count == 0:
        raise ConflictError("A quiz with no questions cannot be published.")

    # 2. Count affected records (enrolled students)
    affected_count = 0
    if quiz.batch_id:
        count_stmt = select(func.count(Enrollments.enrollment_id)).where(
            Enrollments.batch_id == quiz.batch_id,
            Enrollments.status == EnrollmentStatus.CONFIRMED,
        )
        affected_count = (await session.execute(count_stmt)).scalar() or 0
    elif quiz.course_id:
        from backend.models.batch import Batch
        count_stmt = (
            select(func.count(Enrollments.enrollment_id))
            .join(Batch, Batch.id == Enrollments.batch_id)
            .where(
                Batch.course_id == quiz.course_id,
                Enrollments.status == EnrollmentStatus.CONFIRMED,
            )
        )
        affected_count = (await session.execute(count_stmt)).scalar() or 0

    # 3. Create ticket
    ticket_mgr = get_ticket_manager()
    params = {
        "assessment_id": str(quiz.public_id),
        "quiz_id": str(quiz.public_id),
        "title": quiz.title,
    }
    summary = (
        f"Publish assessment '{quiz.title}' ({q_count} questions) to "
        f"{affected_count} enrolled student(s)."
    )

    ticket = ticket_mgr.create_ticket(
        action_name="publish_assessment",
        actor_user_id=current_user.id,
        actor_public_id=str(current_user.public_id),
        parameters=params,
        affected_records_count=affected_count,
        preview_summary=summary,
    )

    return ConfirmationTicketResponse(
        ticket_id=ticket.ticket_id,
        action_name=ticket.action_name,
        parameters=ticket.parameters,
        parameters_hash=ticket.parameters_hash,
        affected_records_count=ticket.affected_records_count,
        preview_summary=ticket.preview_summary,
        expires_at=ticket.expires_at.isoformat(),
        status=ticket.status.value,
    )


@router.post(
    "/confirm",
    response_model=ConfirmationExecuteResponse,
    summary="Confirm and execute an action approval ticket",
)
async def confirm_action_ticket(
    payload: ConfirmationExecuteRequest,
    current_user: CurrentUser,
    session: DBSession,
    request: Request,
) -> ConfirmationExecuteResponse:
    """Execute a previously staged action approval ticket under two-phase verification."""
    client_ip = request.client.host if request.client else None
    exec_svc = ConfirmationExecutionService(session)

    result = await exec_svc.execute_ticket(
        ticket_id=payload.ticket_id,
        actor=current_user,
        provided_parameters=payload.parameters or None,
        client_ip=client_ip,
    )

    return ConfirmationExecuteResponse(
        success=True,
        result=result,
    )


# =============================================================================
# AUDIO TRANSCRIPTION
# =============================================================================


@router.post(
    "/transcribe",
    response_model=AudioTranscriptionResponse,
    summary="Transcribe voice audio to text using Whisper",
)
async def transcribe_audio(
    current_user: CurrentUser,
    file: UploadFile = File(...),
) -> AudioTranscriptionResponse:
    """Convert spoken voice audio into text using configured transcription model."""
    content = await file.read()
    if not content:
        raise ValidationError("Audio file is empty.")

    filename = file.filename or "recording.webm"
    client = get_openai_client()
    text = await client.transcribe_audio(audio_file=(filename, content))
    return AudioTranscriptionResponse(text=text)


# =============================================================================
# CONVERSATION MEMORY & DATA SUBJECT ERASURE
# =============================================================================


@router.get(
    "/history",
    response_model=ConversationHistoryResponse,
    summary="Get user-scoped AI conversation history",
)
async def get_conversation_history(
    current_user: CurrentUser,
    session: DBSession,
    limit: int = Query(default=50, ge=1, le=100),
) -> ConversationHistoryResponse:
    """Retrieve chronologically ordered conversation history for the authenticated caller."""
    state_mgr = ConversationStateManager(session)
    messages = await state_mgr.get_recent_history(user_id=current_user.id, limit=limit)
    items = [
        ConversationMessageItem(
            message_id=m["message_id"],
            role=m["role"],
            content=m["content"],
            tool_calls=m.get("tool_calls"),
            created_at=m.get("created_at"),
        )
        for m in messages
    ]
    return ConversationHistoryResponse(messages=items, total=len(items))


@router.delete(
    "/history",
    response_model=ClearHistoryResponse,
    summary="Permanently delete user's AI conversation history (Subject Erasure)",
)
async def clear_conversation_history(
    current_user: CurrentUser,
    session: DBSession,
) -> ClearHistoryResponse:
    """Permanently delete all stored AI conversation messages for the caller."""
    state_mgr = ConversationStateManager(session)
    deleted_count = await state_mgr.clear_history(user_id=current_user.id)
    return ClearHistoryResponse(success=True, deleted_count=deleted_count)
