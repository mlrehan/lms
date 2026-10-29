"""SuperAdmin Operations Tools.

Provides high-privilege administrative tools for system-wide operations, data synchronization,
bulk deletions, user account management, and platform health diagnostics.
Strictly enforced by server-side SuperAdmin role verification and human-in-the-loop confirmation tickets.
"""

from __future__ import annotations

import asyncio
from typing import Any
import uuid

from sqlalchemy import func, select, update

from backend.ai.security import RiskLevel, SecurityPolicyEngine, ToolPolicy
from backend.ai.tools.registry import (
    BOUND_PREFIX,
    ConfirmationPreview,
    ToolDefinition,
    ToolExecutionContext,
)
from backend.core.config import get_settings
from backend.core.errors import AuthorizationError, ConflictError, NotFoundError
from backend.core.logging import get_logger
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.identity.user import User
from backend.models.sync_pipeline import SyncPipelineRun
from backend.services import audit_service
from backend.services.sync_pipeline_service import SyncPipelineService
from backend.utils.enums import Roles, UserStatus

logger = get_logger(__name__)


# =============================================================================
# CONFIRMATION
# =============================================================================
#
# Every write here is staged by the registry (`requires_confirmation=True`) and
# runs only when the person confirms the ticket. There is deliberately no
# `confirmed` argument: the model fills tool arguments in, so a flag it can set
# is a confirmation it can give itself.

# The AI never hands out the roles that administer the platform. Doing that
# from a chat window -- where the instruction may have come from text the model
# read rather than from the person -- is exactly the escalation to rule out.
_ROLES_NOT_GRANTABLE_BY_AI = frozenset({Roles.SUPER_ADMIN.value, Roles.ADMIN.value})

# A bulk deletion binds the exact accounts shown. Past this many, a chat
# confirmation is the wrong tool and the Users screen is the right one.
_MAX_BULK_DELETE = 200


def _require_super_admin(user: User, what: str) -> None:
    if Roles.SUPER_ADMIN.value not in SecurityPolicyEngine.caller_roles(user):
        raise AuthorizationError(f"Only Super Administrators can {what}.")


def _display_name(target: User) -> str:
    return f"{target.first_name or ''} {target.last_name or ''}".strip() or "Unnamed account"


# =============================================================================
# 1. SYNC ALL DATA
# =============================================================================


