"""Security endpoints (spec §20): incidents, lockouts, live sessions.

Gated on `security.*`, not `audit.*`. The two are separated so a future
SECURITY_OFFICER role can respond to incidents — see who is locked out, end a
compromised session — without also being handed the institution's entire
change history, which is what `audit.read` grants.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.core.privacy import visible_username
from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession, commit_before_responding
from backend.schemas.audit import (
    AdminSessionResponse,
    AuditLogResponse,
    LockedAccountResponse,
    RevocationResponse,
    SecuritySummaryResponse,
    UnlockResponse,
)
from backend.schemas.base import Page, PageParams
from backend.services.audit_query_service import SECURITY_ACTIONS, AuditQueryService
from backend.services.security_service import (
    DEFAULT_SUMMARY_HOURS,
    MAX_SUMMARY_HOURS,
    SecurityService,
)

router = APIRouter(prefix="/security", tags=["Security"])

_READ = require_permissions(perm(Module.SECURITY, Action.READ))
_MANAGE = require_permissions(perm(Module.SECURITY, Action.MANAGE))


@router.get("/summary", response_model=SecuritySummaryResponse, summary="Security posture")
async def summary(
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
    hours: Annotated[int, Query(ge=1, le=MAX_SUMMARY_HOURS)] = DEFAULT_SUMMARY_HOURS,
) -> SecuritySummaryResponse:
    """Counts over a window, plus two live figures — accounts locked *now*
    and sessions active *now* — which are deliberately not windowed: "how
    many people are shut out at this moment" is not a question about the last
    24 hours."""
    return await SecurityService(session).summary(hours=hours)


@router.get("/events", response_model=Page[AuditLogResponse], summary="Security events")
async def security_events(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(_READ)],
    action: Annotated[
        list[str] | None, Query(description="Narrow within the security set.")
    ] = None,
    actor_id: Annotated[uuid.UUID | None, Query()] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query(description="Exclusive.")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[AuditLogResponse]:
    """The audit trail narrowed to the eight actions that describe an
    incident — failed sign-ins, lockouts, refresh-token reuse, password
    changes and resets, permission changes, and session revocations.

    Successful sign-ins are deliberately excluded: they are the highest-volume
    rows in the table and would bury everything anyone opens this screen to
    find. They stay one filter away on `/audit-logs?action=LOGIN`.

    A caller-supplied `action` can only *narrow* this set, never widen it —
    passing `CREATE` returns nothing rather than turning this into a second,
    less-privileged audit-log endpoint.
    """
    allowed = set(SECURITY_ACTIONS)
    actions = sorted(allowed.intersection(action)) if action else list(SECURITY_ACTIONS)
    if action and not actions:
        # Every requested action was outside the security set. Returning the
        # full set here would silently ignore the filter and show more than
        # was asked for, which is the wrong direction to fail on this surface.
        return Page.build([], total=0, params=params)

    rows, total, _ = await AuditQueryService(session).search(
        params,
        actions=actions,
        actor_id=actor_id,
        date_from=date_from,
        date_to=date_to,
        query=q,
    )
    return Page.build(rows, total=total, params=params)


@router.get(
    "/locked-accounts",
    response_model=Page[LockedAccountResponse],
    summary="Accounts locked out",
)
async def locked_accounts(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(_READ)],
    include_expired: Annotated[
        bool, Query(description="Include locks whose expiry has already passed.")
    ] = False,
) -> Page[LockedAccountResponse]:
    """By default only accounts *currently* shut out. A lock whose
    `locked_until` has passed is over — the flag is simply still set, because
    it is cleared on the next successful sign-in — and listing those would
    send an administrator to unlock people who are not locked out."""
    rows, total = await SecurityService(session).locked_accounts(
        params, include_expired=include_expired
    )
    return Page.build(rows, total=total, params=params)


@router.post(
    "/accounts/{user_id}/unlock",
    response_model=UnlockResponse,
    summary="Clear a failed-login lockout",
)
async def unlock_account(
    user_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_MANAGE)],
) -> UnlockResponse:
    """Clears the lock and the failed-attempt counter, and **does not touch
    `status`** — an account can be both suspended and locked, and unlocking
    must not quietly reinstate somebody the institution suspended.

    Idempotent: unlocking an account that is not locked succeeds and reports
    `was_locked: false`. An administrator answering "I can't sign in" should
    not have to diagnose why before they are allowed to act.
    """
    user, was_locked = await SecurityService(session).unlock(user_id, actor=actor)
    # "Try signing in now" has to be true when the administrator reads this
    # response -- see `commit_before_responding`.
    await commit_before_responding(session)
    return UnlockResponse(
        public_id=user.public_id, username=visible_username(user), was_locked=was_locked
    )


@router.get(
    "/sessions", response_model=Page[AdminSessionResponse], summary="Live sessions"
)
async def list_sessions(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(_READ)],
    user_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[AdminSessionResponse]:
    """Every unrevoked, unexpired refresh-token session in the institution.

    The token hash is never selected, let alone returned: ending a session has
    never required being able to use it.
    """
    rows, total = await SecurityService(session).sessions(params, user_public_id=user_id)
    return Page.build(rows, total=total, params=params)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke any session",
)
async def revoke_session(
    session_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_MANAGE)],
) -> Response:
    """The administrative counterpart to `/auth/sessions/{id}`, which is
    scoped to the caller's own. Recorded in the audit trail like any other
    privileged act — ending someone's session is exactly what an attacker
    holding an administrator's credentials would do."""
    await SecurityService(session).revoke_session(session_id, actor=actor)
    await commit_before_responding(session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/accounts/{user_id}/sessions/revoke-all",
    response_model=RevocationResponse,
    summary="End every session for one account",
)
async def revoke_all_sessions(
    user_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_MANAGE)],
) -> RevocationResponse:
    """The containment action for a compromised account. Refuses the caller's
    own id with a 409 pointing at `/auth/logout-all` — doing this to yourself
    through the incident-response route would sign you out mid-incident with
    nothing explaining why."""
    revoked = await SecurityService(session).revoke_all_for_user(user_id, actor=actor)
    # Containment: the sessions must be dead by the time this returns, or the
    # count is a claim about the future rather than a report.
    await commit_before_responding(session)
    return RevocationResponse(revoked=revoked)
