"""Batch endpoints addressed directly (spec §6).

Creation lives under `/courses/{id}/batches` because a batch cannot exist
without a course. Reads and edits live here, at `/batches/{id}`, because once
it exists a batch is its own resource and a client holding its id should not
need to know the course's.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.schemas.base import Page, PageParams
from backend.schemas.batch import BatchResponse, BatchSummary, BatchUpdateRequest
from backend.services.batch_service import BatchService

router = APIRouter(prefix="/batches", tags=["Batches"])


async def batch_response(service: BatchService, batch) -> BatchResponse:  # type: ignore[no-untyped-def]
    occupied, remaining = await service.seat_counts(batch)
    return BatchResponse(
        public_id=batch.public_id,
        batch_code=batch.batch_code,
        is_active=batch.is_active,
        start_date=batch.start_date,
        end_date=batch.end_date,
        capacity=batch.capacity,
        course_id=batch.course.public_id,
        course_title=batch.course.title,
        academic_year_id=batch.academic_year.public_id if batch.academic_year else None,
        academic_year_label=batch.academic_year.label if batch.academic_year else None,
        semester_id=batch.semester.public_id if batch.semester else None,
        semester_name=batch.semester.name if batch.semester else None,
        duration_hours=batch.duration_hours,
        number_of_sessions=batch.number_of_sessions,
        notes=batch.notes,
        enrolled_count=occupied,
        seats_available=remaining,
    )


@router.get("", response_model=Page[BatchSummary], summary="List batches")
async def list_batches(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.BATCH, Action.READ)))],
    is_active: Annotated[bool | None, Query()] = None,
) -> Page[BatchSummary]:
    """Row-scoped: a Tutor sees the batches they teach, a Student the batch
    they are enrolled in, a Guardian or Corporate Manager the batches of the
    people they are responsible for."""
    batches, total = await BatchService(session).list_batches(
        params, actor=actor, is_active=is_active
    )
    return Page.build(
        [BatchSummary.model_validate(b) for b in batches], total=total, params=params
    )


@router.get("/{batch_id}", response_model=BatchResponse, summary="Get one batch")
async def get_batch(
    batch_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.BATCH, Action.READ)))],
) -> BatchResponse:
    service = BatchService(session)
    return await batch_response(service, await service.get(batch_id, actor=actor))


@router.patch("/{batch_id}", response_model=BatchResponse, summary="Update a batch")
async def update_batch(
    batch_id: uuid.UUID,
    payload: BatchUpdateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.BATCH, Action.UPDATE)))],
) -> BatchResponse:
    """Capacity cannot be lowered below the number already enrolled."""
    service = BatchService(session)
    return await batch_response(service, await service.update(batch_id, payload, actor=actor))


@router.delete(
    "/{batch_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an empty batch"
)
async def delete_batch(
    batch_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.BATCH, Action.DELETE)))],
) -> Response:
    """Refused while anyone is enrolled -- deactivate it instead."""
    await BatchService(session).delete(batch_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
