"""Security operations (spec §20): lockouts, live sessions, incident feed.

The audit trail answers "what has happened"; this module answers the three
questions an administrator has *while something is happening*: who is locked
out, who is signed in, and what has been failing.

**Every action here is itself audited.** Unlocking an account and ending
someone else's session are exactly the moves an attacker with an
administrator's credentials would make, so they are recorded with the same
weight as a permission change. An incident-response tool that leaves no trace
of the response is a gap in the trail precisely where it matters most.

**Unlocking is not "set the account active".** Until now the only way to
clear a lockout was to push the account through `SetUserStatus` to ACTIVE,
which clears the counters as a *side effect* — so an already-active locked
account could only be freed by setting a status it already had, and an
administrator had no reason to guess that. This is the deliberate operation,
and it does not touch `status`: an account can be both suspended and locked,
and unlocking must not silently reinstate someone the institution suspended.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, NotFoundError
from backend.models.identity.token import Token
from backend.models.identity.user import User
from backend.repositories.audit import AuditRepository
from backend.repositories.token import TokenRepository
from backend.schemas.audit import (
    AdminSessionResponse,
    LockedAccountResponse,
    SecuritySummaryResponse,
)
from backend.schemas.base import PageParams
from backend.services import audit_service
from backend.core.notification_types import NotificationType
from backend.services.audit_service import AuditAction
from backend.services.notification_service import NotificationService

DEFAULT_SUMMARY_HOURS = 24
MAX_SUMMARY_HOURS = 24 * 90


def _now() -> datetime:
    return datetime.now(UTC)


def _locked_out_sql(now: datetime):  # type: ignore[no-untyped-def]
    """The WHERE-clause form of `User.is_locked_out`, minus the flag itself.

    A NULL `locked_until` means an indefinite lock, matching the property. The
    two are separate expressions only because SQLAlchemy cannot push a Python
    property into SQL; `tests` assert they never diverge.
    """
    return or_(User.locked_until.is_(None), User.locked_until > now)


class SecurityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logs = AuditRepository(session)
        self.tokens = TokenRepository(session)

    # -- reads ---------------------------------------------------------------

    async def summary(self, *, hours: int = DEFAULT_SUMMARY_HOURS) -> SecuritySummaryResponse:
        now = _now()
        since = now - timedelta(hours=hours)

        return SecuritySummaryResponse(
            window_hours=hours,
            failed_logins=await self.logs.count_since(
                actions=(AuditAction.LOGIN_FAILED,), since=since
            ),
            accounts_locked_now=await self._locked_count(now),
            lockout_events=await self.logs.count_since(
                actions=(AuditAction.ACCOUNT_LOCKED,), since=since
            ),
            token_reuse_detections=await self.logs.count_since(
                actions=(AuditAction.TOKEN_REUSE_DETECTED,), since=since
            ),
            permission_changes=await self.logs.count_since(
                actions=(AuditAction.PERMISSION_CHANGE,), since=since
            ),
            active_sessions=await self._active_session_count(now),
            generated_at=now,
        )

    async def locked_accounts(
        self, params: PageParams, *, include_expired: bool = False
    ) -> tuple[list[LockedAccountResponse], int]:
        now = _now()
        stmt = select(User).where(User.is_locked.is_(True))
        if not include_expired:
            # `_locked_out_sql` is the SQL mirror of `User.is_locked_out` --
            # a Python property cannot run in a WHERE clause. A test asserts
            # the two agree on every state, because a third reading of "is
            # this account locked out?" is exactly what this phase found.
            # A lock whose expiry has passed is over -- the row simply has not
            # been cleared yet, because that happens on the next successful
            # sign-in. Listing those as "locked" would send an administrator
            # to unlock accounts nobody is shut out of.
            stmt = stmt.where(_locked_out_sql(now))
        stmt = stmt.order_by(User.locked_until.desc().nullslast(), User.id)

        rows, total = await self._paginate_users(stmt, params)
        return [
            LockedAccountResponse(
                public_id=u.public_id,
                username=u.username,
                email=u.email,
                full_name=u.full_name,
                failed_login_attempts=u.failed_login_attempts or 0,
                locked_until=u.locked_until,
                is_expired=bool(u.locked_until is not None and u.locked_until <= now),
            )
            for u in rows
        ], total

    async def sessions(
        self, params: PageParams, *, user_public_id: uuid.UUID | None = None
    ) -> tuple[list[AdminSessionResponse], int]:
        """Live refresh-token sessions across the institution.

        The token hash is never selected, let alone returned. A session list
        exists so an administrator can *end* a session, and being able to end
        one has never required being able to use it.
        """
        now = _now()
        stmt = (
            select(Token, User)
            .join(User, Token.user_id == User.id)
            .where(Token.revoked.is_(False), Token.expires_at > now)
        )
        if user_public_id is not None:
            stmt = stmt.where(User.id == (await self._load_user(user_public_id)).id)
        stmt = stmt.order_by(Token.created_at.desc(), Token.id.desc())

        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = int((await self.session.execute(count_stmt)).scalar_one())
        rows = (
            await self.session.execute(stmt.limit(params.limit).offset(params.offset))
        ).all()

        return [
            AdminSessionResponse(
                public_id=token.public_id,
                user_id=user.public_id,
                username=user.username,
                created_at=token.created_at,
                expires_at=token.expires_at,
                user_agent=token.user_agent,
                ip_address=token.ip_address,
            )
            for token, user in rows
        ], total

    # -- writes --------------------------------------------------------------

    async def unlock(self, public_id: uuid.UUID, *, actor: User) -> tuple[User, bool]:
        """Clear a failed-login lockout. Returns `(user, was_locked)`.

        Deliberately idempotent: unlocking an account that is not locked is a
        success, not a 409. An administrator responding to "I can't sign in"
        should not have to establish *why* first, and a refusal here would
        send them looking for a second, non-existent problem.
        """
        user = await self._load_user(public_id)
        was_locked = bool(user.is_locked)

        user.is_locked = False
        user.locked_until = None
        user.failed_login_attempts = 0

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="user",
            entity_id=user.id,
            details={"security": "account_unlocked", "was_locked": was_locked},
        )

        if was_locked:
            await NotificationService(self.session).notify(
                user_id=user.id,
                type_=NotificationType.ACCOUNT_UNLOCKED,
                title="Your account was unlocked",
                body="An administrator cleared the lock on your account. You can sign in again.",
            )
        return user, was_locked

    async def revoke_session(self, public_id: uuid.UUID, *, actor: User) -> None:
        stmt = select(Token).where(Token.public_id == public_id, Token.revoked.is_(False))
        token = (await self.session.execute(stmt)).scalar_one_or_none()
        if token is None:
            raise NotFoundError("Session not found.")

        await self.tokens.revoke(token)
        audit_service.record(
            self.session,
            action=AuditAction.SESSION_REVOKED,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="token",
            entity_id=token.id,
            details={"revoked_for_user_id": token.user_id, "by": "security_admin"},
        )

    async def revoke_all_for_user(self, public_id: uuid.UUID, *, actor: User) -> int:
        user = await self._load_user(public_id)
        if user.id == actor.id:
            # Not a safety rail so much as a routing one: ending your own
            # sessions is `/auth/logout-all`, which knows to clear the
            # caller's own cookies. Doing it through the incident-response
            # endpoint would sign the administrator out mid-incident with no
            # indication of why.
            raise ConflictError(
                "Use /auth/logout-all to end your own sessions.",
            )

        revoked = await self.tokens.revoke_all_for_user(user.id)
        audit_service.record(
            self.session,
            action=AuditAction.LOGOUT_ALL,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="user",
            entity_id=user.id,
            details={"sessions_revoked": revoked, "by": "security_admin"},
        )

        # `notify`, not `emit`. Both deliver a mandatory type, but only
        # `notify` routes through `wants()` -- which is where "mandatory
        # types ignore opt-outs" actually lives. Calling `emit` skipped that
        # rule rather than relying on it, so removing the rule broke nothing
        # and no test could tell. `wants()` short-circuits on a mandatory
        # type without querying, so the check costs nothing either.
        await NotificationService(self.session).notify(
            user_id=user.id,
            type_=NotificationType.SESSIONS_REVOKED,
            title="Your sessions were ended",
            body=(
                "An administrator signed you out of every device. "
                "If this was not expected, contact the institution."
            ),
            meta={"sessions_revoked": revoked},
        )
        return revoked

    # -- helpers -------------------------------------------------------------

    async def _locked_count(self, now: datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(User)
            .where(User.is_locked.is_(True), _locked_out_sql(now))
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def _active_session_count(self, now: datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(Token)
            .where(Token.revoked.is_(False), Token.expires_at > now)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def _paginate_users(self, stmt, params: PageParams):  # type: ignore[no-untyped-def]
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = int((await self.session.execute(count_stmt)).scalar_one())
        rows = (
            (await self.session.execute(stmt.limit(params.limit).offset(params.offset)))
            .scalars()
            .unique()
            .all()
        )
        return rows, total

    async def _load_user(self, public_id: uuid.UUID) -> User:
        stmt = select(User).where(User.public_id == public_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise NotFoundError("User not found.")
        return user

