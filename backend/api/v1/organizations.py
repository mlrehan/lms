"""Corporate organization, manager and membership endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.core.privacy import visible_email, visible_username
from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.organization import OrganizationManager, OrganizationMembership
from backend.schemas.base import Page, PageParams
from backend.schemas.organization import (
    AddMemberRequest,
    AppointManagerRequest,
    ManagerResponse,
    MembershipResponse,
    MembershipStatusRequest,
    OrganizationCreateRequest,
    OrganizationResponse,
    OrganizationSummary,
    OrganizationUpdateRequest,
)
from backend.services.organization_service import OrganizationService
from backend.utils.enums import OrganizationMembershipStatus

router = APIRouter(prefix="/organizations", tags=["Organizations"])


def _manager_response(m: OrganizationManager) -> ManagerResponse:
    return ManagerResponse(
        public_id=m.public_id,
        user_id=m.user.public_id,
        username=visible_username(m.user),
        full_name=m.user.full_name,
        email=visible_email(m.user),
        title=m.title,
        is_active=m.is_active,
        invited_at=m.invited_at,
    )


def _membership_response(m: OrganizationMembership) -> MembershipResponse:
    return MembershipResponse(
        public_id=m.public_id,
        user_id=m.user.public_id,
        username=visible_username(m.user),
        full_name=m.user.full_name,
        email=visible_email(m.user),
        employee_code=m.employee_code,
        department=m.department,
        status=m.status,
        invited_at=m.invited_at,
        joined_at=m.joined_at,
        organization_id=m.organization.public_id,
        organization_name=m.organization.name,
    )


# =============================================================================
# ORGANIZATIONS
# =============================================================================


@router.get("", response_model=Page[OrganizationSummary], summary="List organizations")
async def list_organizations(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ORGANIZATION, Action.READ)))
    ],
    query: Annotated[str | None, Query(max_length=100)] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> Page[OrganizationSummary]:
    """Row-scoped, with no browsing case: a Corporate Manager sees only the
    organization they manage. Unlike the course catalogue, one company has no
    business enumerating the others."""
    orgs, total = await OrganizationService(session).list_organizations(
        params, actor=actor, query=query, is_active=is_active
    )
    return Page.build(
        [OrganizationSummary.model_validate(o) for o in orgs], total=total, params=params
    )


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an organization",
)
async def create_organization(
    payload: OrganizationCreateRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ORGANIZATION, Action.CREATE)))
    ],
) -> OrganizationResponse:
    org = await OrganizationService(session).create(payload, actor=actor)
    return OrganizationResponse.model_validate(org)


@router.get(
    "/{organization_id}", response_model=OrganizationResponse, summary="Get one organization"
)
async def get_organization(
    organization_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ORGANIZATION, Action.READ)))
    ],
) -> OrganizationResponse:
    service = OrganizationService(session)
    org = await service.get(organization_id, actor=actor)
    managers, members = await service.counts(org)
    response = OrganizationResponse.model_validate(org)
    response.manager_count = managers
    response.member_count = members
    return response


@router.patch(
    "/{organization_id}", response_model=OrganizationResponse, summary="Update an organization"
)
async def update_organization(
    organization_id: uuid.UUID,
    payload: OrganizationUpdateRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ORGANIZATION, Action.UPDATE)))
    ],
) -> OrganizationResponse:
    org = await OrganizationService(session).update(organization_id, payload, actor=actor)
    return OrganizationResponse.model_validate(org)


@router.delete(
    "/{organization_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an empty organization",
)
async def delete_organization(
    organization_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ORGANIZATION, Action.DELETE)))
    ],
) -> Response:
    """Refused while it still has current members."""
    await OrganizationService(session).soft_delete(organization_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# MANAGERS
# =============================================================================


@router.get(
    "/{organization_id}/managers",
    response_model=list[ManagerResponse],
    summary="List an organization's managers",
)
async def list_managers(
    organization_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ORGANIZATION, Action.READ)))
    ],
    include_inactive: Annotated[bool, Query()] = False,
) -> list[ManagerResponse]:
    rows = await OrganizationService(session).list_managers(
        organization_id, actor=actor, include_inactive=include_inactive
    )
    return [_manager_response(m) for m in rows]


@router.post(
    "/{organization_id}/managers",
    response_model=ManagerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Appoint a manager",
)
async def appoint_manager(
    organization_id: uuid.UUID,
    payload: AppointManagerRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ORGANIZATION, Action.APPOINT)))
    ],
) -> ManagerResponse:
    """Appointing somebody manager of a company **grants no student**.

    It used to grant all of them: a manager saw every employee of every
    company they managed. Students are assigned one at a time now, on
    `/manager-links`, so an appointment is a statement about the company and
    nothing about anybody's records.

    Still gated on `organization.appoint`, which Corporate Managers
    deliberately do not hold -- a manager who could appoint co-managers could
    put a colleague in a position to be assigned their roster without the
    institution's involvement.

    A user manages at most one organization at a time.
    """
    return _manager_response(
        await OrganizationService(session).appoint_manager(organization_id, payload, actor=actor)
    )


@router.delete(
    "/{organization_id}/managers/{manager_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a manager appointment",
)
async def revoke_manager(
    organization_id: uuid.UUID,
    manager_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ORGANIZATION, Action.APPOINT)))
    ],
) -> Response:
    """Deactivates rather than deletes: who had access to these employees'
    data, and when, is exactly what an audit would ask about."""
    await OrganizationService(session).revoke_manager(organization_id, manager_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# MEMBERS
# =============================================================================


@router.get(
    "/{organization_id}/members",
    response_model=Page[MembershipResponse],
    summary="List an organization's employees",
)
async def list_members(
    organization_id: uuid.UUID,
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ORGANIZATION, Action.READ)))
    ],
    membership_status: Annotated[
        OrganizationMembershipStatus | None, Query(alias="status")
    ] = None,
) -> Page[MembershipResponse]:
    rows, total = await OrganizationService(session).list_members(
        params,
        actor=actor,
        organization_public_id=organization_id,
        status=membership_status,
    )
    return Page.build([_membership_response(m) for m in rows], total=total, params=params)


@router.post(
    "/{organization_id}/members",
    response_model=MembershipResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add or invite an employee",
)
async def add_member(
    organization_id: uuid.UUID,
    payload: AddMemberRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ORGANIZATION, Action.INVITE)))
    ],
) -> MembershipResponse:
    """A user belongs to at most one organization at a time. Adding someone
    who already belongs elsewhere is refused with a 409 naming the other
    organization, rather than silently moving them."""
    return _membership_response(
        await OrganizationService(session).add_member(organization_id, payload, actor=actor)
    )


@router.put(
    "/{organization_id}/members/{membership_id}/status",
    response_model=MembershipResponse,
    summary="Activate, suspend or remove an employee",
)
async def set_member_status(
    organization_id: uuid.UUID,
    membership_id: uuid.UUID,
    payload: MembershipStatusRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ORGANIZATION, Action.INVITE)))
    ],
) -> MembershipResponse:
    """INVITED → ACTIVE, and ACTIVE ⇄ SUSPENDED, with REMOVED as the exit.
    REMOVED is terminal: re-hiring creates a fresh membership rather than
    resurrecting the old one, so the previous spell of employment stays
    intact.

    Removing someone also deletes their assignments to this company's
    managers, so those managers lose access to their records at once. That
    used to follow from the status alone, when visibility was read from this
    row; it is now an explicit act, because a separate table grants it."""
    return _membership_response(
        await OrganizationService(session).set_member_status(
            membership_id, payload.status, organization_public_id=organization_id, actor=actor
        )
    )
