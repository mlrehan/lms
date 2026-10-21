"""Unit tests for AI Orchestrator & Supervisor."""

import asyncio
import pytest
from datetime import UTC, datetime

from backend.ai.orchestrator import AIOrchestrator, UserIntent
from backend.models.identity.permission import Permission
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.utils.enums import Roles


def make_test_user(*, role_name: str) -> User:
    user = User(
        id=1,
        username="alice",
        slug="alice",
        hashed_password="pw",
        timezone="Europe/London",
    )
    role = Role(id=1, name=role_name)
    user.roles = [role]
    return user


def test_resolve_caller_primary_role():
    superadmin = make_test_user(role_name=Roles.SUPER_ADMIN.value)
    assert AIOrchestrator.resolve_caller_primary_role(superadmin) == Roles.SUPER_ADMIN.value

    tutor = make_test_user(role_name=Roles.TUTOR.value)
    assert AIOrchestrator.resolve_caller_primary_role(tutor) == Roles.TUTOR.value

    student = make_test_user(role_name=Roles.STUDENT.value)
    assert AIOrchestrator.resolve_caller_primary_role(student) == Roles.STUDENT.value


def test_resolve_date_window():
    start, end = AIOrchestrator.resolve_date_window(phrase="today", user_timezone="UTC")
    assert end > start
    assert (end - start).total_seconds() == 86400  # exactly 24 hours

    start_w, end_w = AIOrchestrator.resolve_date_window(phrase="this week", user_timezone="Europe/London")
    assert end_w > start_w
    assert (end_w - start_w).days == 7


def test_classify_intent():
    async def run_test():
        orchestrator = AIOrchestrator()
        tutor = make_test_user(role_name=Roles.TUTOR.value)

        res_quiz = await orchestrator.classify_intent(
            prompt="Generate a 5-question quiz for my Python class",
            caller=tutor,
        )
        assert res_quiz.intent == UserIntent.TEACHING_ASSESSMENT
        assert res_quiz.target_role == Roles.TUTOR.value

        res_sched = await orchestrator.classify_intent(
            prompt="What classes do I have scheduled for today?",
            caller=tutor,
        )
        assert res_sched.intent == UserIntent.SCHEDULE_ATTENDANCE

        res_doc = await orchestrator.classify_intent(
            prompt="Search for lecture sheets on database normalization",
            caller=tutor,
        )
        assert res_doc.intent == UserIntent.DOCUMENT_SEARCH

        res_concept = await orchestrator.classify_intent(
            prompt="Explain the difference between inner and outer joins",
            caller=tutor,
        )
        assert res_concept.intent == UserIntent.STUDY_CONCEPT

    asyncio.run(run_test())

