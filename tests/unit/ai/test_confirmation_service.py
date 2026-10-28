"""Unit tests for Confirmation Execution Service."""

import asyncio
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.ai.security import SecurityError
from backend.ai.tickets import ConfirmationTicketManager, get_ticket_manager
from backend.ai.workflows.confirmation_service import ConfirmationExecutionService
from backend.core.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from backend.models.identity.permission import Permission
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.utils.enums import Roles


def make_actor(*, user_id: int = 1, perms: list[str]) -> User:
    u = User(id=user_id, username="tutor1", slug="tutor1", hashed_password="pw")
    r = Role(id=1, name=Roles.TUTOR.value)
    r.permissions = [Permission(id=i + 1, name=p) for i, p in enumerate(perms)]
    u.roles = [r]
    return u


def test_execute_publish_assessment_success():
    async def run_test():
        mgr = get_ticket_manager()
        quiz_id = str(uuid.uuid4())
        actor = make_actor(user_id=10, perms=["quiz.publish"])

        ticket = await mgr.create_ticket(
            action_name="publish_assessment",
            actor_user_id=10,
            actor_public_id="actor-public-uuid",
            parameters={"assessment_id": quiz_id},
            affected_records_count=20,
            preview_summary="Publish quiz to 20 students",
        )

        mock_quiz = MagicMock()
        mock_quiz.id = 501
        mock_quiz.public_id = uuid.UUID(quiz_id)
        mock_quiz.title = "Unit 1 Quiz"
        mock_quiz.is_published = True
        mock_quiz.scope = MagicMock(value="BATCH")
        mock_quiz.batch_id = 112

        with patch("backend.ai.workflows.confirmation_service.QuizService") as mock_qs_cls:
            mock_qs = MagicMock()
            mock_qs.set_published = AsyncMock(return_value=mock_quiz)
            mock_qs_cls.return_value = mock_qs

            with patch("backend.ai.workflows.confirmation_service.audit_service") as mock_audit:
                mock_audit.record = MagicMock()
                mock_audit.AuditAction.UPDATE = "UPDATE"

                svc = ConfirmationExecutionService(session=MagicMock())
                res = await svc.execute_ticket(
                    ticket_id=ticket.ticket_id,
                    actor=actor,
                    provided_parameters={"assessment_id": quiz_id},
                )

                assert res["success"] is True
                assert res["status"] == "PUBLISHED"
                assert res["assessment_id"] == quiz_id
                mock_qs.set_published.assert_awaited_once_with(
                    uuid.UUID(quiz_id), True, actor=actor
                )
                mock_audit.record.assert_called_once()

    asyncio.run(run_test())


def test_execute_publish_fails_on_permission_denial():
    async def run_test():
        mgr = get_ticket_manager()
        quiz_id = str(uuid.uuid4())
        actor_without_perm = make_actor(user_id=10, perms=[])  # Missing quiz.publish

        ticket = await mgr.create_ticket(
            action_name="publish_assessment",
            actor_user_id=10,
            actor_public_id="actor-public-uuid",
            parameters={"assessment_id": quiz_id},
            affected_records_count=20,
            preview_summary="Publish quiz",
        )

        svc = ConfirmationExecutionService(session=MagicMock())
        with pytest.raises(AuthorizationError) as exc:
            await svc.execute_ticket(
                ticket_id=ticket.ticket_id,
                actor=actor_without_perm,
                provided_parameters={"assessment_id": quiz_id},
            )
        assert "permission to publish" in str(exc.value).lower()

    asyncio.run(run_test())


def test_execute_ticket_detects_parameter_tampering():
    async def run_test():
        mgr = get_ticket_manager()
        quiz_id_original = str(uuid.uuid4())
        quiz_id_altered = str(uuid.uuid4())
        actor = make_actor(user_id=10, perms=["quiz.publish"])

        ticket = await mgr.create_ticket(
            action_name="publish_assessment",
            actor_user_id=10,
            actor_public_id="actor-public-uuid",
            parameters={"assessment_id": quiz_id_original},
            affected_records_count=20,
            preview_summary="Publish original quiz",
        )

        svc = ConfirmationExecutionService(session=MagicMock())
        with pytest.raises(SecurityError) as exc:
            await svc.execute_ticket(
                ticket_id=ticket.ticket_id,
                actor=actor,
                provided_parameters={"assessment_id": quiz_id_altered},  # Altered!
            )
        assert "altered" in str(exc.value).lower()

    asyncio.run(run_test())

