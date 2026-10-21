"""Base Agent Execution Framework.

Defines the core agent lifecycle, multi-turn tool calling loop, and zero-trust
caller authorization binding.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Sequence
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.client import OpenAIClient, get_openai_client
from backend.ai.security import SecurityPolicyEngine
from backend.ai.tools.registry import (
    ToolExecutionContext,
    ToolRegistry,
    get_tool_registry,
)
from backend.core.logging import get_logger
from backend.models.identity.user import User

logger = get_logger(__name__)


@dataclass
class AgentResponse:
    """Standardized response from an agent turn."""

    text: str
    role: str
    tool_calls_made: list[dict[str, Any]] = field(default_factory=list)
    confirmation_ticket: dict[str, Any] | None = None
    success: bool = True


class BaseAgent:
    """Abstract base class for role-bound specialized LMS agents."""

    role_name: str = "BASE"
    system_prompt: str = "You are an intelligent LMS assistant."

    def __init__(
        self,
        *,
        user: User,
        session: AsyncSession,
        client: OpenAIClient | None = None,
        tool_registry: ToolRegistry | None = None,
        client_ip: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.user = user
        self.session = session
        self.client = client or get_openai_client()
        self.tool_registry = tool_registry or get_tool_registry()
        self.client_ip = client_ip
        self.request_id = request_id

    def get_effective_system_prompt(self) -> str:
        """Return system prompt enhanced with caller context."""
        caller_name = (
            f"{self.user.first_name or ''} {self.user.last_name or ''}".strip()
            or self.user.username
        )
        held_roles = ", ".join(SecurityPolicyEngine.caller_roles(self.user))
        return (
            f"{self.system_prompt}\n\n"
            f"[CALLER CONTEXT]\n"
            f"User: {caller_name} (Username: {self.user.username})\n"
            f"Public ID: {self.user.public_id}\n"
            f"Roles: {held_roles}\n"
            f"Timezone: {self.user.timezone or 'UTC'}\n"
            f"Strict Invariant: All facts must come from tool queries. Never invent or hallucinate course, batch, or student IDs."
        )

    async def execute_turn(
        self,
        *,
        prompt: str,
        conversation_history: Sequence[dict[str, str]] | None = None,
    ) -> AgentResponse:
        """Execute one conversational turn with dynamic multi-step tool calls."""
        # 1. Sanitize user input against prompt injection
        sanitized = SecurityPolicyEngine.sanitize_user_input(prompt)

        # 2. Get authorized tools for this specific caller
        authorized_tools = self.tool_registry.list_tools_for_caller(self.user)
        openai_tools = (
            self.tool_registry.to_openai_tools(authorized_tools)
            if authorized_tools
            else None
        )

        # 3. Assemble message payload
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.get_effective_system_prompt()},
        ]

        if conversation_history:
            for msg in conversation_history[-6:]:  # Bound recent history to prevent context overflow
                role = msg.get("role", "user")
                if role in ("user", "assistant"):
                    messages.append({"role": role, "content": msg.get("content", "")})

        messages.append({"role": "user", "content": sanitized})

        # 4. Multi-turn tool execution loop (max 4 turns to prevent unbounded looping)
        tools_executed: list[dict[str, Any]] = []
        confirmation_needed: dict[str, Any] | None = None

        for turn in range(4):
            completion = await self.client.chat_completion(
                messages=messages,
                tools=openai_tools,
            )

            choice = completion.choices[0]
            msg = choice.message

            # If no tool calls were requested, return final text
            if not msg.tool_calls:
                return AgentResponse(
                    text=msg.content or "Task completed.",
                    role=self.role_name,
                    tool_calls_made=tools_executed,
                    confirmation_ticket=confirmation_needed,
                    success=True,
                )

            # Tool call requested by LLM
            messages.append(msg.model_dump())

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                fn_args_raw = tc.function.arguments or "{}"
                try:
                    fn_args = json.loads(fn_args_raw)
                except Exception:
                    fn_args = {}

                logger.info("Agent %s executing tool: %s", self.role_name, fn_name)

                ctx = ToolExecutionContext(
                    user=self.user,
                    session=self.session,
                    client_ip=self.client_ip,
                    request_id=self.request_id,
                )

                try:
                    tool_result = await self.tool_registry.execute_tool(
                        name=fn_name,
                        arguments=fn_args,
                        context=ctx,
                    )
                except Exception as exc:
                    logger.warning("Tool %s execution raised: %s", fn_name, exc)
                    tool_result = {"error": str(exc), "success": False}

                tools_executed.append({
                    "tool": fn_name,
                    "arguments": fn_args,
                    "result": tool_result,
                })

                # Check if this tool produced a confirmation requirement
                if tool_result.get("status") == "REQUIRES_CONFIRMATION":
                    confirmation_needed = tool_result

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_result),
                })

        # Final response synthesis
        final_completion = await self.client.chat_completion(
            messages=messages,
            tools=None,
        )
        return AgentResponse(
            text=final_completion.choices[0].message.content or "Completed.",
            role=self.role_name,
            tool_calls_made=tools_executed,
            confirmation_ticket=confirmation_needed,
            success=True,
        )

