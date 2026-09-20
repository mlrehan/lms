"""Authentication: sign-in, token issuance, rotation, and revocation (spec §3).

Three things in here are subtle enough to be worth reading before changing:

1. **Failed logins are written in an independent transaction.** The request
   is about to raise a 401, and raising rolls back the request's transaction
   -- which would take the `failed_login_attempts` increment with it. The
   counter would sit at zero forever and the lockout would never fire, while
   every test that checks "wrong password returns 401" still passes. See
   `audit_service.record_independently` and `_register_failed_attempt`.

2. **Login is constant-work whether or not the account exists.** A missing
   user still costs one Argon2 verification against a real dummy hash, so
   response time doesn't answer "is this address registered?". The dummy is
   *computed* at import from a real hash function rather than pasted in as a
   literal -- a hand-written fake hash fails to parse, returns early, and
   silently removes the very timing protection it was added for.

3. **Refresh tokens rotate, and reuse is treated as a breach.** Presenting a
   token that was already exchanged means two parties hold it: the rightful
   owner and someone who copied it. There is no way to tell which one is
   asking, so every session for that user is revoked and both are forced to
   sign in again.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.config import SecuritySettings
from backend.core.errors import AuthenticationError
from backend.core.logging import get_logger
from backend.models.identity.token import Token
from backend.models.identity.user import User
from backend.repositories.token import TokenRepository
from backend.repositories.user import UserRepository
from backend.security import password as pwd
from backend.security.jwt import JWTService
from backend.security.refresh_tokens import generate_refresh_token, hash_refresh_token
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.utils.enums import TokenType, UserStatus

logger = get_logger(__name__)

# A genuine Argon2 hash of a value no one can present, computed once at
# import. Verifying against this costs the same as verifying a real user's
# password, which is the entire point -- see the module docstring.
_DUMMY_PASSWORD_HASH = pwd.hash_password(uuid.uuid4().hex)


class IssuedTokens:
    __slots__ = ("access_token", "refresh_token", "expires_in")

    def __init__(self, *, access_token: str, refresh_token: str, expires_in: int) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_in = expires_in


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        jwt_service: JWTService,
        settings: SecuritySettings,
    ) -> None:
        self.session = session
        # Used only for writes that must survive the request raising --
        # see the module docstring.
        self._session_factory = session_factory
        self._jwt = jwt_service
        self._settings = settings
        self.users = UserRepository(session)
        self.tokens = TokenRepository(session)

    # -- sign in -------------------------------------------------------------

    async def authenticate(
        self,
        *,
        identifier: str,
        raw_password: str,
        user_agent: str | None,
    ) -> User:
        user = await self.users.get_by_identifier(identifier)

        if user is None:
            # Burn equivalent time, then refuse identically to a wrong
            # password. The caller cannot tell the two apart.
            pwd.verify_password(_DUMMY_PASSWORD_HASH, raw_password)
            await audit_service.record_independently(
                self._session_factory,
                action=AuditAction.LOGIN_FAILED,
                actor_email=identifier[:320],
                success=False,
                details={"reason": "unknown_identifier"},
                user_agent=user_agent,
            )
            raise AuthenticationError("Incorrect credentials.")

        if self._is_locked_out(user):
            await audit_service.record_independently(
                self._session_factory,
                action=AuditAction.LOGIN_FAILED,
                actor_user_id=user.id,
                actor_email=user.email,
                success=False,
                details={"reason": "account_locked"},
                user_agent=user_agent,
            )
            raise AuthenticationError(
                "This account is temporarily locked after repeated failed sign-in attempts."
            )

        if not pwd.verify_password(user.hashed_password, raw_password):
            await self._register_failed_attempt(user, user_agent=user_agent)
            raise AuthenticationError("Incorrect credentials.")

        # Status is checked *after* the password, and reported with the same
        # message: checking first would let anyone probe which accounts are
        # suspended without knowing a single password.
        #
        # `can_login` rides on the same rule for the same reason. Accounts
        # provisioned from LAIT are ACTIVE but ship with a shared default
        # password, so the *correct* password alone must not be enough --
        # and the refusal must be word-for-word the wrong-password one, or
        # a caller who guesses the default learns that guess was right.
        if not user.is_login_permitted:
            await audit_service.record_independently(
                self._session_factory,
                action=AuditAction.LOGIN_FAILED,
                actor_user_id=user.id,
                actor_email=user.email,
                success=False,
                details={
                    "reason": (
                        f"status_{user.status.value.lower()}"
                        if user.status is not UserStatus.ACTIVE
                        else "login_not_enabled"
                    )
                },
                user_agent=user_agent,
            )
            raise AuthenticationError("Incorrect credentials.")

        # Success. These writes belong to the request's own transaction.
        user.failed_login_attempts = 0
        user.is_locked = False
        user.locked_until = None
        user.last_login = datetime.now(UTC)

        # Transparent hash upgrade: if the stored hash predates a cost-
        # parameter increase, this is the one moment we hold the plaintext
        # and can re-hash it without involving the user.
        if pwd.needs_rehash(user.hashed_password):
            user.hashed_password = pwd.hash_password(raw_password)

        return user

    def _is_locked_out(self, user: User) -> bool:
        # Delegates to `User.is_locked_out`. This method used to hold its own
        # copy of the rule and disagreed with the one on the request path --
        # see that property's docstring.
        return user.is_locked_out

    async def _register_failed_attempt(self, user: User, *, user_agent: str | None) -> None:
        """Increment the failure counter and lock if the threshold is hit.

        Runs in its own transaction (see module docstring): the caller raises
        immediately after, and that rollback would otherwise discard this.
        """
        attempts = (user.failed_login_attempts or 0) + 1
        should_lock = attempts >= self._settings.max_failed_login_attempts
        locked_until = (
            datetime.now(UTC) + timedelta(seconds=self._settings.lockout_duration_seconds)
            if should_lock
            else None
        )

        try:
            async with self._session_factory.begin() as s:
                fresh = await s.get(User, user.id)
                if fresh is not None:
                    fresh.failed_login_attempts = attempts
                    if should_lock:
                        fresh.is_locked = True
                        fresh.locked_until = locked_until
        except Exception:  # noqa: BLE001 - must not mask the 401
            logger.exception("Failed to record failed-login attempt", extra={"user_id": user.id})

        await audit_service.record_independently(
            self._session_factory,
            action=AuditAction.ACCOUNT_LOCKED if should_lock else AuditAction.LOGIN_FAILED,
            actor_user_id=user.id,
            actor_email=user.email,
            success=False,
            details={"reason": "bad_password", "attempts": attempts},
            user_agent=user_agent,
        )

    # -- token issuance ------------------------------------------------------

    async def issue_tokens(
        self,
        user: User,
        *,
        remember_me: bool = False,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> IssuedTokens:
        access_token = self._jwt.create_access_token(subject=user.public_id)

        raw_refresh = generate_refresh_token()
        ttl = (
            self._settings.remember_me_refresh_token_ttl_seconds
            if remember_me
            else self._settings.refresh_token_ttl_seconds
        )

        self.tokens.add(
            Token(
                user_id=user.id,
                token_hash=hash_refresh_token(raw_refresh),
                token_type=TokenType.REFRESH,
                expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
                user_agent=(user_agent or None) and user_agent[:255],
                ip_address=ip_address,
            )
        )

        return IssuedTokens(
            access_token=access_token,
            refresh_token=raw_refresh,
            expires_in=self._jwt.access_ttl_seconds,
        )

    # -- rotation ------------------------------------------------------------

    async def refresh(
        self,
        *,
        raw_refresh_token: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[User, IssuedTokens]:
        token_hash = hash_refresh_token(raw_refresh_token)
        session_row = await self.tokens.get_active_by_hash(token_hash)

        if session_row is None:
            await self._handle_refresh_miss(token_hash, user_agent=user_agent)
            raise AuthenticationError("Invalid or expired session.")

        user = await self.users.get_by_id_with_roles(session_row.user_id)
        if user is None or not user.is_login_permitted:
            # The session outlived the account's ability to use it -- a user
            # suspended five minutes ago must not be able to mint a fresh
            # access token from a refresh token issued before that.
            await self.tokens.revoke_all_for_user(session_row.user_id)
            raise AuthenticationError("Invalid or expired session.")

        # Rotation: the presented token is spent the moment it is accepted,
        # so a copy of it is worthless from here on.
        await self.tokens.revoke(session_row)

        issued = await self.issue_tokens(
            user,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        audit_service.record(
            self.session,
            action=AuditAction.TOKEN_REFRESH,
            actor_user_id=user.id,
            actor_email=user.email,
            user_agent=user_agent,
        )
        return user, issued

    async def _handle_refresh_miss(self, token_hash: str, *, user_agent: str | None) -> None:
        """Distinguish "never existed" from "already used", and treat the
        second as a compromise."""
        known = await self.tokens.get_by_hash_any_state(token_hash)
        if known is None or not known.revoked:
            return

        # Replay of a spent token. We cannot tell the legitimate holder from
        # the thief, so we end every session and make both re-authenticate.
        try:
            async with self._session_factory.begin() as s:
                repo = TokenRepository(s)
                await repo.revoke_all_for_user(known.user_id)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to revoke sessions after token reuse", extra={"user_id": known.user_id})

        await audit_service.record_independently(
            self._session_factory,
            action=AuditAction.TOKEN_REUSE_DETECTED,
            actor_user_id=known.user_id,
            success=False,
            details={"reason": "refresh_token_replayed"},
            user_agent=user_agent,
        )
        logger.warning("Refresh token reuse detected", extra={"user_id": known.user_id})

    # -- revocation ----------------------------------------------------------

    async def logout(self, *, raw_refresh_token: str, user: User) -> None:
        session_row = await self.tokens.get_active_by_hash(hash_refresh_token(raw_refresh_token))
        # Only the owner may end a session with this call; a token belonging
        # to someone else is ignored rather than revoked.
        if session_row is not None and session_row.user_id == user.id:
            await self.tokens.revoke(session_row)

        audit_service.record(
            self.session,
            action=AuditAction.LOGOUT,
            actor_user_id=user.id,
            actor_email=user.email,
        )

    async def logout_all(self, user: User) -> int:
        revoked = await self.tokens.revoke_all_for_user(user.id)
        audit_service.record(
            self.session,
            action=AuditAction.LOGOUT_ALL,
            actor_user_id=user.id,
            actor_email=user.email,
            details={"sessions_revoked": revoked},
        )
        return revoked

    async def change_password(
        self,
        user: User,
        *,
        current_password: str,
        new_password: str,
    ) -> None:
        if not pwd.verify_password(user.hashed_password, current_password):
            await audit_service.record_independently(
                self._session_factory,
                action=AuditAction.PASSWORD_CHANGED,
                actor_user_id=user.id,
                actor_email=user.email,
                success=False,
                details={"reason": "current_password_incorrect"},
            )
            raise AuthenticationError("The current password is incorrect.")

        user.hashed_password = pwd.hash_password(new_password)

        # Changing a password must end every other session, or a stolen
        # session survives the exact action taken to stop it.
        await self.tokens.revoke_all_for_user(user.id)
        audit_service.record(
            self.session,
            action=AuditAction.PASSWORD_CHANGED,
            actor_user_id=user.id,
            actor_email=user.email,
        )
