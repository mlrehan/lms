"""Authentication endpoints (spec §3)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response, status

from backend.api.deps import AuthServiceDep, CurrentUser, UserAgent, resolve_permissions
from backend.core.context import get_client_ip
from backend.core.errors import NotFoundError
from backend.db.dependencies import DBSession
from backend.repositories.token import TokenRepository
from backend.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    SessionResponse,
    TokenResponse,
)
from backend.schemas.user import CurrentUserResponse
from backend.security.refresh_tokens import hash_refresh_token
from backend.services import audit_service
from backend.services.audit_service import AuditAction

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse, summary="Sign in with an email or username")
async def login(
    payload: LoginRequest,
    auth: AuthServiceDep,
    session: DBSession,
    user_agent: UserAgent,
) -> TokenResponse:
    user = await auth.authenticate(
        identifier=payload.identifier,
        raw_password=payload.password,
        user_agent=user_agent,
    )
    issued = await auth.issue_tokens(
        user,
        remember_me=payload.remember_me,
        user_agent=user_agent,
        ip_address=get_client_ip(),
    )
    audit_service.record(
        session,
        action=AuditAction.LOGIN,
        actor_user_id=user.id,
        actor_email=user.email,
        user_agent=user_agent,
    )
    return TokenResponse(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_in=issued.expires_in,
    )


@router.post("/refresh", response_model=TokenResponse, summary="Exchange a refresh token")
async def refresh(
    payload: RefreshRequest,
    auth: AuthServiceDep,
    user_agent: UserAgent,
) -> TokenResponse:
    """Rotates: the presented token is revoked and a new pair returned.

    Presenting an already-spent token revokes *every* session for that user
    -- see `AuthService._handle_refresh_miss`.
    """
    _user, issued = await auth.refresh(
        raw_refresh_token=payload.refresh_token,
        user_agent=user_agent,
        ip_address=get_client_ip(),
    )
    return TokenResponse(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_in=issued.expires_in,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="End this session")
async def logout(
    payload: LogoutRequest,
    auth: AuthServiceDep,
    current_user: CurrentUser,
) -> Response:
    await auth.logout(raw_refresh_token=payload.refresh_token, user=current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End every session on every device",
)
async def logout_all(auth: AuthServiceDep, current_user: CurrentUser) -> Response:
    await auth.logout_all(current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=CurrentUserResponse, summary="The signed-in user")
async def me(current_user: CurrentUser) -> CurrentUserResponse:
    response = CurrentUserResponse.model_validate(current_user)
    # Permissions are derived from roles rather than stored on the user, so
    # they are the one field the ORM object cannot supply directly.
    response.permissions = sorted(resolve_permissions(current_user))
    return response


@router.post(
    "/password/change",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change your own password",
)
async def change_password(
    payload: ChangePasswordRequest,
    auth: AuthServiceDep,
    current_user: CurrentUser,
) -> Response:
    """Succeeds only with the current password, and ends every session --
    including this one, so the caller must sign in again."""
    await auth.change_password(
        current_user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/sessions",
    response_model=list[SessionResponse],
    summary="List your active sessions",
)
async def list_sessions(
    session: DBSession,
    current_user: CurrentUser,
    request: Request,
) -> list[SessionResponse]:
    """Spec §3's 'Session management' -- which devices am I signed in on."""
    tokens = TokenRepository(session)
    rows = await tokens.list_active_for_user(current_user.id)

    # If the caller sent their refresh token as a hint, mark which row is
    # this session so a UI can label it "current device" and avoid offering
    # to revoke the session the user is presently using.
    presented = request.headers.get("x-refresh-token")
    current_hash = hash_refresh_token(presented) if presented else None

    return [
        SessionResponse(
            public_id=row.public_id,
            created_at=row.created_at,
            expires_at=row.expires_at,
            user_agent=row.user_agent,
            ip_address=row.ip_address,
            is_current=bool(current_hash and row.token_hash == current_hash),
        )
        for row in rows
    ]


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke one of your sessions",
)
async def revoke_session(
    session_id: uuid.UUID,
    session: DBSession,
    current_user: CurrentUser,
) -> Response:
    tokens = TokenRepository(session)
    row = await tokens.get_active_for_user_by_public_id(current_user.id, session_id)
    if row is None:
        # Scoped to the caller, so another user's real session id lands here
        # too -- 404 rather than 403, which would confirm it exists.
        raise NotFoundError("Session not found.")

    await tokens.revoke(row)
    audit_service.record(
        session,
        action=AuditAction.SESSION_REVOKED,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        entity_type="token",
        entity_id=row.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
