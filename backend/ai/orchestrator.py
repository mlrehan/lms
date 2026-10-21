"""AI System Supervisor & Orchestration Core.

Coordinates intent resolution, role dispatch, natural-language entity parsing,
and response synthesis without ever bypassing caller RBAC or row scoping.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Sequence
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field

from backend.ai.client import OpenAIClient, get_openai_client
from backend.ai.config import get_ai_settings
from backend.ai.security import RiskLevel, SecurityPolicyEngine
from backend.core.logging import get_logger
from backend.models.identity.user import User
from backend.utils.enums import Roles

logger = get_logger(__name__)


def create_role_agent(
    *,
    user: User,
    session: Any,
    client: OpenAIClient | None = None,
    client_ip: str | None = None,
    request_id: str | None = None,
) -> Any:
    """Instantiate the appropriate specialized role agent for the authenticated caller."""
    from backend.ai.agents.corporate import CorporateManagerAgent
    from backend.ai.agents.guardian import GuardianAgent
    from backend.ai.agents.student import StudentAgent
    from backend.ai.agents.superadmin import SuperAdminAgent
    from backend.ai.agents.tutor import TutorAgent

    held_roles = SecurityPolicyEngine.caller_roles(user)

    if Roles.SUPER_ADMIN.value in held_roles or Roles.ADMIN.value in held_roles:
        return SuperAdminAgent(
            user=user,
            session=session,
            client=client,
            client_ip=client_ip,
            request_id=request_id,
        )
    if Roles.TUTOR.value in held_roles:
        return TutorAgent(
            user=user,
            session=session,
            client=client,
            client_ip=client_ip,
            request_id=request_id,
        )
    if Roles.CORPORATE_MANAGER.value in held_roles:
        return CorporateManagerAgent(
            user=user,
            session=session,
            client=client,
            client_ip=client_ip,
            request_id=request_id,
        )
    if Roles.GUARDIAN.value in held_roles:
        return GuardianAgent(
            user=user,
            session=session,
            client=client,
            client_ip=client_ip,
            request_id=request_id,
        )
    return StudentAgent(
        user=user,
        session=session,
        client=client,
        client_ip=client_ip,
        request_id=request_id,
    )


class UserIntent(str, Enum):
    """Broad categories for multi-agent routing."""

    TEACHING_ASSESSMENT = "TEACHING_ASSESSMENT"  # Quizzes, assignments, exams, rubrics
    SCHEDULE_ATTENDANCE = "SCHEDULE_ATTENDANCE"  # Sessions, calendar, attendance, absences
    STUDY_CONCEPT = "STUDY_CONCEPT"              # Educational guidance, practice problems, code help
    PROGRESS_REPORTING = "PROGRESS_REPORTING"    # Grades, performance, at-risk flags, corporate training
    ADMIN_OPERATIONS = "ADMIN_OPERATIONS"        # System health, configuration, sync pipelines
    DOCUMENT_SEARCH = "DOCUMENT_SEARCH"          # Semantic search across course materials
    GENERAL_CONVERSATION = "GENERAL_CONVERSATION"


class IntentResolutionResult(BaseModel):
    """Classified intent with extracted entities."""

    intent: UserIntent
    target_role: str
    confidence: float = 1.0
    extracted_entities: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""


class AIOrchestrator:
    """Central supervisor coordinating role agents and safe tool execution."""

    def __init__(self, client: OpenAIClient | None = None) -> None:
        self.client = client or get_openai_client()
        self.settings = get_ai_settings()

    @staticmethod
    def resolve_caller_primary_role(user: User) -> str:
        """Resolve the caller's highest-priority role for routing context."""
        held = SecurityPolicyEngine.caller_roles(user)
        # Order of precedence: SUPER_ADMIN > ADMIN > TUTOR > CORPORATE_MANAGER > GUARDIAN > STUDENT
        if Roles.SUPER_ADMIN.value in held:
            return Roles.SUPER_ADMIN.value
        if Roles.ADMIN.value in held:
            return Roles.ADMIN.value
        if Roles.TUTOR.value in held:
            return Roles.TUTOR.value
        if Roles.CORPORATE_MANAGER.value in held:
            return Roles.CORPORATE_MANAGER.value
        if Roles.GUARDIAN.value in held:
            return Roles.GUARDIAN.value
        return Roles.STUDENT.value

    @staticmethod
    def resolve_date_window(
        *,
        phrase: str,
        user_timezone: str | None = None,
    ) -> tuple[datetime, datetime]:
        """Resolve relative natural language date terms into an absolute UTC time window.

        Supports 'today', 'tomorrow', 'yesterday', 'this week', 'next week', 'this month'.
        """
        tz_name = user_timezone or "UTC"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")

        now_local = datetime.now(tz)
        today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

        cleaned = phrase.strip().lower()

        if "today" in cleaned:
            start = today_start_local
            end = start + timedelta(days=1)
        elif "tomorrow" in cleaned:
            start = today_start_local + timedelta(days=1)
            end = start + timedelta(days=1)
        elif "yesterday" in cleaned:
            start = today_start_local - timedelta(days=1)
            end = today_start_local
        elif "this week" in cleaned:
            # Week starts on Monday
            start = today_start_local - timedelta(days=today_start_local.weekday())
            end = start + timedelta(days=7)
        elif "next week" in cleaned:
            start = today_start_local - timedelta(days=today_start_local.weekday()) + timedelta(days=7)
            end = start + timedelta(days=7)
        elif "this month" in cleaned:
            start = today_start_local.replace(day=1)
            # Rough 31-day window
            end = start + timedelta(days=32)
            end = end.replace(day=1)
        else:
            # Default to 30 days ahead from today
            start = today_start_local
            end = start + timedelta(days=30)

        return (
            start.astimezone(UTC),
            end.astimezone(UTC),
        )

    async def classify_intent(
        self,
        *,
        prompt: str,
        caller: User,
    ) -> IntentResolutionResult:
        """Classify user intent using the configured intent model with fast heuristics."""
        sanitized = SecurityPolicyEngine.sanitize_user_input(prompt)
        primary_role = self.resolve_caller_primary_role(caller)

        lowered = sanitized.lower()

        # Deterministic fast-path heuristics
        if any(w in lowered for w in ("quiz", "assignment", "exam", "question", "assessment", "rubric")):
            return IntentResolutionResult(
                intent=UserIntent.TEACHING_ASSESSMENT,
                target_role=primary_role,
                summary="Assessment and instructional workflows",
            )
        if any(w in lowered for w in ("schedule", "calendar", "class", "session", "attendance", "absent")):
            return IntentResolutionResult(
                intent=UserIntent.SCHEDULE_ATTENDANCE,
                target_role=primary_role,
                summary="Scheduling and attendance intelligence",
            )
        if any(w in lowered for w in ("grade", "transcript", "score", "progress", "completion", "at risk")):
            return IntentResolutionResult(
                intent=UserIntent.PROGRESS_REPORTING,
                target_role=primary_role,
                summary="Academic progress and performance reporting",
            )
        if any(w in lowered for w in ("search", "resource", "lecture sheet", "slide", "material", "notes")):
            return IntentResolutionResult(
                intent=UserIntent.DOCUMENT_SEARCH,
                target_role=primary_role,
                summary="Document and curriculum search",
            )
        if any(w in lowered for w in ("explain", "how to", "debug", "python", "sql", "practice", "concept")):
            return IntentResolutionResult(
                intent=UserIntent.STUDY_CONCEPT,
                target_role=primary_role,
                summary="Personalized learning and concept tutoring",
            )
        if primary_role in (Roles.SUPER_ADMIN.value, Roles.ADMIN.value) and any(w in lowered for w in ("sync", "health", "reset", "purge", "recreate")):
            return IntentResolutionResult(
                intent=UserIntent.ADMIN_OPERATIONS,
                target_role=primary_role,
                summary="Administrative operations and diagnostics",
            )

        return IntentResolutionResult(
            intent=UserIntent.GENERAL_CONVERSATION,
            target_role=primary_role,
            summary="General educational dialogue",
        )

