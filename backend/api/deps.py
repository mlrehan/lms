"""Request dependencies: authentication, authorization, and service wiring.

**Why the caller is loaded from the database on every request.** The access
token proves *who* is asking, and nothing more -- it carries no roles and no
permissions. Those are read fresh each time. The cost is one indexed query;
what it buys is that revoking a role, suspending an account, or locking a
user takes effect on the very next request instead of whenever a token
happens to expire. Baking permissions into the token would make the hot path
cheaper and make "remove this person's access now" impossible to honour for
up to the full token lifetime.
"""

from __future__ import annotations

from typing import Annotated, Iterable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import Settings, get_settings
from backend.core.context import user_id_ctx
from backend.core.errors import AuthenticationError, AuthorizationError
from backend.db.dependencies import DBSession
from backend.db.manager import DatabaseManager
from backend.models.identity.user import User
from backend.repositories.user import UserRepository
from backend.security.jwt import JWTService
from backend.services.auth_service import AuthService
from backend.utils.enums import Roles, UserStatus

# `auto_error=False` so a missing header raises our own AuthenticationError
# (a `{code, message}` body like every other error) rather than FastAPI's
# default `{"detail": ...}` shape, which no client should have to special-case.
_bearer = HTTPBearer(auto_error=False)


def get_app_settings() -> Settings:
    return get_settings()


AppSettings = Annotated[Settings, Depends(get_app_settings)]


def get_jwt_service(settings: AppSettings) -> JWTService:
    return JWTService(settings.security)


JWTDep = Annotated[JWTService, Depends(get_jwt_service)]


def get_session_factory(request: Request):  # type: ignore[no-untyped-def]
    """The raw session factory, for services that must write outside the
    request transaction (failed-login counters, security audit rows)."""
    db: DatabaseManager = request.app.state.db
    return db.session_factory


SessionFactory = Annotated[object, Depends(get_session_factory)]


def get_auth_service(
    session: DBSession,
    settings: AppSettings,
    jwt_service: JWTDep,
    request: Request,
) -> AuthService:
    db: DatabaseManager = request.app.state.db
    return AuthService(
        session,
        session_factory=db.session_factory,
        jwt_service=jwt_service,
        settings=settings.security,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


# =============================================================================
# AUTHENTICATION
# =============================================================================


async def get_current_user(
    session: DBSession,
    jwt_service: JWTDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Authentication required.")

    claims = jwt_service.verify_access_token(credentials.credentials)

    users = UserRepository(session)
    user = await users.get_by_public_id_with_roles(claims.subject)

    # A token that is cryptographically valid but whose account is gone,
    # suspended or locked is refused here, and refused *identically* to a
    # bad token: telling a bearer which of those applies confirms the account
    # exists and describes its state to whoever holds a stolen token.
    #
    # `is_locked_out`, not the raw `is_locked` column: a lockout that has
    # lapsed is over, and reading the flag directly rejected a still-valid
    # token belonging to somebody who could sign in again perfectly well.
    if user is None or user.status is not UserStatus.ACTIVE or user.is_locked_out:
        raise AuthenticationError("Authentication required.")

    # Feeds the structured logger, so every log line emitted while handling
    # this request carries the acting user.
    user_id_ctx.set(str(user.public_id))
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


# =============================================================================
# AUTHORIZATION
# =============================================================================


def resolve_permissions(user: User) -> set[str]:
    """Flatten the caller's roles into the set of permission names they hold.

    Roles and their permissions were eager-loaded by the repository, so this
    walks objects already in memory rather than issuing further queries.
    """
    return {
        permission.name
        for role in (user.roles or [])
        for permission in (role.permissions or [])
    }


def require_permissions(*required: str, require_all: bool = True):
    """Dependency factory gating a route on permission names.

    ``require_all=True`` (the default) demands every listed permission.
    ``require_all=False`` accepts any one of them, for routes reachable by
    genuinely different roles for different reasons.

    The names are checked against the catalog at import time, not at request
    time: a typo in `require_permissions("corse.read")` would otherwise be a
    route that silently denies everyone, and would most likely be discovered
    in production by the person it locked out.
    """
    from backend.core.permissions import ALL_PERMISSIONS

    unknown = [name for name in required if name not in ALL_PERMISSIONS]
    if unknown:
        raise RuntimeError(
            f"require_permissions() references unknown permission(s): {', '.join(unknown)}. "
            "Add them to backend/core/permissions.py or fix the spelling."
        )

    async def dependency(user: CurrentUser) -> User:
        held = resolve_permissions(user)
        ok = held.issuperset(required) if require_all else bool(held.intersection(required))
        if not ok:
            missing = sorted(set(required) - held)
            raise AuthorizationError(
                "You do not have permission to perform this action.",
                details={"required": missing},
            )
        return user

    return dependency


def require_roles(*names: str):
    """Gate on role membership rather than a permission.

    Used sparingly and only where the *role itself* is the subject -- e.g. a
    Super-Admin-only operation whose danger comes from who you are, not from
    a capability that would sensibly be delegated. Everything else should
    gate on a permission, so grants stay editable without a code change.
    """
    allowed = {n.upper() for n in names}

    async def dependency(user: CurrentUser) -> User:
        if not {(r.name or "").upper() for r in (user.roles or [])} & allowed:
            raise AuthorizationError("You do not have permission to perform this action.")
        return user

    return dependency


def is_super_admin(user: User) -> bool:
    return any((r.name or "").upper() == Roles.SUPER_ADMIN.value for r in (user.roles or []))


# =============================================================================
# REQUEST METADATA
# =============================================================================


def get_user_agent(request: Request) -> str | None:
    agent = request.headers.get("user-agent")
    return agent[:255] if agent else None


UserAgent = Annotated[str | None, Depends(get_user_agent)]