async def preview_sync_all_data(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> ConfirmationPreview:
    _require_super_admin(context.user, "trigger full data synchronization")
    return ConfirmationPreview(summary="Sync all data defined in the dashboard?", affected_records_count=0)


async def handle_sync_all_data(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Start the complete data synchronization pipeline (runs only after confirmation)."""
    user = context.user
    _require_super_admin(user, "trigger full data synchronization")

    from backend.ai.runtime import get_ai_runtime

    runtime = get_ai_runtime()
    try:
        # The application's own engine and event bus, exactly as the dashboard
        # button uses them -- so the run's progress reaches the sync panel live.
        service = SyncPipelineService(
            runtime.session_factory,
            get_settings(),
            event_bus=runtime.event_bus,
        )
        run = await service.start(
            trigger_type="MANUAL_AI",
            triggered_by_user_id=user.id,
        )
    except ConflictError:
        return {
            "success": False,
            "status": "RUNNING",
            "message": "A synchronization is already running; no new one was started.",
        }

    # Same as the dashboard: the pipeline runs in the background and reports
    # its own progress. Saying "synchronized" here would claim an outcome that
    # has not happened yet.
    asyncio.create_task(service.execute(run.id))

    audit_service.record(
        context.session,
        action=audit_service.AuditAction.AI_CONFIRMED_ACTION,
        actor_user_id=user.id,
        actor_email=user.email,
        entity_type="sync_pipeline",
        entity_id=run.id,
        details={
            "operation": "SYNC_ALL_DATA",
            "trigger": "AI_SUPERADMIN",
        },
    )

    return {
        "success": True,
        "status": "STARTED",
        "message": "Synchronization started. Its progress is shown on the dashboard's sync panel.",
        "run_id": run.id,
    }


# =============================================================================
# 2. DELETE INACTIVE USERS
# =============================================================================


async def preview_delete_inactive_users(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> ConfirmationPreview:
    user = context.user
    _require_super_admin(user, "perform bulk deletion of inactive users")
    rows = (
        await context.session.execute(
            select(User.public_id).where(
                User.status == UserStatus.INACTIVE,
                User.deleted_at.is_(None),
                User.id != user.id,
            )
        )
    ).scalars().all()
    count = len(rows)
    if count > _MAX_BULK_DELETE:
        raise ConflictError(
            f"{count} inactive accounts is more than the assistant deletes at once "
            f"({_MAX_BULK_DELETE}). Use the Users screen instead."
        )
    return ConfirmationPreview(
        summary=f"Delete {count} inactive users? This cannot be undone.",
        affected_records_count=count,
        # Bound now, so confirming deletes the accounts that were counted --
        # not whichever accounts happen to be inactive when "yes" arrives.
        bound_parameters={"user_ids": [str(pid) for pid in rows]},
    )


async def handle_delete_inactive_users(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Delete the inactive accounts bound into the confirmed ticket."""
    from backend.services.user_service import UserService

    user = context.user
    _require_super_admin(user, "perform bulk deletion of inactive users")

    bound = arguments.get(f"{BOUND_PREFIX}user_ids")
    if bound is None:
        raise ConflictError("This deletion has no confirmed list of accounts; ask for it again.")

    users = UserService(context.session)
    deleted = 0
    skipped = 0
    for raw in bound:
        target = (
            await context.session.execute(select(User).where(User.public_id == uuid.UUID(str(raw))))
        ).scalar_one_or_none()
        # Re-checked at execution: an account reactivated since the preview
        # is no longer what the person agreed to delete.
        if target is None or target.status != UserStatus.INACTIVE or target.deleted_at is not None:
            skipped += 1
            continue
        await users.soft_delete(target.public_id, actor=user)
        deleted += 1

    message = f"{deleted} inactive user(s) deleted."
    if skipped:
        message += f" {skipped} skipped because they were no longer inactive."
    return {
        "success": True,
        "status": "DELETED",
        "count": deleted,
        "skipped": skipped,
        "message": message,
    }


# =============================================================================
# 3. PLATFORM HEALTH & SYSTEM OVERVIEW
# =============================================================================


async def handle_get_system_overview(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Retrieve platform health, user registry statistics, and course counts."""
    user = context.user
    held_roles = SecurityPolicyEngine.caller_roles(user)
    if Roles.SUPER_ADMIN.value not in held_roles and Roles.ADMIN.value not in held_roles:
        raise AuthorizationError("Only Administrators can view system-wide diagnostics.")

    session = context.session

    from backend.services.security_service import SecurityService

    # Live accounts only: soft-deleted rows keep their status column, and
    # counting them inflated "active users" by every account ever removed.
    live = (User.deleted_at.is_(None), User.status != UserStatus.DELETED)
    by_status = dict(
        (await session.execute(select(User.status, func.count(User.id)).where(*live).group_by(User.status))).all()
    )
    total_users = sum(by_status.values())
    total_courses = (await session.execute(select(func.count(Course.id)).where(~Course.is_deleted))).scalar() or 0
    total_batches = (await session.execute(select(func.count(Batch.id)))).scalar() or 0
    security = await SecurityService(session).summary(hours=24)

    runs = (
        await session.execute(select(SyncPipelineRun).order_by(SyncPipelineRun.started_at.desc()).limit(10))
    ).scalars().all()
    latest = runs[0] if runs else None
    last_completed = next((r for r in runs if r.status == "COMPLETED"), None)

    def describe(run: Any) -> str | None:
        if run is None:
            return None
        when = run.started_at.strftime("%Y-%m-%d %H:%M UTC") if run.started_at else "unknown time"
        return f"{run.status} ({when})" + (f": {run.failure_reason}" if run.failure_reason else "")

    # Facts, not a verdict. The old reply said "Healthy (All services
    # operational)" unconditionally -- a status nothing had checked. What can
    # honestly be said is what was read, and what looks wrong.
    attention: list[str] = []
    if latest is not None and latest.status not in ("COMPLETED", "RUNNING"):
        attention.append(f"The latest data sync did not complete: {describe(latest)}.")
    if latest is None:
        attention.append("No data sync has ever run.")
    if security.accounts_locked_now:
        attention.append(f"{security.accounts_locked_now} account(s) are locked out right now.")
    if security.token_reuse_detections:
        attention.append(f"{security.token_reuse_detections} refresh-token reuse detection(s) in the last 24 hours.")
    if security.failed_logins >= 20:
        attention.append(f"{security.failed_logins} failed sign-ins in the last 24 hours.")

    return {
        "database": "reachable (these figures were read from it just now)",
        "users": {"total": total_users, **{str(k.value if hasattr(k, 'value') else k): v for k, v in by_status.items()}},
        "total_courses": total_courses,
        "total_batches": total_batches,
        "active_sessions": security.active_sessions,
        "failed_logins_24h": security.failed_logins,
        "accounts_locked_now": security.accounts_locked_now,
        "latest_sync": describe(latest) or "never run",
        "last_completed_sync": describe(last_completed) or "none",
        "needs_attention": attention or ["Nothing in these checks needs attention."],
        "note": "These checks cover the database, accounts and data sync; they do not test external services.",
    }


# =============================================================================
# 4. MANAGE USER (ROLE & STATUS)
# =============================================================================


async def _resolve_manage_user_change(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> tuple[User, str | None, UserStatus | None, str | None, bool | None]:
    """Validate a requested change completely, before anything is staged."""
    user = context.user
    _require_super_admin(user, "manage user roles and status")

    user_identifier = str(arguments.get("user_identifier") or "").strip()
    if not user_identifier:
        raise NotFoundError("User identifier is required.")

    target_user = (
        await context.session.execute(
            select(User).where(
                (User.email == user_identifier) | (User.username == user_identifier),
                User.deleted_at.is_(None),
            )
        )
    ).scalars().first()
    if not target_user:
        raise NotFoundError(f"User '{user_identifier}' not found.")
    if target_user.id == user.id:
        raise ConflictError("You cannot modify your own account through the assistant.")

    new_role = (arguments.get("new_role") or "").strip().upper() or None
    if new_role is not None:
        if new_role in _ROLES_NOT_GRANTABLE_BY_AI:
            raise ConflictError(
                f"The assistant does not grant the {new_role} role. Assign it from the Users screen."
            )
        if new_role not in {r.value for r in Roles}:
            raise NotFoundError(f"Role '{new_role}' does not exist.")

    new_status: UserStatus | None = None
    raw_status = (arguments.get("new_status") or "").strip().upper()
    if raw_status:
        try:
            new_status = UserStatus(raw_status)
        except ValueError:
            raise NotFoundError(f"Status '{raw_status}' does not exist.") from None
        if new_status is UserStatus.DELETED:
            raise ConflictError("Deleting an account is not a status change; use the Users screen.")

    remove_role = (arguments.get("remove_role") or "").strip().upper() or None
    if remove_role is not None:
        if remove_role in _ROLES_NOT_GRANTABLE_BY_AI:
            raise ConflictError(
                f"The assistant does not remove the {remove_role} role. Change administrators on the Users screen."
            )
        held = {r.name for r in (target_user.roles or [])}
        if remove_role not in held:
            raise ConflictError(f"{_display_name(target_user)} does not hold the {remove_role} role.")
        if held == {remove_role} and new_role is None:
            raise ConflictError(
                f"{remove_role} is {_display_name(target_user)}'s only role; give the role to replace it with."
            )

    can_login = arguments.get("can_login")
    if not isinstance(can_login, bool) or can_login == bool(target_user.can_login):
        # A value the account already has is not a change. Driven live, the
        # model sent can_login=false on a role swap nobody asked to block, and
        # the preview offered "block sign-in (and end their sessions)" as if it
        # were part of the request.
        can_login = None
    if new_status is not None and new_status == target_user.status:
        new_status = None

    if new_role is None and new_status is None and remove_role is None and can_login is None:
        raise ConflictError("Nothing to change: give a role to add or remove, a new status, or sign-in on/off.")
    return target_user, new_role, new_status, remove_role, can_login


async def preview_manage_user(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> ConfirmationPreview:
    target, new_role, new_status, remove_role, can_login = await _resolve_manage_user_change(arguments, context)
    changes = []
    if new_role:
        changes.append(f"add the {new_role} role")
    if remove_role:
        changes.append(f"remove the {remove_role} role")
    if new_status:
        changes.append(f"set status to {new_status.value}")
    if can_login is not None:
        changes.append("allow sign-in" if can_login else "block sign-in (and end their sessions)")
    return ConfirmationPreview(
        summary=f"For {_display_name(target)} ({target.username}): {' and '.join(changes)}?",
        bound_parameters={"target_id": str(target.public_id)},
    )


async def handle_manage_user(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Apply a confirmed role/status change through UserService and its guards."""
    from backend.services.user_service import UserService

    user = context.user
    target, new_role, new_status, remove_role, can_login = await _resolve_manage_user_change(arguments, context)
    bound_target = arguments.get(f"{BOUND_PREFIX}target_id")
    if bound_target is None or str(target.public_id) != str(bound_target):
        raise ConflictError("The account no longer matches the one confirmed; ask for the change again.")

    users = UserService(context.session)
    if new_status is not None:
        target = await users.set_status(target.public_id, new_status, actor=user)
    if new_role is not None or remove_role is not None:
        current = [r.name for r in (target.roles or [])]
        wanted = [r for r in current if r != remove_role]
        if new_role is not None and new_role not in wanted:
            wanted.append(new_role)
        if sorted(wanted) != sorted(current):
            target = await users.set_roles(target.public_id, wanted, actor=user)
    default_password = False
    if can_login is not None:
        target, default_password = await users.set_login_access(target.public_id, can_login, actor=user)

    return {
        "success": True,
        "user": target.username,
        "roles": sorted(r.name for r in (target.roles or [])),
        "status": target.status.value,
        "can_login": bool(target.can_login),
        "message": "User updated.",
        **(
            {"warning": "Sign-in is allowed but the account still uses the shared default password; "
                        "set a personal password on the Users screen."}
            if can_login and default_password else {}
        ),
    }


# =============================================================================
# TOOL DEFINITIONS & EXPORTS
# =============================================================================

sync_all_data_tool = ToolDefinition(
    name="sync_all_data",
    description="Synchronize all platform data (users, courses, batches, sessions, enrollments) exactly as in the SuperAdmin dashboard.",
    policy=ToolPolicy(
        name="sync_all_data",
        description="Sync all platform data",
        required_permissions=("user.sync", "course.sync"),
        allowed_roles=(Roles.SUPER_ADMIN.value,),
        risk_level=RiskLevel.HIGH,
        requires_confirmation=True,
    ),
    parameters_schema={
        "type": "object",
        "properties": {},
        "required": [],
    },
    handler=handle_sync_all_data,
    preview=preview_sync_all_data,
)

delete_inactive_users_tool = ToolDefinition(
    name="delete_inactive_users",
    description="Bulk delete inactive user accounts under SuperAdmin authority.",
    policy=ToolPolicy(
        name="delete_inactive_users",
        description="Delete inactive users",
        required_permissions=("user.delete",),
        allowed_roles=(Roles.SUPER_ADMIN.value,),
        risk_level=RiskLevel.CRITICAL,
        requires_confirmation=True,
    ),
    parameters_schema={
        "type": "object",
        "properties": {},
        "required": [],
    },
    handler=handle_delete_inactive_users,
    preview=preview_delete_inactive_users,
)

get_system_overview_tool = ToolDefinition(
    name="get_system_overview",
    description="Retrieve platform health, user registry statistics, active courses, and sync status.",
    policy=ToolPolicy(
        name="get_system_overview",
        description="View system health and overview",
        required_permissions=("institution.view_all",),
        risk_level=RiskLevel.LOW,
    ),
    parameters_schema={
        "type": "object",
        "properties": {},
        "required": [],
    },
    handler=handle_get_system_overview,
)

manage_user_tool = ToolDefinition(
    name="manage_user",
    description=(
        "Change an account: add or remove a non-administrator role, set its status (ACTIVE, INACTIVE, SUSPENDED), "
        "or allow/block sign-in. To clear a sign-in lockout use unlock_account instead. Confirmed first."
    ),
    policy=ToolPolicy(
        name="manage_user",
        description="Manage user account",
        required_permissions=("user.update",),
        allowed_roles=(Roles.SUPER_ADMIN.value,),
        risk_level=RiskLevel.HIGH,
        requires_confirmation=True,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "user_identifier": {
                "type": "string",
                "description": "Username or email of the user to manage.",
            },
            "new_role": {
                "type": "string",
                "description": "Optional role name to assign (e.g. TUTOR, STUDENT, CORPORATE_MANAGER).",
            },
            "new_status": {
                "type": "string",
                "description": "Optional status to set (ACTIVE, INACTIVE, SUSPENDED).",
            },
            "remove_role": {
                "type": "string",
                "description": "Optional role to remove (not SUPER_ADMIN or ADMIN).",
            },
            "can_login": {
                "type": "boolean",
                "description": "Optional: true allows sign-in, false blocks it.",
            },
        },
        "required": ["user_identifier"],
    },
    handler=handle_manage_user,
    preview=preview_manage_user,
)
