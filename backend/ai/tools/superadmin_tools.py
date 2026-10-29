"""Super Admin administration through the services the console itself uses.

Driven live, the assistant had no tool for creating an account, removing a
role, unlocking a lockout, enrolling a student, reading a setting or searching
the audit trail -- so it wrote SQL. It tried `INSERT INTO users` (no password
hash, no audit row), `DELETE FROM user_roles`, and `INSERT INTO enrollments`
(no capacity lock, no notification, no webhook), and only the backup guard on
the SQL tool stopped it. Then it explained the refusal with a reason it had
made up.

**Each tool here calls the same service method the matching console screen
calls**, with the Super Admin as actor. So every rule, audit row,
notification and webhook is the service's own, and a refusal comes back with
the service's own words -- which is what the assistant must report.

**Super Admin only, on every tool**, through `allowed_roles` (the registry
checks it before the handler runs) and the permission the console route
requires. Administrators share the agent but not these tools.

**Changes are confirmed with a server-written preview** whose target is
bound into the ticket, as everywhere else in this layer.

**No password ever passes through the assistant.** An account it creates gets
a random password nobody sees and starts with sign-in disabled; the
administrator sets a password and allows sign-in on the Users screen. A
password typed into a chat would sit in the conversation history.
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from backend.ai.security import RiskLevel, ToolPolicy
from backend.ai.tools.admin_tools import _ROLES_NOT_GRANTABLE_BY_AI, _display_name, _require_super_admin
from backend.ai.tools.registry import BOUND_PREFIX, ConfirmationPreview, ToolDefinition, ToolExecutionContext
from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.models.batch import Batch
from backend.models.identity.user import User
from backend.utils.enums import EnrollmentStatus, Roles, UserStatus

_SA = (Roles.SUPER_ADMIN.value,)
_MAX_ROWS = 50


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


async def _find_user(context: ToolExecutionContext, identifier: Any) -> User:
    """One account, by username, email or full name -- never a guess between several."""
    ident = str(identifier or "").strip()
    if not ident:
        raise ValidationError("Name the account by username, email or full name.")
    live = (User.deleted_at.is_(None), User.status != UserStatus.DELETED)
    exact = (
        await context.session.execute(
            select(User).where(*live, or_(func.lower(User.email) == ident.lower(), func.lower(User.username) == ident.lower()))
        )
    ).scalars().all()
    if len(exact) == 1:
        return exact[0]
    full = func.lower(func.concat_ws(" ", User.first_name, User.last_name))
    by_name = (
        await context.session.execute(select(User).where(*live, full == " ".join(ident.lower().split())).limit(3))
    ).scalars().all()
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        raise ConflictError(f"More than one account is named '{ident}'. Give the email or username instead.")
    raise NotFoundError(f"No account matches '{ident}'.")


def _summary(user: User) -> dict[str, Any]:
    return {
        "name": _display_name(user),
        "username": user.username,
        "email": user.email,
        "roles": sorted(r.name for r in (user.roles or [])),
        "status": user.status.value,
        "can_login": bool(user.can_login),
        "locked_out": bool(user.is_locked_out),
        "last_login": _iso(getattr(user, "last_login", None)),
    }


# =============================================================================
# People
# =============================================================================


async def handle_find_users(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    _require_super_admin(context.user, "search accounts")
    query = str(arguments.get("query") or "").strip().lower()
    role = str(arguments.get("role") or "").strip().upper()
    stmt = select(User).where(User.deleted_at.is_(None), User.status != UserStatus.DELETED)
    if query:
        like = f"%{query}%"
        stmt = stmt.where(or_(
            func.lower(User.email).like(like),
            func.lower(User.username).like(like),
            func.lower(func.concat_ws(" ", User.first_name, User.last_name)).like(like),
        ))
    if role:
        from backend.models.identity.role import Role

        stmt = stmt.where(User.roles.any(Role.name == role))
    total = (await context.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await context.session.execute(stmt.order_by(User.first_name, User.last_name).limit(_MAX_ROWS))).scalars().all()
    return {"total": total, "shown": len(rows), "users": [_summary(u) for u in rows]}


find_users_tool = ToolDefinition(
    name="find_users",
    description=(
        "Search accounts by name, email or username, optionally by role. Returns roles, status, whether they can "
        "sign in and whether they are locked out. Use this instead of SQL to look people up."
    ),
    policy=ToolPolicy(name="find_users", description="Search accounts", required_permissions=("user.read",),
                      allowed_roles=_SA, risk_level=RiskLevel.LOW),
    parameters_schema={"type": "object", "properties": {
        "query": {"type": "string", "description": "Part of a name, email or username (optional)"},
        "role": {"type": "string", "description": "Only accounts holding this role (optional)"},
    }},
    handler=handle_find_users,
)


def _new_account(arguments: dict[str, Any]) -> dict[str, Any]:
    email = str(arguments.get("email") or "").strip().lower()
    first = str(arguments.get("first_name") or "").strip()
    last = str(arguments.get("last_name") or "").strip()
    if not email or "@" not in email:
        raise ValidationError("A valid email address is required.")
    if not first:
        raise ValidationError("A first name is required.")
    # The username rule allows letters, digits, '.', '_' and '-': the part of
    # the email before the '@' fits it once anything else is dropped.
    username = str(arguments.get("username") or "").strip() or re.sub(r"[^A-Za-z0-9._-]", "", email.split("@")[0])
    roles = sorted({str(r).strip().upper() for r in (arguments.get("roles") or []) if str(r).strip()})
    if not roles:
        raise ValidationError("Give at least one role (STUDENT, TUTOR, GUARDIAN or CORPORATE_MANAGER).")
    for role in roles:
        if role in _ROLES_NOT_GRANTABLE_BY_AI:
            raise ConflictError(f"The assistant does not grant the {role} role. Create administrators on the Users screen.")
        if role not in {r.value for r in Roles}:
            raise NotFoundError(f"Role '{role}' does not exist.")
    account = {"email": email, "first_name": first, "last_name": last or None, "username": username, "roles": roles}
    # The service's own request schema, checked now: a rule it enforces must
    # refuse before the Super Admin confirms, not after.
    from pydantic import ValidationError as SchemaError

    from backend.schemas.user import UserCreateRequest

    try:
        UserCreateRequest(**{k: v for k, v in account.items()}, password=secrets.token_urlsafe(32), can_login=False)
    except SchemaError as exc:
        problems = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise ValidationError(f"The account cannot be created: {problems}.") from exc
    return account


async def _assert_new_account_free(context: ToolExecutionContext, account: dict[str, Any]) -> None:
    clash = (
        await context.session.execute(
            select(User.id).where(or_(func.lower(User.email) == account["email"],
                                      func.lower(User.username) == account["username"].lower())).limit(1)
        )
    ).scalar_one_or_none()
    if clash is not None:
        raise ConflictError("An account with that email or username already exists.")


async def preview_create_user(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    _require_super_admin(context.user, "create accounts")
    account = _new_account(arguments)
    await _assert_new_account_free(context, account)
    name = f"{account['first_name']} {account['last_name'] or ''}".strip()
    return ConfirmationPreview(
        summary=(
            f"Create an account for {name} ({account['email']}, username {account['username']}) with role(s) "
            f"{', '.join(account['roles'])}. Sign-in starts disabled: set a password and allow sign-in on the Users screen."
        ),
        bound_parameters={"account": account},
    )


async def handle_create_user(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.schemas.user import UserCreateRequest
    from backend.services.user_service import UserService

    _require_super_admin(context.user, "create accounts")
    account = _new_account(arguments)
    if account != arguments.get(f"{BOUND_PREFIX}account"):
        raise ConflictError("The account details no longer match what was confirmed; ask again.")
    await _assert_new_account_free(context, account)
    created = await UserService(context.session).create(
        UserCreateRequest(
            username=account["username"], email=account["email"],
            # Random and never shown: nobody can sign in with it, and sign-in is
            # disabled until an administrator sets a real password.
            password=secrets.token_urlsafe(32),
            first_name=account["first_name"], last_name=account["last_name"],
            can_login=False, roles=account["roles"],
        ),
        actor=context.user,
    )
    return {
        "success": True,
        "account": _summary(created),
        "message": (
            f"Account created for {_display_name(created)}. Sign-in is disabled until a password is set and sign-in is "
            "allowed on the Users screen."
        ),
    }


create_user_tool = ToolDefinition(
    name="create_user",
    description=(
        "Create a non-administrator account (STUDENT, TUTOR, GUARDIAN, CORPORATE_MANAGER). Sign-in starts disabled; "
        "the Super Admin sets the password on the Users screen. Confirmed before it is created."
    ),
    policy=ToolPolicy(name="create_user", description="Create an account", required_permissions=("user.create",),
                      allowed_roles=_SA, risk_level=RiskLevel.HIGH, requires_confirmation=True, audit_action="CREATE"),
    parameters_schema={"type": "object", "properties": {
        "first_name": {"type": "string"}, "last_name": {"type": "string"},
        "email": {"type": "string"},
        "username": {"type": "string", "description": "Optional; defaults to the email address"},
        "roles": {"type": "array", "items": {"type": "string"}},
    }, "required": ["first_name", "email", "roles"]},
    handler=handle_create_user,
    preview=preview_create_user,
)


# =============================================================================
# Security
# =============================================================================


async def handle_get_security_overview(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.schemas.base import PageParams
    from backend.services.security_service import SecurityService

    _require_super_admin(context.user, "view security")
    hours = max(1, min(int(arguments.get("hours") or 24), 24 * 30))
    service = SecurityService(context.session)
    summary = await service.summary(hours=hours)
    locked, total_locked = await service.locked_accounts(PageParams(limit=_MAX_ROWS, offset=0))
    return {
        "window_hours": hours,
        "failed_logins": summary.failed_logins,
        "lockout_events": summary.lockout_events,
        "accounts_locked_now": summary.accounts_locked_now,
        "token_reuse_detections": summary.token_reuse_detections,
        "permission_changes": summary.permission_changes,
        "active_sessions": summary.active_sessions,
        "locked_accounts": [
            {"name": a.full_name, "email": a.email, "failed_attempts": a.failed_login_attempts,
             "locked_until": _iso(a.locked_until) or "indefinitely"}
            for a in locked
        ],
        "locked_total": total_locked,
    }


get_security_overview_tool = ToolDefinition(
    name="get_security_overview",
    description=(
        "Security posture for a window (default 24 hours): failed sign-ins, lockouts, token-reuse detections, "
        "permission changes, active sessions, and the accounts locked out right now."
    ),
    policy=ToolPolicy(name="get_security_overview", description="View security posture",
                      required_permissions=("security.read",), allowed_roles=_SA, risk_level=RiskLevel.LOW),
    parameters_schema={"type": "object", "properties": {"hours": {"type": "integer"}}},
    handler=handle_get_security_overview,
)


async def _security_target(arguments: dict[str, Any], context: ToolExecutionContext, what: str) -> User:
    _require_super_admin(context.user, what)
    target = await _find_user(context, arguments.get("user"))
    if target.id == context.user.id:
        raise ConflictError("You cannot do that to your own account through the assistant.")
    return target


async def preview_unlock_account(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    target = await _security_target(arguments, context, "unlock accounts")
    state = "locked out" if target.is_locked_out else "not currently locked out"
    return ConfirmationPreview(
        summary=(f"Unlock {_display_name(target)} ({target.email}), who is {state}: clear the failed sign-in count and "
                 "the lock. Their status and sign-in permission are not changed."),
        bound_parameters={"target_id": str(target.public_id)},
    )


async def handle_unlock_account(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.services.security_service import SecurityService

    target = await _security_target(arguments, context, "unlock accounts")
    if str(target.public_id) != str(arguments.get(f"{BOUND_PREFIX}target_id")):
        raise ConflictError("The account no longer matches the one confirmed; ask again.")
    user, was_locked = await SecurityService(context.session).unlock(target.public_id, actor=context.user)
    return {
        "success": True, "user": _display_name(user), "was_locked": was_locked,
        "message": f"{_display_name(user)} is unlocked." if was_locked else f"{_display_name(user)} was not locked; nothing changed.",
    }


unlock_account_tool = ToolDefinition(
    name="unlock_account",
    description="Clear a sign-in lockout (failed attempts and lock). Does not change status or sign-in permission. Confirmed first.",
    policy=ToolPolicy(name="unlock_account", description="Unlock an account", required_permissions=("security.manage",),
                      allowed_roles=_SA, risk_level=RiskLevel.HIGH, requires_confirmation=True, audit_action="UPDATE"),
    parameters_schema={"type": "object", "properties": {"user": {"type": "string", "description": "Email, username or full name"}},
                       "required": ["user"]},
    handler=handle_unlock_account,
    preview=preview_unlock_account,
)


async def preview_revoke_sessions(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    target = await _security_target(arguments, context, "end sessions")
    return ConfirmationPreview(
        summary=f"Sign {_display_name(target)} ({target.email}) out everywhere: end every active session on every device.",
        bound_parameters={"target_id": str(target.public_id)},
    )


async def handle_revoke_sessions(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.services.security_service import SecurityService

    target = await _security_target(arguments, context, "end sessions")
    if str(target.public_id) != str(arguments.get(f"{BOUND_PREFIX}target_id")):
        raise ConflictError("The account no longer matches the one confirmed; ask again.")
    count = await SecurityService(context.session).revoke_all_for_user(target.public_id, actor=context.user)
    return {"success": True, "user": _display_name(target), "sessions_ended": count,
            "message": f"Ended {count} session(s) for {_display_name(target)}."}


revoke_user_sessions_tool = ToolDefinition(
    name="revoke_user_sessions",
    description="Sign a person out everywhere by ending all their sessions (e.g. a suspected compromise). Confirmed first.",
    policy=ToolPolicy(name="revoke_user_sessions", description="End a person's sessions",
                      required_permissions=("security.manage",), allowed_roles=_SA, risk_level=RiskLevel.HIGH,
                      requires_confirmation=True, audit_action="UPDATE"),
    parameters_schema={"type": "object", "properties": {"user": {"type": "string"}}, "required": ["user"]},
    handler=handle_revoke_sessions,
    preview=preview_revoke_sessions,
)


async def handle_search_audit_log(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.schemas.base import PageParams
    from backend.services.audit_query_service import AuditQueryService

    _require_super_admin(context.user, "search the audit log")

    def when(key: str) -> datetime | None:
        raw = str(arguments.get(key) or "").strip()
        if not raw:
            return None
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValidationError(f"{key} must be an ISO date or date-time.") from exc
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    actor_id = None
    if arguments.get("actor"):
        actor_id = (await _find_user(context, arguments["actor"])).public_id
    actions = [str(a).strip().upper() for a in (arguments.get("actions") or []) if str(a).strip()] or None
    success = arguments.get("success")
    limit = max(1, min(int(arguments.get("limit") or 20), _MAX_ROWS))
    date_from = when("date_from")
    if date_from is None and not any(arguments.get(k) for k in ("date_to", "actor", "query")):
        date_from = datetime.now(UTC) - timedelta(days=30)
    rows, total, _ = await AuditQueryService(context.session).search(
        PageParams(limit=limit, offset=0), actions=actions, actor_id=actor_id,
        entity_type=(str(arguments.get("entity_type") or "").strip() or None),
        success=success if isinstance(success, bool) else None,
        date_from=date_from, date_to=when("date_to"),
        query=(str(arguments.get("query") or "").strip() or None),
    )
    return {
        "total": total, "shown": len(rows),
        "events": [
            {"when": _iso(r.created_at), "action": r.action, "success": r.success,
             "actor": r.actor_email or r.actor_username or "system",
             "entity": f"{r.entity_type} {r.entity_label or ''}".strip() if r.entity_type else None,
             "ip": r.ip_address,
             "location": (r.location.city or r.location.country) if r.location and r.location.status == "OK" else None,
             "details": r.details}
            for r in rows
        ],
    }


search_audit_log_tool = ToolDefinition(
    name="search_audit_log",
    description=(
        "Search the audit trail: by action (e.g. LOGIN, LOGIN_FAILED, CREATE, UPDATE, DELETE, ACCOUNT_LOCKED), actor, "
        "entity type, success, date range and free text. Defaults to the last 30 days."
    ),
    policy=ToolPolicy(name="search_audit_log", description="Search the audit log", required_permissions=("audit.read",),
                      allowed_roles=_SA, risk_level=RiskLevel.LOW),
    parameters_schema={"type": "object", "properties": {
        "actions": {"type": "array", "items": {"type": "string"}},
        "actor": {"type": "string", "description": "Email, username or full name of who did it"},
        "entity_type": {"type": "string"},
        "success": {"type": "boolean"},
        "date_from": {"type": "string"}, "date_to": {"type": "string"},
        "query": {"type": "string"},
        "limit": {"type": "integer", "description": "At most 50"},
    }},
    handler=handle_search_audit_log,
)


# =============================================================================
# Configuration
# =============================================================================


async def handle_get_system_settings(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.schemas.base import PageParams
    from backend.services.setting_service import SettingService

    _require_super_admin(context.user, "read system settings")
    service = SettingService(context.session)
    key = str(arguments.get("key") or "").strip()
    if key:
        try:
            s = await service.get(key)
        except NotFoundError:
            return {"key": key, "exists": False, "message": f"No setting named '{key}' is stored."}
        return {"key": s.key, "exists": True, "value": s.value, "description": s.description}
    rows, total = await service.list(PageParams(limit=200, offset=0), prefix=(str(arguments.get("prefix") or "").strip() or None))
    return {"total": total, "settings": [{"key": s.key, "value": s.value, "description": s.description} for s in rows]}


get_system_settings_tool = ToolDefinition(
    name="get_system_settings",
    description="Read system settings: one by key, or all (optionally those starting with a prefix such as 'sync.').",
    policy=ToolPolicy(name="get_system_settings", description="Read system settings",
                      required_permissions=("setting.read",), allowed_roles=_SA, risk_level=RiskLevel.LOW),
    parameters_schema={"type": "object", "properties": {"key": {"type": "string"}, "prefix": {"type": "string"}}},
    handler=handle_get_system_settings,
)


async def _setting_change(arguments: dict[str, Any], context: ToolExecutionContext) -> tuple[str, str, str | None]:
    _require_super_admin(context.user, "change system settings")
    key = str(arguments.get("key") or "").strip()
    if not key or len(key) > 255:
        raise ValidationError("Give the setting's key.")
    if "value" not in arguments or arguments.get("value") is None:
        raise ValidationError("Give the new value.")
    value = str(arguments["value"])
    from backend.services.setting_service import SettingService

    try:
        current = (await SettingService(context.session).get(key)).value
    except NotFoundError:
        current = None
    return key, value, current


async def preview_update_system_setting(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    key, value, current = await _setting_change(arguments, context)
    before = f"from '{current}'" if current is not None else "(a new setting)"
    return ConfirmationPreview(
        summary=f"Change system setting '{key}' {before} to '{value}'. This affects everyone using the platform.",
        bound_parameters={"key": key, "value": value},
    )


async def handle_update_system_setting(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.schemas.administration import SettingWriteRequest
    from backend.services.setting_service import SettingService

    key, value, current = await _setting_change(arguments, context)
    if key != arguments.get(f"{BOUND_PREFIX}key") or value != arguments.get(f"{BOUND_PREFIX}value"):
        raise ConflictError("The setting no longer matches what was confirmed; ask again.")
    saved = await SettingService(context.session).put(key, SettingWriteRequest(value=value), actor=context.user)
    return {"success": True, "key": saved.key, "previous": current, "value": saved.value,
            "message": f"Setting '{saved.key}' is now '{saved.value}'."}


update_system_setting_tool = ToolDefinition(
    name="update_system_setting",
    description="Change (or create) a system setting by key. The Super Admin confirms the old and new value first.",
    policy=ToolPolicy(name="update_system_setting", description="Change a system setting",
                      required_permissions=("setting.update",), allowed_roles=_SA, risk_level=RiskLevel.HIGH,
                      requires_confirmation=True, audit_action="UPDATE"),
    parameters_schema={"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
                       "required": ["key", "value"]},
    handler=handle_update_system_setting,
    preview=preview_update_system_setting,
)


# =============================================================================
# Enrolments
# =============================================================================


async def _enrollment_change(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    _require_super_admin(context.user, "manage enrolments")
    student = await _find_user(context, arguments.get("student"))
    code = str(arguments.get("batch_code") or "").strip()
    batch = (await context.session.execute(select(Batch).where(Batch.batch_code == code))).scalar_one_or_none()
    if batch is None:
        raise NotFoundError(f"Batch '{code}' not found.")
    action = str(arguments.get("action") or "enroll").strip().lower()
    if action == "enroll":
        # The service's own preconditions, checked before the Super Admin is
        # asked to confirm. Driven live, a COMPLETED course was refused only
        # after confirmation -- a dialog that approves something impossible.
        from backend.models.enrollment import Enrollments
        from backend.services.enrollment_service import EnrollmentService, _ENROLLABLE_COURSE_STATUSES

        EnrollmentService._assert_is_student(student)
        if not batch.is_active:
            raise ConflictError(f"Batch {code} is not accepting enrolments.")
        if batch.course is not None and batch.course.status not in _ENROLLABLE_COURSE_STATUSES:
            raise ConflictError(
                f"Batch {code}'s course is {batch.course.status.value}, so it is not open for enrolment."
            )
        live = (
            await context.session.execute(
                select(Enrollments.enrollment_id).where(
                    Enrollments.student_id == student.id, Enrollments.batch_id == batch.id,
                    Enrollments.status.in_((EnrollmentStatus.PENDING, EnrollmentStatus.CONFIRMED)),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if live is not None:
            raise ConflictError(f"{_display_name(student)} is already enrolled in batch {code}.")
        return {"action": "enroll", "student": student, "batch": batch, "status": None}
    if action != "set_status":
        raise ValidationError("action must be 'enroll' or 'set_status'.")
    try:
        status = EnrollmentStatus(str(arguments.get("status") or "").strip().upper())
    except ValueError as exc:
        raise ValidationError(f"status must be one of {', '.join(s.value for s in EnrollmentStatus)}.") from exc
    from backend.models.enrollment import Enrollments

    current = (
        await context.session.execute(
            select(Enrollments).where(Enrollments.student_id == student.id, Enrollments.batch_id == batch.id)
            .order_by(Enrollments.enrollment_date.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if current is None:
        raise NotFoundError(f"{_display_name(student)} has no enrolment in batch {code}.")
    return {"action": "set_status", "student": student, "batch": batch, "status": status, "enrollment": current}


async def preview_manage_enrollment(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    c = await _enrollment_change(arguments, context)
    who, course = _display_name(c["student"]), c["batch"].course.title if c["batch"].course else ""
    if c["action"] == "enroll":
        summary = f"Enrol {who} ({c['student'].email}) in batch {c['batch'].batch_code} ({course}) as CONFIRMED. They are notified."
        bound = {"action": "enroll", "student": str(c["student"].public_id), "batch": str(c["batch"].public_id)}
    else:
        summary = (f"Change {who}'s enrolment in batch {c['batch'].batch_code} ({course}) from "
                   f"{c['enrollment'].status.value} to {c['status'].value}.")
        bound = {"action": "set_status", "enrollment": str(c["enrollment"].public_id), "status": c["status"].value}
    return ConfirmationPreview(summary=summary, bound_parameters={"change": bound})


async def handle_manage_enrollment(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.services.enrollment_service import EnrollmentService

    c = await _enrollment_change(arguments, context)
    bound = arguments.get(f"{BOUND_PREFIX}change") or {}
    service = EnrollmentService(context.session)
    if c["action"] == "enroll":
        if bound != {"action": "enroll", "student": str(c["student"].public_id), "batch": str(c["batch"].public_id)}:
            raise ConflictError("The enrolment no longer matches what was confirmed; ask again.")
        row = await service.enroll(student_public_id=c["student"].public_id, batch_public_id=c["batch"].public_id,
                                   confirmed=True, actor=context.user)
    else:
        if bound != {"action": "set_status", "enrollment": str(c["enrollment"].public_id), "status": c["status"].value}:
            raise ConflictError("The enrolment no longer matches what was confirmed; ask again.")
        row = await service.set_status(c["enrollment"].public_id, c["status"], actor=context.user)
    return {"success": True, "student": _display_name(c["student"]), "batch": c["batch"].batch_code,
            "status": row.status.value,
            "message": f"{_display_name(c['student'])} is {row.status.value} in batch {c['batch'].batch_code}."}


manage_enrollment_tool = ToolDefinition(
    name="manage_enrollment",
    description=(
        "Enrol a student in a batch (action 'enroll'), or change an existing enrolment's status (action 'set_status': "
        "e.g. DROPPED, CANCELLED, COMPLETED). Goes through the enrolment rules (capacity, open batch, notifications). "
        "Confirmed first."
    ),
    policy=ToolPolicy(name="manage_enrollment", description="Manage an enrolment",
                      required_permissions=("enrollment.create", "enrollment.update"), allowed_roles=_SA,
                      risk_level=RiskLevel.HIGH, requires_confirmation=True, audit_action="UPDATE"),
    parameters_schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["enroll", "set_status"]},
        "student": {"type": "string", "description": "Email, username or full name"},
        "batch_code": {"type": "string"},
        "status": {"type": "string", "description": "For set_status"},
    }, "required": ["action", "student", "batch_code"]},
    handler=handle_manage_enrollment,
    preview=preview_manage_enrollment,
)


SUPERADMIN_TOOLS = (
    find_users_tool,
    create_user_tool,
    get_security_overview_tool,
    unlock_account_tool,
    revoke_user_sessions_tool,
    search_audit_log_tool,
    get_system_settings_tool,
    update_system_setting_tool,
    manage_enrollment_tool,
)
