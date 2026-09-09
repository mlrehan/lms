"""Role and permission endpoints (spec §20, §23)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.schemas.role import (
    PermissionResponse,
    RoleCreateRequest,
    RolePermissionsRequest,
    RoleResponse,
    RoleUpdateRequest,
)
from backend.services.role_service import RoleService

router = APIRouter(tags=["Roles & permissions"])


def _to_response(role) -> RoleResponse:  # type: ignore[no-untyped-def]
    return RoleResponse(
        name=role.name,
        description=role.description,
        permissions=sorted(p.name for p in (role.permissions or [])),
    )


# =============================================================================
# ROLES
# =============================================================================


@router.get(
    "/roles",
    response_model=list[RoleResponse],
    summary="List all roles",
    dependencies=[Depends(require_permissions(perm(Module.ROLE, Action.READ)))],
)
async def list_roles(session: DBSession) -> list[RoleResponse]:
    """Not paginated: the role catalog is a handful of rows by design, and
    paging it would add a page-loop to every client for no benefit."""
    return [_to_response(r) for r in await RoleService(session).list_roles()]


@router.post(
    "/roles",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom role",
)
async def create_role(
    payload: RoleCreateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.ROLE, Action.CREATE)))],
) -> RoleResponse:
    return _to_response(await RoleService(session).create_role(payload, actor=actor))


@router.get(
    "/roles/{role_name}",
    response_model=RoleResponse,
    summary="Get one role",
    dependencies=[Depends(require_permissions(perm(Module.ROLE, Action.READ)))],
)
async def get_role(role_name: str, session: DBSession) -> RoleResponse:
    return _to_response(await RoleService(session).get_role(role_name))


@router.patch(
    "/roles/{role_name}",
    response_model=RoleResponse,
    summary="Update a role's description",
)
async def update_role(
    role_name: str,
    payload: RoleUpdateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.ROLE, Action.UPDATE)))],
) -> RoleResponse:
    return _to_response(await RoleService(session).update_role(role_name, payload, actor=actor))


@router.put(
    "/roles/{role_name}/permissions",
    response_model=RoleResponse,
    summary="Replace a role's permissions",
)
async def set_role_permissions(
    role_name: str,
    payload: RolePermissionsRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.PERMISSION, Action.MANAGE)))
    ],
) -> RoleResponse:
    """Gated on `permission.manage`, which spec §2 withholds from
    Administrator -- changing what a role can do is the single most
    privilege-sensitive operation in the system."""
    return _to_response(
        await RoleService(session).set_permissions(role_name, payload.permissions, actor=actor)
    )


@router.delete(
    "/roles/{role_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a custom role",
)
async def delete_role(
    role_name: str,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.ROLE, Action.DELETE)))],
) -> Response:
    await RoleService(session).delete_role(role_name, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# PERMISSIONS
# =============================================================================


@router.get(
    "/permissions",
    response_model=list[PermissionResponse],
    summary="List the permission catalog",
    dependencies=[Depends(require_permissions(perm(Module.PERMISSION, Action.READ)))],
)
async def list_permissions(
    session: DBSession,
    module: Annotated[str | None, Query(max_length=50)] = None,
) -> list[PermissionResponse]:
    rows = await RoleService(session).list_permissions(module=module)
    return [PermissionResponse.model_validate(p) for p in rows]
