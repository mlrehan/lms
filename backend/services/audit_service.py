"""Audit trail writing (spec §19).

Two entry points, and the difference between them is the whole point of this
module:

* :func:`record` writes into the **caller's** transaction. Correct for
  auditing an action that succeeded -- the audit row and the thing it
  describes commit or roll back together, so the log can never claim
  something happened that didn't.

* :func:`record_independently` opens its **own** session and commits
  immediately. Required for auditing a *refused* action, because the request
  that refused it is about to raise, and raising rolls the request's
  transaction back -- taking the record of the refusal with it. A security
  log that disappears precisely when something suspicious happens is worse
  than no log, because it reads as silence rather than as a gap.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.context import get_client_ip, get_client_ip_scope, get_request_id
from backend.integrations.geoip import get_locator
from backend.core.logging import get_logger
from backend.models.audit import AuditLog

logger = get_logger(__name__)


class AuditAction:
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    LOGOUT_ALL = "LOGOUT_ALL"
    TOKEN_REFRESH = "TOKEN_REFRESH"
    TOKEN_REUSE_DETECTED = "TOKEN_REUSE_DETECTED"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    PASSWORD_RESET_BY_ADMIN = "PASSWORD_RESET_BY_ADMIN"
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    PERMISSION_CHANGE = "PERMISSION_CHANGE"
    SESSION_REVOKED = "SESSION_REVOKED"
    # Spec §19 lists Uploads and Downloads as tracked events in their own
    # right; they were named in the AuditLog model's comment but had no
    # constant here, so the first caller to use one crashed.
    UPLOAD = "UPLOAD"
    DOWNLOAD = "DOWNLOAD"
    # One row per run of the LAIT user synchronisation, in addition to the
    # per-account CREATE/UPDATE rows the run produces.
    USER_SYNC = "USER_SYNC"
    ACADEMIC_SYNC = "ACADEMIC_SYNC"
    GOOGLE_SYNC = "GOOGLE_SYNC"
    GOOGLE_CONNECT = "GOOGLE_CONNECT"
    GOOGLE_DISCONNECT = "GOOGLE_DISCONNECT"
    # Who entered which class, and whether the join window was open at the
    # time. The link is handed out one request at a time precisely so that
    # there is something to record; without this row the endpoint would be a
    # permission check with no memory.
    CLASS_JOIN = "CLASS_JOIN"
    RECORDING_VIEW = "RECORDING_VIEW"
    AI_INTERACTION = "AI_INTERACTION"
    AI_CONFIRMED_ACTION = "AI_CONFIRMED_ACTION"
    AI_SECURITY_ALERT = "AI_SECURITY_ALERT"


def _build(
    *,
    action: str,
    actor_user_id: int | None,
    actor_email: str | None,
    entity_type: str | None,
    entity_id: int | None,
    success: bool,
    details: dict[str, Any] | None,
    user_agent: str | None,
) -> AuditLog:
    ip = get_client_ip()
    scope = get_client_ip_scope()
    geo: dict[str, Any] = {}
    if scope is not None:
        # Only for events a request caused; a scheduled job has no client to place.
        # A local file lookup that never raises: it cannot delay or lose this row.
        geo = get_locator().locate(ip, scope).as_columns()
    return AuditLog(
        **geo,
        ip_scope=scope,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        success=success,
        details=details,
        ip_address=get_client_ip(),
        user_agent=user_agent,
        request_id=get_request_id(),
    )


def record(
    session: AsyncSession,
    *,
    action: str,
    actor_user_id: int | None = None,
    actor_email: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    success: bool = True,
    details: dict[str, Any] | None = None,
    user_agent: str | None = None,
) -> None:
    """Stage an audit row in the caller's transaction."""
    session.add(
        _build(
            action=action,
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            entity_type=entity_type,
            entity_id=entity_id,
            success=success,
            details=details,
            user_agent=user_agent,
        )
    )


async def record_independently(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    action: str,
    actor_user_id: int | None = None,
    actor_email: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    success: bool = False,
    details: dict[str, Any] | None = None,
    user_agent: str | None = None,
) -> None:
    """Write an audit row in its own transaction, committed immediately.

    Never raises: a failure to write the audit row must not replace the
    error the caller was already reporting, which is virtually always the
    more useful one. The failure is logged instead.
    """
    try:
        async with session_factory.begin() as audit_session:
            audit_session.add(
                _build(
                    action=action,
                    actor_user_id=actor_user_id,
                    actor_email=actor_email,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    success=success,
                    details=details,
                    user_agent=user_agent,
                )
            )
    except Exception:  # noqa: BLE001 - see docstring
        logger.exception("Failed to write independent audit record", extra={"audit_action": action})
