"""Batch endpoints addressed directly (spec §6).

Creation lives under `/courses/{id}/batches` because a batch cannot exist
without a course. Reads and edits live here, at `/batches/{id}`, because once
it exists a batch is its own resource and a client holding its id should not
need to know the course's.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.core.privacy import may_see_pricing
from backend.db.dependencies import DBSession
from backend.models.batch import BatchSession
from backend.models.identity.user import User
from backend.schemas.base import Page, PageParams
from backend.schemas.batch import BatchResponse, BatchSummary, BatchUpdateRequest
from backend.services.batch_service import BatchService
from backend.services.mail_audience import display_name

router = APIRouter(prefix="/batches", tags=["Batches"])


async def summarise(session, batches) -> list[BatchSummary]:  # type: ignore[no-untyped-def]
    """The list rows, with the figures a table shows beside each batch -- computed for the whole page in two queries,
    not one per row: how many sessions, the next one, and who teaches most of them."""
    ids = [b.id for b in batches]
    counts: dict[int, int] = {}
    upcoming: dict[int, datetime] = {}
    tutors: dict[int, str] = {}
    if ids:
        now = datetime.now(timezone.utc)
        for bid, n, nxt in (await session.execute(
            select(BatchSession.batch_id, func.count(), func.min(BatchSession.session_start_time).filter(BatchSession.session_start_time >= now))
            .where(BatchSession.batch_id.in_(ids), BatchSession.cancelled_at.is_(None)).group_by(BatchSession.batch_id)
        )).all():
            counts[bid], upcoming[bid] = int(n), nxt
        top: dict[int, tuple[int, int]] = {}
        for bid, tid, n in (await session.execute(
            select(BatchSession.batch_id, BatchSession.tutor_id, func.count())
            .where(BatchSession.batch_id.in_(ids), BatchSession.cancelled_at.is_(None)).group_by(BatchSession.batch_id, BatchSession.tutor_id)
        )).all():
            if bid not in top or n > top[bid][1]:
                top[bid] = (tid, int(n))
        names = {u.id: display_name(u) for u in (await session.execute(select(User).where(User.id.in_({t for t, _ in top.values()})))).scalars().unique()} if top else {}
        tutors = {bid: names[tid] for bid, (tid, _) in top.items() if tid in names}

    out = []
    for b in batches:
        item = BatchSummary.model_validate(b)
        item.course_title = b.course.title if b.course else None
        # Withheld here, not in the table's column list: a column the client
        # declines to draw is still in the payload, and the batch list is the
        # one screen that was publishing the fee to every role.
        item.batch_fee = (
            float(b.batch_fee) if b.batch_fee is not None and may_see_pricing() else None
        )
        item.session_count, item.next_session_start, item.tutor_name = counts.get(b.id, 0), upcoming.get(b.id), tutors.get(b.id)
        out.append(item)
    return out


async def batch_response(service: BatchService, batch) -> BatchResponse:  # type: ignore[no-untyped-def]
    occupied, remaining = await service.seat_counts(batch)
    # Who teaches most of this batch's sessions -- the same figure the list column shows. Derived rather than
    # stored, because a batch has no tutor of its own: its sessions do, and they need not all share one.
    tutor_name = None
    top = (await service.session.execute(
        select(BatchSession.tutor_id, func.count())
        .where(BatchSession.batch_id == batch.id, BatchSession.cancelled_at.is_(None))
        .group_by(BatchSession.tutor_id).order_by(func.count().desc()).limit(1)
    )).first()
    if top and top[0] is not None:
        person = (await service.session.execute(select(User).where(User.id == top[0]))).scalars().first()
        tutor_name = display_name(person) if person else None
    return BatchResponse(
        tutor_name=tutor_name,
        public_id=batch.public_id,
        batch_code=batch.batch_code,
        is_active=batch.is_active,
        start_date=batch.start_date,
        end_date=batch.end_date,
        capacity=batch.capacity,
        total_enrollments=batch.total_enrollments,
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
        training_days=batch.training_days,
        training_method=batch.training_method,
        training_start_day=batch.training_start_day,
        training_end_day=batch.training_end_day,
        training_start_time=batch.training_start_time.strftime("%H:%M") if batch.training_start_time else None,
        training_end_time=batch.training_end_time.strftime("%H:%M") if batch.training_end_time else None,
        class_duration_minutes=batch.class_duration_minutes,
        batch_fee=(
            float(batch.batch_fee)
            if batch.batch_fee is not None and may_see_pricing()
            else None
        ),
        schedule_timezone=batch.schedule_timezone,
    )


@router.get("", response_model=Page[BatchSummary], summary="List batches")
async def list_batches(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.BATCH, Action.READ)))],
    is_active: Annotated[bool | None, Query()] = None,
    tutor_id: Annotated[uuid.UUID | None, Query(description="Batches this person takes sessions for.")] = None,
    student_id: Annotated[uuid.UUID | None, Query(description="Batches this person is enrolled in.")] = None,
    q: Annotated[str | None, Query(max_length=100, description="Batch code, course title, method or days.")] = None,
    sort: Annotated[str | None, Query(pattern="^(batch_code|course|start_date|end_date|enrolled|capacity|fee|method|state)$")] = None,
    direction: Annotated[str, Query(alias="dir", pattern="^(asc|desc)$")] = "asc",
) -> Page[BatchSummary]:
    """Row-scoped: a Tutor sees the batches they teach, a Student the batch
    they are enrolled in, a Guardian or Corporate Manager the batches of the
    people they are responsible for."""
    batches, total = await BatchService(session).list_batches(
        params, actor=actor, is_active=is_active, query=q, sort=sort,
        descending=direction == "desc", tutor_public_id=tutor_id, student_public_id=student_id,
    )
    return Page.build(await summarise(session, batches), total=total, params=params)


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
