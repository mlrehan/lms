"""Unit and Integration tests for SuperAdmin Full Administrative Control."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.ai.agents.superadmin import SuperAdminAgent
from backend.ai.tickets import ConfirmationTicketManager, get_ticket_manager
from backend.ai.tools.admin_tools import (
    handle_delete_inactive_users,
    handle_get_system_overview,
    handle_manage_user,
    handle_sync_all_data,
)
from backend.ai.tools.registry import ToolExecutionContext
from backend.ai.workflows.confirmation_service import ConfirmationExecutionService
from backend.core.errors import AuthorizationError
from backend.models.identity.user import User
from backend.utils.enums import Roles, UserStatus


def make_superadmin_user(user_id: int = 1) -> User:
    user = MagicMock(spec=User)
    user.id = user_id
    user.public_id = "00000000-0000-0000-0000-000000000001"
    user.username = "superadmin"
    user.email = "superadmin@lms.example.com"
    user.first_name = "Super"
    user.last_name = "Admin"
    user.timezone = "UTC"

    role = MagicMock()
    role.name = Roles.SUPER_ADMIN.value
    user.roles = [role]
    return user


def make_regular_student(user_id: int = 2) -> User:
    user = MagicMock(spec=User)
    user.id = user_id
    user.public_id = "00000000-0000-0000-0000-000000000002"
    user.username = "student_user"
    user.email = "student@lms.example.com"
    user.timezone = "UTC"

    role = MagicMock()
    role.name = Roles.STUDENT.value
    user.roles = [role]
    return user


def test_non_superadmin_denied_admin_tools():
    """Non-superadmins must be strictly denied admin tools."""
    async def run():
        student = make_regular_student()
        session = AsyncMock()
        ctx = ToolExecutionContext(user=student, session=session)

        with pytest.raises(AuthorizationError):
            await handle_sync_all_data({}, ctx)

        with pytest.raises(AuthorizationError):
            await handle_delete_inactive_users({}, ctx)

        with pytest.raises(AuthorizationError):
            await handle_get_system_overview({}, ctx)

    asyncio.run(run())


def test_superadmin_sync_all_data_unconfirmed():
    """Unconfirmed sync request must generate an ephemeral ticket."""
    async def run():
        admin = make_superadmin_user()
        session = AsyncMock()
        ctx = ToolExecutionContext(user=admin, session=session)

        res = await handle_sync_all_data({"confirmed": False}, ctx)
        assert res["status"] == "REQUIRES_CONFIRMATION"
        assert "Sync all data defined in the dashboard?" in res["prompt_message"]
        assert "ticket_id" in res
        assert res["ticket_id"].startswith("act_")

    asyncio.run(run())


def test_superadmin_delete_inactive_users_unconfirmed():
    """Unconfirmed delete inactive request must count users and issue confirmation ticket."""
    async def run():
        admin = make_superadmin_user()
        session = AsyncMock()

        mock_result = MagicMock()
        mock_inactive_users = [MagicMock(), MagicMock(), MagicMock()]
        mock_result.scalars.return_value.all.return_value = mock_inactive_users
        session.execute.return_value = mock_result

        ctx = ToolExecutionContext(user=admin, session=session)

        res = await handle_delete_inactive_users({"confirmed": False}, ctx)
        assert res["status"] == "REQUIRES_CONFIRMATION"
        assert "Delete 3 inactive users? This cannot be undone." in res["prompt_message"]
        assert res["affected_records_count"] == 3

    asyncio.run(run())


def test_confirmation_service_executes_sync_all_data():
    """ConfirmationExecutionService successfully executes sync_all_data ticket."""
    async def run():
        admin = make_superadmin_user()
        session = AsyncMock()

        ticket_mgr = get_ticket_manager()
        ticket = ticket_mgr.create_ticket(
            action_name="sync_all_data",
            actor_user_id=admin.id,
            actor_public_id=str(admin.public_id),
            parameters={},
            affected_records_count=0,
            preview_summary="Sync all data defined in the dashboard?",
        )

        with patch("backend.services.sync_pipeline_service.SyncPipelineService.start") as mock_start, \
             patch("backend.services.sync_pipeline_service.SyncPipelineService.execute") as mock_exec:
            mock_run = MagicMock()
            mock_run.id = 42
            mock_start.return_value = mock_run

            exec_svc = ConfirmationExecutionService(session)
            result = await exec_svc.execute_ticket(ticket_id=ticket.ticket_id, actor=admin)

            assert result["success"] is True
            assert result["message"] == "All data synchronized successfully."

    asyncio.run(run())


def test_ticket_manager_latest_pending_and_cancel():
    """Ticket manager correctly identifies latest pending ticket and supports cancellation."""
    admin = make_superadmin_user(user_id=888)
    ticket_mgr = ConfirmationTicketManager()

    ticket = ticket_mgr.create_ticket(
        action_name="sync_all_data",
        actor_user_id=admin.id,
        actor_public_id=str(admin.public_id),
        parameters={},
        affected_records_count=0,
        preview_summary="Sync all data",
    )

    found = ticket_mgr.get_latest_pending_for_user(admin.id)
    assert found is not None
    assert found.ticket_id == ticket.ticket_id

    cancelled = ticket_mgr.cancel_pending_for_user(admin.id)
    assert cancelled is not None
    assert cancelled.status.value == "CANCELLED"

    assert ticket_mgr.get_latest_pending_for_user(admin.id) is None

