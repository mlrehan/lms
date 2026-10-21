"""Standardized AI Tool Registry & Dispatcher.

Enforces zero-trust authorization, schema validation, and human-in-the-loop gating
prior to executing any backend service call.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.security import RiskLevel, SecurityPolicyEngine, ToolPolicy
from backend.ai.tickets import get_ticket_manager
from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.core.logging import get_logger
from backend.models.identity.user import User
from backend.services import audit_service

logger = get_logger(__name__)


@dataclass
class ToolExecutionContext:
    """Runtime context provided to tool execution handlers."""

    user: User
    session: AsyncSession
    client_ip: str | None = None
    request_id: str | None = None


ToolHandler = Callable[[dict[str, Any], ToolExecutionContext], Awaitable[dict[str, Any]]]


@dataclass
class ToolDefinition:
    """Complete specification of an AI tool."""

    name: str
    description: str
    policy: ToolPolicy
    parameters_schema: dict[str, Any]
    handler: ToolHandler

    def to_openai_tool(self) -> dict[str, Any]:
        """Convert into standard OpenAI tool dictionary."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }


class ToolRegistry:
    """Thread-safe registry of authorized AI tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a new tool definition."""
        self._tools[tool.name] = tool
        logger.debug("Registered AI tool: %s", tool.name)

    def get(self, name: str) -> ToolDefinition | None:
        """Retrieve tool by name."""
        return self._tools.get(name)

    def list_tools_for_caller(self, user: User) -> list[ToolDefinition]:
        """Return only tools the caller is authorized to invoke (Deny-by-default)."""
        authorized_tools: list[ToolDefinition] = []
        for tool in self._tools.values():
            try:
                SecurityPolicyEngine.authorize_tool_invocation(
                    tool_policy=tool.policy,
                    user=user,
                )
                authorized_tools.append(tool)
            except AuthorizationError:
                continue
        return authorized_tools

    def to_openai_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        """Format a list of tool definitions into OpenAI API tools structure."""
        return [t.to_openai_tool() for t in tools]

    async def execute_tool(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> dict[str, Any]:
        """Execute an AI tool under caller's authorization and transaction scope."""
        tool = self.get(name)
        if not tool:
            logger.warning("Attempted invocation of unknown tool: %s", name)
            raise NotFoundError(f"AI tool '{name}' does not exist.")

        # 1. Authorize caller against tool policy
        SecurityPolicyEngine.authorize_tool_invocation(
            tool_policy=tool.policy,
            user=context.user,
        )

        # 2. Check if tool requires two-phase human confirmation
        if tool.policy.requires_confirmation:
            ticket_mgr = get_ticket_manager()
            ticket = ticket_mgr.create_ticket(
                action_name=tool.name,
                actor_user_id=context.user.id,
                actor_public_id=str(context.user.public_id),
                parameters=arguments,
                affected_records_count=arguments.get("affected_count", 1),
                preview_summary=arguments.get(
                    "preview_summary",
                    f"Action '{tool.name}' requires explicit operator confirmation.",
                ),
            )
            return {
                "status": "REQUIRES_CONFIRMATION",
                "confirmation_ticket_id": ticket.ticket_id,
                "preview_summary": ticket.preview_summary,
                "expires_at": ticket.expires_at.isoformat(),
                "affected_records_count": ticket.affected_records_count,
            }

        # 3. Execute authorized handler
        logger.info("Executing AI tool '%s' for user %s", name, context.user.public_id)
        result = await tool.handler(arguments, context)

        # 4. Record audit trail if action is defined
        if tool.policy.audit_action:
            try:
                audit_service.record(
                    context.session,
                    action=tool.policy.audit_action,
                    actor=context.user,
                    entity_type=arguments.get("entity_type", "ai_tool"),
                    entity_id=result.get("entity_id"),
                    details={
                        "tool": tool.name,
                        "arguments": {k: v for k, v in arguments.items() if "password" not in k.lower()},
                        "success": result.get("success", True),
                    },
                    client_ip=context.client_ip,
                )
            except Exception as exc:
                logger.error("Failed to write audit log for tool '%s': %s", name, exc)

        return result


_global_tool_registry = ToolRegistry()
_tools_initialized = False


def get_tool_registry() -> ToolRegistry:
    """Return singleton instance of ToolRegistry with standard tools registered."""
    global _global_tool_registry, _tools_initialized
    if not _tools_initialized:
        # Register standard academic, attendance, and reporting tools
        from backend.ai.tools.academic_tools import (
            create_assessment_draft_tool,
            get_course_curriculum_tool,
        )
        from backend.ai.tools.attendance_tools import (
            get_attendance_summary_tool,
            get_my_schedule_tool,
        )
        from backend.ai.tools.reporting_tools import (
            get_corporate_training_progress_tool,
            get_student_academic_summary_tool,
        )
        from backend.ai.tools.rag_tools import search_course_knowledge_tool

        _global_tool_registry.register(create_assessment_draft_tool)
        _global_tool_registry.register(get_course_curriculum_tool)
        _global_tool_registry.register(get_my_schedule_tool)
        _global_tool_registry.register(get_attendance_summary_tool)
        _global_tool_registry.register(get_student_academic_summary_tool)
        _global_tool_registry.register(get_corporate_training_progress_tool)
        _global_tool_registry.register(search_course_knowledge_tool)

        _tools_initialized = True

    return _global_tool_registry
