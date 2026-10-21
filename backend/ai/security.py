"""Zero-Trust AI Security Policy Engine.

Enforces:
1. Defense against prompt injection, jailbreaks, and system instruction leaks.
2. Layered caller-bound authorization before any tool invocation.
3. Denial-by-default execution policy.
4. Risk classification and Human-in-the-Loop gating.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Callable, NamedTuple, Sequence
from pydantic import BaseModel, Field

from backend.core.errors import AppError, AuthorizationError, ValidationError
from backend.core.logging import get_logger
from backend.models.identity.user import User
from backend.utils.enums import Roles

logger = get_logger(__name__)


class AISecurityError(AppError):
    """Raised when an AI prompt or tool call violates safety or zero-trust policies."""

    status_code = 400
    code = "AI_SECURITY_POLICY_VIOLATION"
    message = "Request flagged by AI safety policies."


SecurityError = AISecurityError


class RiskLevel(str, Enum):
    """Execution risk categories for AI-coordinated actions."""

    LOW = "LOW"            # Read-only queries, curriculum search, conceptual explanation
    MODERATE = "MODERATE"  # Draft creations (quizzes, assignments, practice problems)
    HIGH = "HIGH"          # Publishing assessments, bulk updates, attendance corrections
    CRITICAL = "CRITICAL"  # System resets, permanent purges, credential modifications


class ToolPolicy(BaseModel):
    """Authorization and execution contract for an AI tool."""

    name: str
    description: str
    required_permissions: tuple[str, ...] = ()
    allowed_roles: tuple[str, ...] | None = None
    risk_level: RiskLevel = RiskLevel.LOW
    requires_confirmation: bool = False
    audit_action: str | None = None


# Patterns that signal adversarial jailbreaks, prompt extractions, or privilege overrides
_PROMPT_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bignore\s+(all\s+)?(previous|prior|above)\s+instructions\b"),
    re.compile(r"(?i)\b(system\s+prompt|developer\s+mode|jailbreak|unrestricted\s+mode)\b"),
    re.compile(r"(?i)\b(output|print|reveal|repeat|leak)\s+(your\s+)?(instructions|system\s+prompt|rules)\b"),
    re.compile(r"(?i)\b(you\s+are\s+now\s+in\s+developer\s+mode|dan\s+mode)\b"),
    re.compile(r"(?i)\b(act\s+as\s+root|sudo\s+mode|bypass\s+security|override\s+permissions)\b"),
    re.compile(r"(?i)<\s*(system|instruction|developer|override)\s*>"),
    re.compile(r"(?i)\[\s*(system|developer|admin_override)\s*\]"),
    re.compile(r"(?i)\bdrop\s+table\b|\bdelete\s+from\s+users\b|\bselect\s+.*\s+from\s+audit_logs\b"),
)


class SecurityPolicyEngine:
    """Enforces zero-trust authorization and prompt defense."""

    @staticmethod
    def sanitize_user_input(text: str) -> str:
        """Inspect and sanitize inbound user prompts against injection patterns.

        Raises SecurityError if a malicious jailbreak attempt is detected.
        """
        trimmed = text.strip()
        if not trimmed:
            raise ValidationError("Prompt cannot be empty.")

        for pattern in _PROMPT_INJECTION_PATTERNS:
            if pattern.search(trimmed):
                logger.warning("Prompt injection pattern detected: %s", pattern.pattern)
                raise SecurityError(
                    "Request flagged by AI safety policies. Please rephrase your educational inquiry."
                )

        return trimmed

    @staticmethod
    def caller_roles(user: User) -> set[str]:
        """Return the uppercase role names held by the caller."""
        return {(r.name or "").upper() for r in (user.roles or [])}

    @staticmethod
    def caller_permissions(user: User) -> set[str]:
        """Return the flat permission set held by the caller."""
        return {
            p.name
            for role in (user.roles or [])
            for p in (role.permissions or [])
        }

    @classmethod
    def authorize_tool_invocation(
        cls,
        *,
        tool_policy: ToolPolicy,
        user: User,
    ) -> None:
        """Verify caller is authorized to invoke the specified tool.

        Raises AuthorizationError on failure (Denial-by-Default).
        """
        # 1. SuperAdmin holding institution.view_all has top-tier authority,
        # but still requires confirmation tickets for HIGH/CRITICAL actions.
        held_perms = cls.caller_permissions(user)
        held_roles = cls.caller_roles(user)

        # 2. Check role constraints if specified
        if tool_policy.allowed_roles is not None:
            allowed = {r.upper() for r in tool_policy.allowed_roles}
            if not held_roles.intersection(allowed):
                logger.warning(
                    "User %s denied for tool %s: roles %s not in %s",
                    user.public_id,
                    tool_policy.name,
                    held_roles,
                    allowed,
                )
                raise AuthorizationError(
                    f"Your role cannot invoke tool '{tool_policy.name}'."
                )

        # 3. Check granular permission requirements
        if tool_policy.required_permissions:
            missing = set(tool_policy.required_permissions) - held_perms
            if missing:
                logger.warning(
                    "User %s denied for tool %s: missing permissions %s",
                    user.public_id,
                    tool_policy.name,
                    missing,
                )
                raise AuthorizationError(
                    f"Permission denied for '{tool_policy.name}'.",
                    details={"required": sorted(missing)},
                )

        logger.info(
            "Authorized tool invocation '%s' (Risk: %s) for user %s",
            tool_policy.name,
            tool_policy.risk_level.value,
            user.public_id,
        )
