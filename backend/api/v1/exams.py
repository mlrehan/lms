"""Examination endpoints (spec §14)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.core.privacy import visible_username
from backend.api.deps import CurrentUser, require_permissions, resolve_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.exam import Exam, ExamResult
from backend.schemas.base import Page, PageParams
from backend.schemas.exam import (
    ExamCreateRequest,
    ExamInvigilatorsRequest,
    ExamPublishRequest,
    ExamResponse,
    ExamResultResponse,
    ExamSummary,
    ExamUpdateRequest,
    PublishResultsRequest,
    RecordExamResultsRequest,
)
from backend.services.exam_service import ExamService

router = APIRouter(tags=["Examinations"])


def _exam_response(
    e: Exam, *, results: int = 0, published: int = 0, staff: bool = True
) -> ExamResponse:
    """One examination.

    `staff=False` zeroes the two counts. How many of the cohort have been
    marked, and how many of those marks are out, are facts about other
    candidates -- and the second is worse than idle: "28 of 30 published"
    tells a student whose mark is missing that theirs is one of the two being
    withheld, which is exactly what §14's release step exists to avoid saying.

    The invigilator list is safe as it stands: `visible_username` already
    gives a name rather than a login name to anybody without
    `user.view_contact`.
    """
    return ExamResponse(
        public_id=e.public_id,
        title=e.title,
        exam_type=e.exam_type,
        scheduled_at=e.scheduled_at,
        duration_minutes=e.duration_minutes,
        total_marks=e.total_marks,
        passing_marks=e.passing_marks,
        is_published=e.is_published,
        venue_or_link=e.venue_or_link,
        instructions=e.instructions,
        course_id=e.course.public_id if e.course else None,
        course_title=e.course.title if e.course else None,
        batch_id=e.batch.public_id if e.batch else None,
        batch_code=e.batch.batch_code if e.batch else None,
        invigilators=sorted(visible_username(i.tutor) for i in (e.invigilators or [])),
        result_count=results if staff else 0,
        published_result_count=published if staff else 0,
    )


def _result_response(r: ExamResult) -> ExamResultResponse:
    passed = None
    if r.marks_obtained is not None and r.exam is not None:
        passed = Decimal(str(r.marks_obtained)) >= Decimal(str(r.exam.passing_marks))
    return ExamResultResponse(
        public_id=r.public_id,
        exam_id=r.exam.public_id,
        exam_title=r.exam.title,
        student_id=r.student.public_id,
        student_username=visible_username(r.student),
        marks_obtained=r.marks_obtained,
        grade=r.grade,
        remarks=r.remarks,
        is_published=r.is_published,
        total_marks=r.exam.total_marks if r.exam else None,
        passing_marks=r.exam.passing_marks if r.exam else None,
        is_passed=passed,
    )


# =============================================================================
# EXAMS
# =============================================================================


@router.get("/exams", response_model=Page[ExamSummary], summary="List examinations")
async def list_exams(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.EXAM, Action.READ)))],
) -> Page[ExamSummary]:
    """Reachable three ways: through the exam's course, through its batch, or
    by being assigned to invigilate it — a tutor supervising an exam for a
    course they don't teach still needs to see it. Unpublished schedules are
    visible only to callers who can manage exams."""
    rows, total = await ExamService(session).list_exams(params, actor=actor)
    return Page.build([ExamSummary.model_validate(e) for e in rows], total=total, params=params)


@router.post(
    "/exams",
    response_model=ExamResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Schedule an examination",
)
async def create_exam(
    payload: ExamCreateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.EXAM, Action.CREATE)))],
) -> ExamResponse:
    """Must be anchored to a course, a batch, or both — an exam attached to
    neither is unreachable by every scoping query. A batch-anchored exam
    inherits that batch's course automatically."""
    return _exam_response(await ExamService(session).create(payload, actor=actor))


