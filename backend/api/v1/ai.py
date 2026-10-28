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
from backend.ai.config import get_ai_settings
from backend.ai.orchestrator import AIOrchestrator, create_role_agent
from backend.ai.rate_limit import get_request_limiter
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
from backend.db.dependencies import DBSession, commit_before_responding
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
    # 0. Per-person request limit, before any work (including refused prompts,
    # which still cost a guard pass and an audit row).
    get_request_limiter().check(
        user_id=current_user.id,
        bucket="chat",
        limit=get_ai_settings().chat_requests_per_minute,
    )

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
    try:
        recent_history = await state_mgr.get_recent_history(user_id=current_user.id, limit=10)
    except Exception as exc:
        logger.warning("Recent conversation history retrieval failed: %s", exc)
        recent_history = []

    # Typed confirmation. The confirmation card's buttons name their ticket and
    # go through POST /ai/confirm; this path is for someone who types "yes"
    # instead. It may act only when that word is unambiguous: with two actions
    # awaiting confirmation, "yes" does not say which, and guessing "the
    # newest" would confirm something the person may not have been looking at.
    lowered_cmd = sanitized_prompt.lower().strip()
    ticket_mgr = get_ticket_manager()
    reply_role = AIOrchestrator.resolve_caller_primary_role(current_user)

    async def quick_reply(message: str, *, success: bool, tool_calls: list[dict[str, Any]] | None = None) -> Any:
        await state_mgr.append_message(user_id=current_user.id, role="user", content=payload.prompt)
        await state_mgr.append_message(user_id=current_user.id, role="assistant", content=message)
        if payload.stream:
            async def one_frame() -> AsyncIterator[bytes]:
                yield b": keep-alive\n\n"
                frame = {
                    "type": "done" if success else "error",
                    "message": message,
                    "role": reply_role,
                    "tool_calls": tool_calls or [],
                    "success": success,
                }
                yield f"data: {json.dumps(frame, default=str)}\n\n".encode("utf-8")
            return StreamingResponse(one_frame(), headers={"Content-Type": "text/event-stream; charset=utf-8"})
        return AIChatResponse(message=message, role=reply_role, tool_calls=tool_calls or [], success=success)

    if lowered_cmd in ("yes", "y", "confirm", "proceed", "yes, please", "do it"):
        pending = await ticket_mgr.pending_for_user(current_user.id)
        if len(pending) > 1:
            return await quick_reply(
                f"{len(pending)} actions are waiting for your confirmation. "
                "Use the Confirm button on the one you mean.",
                success=False,
            )
        if pending:
            ticket = pending[0]
            client_ip = request.client.host if request.client else None
            try:
                res = await ConfirmationExecutionService(session).execute_ticket(
                    ticket_id=ticket.ticket_id,
                    actor=current_user,
                    client_ip=client_ip,
                )
                await commit_before_responding(session)
            except AppError as exc:
                return await quick_reply(f"The action was not carried out: {exc.message}", success=False)
            succeeded = bool(res.get("success", True))
            return await quick_reply(
                res.get("message") or ("Done." if succeeded else "The action did not complete."),
                success=succeeded,
                tool_calls=[{"tool": ticket.action_name, "result": res}],
            )

    if lowered_cmd in ("no", "n", "cancel", "abort", "stop", "nevermind", "no, cancel"):
        cancelled = await ticket_mgr.cancel_pending_for_user(current_user.id)
        if cancelled:
            noun = "action" if len(cancelled) == 1 else f"{len(cancelled)} actions"
            return await quick_reply(f"Cancelled. Nothing was changed by the {noun} you declined.", success=True)

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
            request=request,
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
        db = getattr(getattr(request, "app", None), "state", None)
        db_mgr = getattr(db, "db", None) if db else None
        if (
            db_mgr
            and hasattr(db_mgr, "session_factory")
            and not str(type(db_mgr)).startswith("<class 'unittest.mock")
        ):
            async with db_mgr.session_factory() as persist_session:
                async with persist_session.begin():
                    persist_mgr = ConversationStateManager(persist_session)
                    await persist_mgr.append_message(
                        user_id=current_user.id,
                        role="user",
                        content=payload.prompt,
                    )
                    await persist_mgr.append_message(
                        user_id=current_user.id,
                        role="assistant",
                        content=turn_response.text,
                        tool_calls=turn_response.tool_calls_made or None,
                    )
        else:
            persist_mgr = ConversationStateManager(session)
            await persist_mgr.append_message(
                user_id=current_user.id,
                role="user",
                content=payload.prompt,
            )
            await persist_mgr.append_message(
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
    request: Request,
    state_mgr: ConversationStateManager | None = None,
) -> StreamingResponse:
    """Stream AI agent response via Server-Sent Events (SSE)."""

    async def sse_generator() -> AsyncIterator[bytes]:
        full_message = ""
        tools_executed: list[dict[str, Any]] = []

        try:
            # Yield initial keep-alive / stream open marker
            yield b": keep-alive\n\n"

            async for event in agent.execute_turn_stream(
                prompt=prompt,
                conversation_history=history,
            ):
                yield f"data: {json.dumps(event)}\n\n".encode("utf-8")

                if event.get("type") == "done":
                    full_message = event.get("message", "")
                    tools_executed = event.get("tool_calls", [])

            # Persist turn in database upon completion using dedicated clean session
            if full_message:
                try:
                    db = getattr(getattr(request, "app", None), "state", None)
                    db_mgr = getattr(db, "db", None) if db else None
                    if (
                        db_mgr
                        and hasattr(db_mgr, "session_factory")
                        and not str(type(db_mgr)).startswith("<class 'unittest.mock")
                    ):
                        async with db_mgr.session_factory() as persist_session:
                            async with persist_session.begin():
                                persist_mgr = ConversationStateManager(persist_session)
                                await persist_mgr.append_message(
                                    user_id=current_user.id,
                                    role="user",
                                    content=prompt,
                                )
                                await persist_mgr.append_message(
                                    user_id=current_user.id,
                                    role="assistant",
                                    content=full_message,
                                    tool_calls=tools_executed or None,
                                )
                    elif state_mgr:
                        await state_mgr.append_message(
                            user_id=current_user.id,
                            role="user",
                            content=prompt,
                        )
                        await state_mgr.append_message(
                            user_id=current_user.id,
                            role="assistant",
                            content=full_message,
                            tool_calls=tools_executed or None,
                        )
                except Exception as exc:
                    logger.warning("Stream state persistence failed: %s", exc)

        except Exception as exc:
            logger.error("SSE stream error: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc), 'success': False})}\n\n".encode("utf-8")

    headers = {
        "Content-Type": "text/event-stream; charset=utf-8",
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

    ticket = await ticket_mgr.create_ticket(
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
    # A confirmed action is reported as done, so it must be done -- committed --
    # before the person is told so (see commit_before_responding).
    await commit_before_responding(session)

    return ConfirmationExecuteResponse(
        # The tool's own verdict, not an unconditional True: a sync that found
        # one already running did nothing, and must not read as success.
        success=bool(result.get("success", True)),
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
    settings = get_ai_settings()
    get_request_limiter().check(
        user_id=current_user.id,
        bucket="transcribe",
        limit=settings.transcribe_requests_per_minute,
    )

    # Browsers label a MediaRecorder capture `audio/webm` or, in some builds,
    # `video/webm`; anything else is not a voice note and is not forwarded.
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if not (content_type.startswith("audio/") or content_type == "video/webm"):
        raise ValidationError("Only audio recordings can be transcribed.")

    # Read one byte past the cap rather than the whole body, so an oversized
    # upload is refused without first being held in memory in full.
    content = await file.read(settings.max_audio_bytes + 1)
    if len(content) > settings.max_audio_bytes:
        raise ValidationError(
            f"Audio is larger than {settings.max_audio_bytes // (1024 * 1024)} MB and was not transcribed."
        )
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
