"""Corporate manager ↔ student link endpoints.

The company and the roster are now separate surfaces. `/organizations/*`
records employment -- who works where, their employee code, which company
sponsors an enrolment. These routes record *access*: which students a
particular manager may read. Appointing somebody a manager no longer hands
them the whole company.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.core.privacy import visible_username
from backend.db.dependencies import DBSession
from backend.models.organization import ManagedStudent
from backend.schemas.base import Page, PageParams
from backend.schemas.managed_student import (
    CreateManagedStudentRequest,
    ManagedStudentResponse,
    UpdateManagedStudentRequest,
)
from backend.services.managed_student_service import ManagedStudentService

router = APIRouter(prefix="/manager-links", tags=["Corporate managers"])


def _response(link: ManagedStudent) -> ManagedStudentResponse:
    return ManagedStudentResponse(
        public_id=link.public_id,
        manager_id=link.manager.public_id,
        manager_username=visible_username(link.manager),
        manager_name=link.manager.full_name,
        student_id=link.student.public_id,
        student_username=visible_username(link.student),
        student_name=link.student.full_name,
        relationship_type=link.relationship_type,
        is_primary=link.is_primary,
        created_at=link.created_at,
    )


@router.get("", response_model=Page[ManagedStudentResponse], summary="List manager links")
async def list_links(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.MANAGED_STUDENT, Action.READ)))
    ],
    manager_id: Annotated[uuid.UUID | None, Query()] = None,
    student_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[ManagedStudentResponse]:
    """Scoped: without `institution.view_all` a caller sees only links they
    are part of — as the manager, or as the student. A Corporate Manager
    reading their own roster is the ordinary case."""
    rows, total = await ManagedStudentService(session).list_links(
        params, actor=actor, manager_public_id=manager_id, student_public_id=student_id
    )
    return Page.build([_response(r) for r in rows], total=total, params=params)


@router.post(
    "",
    response_model=ManagedStudentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Link a manager to a student",
)
async def create_link(
    payload: CreateManagedStudentRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.MANAGED_STUDENT, Action.CREATE)))
    ],
) -> ManagedStudentResponse:
    """Administrative only. The CORPORATE_MANAGER role holds
    `managed_student.read` and not `.create`, because a manager adding
    somebody to their own roster would be asserting their own access — the
    same reason a guardian cannot create their own guardianship.

    Creating the link is what grants that manager sight of the student's
    enrollments, attendance and grades. Employment is not required and is not
    checked: a link can exist without a company, and sharing a company grants
    nothing by itself.
    """
    return _response(await ManagedStudentService(session).create(payload, actor=actor))


@router.get(
    "/{link_id}", response_model=ManagedStudentResponse, summary="Get one manager link"
)
async def get_link(
    link_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.MANAGED_STUDENT, Action.READ)))
    ],
) -> ManagedStudentResponse:
    return _response(await ManagedStudentService(session).get(link_id, actor=actor))


@router.patch(
    "/{link_id}", response_model=ManagedStudentResponse, summary="Update a manager link"
)
async def update_link(
    link_id: uuid.UUID,
    payload: UpdateManagedStudentRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.MANAGED_STUDENT, Action.UPDATE)))
    ],
) -> ManagedStudentResponse:
    """Promoting a link to primary demotes whichever manager previously held
    it — a student has at most one first point of contact."""
    return _response(
        await ManagedStudentService(session).update(link_id, payload, actor=actor)
    )


@router.delete(
    "/{link_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a manager link"
)
async def delete_link(
    link_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.MANAGED_STUDENT, Action.DELETE)))
    ],
) -> Response:
    """Ends that manager's access to the student's records immediately."""
    await ManagedStudentService(session).delete(link_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
