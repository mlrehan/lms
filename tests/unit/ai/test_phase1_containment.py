"""Phase 1 containment of the AI assistants.

Each test pins one guard added in that pass, and each was checked by breaking
the guard and watching the test fail -- a negative test that cannot fail
proves nothing.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile

from backend.ai.agents.base import BaseAgent
from backend.ai.rate_limit import RequestLimiter
from backend.ai.tools.academic_tools import handle_suggest_submission_grade
from backend.ai.tools.registry import ToolExecutionContext, get_tool_registry
from backend.ai.workflows.confirmation_service import ConfirmationExecutionService
from backend.api.v1.ai import ConfirmationExecuteRequest, confirm_action_ticket, transcribe_audio
from backend.core.errors import AuthorizationError, RateLimitError, ValidationError
from backend.core.permissions import ROLE_PERMISSIONS
from backend.models.identity.permission import Permission
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.utils.enums import Roles


def make_user(role_name: str, *, user_id: int = 4242) -> User:
    """A user carrying the role's real grants from the permission catalogue."""
    role = Role(id=1, name=role_name)
    role.permissions = [
        Permission(id=i, name=name)
        for i, name in enumerate(sorted(ROLE_PERMISSIONS[role_name]), start=1)
    ]
    user = User(
        id=user_id,
        public_id=uuid.uuid4(),
        username=f"{role_name.lower()}@example.com",
        first_name="Test",
        last_name=role_name.title(),
        timezone="UTC",
    )
    user.roles = [role]
    return user


class _Agent(BaseAgent):
    role_name = "TEST"
    system_prompt = "You are a test assistant."


# --------------------------------------------------------------------------
# The SQL instructions reach only the Super Admin's prompt
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role_name",
    [Roles.STUDENT.value, Roles.TUTOR.value, Roles.CORPORATE_MANAGER.value, Roles.ADMIN.value],
)
def test_non_super_admin_prompts_carry_no_sql_instructions(role_name):
    agent = _Agent(user=make_user(role_name), session=AsyncMock(), client=MagicMock())
    prompt = agent.get_effective_system_prompt()
    assert "execute_database_query" not in prompt
    assert "Database User ID" not in prompt


def test_super_admin_prompt_carries_the_sql_instructions():
    agent = _Agent(user=make_user(Roles.SUPER_ADMIN.value), session=AsyncMock(), client=MagicMock())
    assert "execute_database_query" in agent.get_effective_system_prompt()


# --------------------------------------------------------------------------
# Confirming a ticket re-checks authorization
# --------------------------------------------------------------------------


def test_a_ticket_does_not_outlive_the_role_that_created_it():
    """Lose the role between preview and confirmation, and the action is refused."""
    async def run():
        admin = make_user(Roles.SUPER_ADMIN.value)
        ctx = ToolExecutionContext(user=admin, session=AsyncMock())
        staged = await get_tool_registry().execute_tool(name="sync_all_data", arguments={}, context=ctx)
        assert staged["status"] == "REQUIRES_CONFIRMATION"

        # Same account, demoted to a student before saying yes.
        demoted = make_user(Roles.STUDENT.value, user_id=admin.id)
        with patch("backend.services.sync_pipeline_service.SyncPipelineService.start", new_callable=AsyncMock) as start:
            with pytest.raises(AuthorizationError):
                await ConfirmationExecutionService(AsyncMock()).execute_ticket(
                    ticket_id=staged["ticket_id"], actor=demoted
                )
            start.assert_not_awaited()

    asyncio.run(run())


