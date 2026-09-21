"""Guardian ↔ student link endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.core.privacy import visible_username
from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.guardian import StudentGuardian
from backend.schemas.base import Page, PageParams
from backend.schemas.guardian import (
    CreateGuardianLinkRequest,
    GuardianLinkResponse,
    UpdateGuardianLinkRequest,
)
from backend.services.guardian_service import GuardianService

router = APIRouter(prefix="/guardian-links", tags=["Guardians"])


def _response(link: StudentGuardian) -> GuardianLinkResponse:
    return GuardianLinkResponse(
        public_id=link.public_id,
        guardian_id=link.guardian.public_id,
        guardian_username=visible_username(link.guardian),
        guardian_name=link.guardian.full_name,
        student_id=link.student.public_id,
        student_username=visible_username(link.student),
        student_name=link.student.full_name,
        relationship_type=link.relationship_type,
        is_primary=link.is_primary,
        created_at=link.created_at,
    )


@router.get("", response_model=Page[GuardianLinkResponse], summary="List guardian links")
async def list_links(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.GUARDIAN, Action.READ)))
    ],
    guardian_id: Annotated[uuid.UUID | None, Query()] = None,
    student_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[GuardianLinkResponse]:
    """Scoped: without `institution.view_all` a caller sees only links they
    are part of — as the guardian, or as the student."""
    rows, total = await GuardianService(session).list_links(
        params, actor=actor, guardian_public_id=guardian_id, student_public_id=student_id
    )
    return Page.build([_response(r) for r in rows], total=total, params=params)


@router.post(
    "",
    response_model=GuardianLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Link a guardian to a student",
)
async def create_link(
    payload: CreateGuardianLinkRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.GUARDIAN, Action.CREATE)))
    ],
) -> GuardianLinkResponse:
    """Administrative only. The GUARDIAN role holds `guardian.read` and not
    `guardian.create`, because "I am this child's guardian" is a claim rather
    than a fact — the institution has to be the one asserting it.

    Creating the link is what grants that guardian sight of the student's
    enrollments, attendance and grades.
    """
    return _response(await GuardianService(session).create(payload, actor=actor))


@router.get("/{link_id}", response_model=GuardianLinkResponse, summary="Get one guardian link")
async def get_link(
    link_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.GUARDIAN, Action.READ)))
    ],
) -> GuardianLinkResponse:
    return _response(await GuardianService(session).get(link_id, actor=actor))


@router.patch(
    "/{link_id}", response_model=GuardianLinkResponse, summary="Update a guardian link"
)
async def update_link(
    link_id: uuid.UUID,
    payload: UpdateGuardianLinkRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.GUARDIAN, Action.UPDATE)))
    ],
) -> GuardianLinkResponse:
    """Promoting a link to primary demotes whichever guardian previously held
    it — a student has at most one primary contact."""
    return _response(await GuardianService(session).update(link_id, payload, actor=actor))


@router.delete(
    "/{link_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a guardian link"
)
async def delete_link(
    link_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.GUARDIAN, Action.DELETE)))
    ],
) -> Response:
    """Ends the guardian's access to that student's records immediately."""
    await GuardianService(session).delete(link_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
