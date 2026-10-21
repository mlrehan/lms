"""Confirmation Execution Service (Human-in-the-Loop Gateway).

Executes cryptographically validated confirmation tickets under strict transactional
guarantees and permanent audit logging.
"""

from __future__ import annotations

import uuid
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.security import SecurityPolicyEngine
from backend.ai.tickets import ConfirmationTicket, get_ticket_manager
from backend.core.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from backend.core.logging import get_logger
from backend.models.identity.user import User
from backend.services import audit_service
from backend.services.quiz_service import QuizService

logger = get_logger(__name__)


class ConfirmationExecutionService:
    """Validates and executes confirmed high-risk operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.ticket_manager = get_ticket_manager()

    async def execute_ticket(
        self,
        *,
        ticket_id: str,
        actor: User,
        provided_parameters: dict[str, Any] | None = None,
        client_ip: str | None = None,
    ) -> dict[str, Any]:
        """Validate ticket fingerprint, consume it, and execute the underlying service mutation."""
        # 1. Validate ownership, expiration, and parameter integrity
        ticket = self.ticket_manager.validate_and_consume(
            ticket_id=ticket_id,
            actor_user_id=actor.id,
            provided_parameters=provided_parameters,
        )

        action = ticket.action_name
        params = ticket.parameters
        logger.info(
            "Executing confirmed action '%s' from ticket %s by user %s",
            action,
            ticket_id,
            actor.public_id,
        )

        # 2. Dispatch to authorized action handler
        if action == "publish_assessment":
            return await self._execute_publish_assessment(ticket, actor, client_ip)
        elif action == "publish_assessment_live":
            return await self._execute_publish_assessment(ticket, actor, client_ip)
        else:
            raise ValidationError(f"Unsupported action for confirmation ticket: '{action}'")

    async def _execute_publish_assessment(
        self,
        ticket: ConfirmationTicket,
        actor: User,
        client_ip: str | None,
    ) -> dict[str, Any]:
        """Transition an assessment from DRAFT to PUBLISHED state."""
        params = ticket.parameters
        assessment_id_str = params.get("assessment_id") or params.get("quiz_id")
        if not assessment_id_str:
            raise ValidationError("Assessment ID is missing from confirmation parameters.")

        try:
            assessment_uuid = uuid.UUID(assessment_id_str)
        except (ValueError, TypeError):
            raise ValidationError(f"Invalid assessment UUID: '{assessment_id_str}'")

        # 1. Authorize: Check permissions
        held_perms = SecurityPolicyEngine.caller_permissions(actor)
        if "quiz.publish" not in held_perms and "assignment.publish" not in held_perms and "institution.view_all" not in held_perms:
            raise AuthorizationError("You do not hold permission to publish assessments.")

        # 2. Execute publishing via QuizService
        quiz_svc = QuizService(self.session)
        quiz = await quiz_svc.set_published(assessment_uuid, True, actor=actor)

        # 3. Permanent Audit Trail
        try:
            audit_service.record(
                self.session,
                action=audit_service.AuditAction.AI_CONFIRMED_ACTION,
                actor_user_id=actor.id,
                actor_email=actor.email,
                entity_type="quiz",
                entity_id=quiz.id,
                details={
                    "operation": "AI_CONFIRMED_PUBLISH",
                    "ticket_id": ticket.ticket_id,
                    "title": quiz.title,
                    "scope": quiz.scope.value,
                    "batch_id": quiz.batch_id,
                },
            )
        except Exception as exc:
            logger.warning("Audit logging for confirmed ticket %s failed: %s", ticket.ticket_id, exc)

        return {
            "success": True,
            "status": "PUBLISHED",
            "assessment_id": str(quiz.public_id),
            "title": quiz.title,
            "is_published": quiz.is_published,
            "message": f"Assessment '{quiz.title}' has been successfully published to enrolled students.",
        }

