"""Phase 2: confirmation that holds across processes, risk-driven gating,
unambiguous typed confirmation, and the corporate enrolment tool.

The Postgres store's race and visibility guarantees are proven separately in
tests/integration/test_ai_ticket_store.py; these pin the rules that hold for
any store.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.ai.rate_limit import RequestLimiter
from backend.ai.security import RiskLevel, ToolPolicy
from backend.ai.tickets import ConfirmationTicketManager
from backend.ai.tools.registry import BOUND_PREFIX, ToolDefinition, ToolExecutionContext, ToolRegistry, get_tool_registry
from backend.ai.workflows.confirmation_service import ConfirmationExecutionService
from backend.api.v1.ai import AIChatRequest, chat_with_agent
from backend.core.errors import ConflictError, NotFoundError
from backend.core.permissions import ROLE_PERMISSIONS
from backend.models.identity.permission import Permission
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.utils.enums import Roles


def make_user(role_name: str, *, user_id: int = 5150) -> User:
    role = Role(id=1, name=role_name)
    role.permissions = [
        Permission(id=i, name=name)
        for i, name in enumerate(sorted(ROLE_PERMISSIONS[role_name]), start=1)
    ]
    user = User(
        id=user_id,
        public_id=uuid.uuid4(),
        username=f"{role_name.lower()}@example.com",
        first_name="Test",
        last_name=role_name.title(),
        timezone="UTC",
    )
    user.roles = [role]
    return user


async def _issue(manager: ConfirmationTicketManager, actor_id: int, name: str = "sync_all_data"):
    return await manager.create_ticket(
        action_name=name,
        actor_user_id=actor_id,
        actor_public_id="pid",
        parameters={},
        affected_records_count=1,
        preview_summary=name,
        via_registry=True,
    )


# --------------------------------------------------------------------------
# Single use
# --------------------------------------------------------------------------


def test_two_concurrent_confirmations_let_exactly_one_through():
    async def run():
        manager = ConfirmationTicketManager()
        ticket = await _issue(manager, 1)
        results = await asyncio.gather(
            manager.validate_and_consume(ticket_id=ticket.ticket_id, actor_user_id=1),
            manager.validate_and_consume(ticket_id=ticket.ticket_id, actor_user_id=1),
            return_exceptions=True,
        )
        assert sum(not isinstance(r, BaseException) for r in results) == 1
        assert sum(isinstance(r, ConflictError) for r in results) == 1

    asyncio.run(run())


# --------------------------------------------------------------------------
# Risk drives confirmation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("risk", [RiskLevel.HIGH, RiskLevel.CRITICAL])
def test_a_high_risk_tool_without_confirmation_cannot_be_registered(risk):
    tool = ToolDefinition(
        name="careless",
        description="test",
        policy=ToolPolicy(name="careless", description="test", risk_level=risk),
        parameters_schema={"type": "object", "properties": {}},
        handler=AsyncMock(),
    )
    with pytest.raises(ValueError, match="does not require confirmation"):
        ToolRegistry().register(tool)


def test_every_registered_high_risk_tool_requires_confirmation():
    for tool in get_tool_registry()._tools.values():
        if tool.policy.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            assert tool.policy.requires_confirmation, tool.name


# --------------------------------------------------------------------------
# Typed "yes" / "no"
# --------------------------------------------------------------------------


def _chat(prompt: str, user: User, manager: ConfirmationTicketManager, execute: AsyncMock):
    session = AsyncMock()
    session.add = MagicMock()
    request = MagicMock()
    request.client.host = "127.0.0.1"
    with patch("backend.api.v1.ai.get_ticket_manager", return_value=manager), \
         patch("backend.api.v1.ai.get_request_limiter", return_value=RequestLimiter()), \
         patch("backend.api.v1.ai.ConfirmationExecutionService.execute_ticket", execute), \
         patch("backend.api.v1.ai.create_role_agent") as agent_factory:
        agent_factory.side_effect = AssertionError("a confirmation word must not reach the model")
        return asyncio.run(
            chat_with_agent(
                payload=AIChatRequest(prompt=prompt, stream=False),
                current_user=user,
                session=session,
                request=request,
            )
        )


def test_yes_with_two_pending_actions_confirms_neither():
    user = make_user(Roles.SUPER_ADMIN.value)
    manager = ConfirmationTicketManager()
    asyncio.run(_issue(manager, user.id, "sync_all_data"))
    asyncio.run(_issue(manager, user.id, "delete_inactive_users"))
    execute = AsyncMock()

    resp = _chat("yes", user, manager, execute)

    execute.assert_not_awaited()
    assert resp.success is False
    assert "2 actions" in resp.message
    assert len(asyncio.run(manager.pending_for_user(user.id))) == 2


def test_yes_with_one_pending_action_confirms_that_one():
    user = make_user(Roles.SUPER_ADMIN.value)
    manager = ConfirmationTicketManager()
    ticket = asyncio.run(_issue(manager, user.id))
    execute = AsyncMock(return_value={"success": True, "message": "Synchronization started."})

    resp = _chat("yes", user, manager, execute)

    execute.assert_awaited_once()
    assert execute.await_args.kwargs["ticket_id"] == ticket.ticket_id
    assert resp.success is True
    assert resp.role == Roles.SUPER_ADMIN.value


def test_no_cancels_every_pending_action():
    user = make_user(Roles.TUTOR.value)
    manager = ConfirmationTicketManager()
    asyncio.run(_issue(manager, user.id, "publish_assessment"))
    asyncio.run(_issue(manager, user.id, "manage_batch_session"))

    resp = _chat("no", user, manager, AsyncMock())

    assert resp.success is True
    assert asyncio.run(manager.pending_for_user(user.id)) == []
    # The reply speaks for the caller's own assistant, not always the Super Admin's.
    assert resp.role == Roles.TUTOR.value


# --------------------------------------------------------------------------
# Corporate enrolment
# --------------------------------------------------------------------------


def _enrolment_context(employee: MagicMock | None, roster: set[int]):
    manager = make_user(Roles.CORPORATE_MANAGER.value)
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = employee
    session.execute.return_value = result
    patcher = patch(
        "backend.services.scope.ScopeResolver._managed_student_ids",
        new_callable=AsyncMock,
        return_value=roster,
    )
    return ToolExecutionContext(user=manager, session=session), patcher


def test_off_roster_and_nonexistent_people_get_the_same_refusal():
    """Two different refusals would tell a manager which addresses have accounts."""
    outsider = MagicMock(id=77, public_id=uuid.uuid4(), first_name="Out", last_name="Sider")

    messages = []
    for employee in (None, outsider):
        ctx, patcher = _enrolment_context(employee, roster={1, 2, 3})
        with patcher, patch("backend.services.enrollment_service.EnrollmentService.enroll", new_callable=AsyncMock) as enroll:
            with pytest.raises(NotFoundError) as exc:
                asyncio.run(get_tool_registry().execute_tool(
                    name="enroll_corporate_employee",
                    arguments={"employee_identifier": "someone@corp.test", "batch_code": "B1"},
                    context=ctx,
                ))
            enroll.assert_not_awaited()
        messages.append(exc.value.message)
    assert messages[0] == messages[1]


def test_enrolment_is_staged_and_its_result_names_no_address():
    employee = MagicMock(id=5, public_id=uuid.uuid4(), first_name="Em", last_name="Ployee")
    employee.email = "em.ployee@corp.test"
    batch = MagicMock(id=9, public_id=uuid.uuid4(), batch_code="B1", course_id=3)

    ctx, patcher = _enrolment_context(employee, roster={5})
    lookups = iter([
        MagicMock(**{"scalars.return_value.first.return_value": employee}),
        MagicMock(**{"scalar_one_or_none.return_value": batch}),
        MagicMock(**{"scalar_one_or_none.return_value": "Python"}),
    ])
    ctx.session.execute = AsyncMock(side_effect=lambda *_a, **_k: next(lookups))
    with patcher, patch("backend.services.enrollment_service.EnrollmentService.enroll", new_callable=AsyncMock) as enroll:
        staged = asyncio.run(get_tool_registry().execute_tool(
            name="enroll_corporate_employee",
            arguments={"employee_identifier": "em.ployee@corp.test", "batch_code": "B1"},
            context=ctx,
        ))
        enroll.assert_not_awaited()
    assert staged["status"] == "REQUIRES_CONFIRMATION"
    assert staged["preview_summary"] == "Enrol Em Ployee in batch B1 (Python)?"

    # Confirm the ticket that was actually staged: its bound ids are what the
    # handler checks, so a preview that bound nothing must fail here.
    lookups = iter([
        MagicMock(**{"scalars.return_value.first.return_value": employee}),
        MagicMock(**{"scalar_one_or_none.return_value": batch}),
        MagicMock(**{"scalar_one_or_none.return_value": "Python"}),
        MagicMock(**{"scalars.return_value.first.return_value": None}),  # not already enrolled
    ])
    ctx.session.execute = AsyncMock(side_effect=lambda *_a, **_k: next(lookups))
    with patcher, patch("backend.services.enrollment_service.EnrollmentService.enroll", new_callable=AsyncMock) as enroll:
        enroll.return_value = MagicMock(public_id=uuid.uuid4(), status=MagicMock(value="CONFIRMED"))
        res = asyncio.run(ConfirmationExecutionService(ctx.session).execute_ticket(
            ticket_id=staged["ticket_id"], actor=ctx.user
        ))
        enroll.assert_awaited_once()
    assert res["success"] is True
    assert "em.ployee@corp.test" not in str(res)


# --------------------------------------------------------------------------
# The sync tool borrows the application's engine
# --------------------------------------------------------------------------


def test_sync_tool_uses_the_registered_engine_not_a_new_one():
    from backend.ai import runtime as rt
    from backend.ai.tools.admin_tools import handle_sync_all_data

    async def run():
        factory = MagicMock(name="app-session-factory")
        bus = MagicMock(name="app-event-bus")
        rt.configure_ai_runtime(session_factory=factory, event_bus=bus)
        try:
            with patch("backend.db.manager.DatabaseManager", side_effect=AssertionError("built a new engine")), \
                 patch("backend.ai.tools.admin_tools.SyncPipelineService") as service_cls:
                service = service_cls.return_value
                service.start = AsyncMock(return_value=MagicMock(id=7))
                service.execute = AsyncMock()
                res = await handle_sync_all_data({}, ToolExecutionContext(user=make_user(Roles.SUPER_ADMIN.value), session=AsyncMock()))
                await asyncio.sleep(0)
            assert service_cls.call_args.args[0] is factory
            assert service_cls.call_args.kwargs["event_bus"] is bus
            assert res["status"] == "STARTED"
        finally:
            rt._runtime = None

    asyncio.run(run())