def test_the_registry_itself_reauthorizes_on_confirmation():
    """Not left to the handler: a tool whose handler checks nothing is still
    refused on confirmation once the caller no longer holds its permission."""
    from backend.ai.security import RiskLevel, ToolPolicy
    from backend.ai.tools.registry import ToolDefinition, ToolRegistry

    async def run():
        handler = AsyncMock(return_value={"success": True})
        registry = ToolRegistry()
        registry.register(ToolDefinition(
            name="unguarded_write",
            description="test",
            policy=ToolPolicy(
                name="unguarded_write",
                description="test",
                required_permissions=("user.update",),
                risk_level=RiskLevel.HIGH,
                requires_confirmation=True,
            ),
            parameters_schema={"type": "object", "properties": {}},
            handler=handler,
        ))
        admin = make_user(Roles.SUPER_ADMIN.value)
        staged = await registry.execute_tool(
            name="unguarded_write", arguments={}, context=ToolExecutionContext(user=admin, session=AsyncMock())
        )
        demoted = make_user(Roles.STUDENT.value, user_id=admin.id)
        with patch("backend.ai.tools.registry.get_tool_registry", return_value=registry):
            with pytest.raises(AuthorizationError):
                await ConfirmationExecutionService(AsyncMock()).execute_ticket(
                    ticket_id=staged["ticket_id"], actor=demoted
                )
        handler.assert_not_awaited()

    asyncio.run(run())


def test_the_model_cannot_supply_server_bound_parameters():
    """`_bound_*` keys are the server's. Sent by the model, they never reach a
    handler -- even for a tool that is not staged and has no preview of its own
    to overwrite them."""
    from backend.ai.security import RiskLevel, ToolPolicy
    from backend.ai.tools.registry import BOUND_PREFIX, ToolDefinition, ToolRegistry

    async def run():
        handler = AsyncMock(return_value={"success": True})
        registry = ToolRegistry()
        registry.register(ToolDefinition(
            name="plain_tool",
            description="test",
            policy=ToolPolicy(name="plain_tool", description="test", risk_level=RiskLevel.LOW),
            parameters_schema={"type": "object", "properties": {}},
            handler=handler,
        ))
        await registry.execute_tool(
            name="plain_tool",
            arguments={"keep": 1, f"{BOUND_PREFIX}target_id": "forged"},
            context=ToolExecutionContext(user=make_user(Roles.TUTOR.value), session=AsyncMock()),
        )
        passed = handler.await_args.args[0]
        assert passed == {"keep": 1}

    asyncio.run(run())


def test_confirm_endpoint_reports_the_actions_own_verdict_and_commits_first():
    """A confirmed action that did nothing is not reported as success, and the
    write is committed before the response says it happened."""
    async def run():
        admin = make_user(Roles.SUPER_ADMIN.value)
        session = AsyncMock()
        request = MagicMock()
        request.client.host = "127.0.0.1"
        with patch(
            "backend.api.v1.ai.ConfirmationExecutionService.execute_ticket",
            new_callable=AsyncMock,
            return_value={"success": False, "status": "RUNNING", "message": "already running"},
        ):
            resp = await confirm_action_ticket(
                payload=ConfirmationExecuteRequest(ticket_id="act_x"),
                current_user=admin,
                session=session,
                request=request,
            )
        assert resp.success is False
        session.commit.assert_awaited()

    asyncio.run(run())


# --------------------------------------------------------------------------
# Grade suggestions never default and never record
# --------------------------------------------------------------------------


def _grading_context():
    tutor = make_user(Roles.TUTOR.value)
    session = AsyncMock()
    sub, asmt, student = MagicMock(), MagicMock(), MagicMock()
    sub.public_id = uuid.uuid4()
    asmt.course_id = 1
    asmt.max_score = 100
    student.first_name, student.last_name = "Ana", "Lee"
    student.username = "ana.lee@example.com"
    result = MagicMock()
    result.first.return_value = (sub, asmt, student)
    session.execute.return_value = result
    return ToolExecutionContext(user=tutor, session=session), sub, student


def test_a_missing_suggested_grade_is_refused_not_defaulted_to_full_marks():
    async def run():
        ctx, sub, _ = _grading_context()
        with patch("backend.services.scope.ScopeResolver.visible_course_ids", new_callable=AsyncMock) as vis:
            vis.return_value = MagicMock(allows=MagicMock(return_value=True))
            with pytest.raises(ValidationError):
                await handle_suggest_submission_grade({"submission_id": str(sub.public_id)}, ctx)

    asyncio.run(run())


