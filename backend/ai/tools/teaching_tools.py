"""Teaching preparation: what a tutor's next class is and what it should cover.

A thin tool over `backend.ai.teaching_context`, which does the work and holds
the reasoning. Read-only and LOW risk: it changes nothing, and every record it
returns is admitted by the service that owns it, with the caller as actor.
"""

from __future__ import annotations

import uuid
from typing import Any

from backend.ai.security import RiskLevel, ToolPolicy
from backend.ai.teaching_context import build_teaching_context
from backend.ai.tools.registry import ToolDefinition, ToolExecutionContext
from backend.core.errors import ValidationError
from backend.utils.enums import Roles


async def handle_get_teaching_context(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    session_id = (arguments.get("session_id") or "").strip() or None
    if session_id:
        try:
            uuid.UUID(session_id)
        except ValueError as exc:
            raise ValidationError("session_id must be a session's id as returned by get_my_schedule.") from exc
    return await build_teaching_context(
        context.session,
        context.user,
        batch_code=(arguments.get("batch_code") or "").strip() or None,
        session_id=session_id,
    )


get_teaching_context_tool = ToolDefinition(
    name="get_teaching_context",
    description=(
        "Use FIRST for any question about what to teach or how to prepare: 'what should I teach', "
        "'my next class', lesson plans, explanations, exercises or examples for a class. Returns the "
        "caller's next class (or the class for a batch/session given), its course, the course's "
        "official published outline and overview, its position in the batch (class n of N), evidence "
        "of earlier teaching, course files, assessments and the practice editors -- each labelled with "
        "its source (verified_lms, verified_course_page, missing)."
    ),
    policy=ToolPolicy(
        name="get_teaching_context",
        description="Prepare for a class you teach",
        required_permissions=("session.read",),
        allowed_roles=(Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value),
        risk_level=RiskLevel.LOW,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "batch_code": {
                "type": "string",
                "description": "A batch the caller teaches, when the question names one (optional).",
            },
            "session_id": {
                "type": "string",
                "description": "A specific session id from get_my_schedule (optional).",
            },
        },
    },
    handler=handle_get_teaching_context,
)
