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
from backend.ai.output_policy import redact_tool_result
from backend.ai.tickets import get_ticket_manager
from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.core.logging import get_logger
from backend.core.privacy import set_viewer
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
class ConfirmationPreview:
    """What a person is shown before confirming -- composed by the server."""

    summary: str
    affected_records_count: int = 1
    # Facts fixed at preview time (e.g. exactly which records), merged into the
    # ticket so execution acts on what was shown rather than re-deciding.
    bound_parameters: dict[str, Any] | None = None


PreviewBuilder = Callable[[dict[str, Any], ToolExecutionContext], Awaitable[ConfirmationPreview]]

_CONFIRMATION_REQUIRED_AT = frozenset({RiskLevel.HIGH, RiskLevel.CRITICAL})

# Keys beginning with this prefix are written by the server into a ticket.
# Anything the model sends under it is discarded, so it cannot pre-bind them.
BOUND_PREFIX = "_bound_"


@dataclass
class ToolDefinition:
    """Complete specification of an AI tool."""

    name: str
    description: str
    policy: ToolPolicy
    parameters_schema: dict[str, Any]
    handler: ToolHandler
    preview: PreviewBuilder | None = None

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
        """Register a new tool definition.

        A HIGH or CRITICAL tool that runs without confirmation is refused at
        registration -- which happens at import, so it is a startup error
        rather than a consequential write the model can make on its own.
        Risk is declared once, and confirmation follows from it.
        """
        if tool.policy.risk_level in _CONFIRMATION_REQUIRED_AT and not tool.policy.requires_confirmation:
            raise ValueError(
                f"AI tool '{tool.name}' is {tool.policy.risk_level.value} risk but does not require "
                "confirmation. Set requires_confirmation=True (and confirm_actions to narrow it)."
            )
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

        arguments = {k: v for k, v in arguments.items() if not str(k).startswith(BOUND_PREFIX)}

        # 2. Check if tool requires two-phase human confirmation
        if tool.policy.needs_confirmation(arguments):
            return await self._stage(tool, arguments, context)

        return await self._run(tool, arguments, context)

    async def execute_confirmed(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> dict[str, Any]:
        """Run a tool whose ticket a person has just confirmed.

        Authorization is checked again: the person may have lost the role
        between preview and confirmation, and a ticket must not outlive that.
        """
        tool = self.get(name)
        if not tool:
            raise NotFoundError(f"AI tool '{name}' does not exist.")
        SecurityPolicyEngine.authorize_tool_invocation(
            tool_policy=tool.policy,
            user=context.user,
        )
        return await self._run(tool, arguments, context)

    async def _stage(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> dict[str, Any]:
        """Issue a confirmation ticket instead of running the tool.

        The summary is the server's, never the model's: a model that could
        write the confirmation text could describe a deletion as a refresh.
        """
        if tool.preview is not None:
            preview = await tool.preview(arguments, context)
        else:
            preview = ConfirmationPreview(summary=f"Confirm the action '{tool.name}'.")
        parameters = dict(arguments)
        for key, value in (preview.bound_parameters or {}).items():
            parameters[f"{BOUND_PREFIX}{key}"] = value

        ticket = await get_ticket_manager().create_ticket(
            action_name=tool.name,
            actor_user_id=context.user.id,
            actor_public_id=str(context.user.public_id),
            parameters=parameters,
            affected_records_count=preview.affected_records_count,
            preview_summary=preview.summary,
            via_registry=True,
        )
        return redact_tool_result({
            "status": "REQUIRES_CONFIRMATION",
            "success": False,
            "ticket_id": ticket.ticket_id,
            "confirmation_ticket_id": ticket.ticket_id,
            "action_name": ticket.action_name,
            "parameters_hash": ticket.parameters_hash,
            "preview_summary": ticket.preview_summary,
            "expires_at": ticket.expires_at.isoformat(),
            "affected_records_count": ticket.affected_records_count,
            "message": "Nothing has been done yet. The action is waiting for the user's confirmation.",
        })

    async def _run(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> dict[str, Any]:
        name = tool.name
        # The privacy rules key on who is asking. Recorded here, from the
        # authenticated caller, so they hold for every tool call however it was
        # reached -- a chat turn, a stream, or a confirmation.
        set_viewer(context.user)

        # 3. Execute authorized handler
        logger.info("Executing AI tool '%s' for user %s", name, context.user.public_id)
        result = await tool.handler(arguments, context)

        # 4. Record audit trail if action is defined. This used to pass
        # `actor=` and `client_ip=`, which `record()` does not accept: every
        # call raised TypeError into the except below, so no tool-level audit
        # row was ever written and only a log line said so.
        if tool.policy.audit_action:
            try:
                audit_service.record(
                    context.session,
                    action=tool.policy.audit_action,
                    actor_user_id=context.user.id,
                    actor_email=context.user.email,
                    entity_type=arguments.get("entity_type", "ai_tool"),
                    entity_id=result.get("entity_id"),
                    success=bool(result.get("success", True)),
                    details={
                        "tool": tool.name,
                        "via": "ai_assistant",
                        "arguments": {k: v for k, v in arguments.items() if "password" not in k.lower()},
                        "client_ip": context.client_ip,
                        "request_id": context.request_id,
                    },
                )
            except Exception as exc:
                logger.error("Failed to write audit log for tool '%s': %s", name, exc)

        # 5. One privacy rule for every result, before the model, the stream
        # or saved history sees it.
        return redact_tool_result(result)


_global_tool_registry = ToolRegistry()
_tools_initialized = False


def get_tool_registry() -> ToolRegistry:
    """Return singleton instance of ToolRegistry with standard tools registered."""
    global _global_tool_registry, _tools_initialized
    if not _tools_initialized:
        # Register standard academic, attendance, and reporting tools
        from backend.ai.tools.academic_tools import (
            create_assessment_draft_tool,
            create_assignment_draft_tool,
            create_examination_draft_tool,
            get_course_curriculum_tool,
            get_pending_submissions_tool,
            get_quiz_evaluation_summary_tool,
            manage_course_resources_tool,
            publish_assessment_tool,
            suggest_submission_grade_tool,
        )
        from backend.ai.tools.attendance_tools import (
            get_attendance_summary_tool,
            get_my_schedule_tool,
            manage_batch_session_tool,
            mark_session_attendance_tool,
        )
        from backend.ai.tools.reporting_tools import (
            enroll_corporate_employee_tool,
            generate_institution_report_tool,
            get_batch_student_performance_and_gaps_tool,
            get_corporate_training_progress_tool,
            get_guardian_dependents_tool,
            get_student_academic_summary_tool,
            get_student_assessments_and_deadlines_tool,
            get_student_enrolled_courses_tool,
        )
        from backend.ai.tools.admin_tools import (
            delete_inactive_users_tool,
            get_system_overview_tool,
            manage_user_tool,
            sync_all_data_tool,
        )
        from backend.ai.tools.database_tools import (
            execute_database_query_tool,
            inspect_database_schema_tool,
        )
        from backend.ai.tools.rag_tools import search_course_knowledge_tool
        from backend.ai.tools.communication_tools import draft_message_tool, post_announcement_tool
        from backend.ai.tools.gradebook_tools import get_batch_gradebook_tool, record_exam_marks_tool

        _global_tool_registry.register(draft_message_tool)
        _global_tool_registry.register(post_announcement_tool)
        _global_tool_registry.register(get_batch_gradebook_tool)
        _global_tool_registry.register(record_exam_marks_tool)

        _global_tool_registry.register(create_assessment_draft_tool)
        _global_tool_registry.register(create_assignment_draft_tool)
        _global_tool_registry.register(create_examination_draft_tool)
        _global_tool_registry.register(publish_assessment_tool)
        _global_tool_registry.register(get_pending_submissions_tool)
        _global_tool_registry.register(suggest_submission_grade_tool)
        _global_tool_registry.register(get_quiz_evaluation_summary_tool)
        _global_tool_registry.register(manage_course_resources_tool)
        _global_tool_registry.register(get_course_curriculum_tool)
        _global_tool_registry.register(get_my_schedule_tool)
        _global_tool_registry.register(get_attendance_summary_tool)
        _global_tool_registry.register(mark_session_attendance_tool)
        _global_tool_registry.register(manage_batch_session_tool)
        _global_tool_registry.register(get_student_academic_summary_tool)
        _global_tool_registry.register(get_corporate_training_progress_tool)
        _global_tool_registry.register(get_batch_student_performance_and_gaps_tool)
        _global_tool_registry.register(generate_institution_report_tool)
        _global_tool_registry.register(get_guardian_dependents_tool)
        _global_tool_registry.register(get_student_assessments_and_deadlines_tool)
        _global_tool_registry.register(get_student_enrolled_courses_tool)
        _global_tool_registry.register(enroll_corporate_employee_tool)
        # submit_assignment_solution is deliberately not registered: an
        # assistant that writes a student's answer and hands it in for them is
        # the academic-integrity failure the student prompt forbids.
        _global_tool_registry.register(search_course_knowledge_tool)
        _global_tool_registry.register(sync_all_data_tool)
        _global_tool_registry.register(delete_inactive_users_tool)
        _global_tool_registry.register(get_system_overview_tool)
        _global_tool_registry.register(manage_user_tool)
        _global_tool_registry.register(execute_database_query_tool)
        _global_tool_registry.register(inspect_database_schema_tool)

        _tools_initialized = True

    return _global_tool_registry
