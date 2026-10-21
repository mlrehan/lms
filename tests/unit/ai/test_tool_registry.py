"""Unit tests for Standardized Tool Registry and Dispatcher."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.ai.security import RiskLevel, ToolPolicy
from backend.ai.tools.registry import (
    ToolDefinition,
    ToolExecutionContext,
    ToolRegistry,
    get_tool_registry,
)
from backend.core.errors import AuthorizationError, NotFoundError
from backend.models.identity.permission import Permission
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.utils.enums import Roles


def make_user(*, role_name: str, perms: list[str]) -> User:
    u = User(id=1, username="testuser", slug="testuser", hashed_password="pw")
    r = Role(id=1, name=role_name)
    r.permissions = [Permission(id=i + 1, name=p) for i, p in enumerate(perms)]
    u.roles = [r]
    return u


def test_standard_tool_registry_populated():
    reg = get_tool_registry()
    assert reg.get("create_assessment_draft") is not None
    assert reg.get("get_my_schedule") is not None
    assert reg.get("get_attendance_summary") is not None
    assert reg.get("get_student_academic_summary") is not None
    assert reg.get("get_corporate_training_progress") is not None


def test_list_tools_for_caller_role_scoping():
    reg = get_tool_registry()

    tutor = make_user(
        role_name=Roles.TUTOR.value,
        perms=["quiz.create", "session.read", "attendance.read", "grade.read", "course.read"],
    )
    tutor_tools = [t.name for t in reg.list_tools_for_caller(tutor)]
    assert "create_assessment_draft" in tutor_tools
    assert "get_my_schedule" in tutor_tools
    assert "get_attendance_summary" in tutor_tools
    assert "get_corporate_training_progress" not in tutor_tools  # Corporate manager only!

    student = make_user(
        role_name=Roles.STUDENT.value,
        perms=["session.read", "attendance.read", "grade.read", "course.read"],
    )
    student_tools = [t.name for t in reg.list_tools_for_caller(student)]
    assert "create_assessment_draft" not in student_tools  # Denied to students!
    assert "get_my_schedule" in student_tools
    assert "get_attendance_summary" in student_tools


def test_to_openai_tools_formatting():
    reg = get_tool_registry()
    tools = [reg.get("get_my_schedule")]
    formatted = reg.to_openai_tools(tools)
    assert len(formatted) == 1
    assert formatted[0]["type"] == "function"
    assert formatted[0]["function"]["name"] == "get_my_schedule"
    assert "properties" in formatted[0]["function"]["parameters"]


def test_execute_tool_requires_confirmation_flow():
    async def run_test():
        reg = ToolRegistry()
        mock_handler = AsyncMock(return_value={"executed": True})
        risky_tool = ToolDefinition(
            name="publish_assessment_live",
            description="Publish assessment to live class",
            policy=ToolPolicy(
                name="publish_assessment_live",
                description="Publish",
                risk_level=RiskLevel.HIGH,
                requires_confirmation=True,
            ),
            parameters_schema={"type": "object", "properties": {}},
            handler=mock_handler,
        )
        reg.register(risky_tool)

        ctx = ToolExecutionContext(
            user=make_user(role_name=Roles.TUTOR.value, perms=[]),
            session=MagicMock(),
        )
        result = await reg.execute_tool(
            name="publish_assessment_live",
            arguments={"affected_count": 25, "preview_summary": "Publish to 25 students"},
            context=ctx,
        )

        assert result["status"] == "REQUIRES_CONFIRMATION"
        assert "confirmation_ticket_id" in result
        assert result["affected_records_count"] == 25
        # Handler should NOT have been executed autonomously
        mock_handler.assert_not_called()

    asyncio.run(run_test())
