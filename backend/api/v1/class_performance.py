"""Class performance marks (spec §11).

Every route is gated on a `class_performance.*` permission rather than on a role
name (§21), and the *row* scoping — which sessions, which students — happens in
the service (§20). A permission says "may do this at all"; the service says "to
these rows". Neither is enough alone: a tutor holds `class_performance.create`
for their own classes, not for the whole institution's.

The read is deliberately wider than the write. A student, a guardian and a
corporate manager all hold `class_performance.read` so that §37's drill-down can
explain a `PRACTICAL` figure to the person it is about — the service then shows
them released marks for the students in their care only.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.core.privacy import visible_username
from backend.db.dependencies import DBSession
from backend.models.class_performance import ClassPerformanceMark
from backend.schemas.class_performance import (
    ClassPerformanceMarkResponse,
    ClassPerformanceSheetResponse,
    ClassPerformanceSheetRow,
    ClassPerformanceSheetSession,
    MarkPerson,
    SaveClassPerformanceRequest,
    SetClassPerformanceStateRequest,
    StudentClassPerformanceResponse,
)
from backend.services.class_performance_service import (
    CRITERIA,
    ClassPerformanceService,
)
from backend.utils.enums import ResultState

router = APIRouter(prefix="/class-performance", tags=["Class performance"])

_READ = require_permissions(perm(Module.CLASS_PERFORMANCE, Action.READ))
_RECORD = require_permissions(perm(Module.CLASS_PERFORMANCE, Action.CREATE))
_RELEASE = require_permissions(perm(Module.CLASS_PERFORMANCE, Action.PUBLISH))
_REMOVE = require_permissions(perm(Module.CLASS_PERFORMANCE, Action.DELETE))

_HUNDRED = Decimal("100")


def _person(user: object) -> MarkPerson | None:
    if user is None:
        return None
    return MarkPerson(public_id=user.public_id, name=visible_username(user))  # type: ignore[attr-defined]


def _mark(row: ClassPerformanceMark) -> ClassPerformanceMarkResponse:
    return ClassPerformanceMarkResponse(
        public_id=row.public_id,
        student=_person(row.student),  # type: ignore[arg-type]
        max_score=row.max_score,
        overall_score=row.overall_score,
        # The figure the transcript will use, computed by the engine rather than
        # re-derived here -- §23's single source of truth applies to a display
        # field just as much as to a stored one.
        average=ClassPerformanceService.average(row),
        comment=row.comment,
        custom_scores=row.custom_scores,
        state=row.state,
        recorded_at=row.recorded_at,
        updated_at=row.updated_at,
        **{c: getattr(row, c) for c in CRITERIA},
    )


@router.get(
    "/sessions/{session_id}",
    response_model=ClassPerformanceSheetResponse,
    summary="The class performance sheet for one session",
)
async def get_sheet(
    session_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> ClassPerformanceSheetResponse:
    """The roster plus whatever has been recorded.

    A student appears with a null `mark` until somebody assesses them — not as a
    zero, which is a mark and would be averaged in.
    """
    service = ClassPerformanceService(session)
    batch_session, roster, marks, can_edit = await service.sheet(session_id, actor=actor)

    states = {m.state for m in marks.values()}
    batch = batch_session.batch
    return ClassPerformanceSheetResponse(
        session=ClassPerformanceSheetSession(
            public_id=batch_session.public_id,
            session_start_time=batch_session.session_start_time,
            session_end_time=batch_session.session_end_time,
            classroom=batch_session.classroom,
            batch_code=batch.batch_code if batch else None,
            course_title=batch.course.title if batch and batch.course else None,
            assigned_tutor=_person(getattr(batch_session, "tutor", None)),
        ),
        rows=[
            ClassPerformanceSheetRow(
                student=_person(student),  # type: ignore[arg-type]
                mark=_mark(marks[student.id]) if student.id in marks else None,
            )
            for student in roster
        ],
        can_edit=can_edit,
        would_be_on_behalf=can_edit and batch_session.tutor_id != actor.id,
        # Null when the marks disagree: a part-released sheet is a real state
        # and is reported as such rather than rounded to whichever value
        # happens to come first.
        state=next(iter(states)) if len(states) == 1 else None,
        marked=len(marks),
        total=len(roster),
    )


@router.put(
    "/sessions/{session_id}",
    response_model=list[ClassPerformanceMarkResponse],
    summary="Record or correct a whole class",
)
async def save_sheet(
    session_id: uuid.UUID,
    payload: SaveClassPerformanceRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_RECORD)],
) -> list[ClassPerformanceMarkResponse]:
    """Upserts per student, so re-saving corrects rather than duplicating.

    Only the session's assigned tutor may, or the academic office acting on
    their behalf — which is recorded in the audit trail, since `recorded_by`
    names whoever actually typed it.
    """
    rows = await ClassPerformanceService(session).save(
        session_id,
        [e.model_dump() for e in payload.entries],
        actor=actor,
        max_score=payload.max_score,
    )
    return [_mark(r) for r in rows]


@router.post(
    "/sessions/{session_id}/state",
    response_model=list[ClassPerformanceMarkResponse],
    summary="Release or withdraw a session's marks",
)
async def set_state(
    session_id: uuid.UUID,
    payload: SetClassPerformanceStateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_RELEASE)],
) -> list[ClassPerformanceMarkResponse]:
    """Releasing is what makes a mark visible to a student and their guardians,
    so it needs `class_performance.publish` rather than the recording grant — an
    institution can then have tutors who observe and an office that releases.

    Withdrawing back to `DRAFT` uses the same endpoint: a released mark found to
    be wrong has to be retractable, or the only remedy is a silent correction.
    """
    rows = await ClassPerformanceService(session).set_state(
        session_id, payload.state, actor=actor, student_public_id=payload.student_id
    )
    return [_mark(r) for r in rows]


@router.delete(
    "/marks/{mark_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a mark entered in error",
)
async def delete_mark(
    mark_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_REMOVE)],
) -> Response:
    """Deleted rather than zeroed: zero is itself a mark and would be averaged
    into the student's class-performance figure."""
    await ClassPerformanceService(session).delete(mark_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/students/{student_id}",
    response_model=StudentClassPerformanceResponse,
    summary="Every class behind one student's class-performance figure",
)
async def for_student(
    student_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
    batch_id: Annotated[uuid.UUID | None, Query(description="Narrow to one batch.")] = None,
) -> StudentClassPerformanceResponse:
    """§37's drill-down. A student sees their own released marks; a guardian or
    corporate manager sees those of the people in their care; teaching staff see
    drafts too."""
    service = ClassPerformanceService(session)
    rows = await service.for_student(
        student_public_id=student_id, batch_public_id=batch_id, actor=actor
    )

    # The mean across sessions that carry a score, as a percentage. Sessions
    # with nothing assessed are excluded rather than counted as zero (§38) --
    # the same rule the engine applies, which is why a tutor who has marked
    # three of ten classes sees a figure for three, not a collapse to 30%.
    scored = [
        (score, Decimal(r.max_score))
        for r in rows
        if (score := ClassPerformanceService.average(r)) is not None
    ]
    average = (
        (sum(s / m for s, m in scored) / len(scored) * _HUNDRED).quantize(Decimal("0.01"))
        if scored
        else None
    )

    return StudentClassPerformanceResponse(
        marks=[_mark(r) for r in rows],
        sessions=len(rows),
        average=average,
    )