@router.get("/exams/{exam_id}", response_model=ExamResponse, summary="Get one examination")
async def get_exam(
    exam_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.EXAM, Action.READ)))],
) -> ExamResponse:
    service = ExamService(session)
    row = await service.get(exam_id, actor=actor)
    total, published = await service.exams.result_counts(row.id)
    return _exam_response(
        row,
        results=total,
        published=published,
        # The one read a candidate makes. Recording marks is what makes
        # somebody staff here; sitting the paper is not.
        staff=perm(Module.EXAM, Action.UPDATE) in resolve_permissions(actor),
    )


@router.patch("/exams/{exam_id}", response_model=ExamResponse, summary="Update an examination")
async def update_exam(
    exam_id: uuid.UUID,
    payload: ExamUpdateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.EXAM, Action.UPDATE)))],
) -> ExamResponse:
    """`total_marks` cannot be lowered below a mark already recorded."""
    return _exam_response(await ExamService(session).update(exam_id, payload, actor=actor))


@router.put(
    "/exams/{exam_id}/publish",
    response_model=ExamResponse,
    summary="Publish or retract the schedule",
)
async def publish_exam(
    exam_id: uuid.UUID,
    payload: ExamPublishRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.EXAM, Action.PUBLISH)))],
) -> ExamResponse:
    """Publishes the *schedule* only. Results have their own, separate switch
    — a timetable is normally public long before any marks are."""
    return _exam_response(
        await ExamService(session).set_published(exam_id, payload.is_published, actor=actor)
    )


@router.put(
    "/exams/{exam_id}/invigilators",
    response_model=ExamResponse,
    summary="Assign invigilators",
)
async def set_invigilators(
    exam_id: uuid.UUID,
    payload: ExamInvigilatorsRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.EXAM, Action.UPDATE)))],
) -> ExamResponse:
    """An authorization write: an invigilator gains sight of the exam and its
    candidates whether or not they teach the course."""
    return _exam_response(
        await ExamService(session).set_invigilators(exam_id, payload.invigilators, actor=actor)
    )


@router.delete(
    "/exams/{exam_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an examination"
)
async def delete_exam(
    exam_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.EXAM, Action.DELETE)))],
) -> Response:
    """Refused once results are recorded — the cascade would take every mark
    with it."""
    await ExamService(session).delete(exam_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# RESULTS
# =============================================================================


@router.put(
    "/exams/{exam_id}/results",
    response_model=list[ExamResultResponse],
    summary="Record a cohort's marks",
)
async def record_results(
    exam_id: uuid.UUID,
    payload: RecordExamResultsRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.GRADE, Action.UPDATE)))],
) -> list[ExamResultResponse]:
    """Bulk, like attendance marking. Idempotent — re-sending corrects an
    existing mark rather than adding a second.

    Marking someone not enrolled in the exam's course or batch refuses the
    whole sheet, and recording a mark does **not** release it: results start
    unpublished and need the separate publish call below.
    """
    rows = await ExamService(session).record_results(exam_id, payload.entries, actor=actor)
    return [_result_response(r) for r in rows]


@router.put(
    "/exams/{exam_id}/results/publish",
    summary="Release or retract all results for an exam",
)
async def publish_results(
    exam_id: uuid.UUID,
    payload: PublishResultsRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.GRADE, Action.PUBLISH)))],
) -> dict:
    """Until this is called, a recorded result is invisible to the student it
    belongs to."""
    count = await ExamService(session).publish_results(exam_id, payload.is_published, actor=actor)
    return {"is_published": payload.is_published, "results_affected": count}


@router.get(
    "/exam-results", response_model=Page[ExamResultResponse], summary="List exam results"
)
async def list_results(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.GRADE, Action.READ)))],
    exam_id: Annotated[uuid.UUID | None, Query()] = None,
    student_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[ExamResultResponse]:
    """Row-scoped, and additionally filtered to *published* results for
    anyone who cannot manage exams — an unreleased mark must not reach the
    student it describes."""
    rows, total = await ExamService(session).list_results(
        params, actor=actor, exam_public_id=exam_id, student_public_id=student_id
    )
    return Page.build([_result_response(r) for r in rows], total=total, params=params)
