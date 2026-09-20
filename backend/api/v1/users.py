"""User administration endpoints (spec §4)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.schemas.base import Page, PageParams
from backend.schemas.user import (
    AdminSetPasswordRequest,
    UserCreateRequest,
    UserLoginAccessRequest,
    UserLoginAccessResponse,
    UserResponse,
    UserRolesRequest,
    UserStatusRequest,
    UserSummary,
    UserUpdateRequest,
)
from backend.services.user_service import UserService
from backend.utils.enums import UserStatus

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "",
    response_model=Page[UserSummary],
    summary="List and search users",
)
async def list_users(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.USER, Action.READ)))],
    query: Annotated[str | None, Query(max_length=100, description="Match username, email or name.")] = None,
    account_status: Annotated[UserStatus | None, Query(alias="status")] = None,
    role: Annotated[str | None, Query(max_length=50)] = None,
) -> Page[UserSummary]:
    """Row-scoped: a Tutor sees the students in batches they teach, a
    Guardian their linked students, a Corporate Manager their organization's
    employees. Only `institution.view_all` returns the whole directory."""
    users, total = await UserService(session).list_users(
        params, actor=actor, query=query, status=account_status, role=role
    )
    return Page.build(
        [UserSummary.model_validate(u) for u in users], total=total, params=params
    )


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user",
)
async def create_user(
    payload: UserCreateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.USER, Action.CREATE)))],
) -> UserResponse:
    user = await UserService(session).create(payload, actor=actor)
    return UserResponse.model_validate(user)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get one user",
)
async def get_user(
    user_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.USER, Action.READ)))],
) -> UserResponse:
    """Out-of-scope ids answer 404, not 403 -- a 403 would confirm that the
    account exists, which is exactly what someone probing ids is after."""
    return UserResponse.model_validate(await UserService(session).get(user_id, actor=actor))


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="Update a user's profile",
)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.USER, Action.UPDATE)))],
) -> UserResponse:
    user = await UserService(session).update(user_id, payload, actor=actor)
    return UserResponse.model_validate(user)


@router.put(
    "/{user_id}/status",
    response_model=UserResponse,
    summary="Activate, deactivate or suspend a user",
)
async def set_user_status(
    user_id: uuid.UUID,
    payload: UserStatusRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.USER, Action.UPDATE)))],
) -> UserResponse:
    """Anything other than ACTIVE also ends every session that user holds."""
    user = await UserService(session).set_status(user_id, payload.status, actor=actor)
    return UserResponse.model_validate(user)


@router.put(
    "/{user_id}/login-access",
    response_model=UserLoginAccessResponse,
    summary="Allow or block a user from signing in",
)
async def set_login_access(
    user_id: uuid.UUID,
    payload: UserLoginAccessRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.USER, Action.ALLOW_LOGIN)))],
) -> UserLoginAccessResponse:
    """Accounts provisioned from LAIT start blocked. Turning this on while the
    shared default password is still set is allowed but flagged in the response."""
    user, default_in_use = await UserService(session).set_login_access(
        user_id, payload.can_login, actor=actor
    )
    return UserLoginAccessResponse(can_login=user.can_login, default_password_in_use=default_in_use)


@router.put(
    "/{user_id}/roles",
    response_model=UserResponse,
    summary="Replace a user's roles",
)
async def set_user_roles(
    user_id: uuid.UUID,
    payload: UserRolesRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.ROLE, Action.UPDATE)))],
) -> UserResponse:
    """Gated on `role.update`, not `user.update`: granting roles is how
    privilege is escalated, so it is a strictly narrower capability than
    editing a phone number."""
    user = await UserService(session).set_roles(user_id, payload.roles, actor=actor)
    return UserResponse.model_validate(user)


@router.put(
    "/{user_id}/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a user's password (administrator)",
)
async def set_user_password(
    user_id: uuid.UUID,
    payload: AdminSetPasswordRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.USER, Action.UPDATE)))],
) -> Response:
    await UserService(session).set_password(user_id, payload.new_password, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user",
)
async def delete_user(
    user_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.USER, Action.DELETE)))],
) -> Response:
    """Soft delete: the row is retained because `audit_logs` and
    `enrollments` reference it, but the account is gone from every listing
    and cannot sign in."""
    await UserService(session).soft_delete(user_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
