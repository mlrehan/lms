"""Calculated student performance (spec §15, §37).

Read-only, because there is nothing here to write: every input lives in the
module that owns it, and this only puts them together. §23's single source of
truth is a property of the service, and these routes inherit it by having no
way to store anything.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from backend.api.deps import CurrentUser, require_permissions
from backend.core.errors import NotFoundError
from backend.core.permissions import Action, Module, perm
from backend.core.privacy import visible_username
from backend.db.dependencies import DBSession
from backend.models.batch import Batch
from backend.models.identity.user import User
from backend.schemas.performance import ComponentLine, PerformanceResponse
from backend.services.performance_service import PerformanceService, StudentPerformance

router = APIRouter(tags=["Performance"])

_READ = require_permissions(perm(Module.PERFORMANCE, Action.READ))


def _response(row: StudentPerformance, *, student: User, batch: Batch) -> PerformanceResponse:
    p = row.performance
    return PerformanceResponse(
        student_id=student.public_id,
        student_name=visible_username(student),
        batch_id=batch.public_id,
        batch_code=batch.batch_code,
        scheme_name=row.scheme_name,
        components=[
            ComponentLine(
                component_type=c.component_type,
                label=c.label,
                weight_percentage=c.weight_percentage,
                percentage=c.percentage,
                contribution=c.contribution,
                marks_total=c.marks_total,
                marks_scored=c.marks_scored,
                counted=c.counted,
                excluded_reason=c.excluded_reason,
                is_mandatory=c.is_mandatory,
                meets_component_pass=c.meets_component_pass,
            )
            for c in p.components
        ],
        assessed_weight=p.assessed_weight,
        total_weight=p.total_weight,
        current_percentage=p.current_percentage,
        final_percentage=p.final_percentage,
        grade=p.grade,
        gpa=p.gpa,
        is_pass=p.is_pass,
        unconfigured=p.unconfigured,
        failed_mandatory=list(p.failed_mandatory),
        sessions_total=row.sessions_total,
        sessions_attended=row.sessions_attended,
        attendance_percentage=row.attendance_percentage,
    )


@router.get(
    "/performance/students/{student_id}/batches/{batch_id}",
    response_model=PerformanceResponse,
    summary="One student's weighted performance, with the breakdown",
)
async def student_performance(
    student_id: uuid.UUID,
    batch_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> PerformanceResponse:
    """Every figure the headline was built from (§37).

    A student, a guardian and a corporate manager see only **published** marks;
    staff see unreleased marking too, because a tutor who cannot see their own
    work in progress cannot do their job.

    `current_percentage` is the mark out of what has been assessed so far;
    `final_percentage` stays null until every weighted component has a mark.
    They answer different questions and a client must not substitute one for
    the other.
    """
    student = (
        await session.execute(select(User).where(User.public_id == student_id))
    ).scalar_one_or_none()
    batch = (
        await session.execute(select(Batch).where(Batch.public_id == batch_id))
    ).scalar_one_or_none()
    # 404 for either, and identically: §32 requires that grade book data is not
    # reachable by manipulating ids, which includes not confirming which of the
    # two a caller happened to guess correctly.
    if student is None or batch is None:
        raise NotFoundError("Student not found.")

    row = await PerformanceService(session).for_student(
        student_id=student.id, batch_id=batch.id, actor=actor
    )
    return _response(row, student=student, batch=batch)


@router.get(
    "/performance/batches/{batch_id}",
    response_model=list[PerformanceResponse],
    summary="Every student in a batch, for the grade book grid",
)
async def batch_performance(
    batch_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> list[PerformanceResponse]:
    """§36's grid.

    Students this caller may not see are omitted rather than refused: a tutor
    opening a batch should see their own students, not an error because
    somebody else's is in it.
    """
    batch = (
        await session.execute(select(Batch).where(Batch.public_id == batch_id))
    ).scalar_one_or_none()
    if batch is None:
        raise NotFoundError("Batch not found.")

    rows = await PerformanceService(session).for_batch(batch_id=batch.id, actor=actor)
    if not rows:
        return []

    students = {
        u.id: u
        for u in (
            await session.execute(
                select(User).where(User.id.in_([r.student_id for r in rows]))
            )
        )
        .scalars()
        .unique()
        .all()
    }
    return [_response(r, student=students[r.student_id], batch=batch) for r in rows]
