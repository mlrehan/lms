"""Unit tests for Role-Bound Specialized Agents."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.ai.agents.base import AgentResponse, BaseAgent
from backend.ai.agents.corporate import CorporateManagerAgent
from backend.ai.agents.guardian import GuardianAgent
from backend.ai.agents.student import StudentAgent
from backend.ai.agents.superadmin import SuperAdminAgent
from backend.ai.agents.tutor import TutorAgent
from backend.ai.orchestrator import create_role_agent
from backend.models.identity.permission import Permission
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.utils.enums import Roles


def make_user(*, role_name: str) -> User:
    u = User(id=1, username="testuser", slug="testuser", hashed_password="pw", timezone="Europe/London")
    r = Role(id=1, name=role_name)
    u.roles = [r]
    return u


def test_create_role_agent_factory():
    session = MagicMock()

    tutor = make_user(role_name=Roles.TUTOR.value)
    agent_tutor = create_role_agent(user=tutor, session=session)
    assert isinstance(agent_tutor, TutorAgent)
    assert agent_tutor.role_name == Roles.TUTOR.value

    student = make_user(role_name=Roles.STUDENT.value)
    agent_student = create_role_agent(user=student, session=session)
    assert isinstance(agent_student, StudentAgent)
    assert agent_student.role_name == Roles.STUDENT.value

    guardian = make_user(role_name=Roles.GUARDIAN.value)
    agent_guardian = create_role_agent(user=guardian, session=session)
    assert isinstance(agent_guardian, GuardianAgent)

    manager = make_user(role_name=Roles.CORPORATE_MANAGER.value)
    agent_manager = create_role_agent(user=manager, session=session)
    assert isinstance(agent_manager, CorporateManagerAgent)

    admin = make_user(role_name=Roles.SUPER_ADMIN.value)
    agent_admin = create_role_agent(user=admin, session=session)
    assert isinstance(agent_admin, SuperAdminAgent)


def test_effective_system_prompt_structure():
    user = make_user(role_name=Roles.TUTOR.value)
    agent = TutorAgent(user=user, session=MagicMock())
    prompt = agent.get_effective_system_prompt()

    assert "[CALLER CONTEXT]" in prompt
    assert "Username: testuser" in prompt
    assert "Europe/London" in prompt
    assert "TUTOR" in prompt
    assert "Never invent or hallucinate" in prompt


def test_agent_execute_turn_conversational_response():
    async def run_test():
        user = make_user(role_name=Roles.STUDENT.value)
        mock_client = MagicMock()

        # Mock OpenAI response
        mock_choice = MagicMock()
        mock_choice.message.tool_calls = None
        mock_choice.message.content = "Python list comprehensions allow concise loops."
        mock_response = MagicMock(choices=[mock_choice])

        mock_client.chat_completion = AsyncMock(return_value=mock_response)

        agent = StudentAgent(user=user, session=MagicMock(), client=mock_client)
        resp = await agent.execute_turn(prompt="How do list comprehensions work in Python?")

        assert resp.success is True
        assert resp.role == Roles.STUDENT.value
        assert "comprehensions" in resp.text
        assert len(resp.tool_calls_made) == 0

    asyncio.run(run_test())

