"""Unit and Integration tests for SuperAdmin Full Administrative Control."""

import asyncio
import uuid
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
from backend.ai.tools.registry import BOUND_PREFIX, ToolExecutionContext, get_tool_registry
from backend.ai.workflows.confirmation_service import ConfirmationExecutionService
from backend.core.errors import AuthorizationError, ConflictError
from backend.core.permissions import ROLE_PERMISSIONS
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


def _with_real_grants(user: User, role_name: str) -> User:
    """Give a mocked user the role's real permissions, so the registry's own
    authorization runs rather than being bypassed by calling handlers directly."""
    perms = []
    for name in sorted(ROLE_PERMISSIONS[role_name]):
        perm_obj = MagicMock()
        perm_obj.name = name
        perms.append(perm_obj)
    user.roles[0].permissions = perms
    return user


def _superadmin() -> User:
    return _with_real_grants(make_superadmin_user(), Roles.SUPER_ADMIN.value)


def test_sync_all_data_is_staged_even_when_the_model_claims_confirmation():
    """A `confirmed: true` the model writes into the arguments confirms nothing."""
    async def run():
        admin = _superadmin()
        ctx = ToolExecutionContext(user=admin, session=AsyncMock())

        with patch("backend.services.sync_pipeline_service.SyncPipelineService.start") as mock_start:
            res = await get_tool_registry().execute_tool(
                name="sync_all_data", arguments={"confirmed": True}, context=ctx
            )
            mock_start.assert_not_called()

        assert res["status"] == "REQUIRES_CONFIRMATION"
        assert res["success"] is False
        assert res["preview_summary"] == "Sync all data defined in the dashboard?"
        assert res["ticket_id"].startswith("act_")

    asyncio.run(run())


def test_delete_inactive_users_preview_counts_and_binds_the_accounts():
    """The ticket carries the exact accounts counted, written by the server."""
    async def run():
        admin = _superadmin()
        session = AsyncMock()
        ids = [uuid.uuid4() for _ in range(3)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = ids
        session.execute.return_value = mock_result
        ctx = ToolExecutionContext(user=admin, session=session)

        res = await get_tool_registry().execute_tool(
            name="delete_inactive_users",
            # The model tries to pre-bind its own list; it must be discarded.
            arguments={"confirmed": True, f"{BOUND_PREFIX}user_ids": ["not-a-real-id"]},
            context=ctx,
        )

        assert res["status"] == "REQUIRES_CONFIRMATION"
        assert res["preview_summary"] == "Delete 3 inactive users? This cannot be undone."
        assert res["affected_records_count"] == 3
        ticket = await get_ticket_manager().get_ticket(res["ticket_id"])
        assert ticket.parameters[f"{BOUND_PREFIX}user_ids"] == [str(i) for i in ids]
        assert ticket.via_registry is True

    asyncio.run(run())


def test_confirmed_sync_reports_started_not_finished():
    """Confirming starts the pipeline and says so -- it does not claim it finished."""
    async def run():
        admin = _superadmin()
        session = AsyncMock()
        ctx = ToolExecutionContext(user=admin, session=session)

        staged = await get_tool_registry().execute_tool(name="sync_all_data", arguments={}, context=ctx)

        with patch("backend.services.sync_pipeline_service.SyncPipelineService.start", new_callable=AsyncMock) as mock_start, \
             patch("backend.services.sync_pipeline_service.SyncPipelineService.execute", new_callable=AsyncMock):
            mock_run = MagicMock()
            mock_run.id = 42
            mock_start.return_value = mock_run

            result = await ConfirmationExecutionService(session).execute_ticket(
                ticket_id=staged["ticket_id"], actor=admin
            )

        assert result["success"] is True
        assert result["status"] == "STARTED"
        assert "synchronized successfully" not in result["message"].lower()
        mock_start.assert_awaited_once()

    asyncio.run(run())


def test_manage_user_refuses_to_grant_administrative_roles():
    """The assistant never hands out SUPER_ADMIN or ADMIN, confirmed or not."""
    async def run():
        admin = _superadmin()
        session = AsyncMock()
        target = MagicMock(spec=User)
        target.id = 55
        target.public_id = uuid.uuid4()
        result = MagicMock()
        result.scalars.return_value.first.return_value = target
        session.execute.return_value = result
        ctx = ToolExecutionContext(user=admin, session=session)

        for role in ("SUPER_ADMIN", "admin"):
            with pytest.raises(ConflictError):
                await get_tool_registry().execute_tool(
                    name="manage_user",
                    arguments={"user_identifier": "someone", "new_role": role},
                    context=ctx,
                )

    asyncio.run(run())


def test_manage_user_change_is_staged_then_applied_through_user_service():
    """Staged first; on confirmation it runs UserService.set_roles for the bound account."""
    async def run():
        admin = _superadmin()
        session = AsyncMock()
        target = MagicMock(spec=User)
        target.id = 55
        target.public_id = uuid.uuid4()
        target.username = "t.user"
        target.first_name = "Tara"
        target.last_name = "User"
        existing = MagicMock()
        existing.name = Roles.STUDENT.value
        target.roles = [existing]
        target.status = UserStatus.ACTIVE
        result = MagicMock()
        result.scalars.return_value.first.return_value = target
        session.execute.return_value = result
        ctx = ToolExecutionContext(user=admin, session=session)

        with patch("backend.services.user_service.UserService.set_roles", new_callable=AsyncMock) as set_roles:
            staged = await get_tool_registry().execute_tool(
                name="manage_user",
                arguments={"user_identifier": "t.user", "new_role": "TUTOR"},
                context=ctx,
            )
            set_roles.assert_not_awaited()
            assert staged["status"] == "REQUIRES_CONFIRMATION"
            assert "add the TUTOR role" in staged["preview_summary"]

            set_roles.return_value = target
            await ConfirmationExecutionService(session).execute_ticket(
                ticket_id=staged["ticket_id"], actor=admin
            )
            set_roles.assert_awaited_once_with(
                target.public_id, [Roles.STUDENT.value, "TUTOR"], actor=admin
            )

    asyncio.run(run())


def test_ticket_manager_lists_pending_and_cancels_all_of_them():
    """"No" cancels every pending ticket, not just the newest, so a later
    "yes" can never confirm something that was declined."""
    admin = make_superadmin_user(user_id=888)
    ticket_mgr = ConfirmationTicketManager()

    first, second = (
        asyncio.run(ticket_mgr.create_ticket(
            action_name=name,
            actor_user_id=admin.id,
            actor_public_id=str(admin.public_id),
            parameters={},
            affected_records_count=0,
            preview_summary=name,
        ))
        for name in ("sync_all_data", "delete_inactive_users")
    )

    pending = asyncio.run(ticket_mgr.pending_for_user(admin.id))
    assert {t.ticket_id for t in pending} == {first.ticket_id, second.ticket_id}

    cancelled = asyncio.run(ticket_mgr.cancel_pending_for_user(admin.id))
    assert len(cancelled) == 2
    assert asyncio.run(ticket_mgr.pending_for_user(admin.id)) == []
    for t in (first, second):
        assert asyncio.run(ticket_mgr.get_ticket(t.ticket_id)).status.value == "CANCELLED"