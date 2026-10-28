"""Unit tests for AI Streaming and Action Execution Tools."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest

from backend.ai.agents.base import AgentResponse, BaseAgent
from backend.ai.tools.academic_tools import handle_publish_assessment
from backend.ai.tools.attendance_tools import (
    handle_manage_batch_session,
    handle_mark_session_attendance,
)
from backend.ai.tools.registry import BOUND_PREFIX, ToolExecutionContext
from backend.ai.tools.reporting_tools import handle_generate_institution_report
from backend.models.assignment import Assignment
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.core.errors import AuthorizationError
from backend.core.permissions import ROLE_PERMISSIONS
from backend.models.identity.permission import Permission
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.quiz import Quiz
from backend.utils.enums import AssessmentScope, AssessmentState, AttendanceStatus, Roles


def make_test_user(role_name: str = Roles.TUTOR.value) -> User:
    """A user holding the role's real grants from the permission catalogue."""
    role = Role(id=3, name=role_name, description=role_name)
    role.permissions = [
        Permission(id=i, name=name)
        for i, name in enumerate(sorted(ROLE_PERMISSIONS[role_name]), start=1)
    ]
    user = User(
        id=777,
        public_id=uuid.uuid4(),
        username="test.tutor",
        email="test.tutor@example.com",
        first_name="Test",
        last_name="Tutor",
        timezone="UTC",
    )
    user.roles = [role]
    return user


def test_agent_execute_turn_stream():
    """Verify that execute_turn_stream yields status, deltas, and done event."""
    async def run():
        user = make_test_user()
        session = AsyncMock()
        mock_client = AsyncMock()

        # Mock streaming completion
        async def mock_stream_tokens(*args, **kwargs):
            for token in ["Hello", " ", "Tutor", "!"]:
                yield token

        mock_client.stream_chat_completion = mock_stream_tokens

        # Mock chat completion for first turn
        mock_choice = MagicMock()
        mock_choice.message.tool_calls = None
        mock_choice.message.content = "Hello Tutor!"
        mock_choice.message.model_dump.return_value = {"role": "assistant", "content": "Hello Tutor!"}
        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]
        mock_client.chat_completion = AsyncMock(return_value=mock_completion)

        agent = BaseAgent(user=user, session=session, client=mock_client)

        events = []
        async for event in agent.execute_turn_stream(prompt="Hello"):
            events.append(event)

        types = [e.get("type") for e in events]
        assert "status" in types
        assert "delta" in types
        assert "done" in types

        done_event = next(e for e in events if e.get("type") == "done")
        assert done_event["success"] is True
        assert "Hello Tutor!" in done_event["message"]

    asyncio.run(run())


def test_publish_assessment_quiz():
    """Verify handle_publish_assessment publishes a quiz."""
    async def run():
        user = make_test_user()
        session = AsyncMock()
        ctx = ToolExecutionContext(user=user, session=session)

        quiz_uuid = uuid.uuid4()
        mock_quiz = Quiz(
            id=12,
            public_id=quiz_uuid,
            title="Python Quiz",
            course_id=101,
            is_published=False,
        )

        with patch("backend.ai.tools.academic_tools._resolve_for_publish", new_callable=AsyncMock, return_value=mock_quiz), \
             patch("backend.services.quiz_service.QuizService.get", new_callable=AsyncMock, return_value=mock_quiz), \
             patch("backend.services.quiz_service.QuizService.set_published", new_callable=AsyncMock) as mock_pub:
            mock_pub.return_value = mock_quiz
            mock_quiz.is_published = True

            res = await handle_publish_assessment(
                {
                    "assessment_type": "quiz",
                    "assessment_id": str(quiz_uuid),
                    f"{BOUND_PREFIX}assessment_public_id": str(quiz_uuid),
                },
                ctx,
            )

            assert res["success"] is True
            assert res["is_published"] is True
            assert "published" in res["message"].lower()
            mock_pub.assert_awaited_once_with(quiz_uuid, True, actor=user)

    asyncio.run(run())


def test_publish_examination_needs_exam_publish():
    """The console's exam publish route needs `exam.publish`; so does the tool."""
    async def run():
        user = make_test_user(Roles.TUTOR.value)
        user.roles[0].permissions = [p for p in user.roles[0].permissions if p.name != "exam.publish"]
        ctx = ToolExecutionContext(user=user, session=AsyncMock())
        with patch("backend.services.exam_service.ExamService.set_published", new_callable=AsyncMock) as mock_pub:
            with pytest.raises(AuthorizationError):
                await handle_publish_assessment(
                    {"assessment_type": "examination", "assessment_id": str(uuid.uuid4())},
                    ctx,
                )
            mock_pub.assert_not_awaited()

    asyncio.run(run())


def test_manage_batch_session_cancel():
    """An administrator cancels the session that was confirmed, with its reason."""
    async def run():
        user = make_test_user(Roles.ADMIN.value)
        session = AsyncMock()
        ctx = ToolExecutionContext(user=user, session=session)

        sess_uuid = uuid.uuid4()
        mock_session = BatchSession(
            id=99,
            public_id=sess_uuid,
            batch_id=1,
            tutor_id=user.id,
            session_start_time=datetime.now(UTC),
        )

        with patch("backend.services.session_service.SessionService.get", new_callable=AsyncMock, return_value=mock_session):
            res = await handle_manage_batch_session(
                {
                    "action": "cancel",
                    "session_id": str(sess_uuid),
                    "cancelled_reason": "Weather alert",
                    f"{BOUND_PREFIX}session_public_id": str(sess_uuid),
                },
                ctx,
            )
            assert res["success"] is True
            assert res["action"] == "cancel"
            assert mock_session.cancelled_at is not None
            assert mock_session.cancelled_reason == "Weather alert"

    asyncio.run(run())


def test_tutor_cannot_cancel_or_schedule_sessions_through_the_assistant():
    """Tutors hold `session.update` only; scheduling and cancelling are refused."""
    async def run():
        user = make_test_user(Roles.TUTOR.value)
        ctx = ToolExecutionContext(user=user, session=AsyncMock())
        with patch("backend.services.session_service.SessionService.get", new_callable=AsyncMock) as mock_get:
            for action in ("cancel", "create"):
                with pytest.raises(AuthorizationError):
                    await handle_manage_batch_session(
                        {"action": action, "session_id": str(uuid.uuid4()), "batch_code": "B1"},
                        ctx,
                    )
            mock_get.assert_not_awaited()

    asyncio.run(run())