def test_grade_suggestion_records_nothing_and_names_no_login():
    async def run():
        ctx, sub, student = _grading_context()
        with patch("backend.services.scope.ScopeResolver.visible_course_ids", new_callable=AsyncMock) as vis, \
             patch("backend.services.assignment_service.AssignmentService.grade", new_callable=AsyncMock) as grade:
            vis.return_value = MagicMock(allows=MagicMock(return_value=True))
            res = await handle_suggest_submission_grade(
                {"submission_id": str(sub.public_id), "suggested_grade": 70, "apply_immediately": True},
                ctx,
            )
            grade.assert_not_awaited()
        assert res["status"] == "PROPOSED_FOR_REVIEW"
        assert student.username not in str(res)

    asyncio.run(run())


# --------------------------------------------------------------------------
# Request limits
# --------------------------------------------------------------------------


def test_limiter_refuses_past_the_limit_and_recovers_after_the_window():
    now = [1000.0]
    limiter = RequestLimiter(clock=lambda: now[0])
    for _ in range(3):
        limiter.check(user_id=1, bucket="chat", limit=3)
    with pytest.raises(RateLimitError):
        limiter.check(user_id=1, bucket="chat", limit=3)

    # Another person, or another bucket, has its own window.
    limiter.check(user_id=2, bucket="chat", limit=3)
    limiter.check(user_id=1, bucket="transcribe", limit=3)

    now[0] += 61
    limiter.check(user_id=1, bucket="chat", limit=3)


def test_refused_requests_do_not_extend_the_lockout():
    now = [0.0]
    limiter = RequestLimiter(clock=lambda: now[0])
    limiter.check(user_id=1, bucket="chat", limit=1)
    for _ in range(10):
        now[0] += 5
        with pytest.raises(RateLimitError):
            limiter.check(user_id=1, bucket="chat", limit=1)
    now[0] = 61
    limiter.check(user_id=1, bucket="chat", limit=1)


def _upload(content: bytes, content_type: str) -> UploadFile:
    upload = MagicMock(spec=UploadFile)
    upload.content_type = content_type
    upload.filename = "voice.webm"

    async def read(size: int = -1) -> bytes:
        return content if size < 0 else content[:size]

    upload.read = read
    return upload


def test_transcription_refuses_non_audio_and_oversized_uploads():
    async def run():
        user = make_user(Roles.STUDENT.value, user_id=9001)
        settings = MagicMock(transcribe_requests_per_minute=100, max_audio_bytes=10)
        with patch("backend.api.v1.ai.get_ai_settings", return_value=settings), \
             patch("backend.api.v1.ai.get_openai_client") as client:
            with pytest.raises(ValidationError):
                await transcribe_audio(current_user=user, file=_upload(b"<html>", "text/html"))
            with pytest.raises(ValidationError):
                await transcribe_audio(current_user=user, file=_upload(b"x" * 11, "audio/webm"))
            client.assert_not_called()

    asyncio.run(run())


def test_transcription_is_rate_limited_per_person():
    async def run():
        user = make_user(Roles.STUDENT.value, user_id=9002)
        settings = MagicMock(transcribe_requests_per_minute=2, max_audio_bytes=1000)
        with patch("backend.api.v1.ai.get_ai_settings", return_value=settings), \
             patch("backend.api.v1.ai.get_request_limiter", return_value=RequestLimiter()), \
             patch("backend.api.v1.ai.get_openai_client") as factory:
            factory.return_value.transcribe_audio = AsyncMock(return_value="hello")
            for _ in range(2):
                await transcribe_audio(current_user=user, file=_upload(b"abc", "audio/webm"))
            with pytest.raises(RateLimitError):
                await transcribe_audio(current_user=user, file=_upload(b"abc", "audio/webm"))

    asyncio.run(run())
