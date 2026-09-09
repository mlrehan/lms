"""Class session endpoints (spec §8).

Creation is nested under a batch (`/batches/{id}/sessions`) because a session
cannot exist without one; everything else addresses the session directly.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.batch import BatchSession
from backend.schemas.base import Page, PageParams
from backend.schemas.session import (
    SessionCreateRequest,
    SessionResponse,
    SessionSummary,
    SessionUpdateRequest,
)
from backend.services.session_service import SessionService

router = APIRouter(tags=["Sessions"])


def _response(s: BatchSession, *, attendance_recorded: bool = False) -> SessionResponse:
    return SessionResponse(
        public_id=s.public_id,
        session_start_time=s.session_start_time,
        session_end_time=s.session_end_time,
        duration_minutes=s.duration_minutes,
        platform=s.platform,
        classroom=s.classroom,
        batch_id=s.batch.public_id,
        batch_code=s.batch.batch_code,
        course_title=s.batch.course.title if s.batch.course else None,
        tutor_id=s.tutor.public_id,
        tutor_username=s.tutor.username,
        meeting_link=s.meeting_link,
        recording_link=s.recording_link,
        tutor_notes=s.tutor_notes,
        student_notes=s.student_notes,
        attendance_recorded=attendance_recorded,
    )


@router.get("/sessions", response_model=Page[SessionSummary], summary="List sessions")
async def list_sessions(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.SESSION, Action.READ)))],
    batch_id: Annotated[uuid.UUID | None, Query()] = None,
    starts_after: Annotated[datetime | None, Query()] = None,
    starts_before: Annotated[datetime | None, Query()] = None,
    mine_only: Annotated[bool, Query(description="Only sessions I am the tutor for.")] = False,
) -> Page[SessionSummary]:
    """Row-scoped through the batch: a Tutor sees sessions of batches they
    teach, a Student those of the batch they are enrolled in, a Guardian or
    Corporate Manager those of the people in their care.

    `mine_only=true` gives a tutor their own timetable — spec §17's "Today's
    classes" — by narrowing to sessions where they are the assigned tutor.
    """
    rows, total = await SessionService(session).list_sessions(
        params,
        actor=actor,
        batch_public_id=batch_id,
        starts_after=starts_after,
        starts_before=starts_before,
        mine_only=mine_only,
    )
    return Page.build(
        [SessionSummary.model_validate(r) for r in rows], total=total, params=params
    )


@router.post(
    "/batches/{batch_id}/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Schedule a session",
)
async def create_session(
    batch_id: uuid.UUID,
    payload: SessionCreateRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.SESSION, Action.CREATE)))
    ],
) -> SessionResponse:
    """Assigning the tutor is an authorization write: `batch_sessions.tutor_id`
    is one of the two routes by which a tutor reaches a batch's students, so
    covering a single session grants access to that batch's roster.

    Double-booking a tutor across overlapping sessions is refused.
    """
    return _response(await SessionService(session).create(batch_id, payload, actor=actor))


@router.get(
    "/batches/{batch_id}/sessions",
    response_model=Page[SessionSummary],
    summary="List a batch's sessions",
)
async def list_batch_sessions(
    batch_id: uuid.UUID,
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.SESSION, Action.READ)))],
) -> Page[SessionSummary]:
    rows, total = await SessionService(session).list_sessions(
        params, actor=actor, batch_public_id=batch_id
    )
    return Page.build(
        [SessionSummary.model_validate(r) for r in rows], total=total, params=params
    )


@router.get("/sessions/{session_id}", response_model=SessionResponse, summary="Get one session")
async def get_session(
    session_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.SESSION, Action.READ)))],
) -> SessionResponse:
    service = SessionService(session)
    row = await service.get(session_id, actor=actor)
    marked = await service.sessions.count_attendance(row.id)
    return _response(row, attendance_recorded=marked > 0)


@router.patch(
    "/sessions/{session_id}", response_model=SessionResponse, summary="Update a session"
)
async def update_session(
    session_id: uuid.UUID,
    payload: SessionUpdateRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.SESSION, Action.UPDATE)))
    ],
) -> SessionResponse:
    """Tutors hold `session.update`, so they can add notes and a recording
    link to their own sessions without being able to schedule new ones."""
    return _response(await SessionService(session).update(session_id, payload, actor=actor))


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a session",
)
async def delete_session(
    session_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.SESSION, Action.DELETE)))
    ],
) -> Response:
    """Refused once attendance has been recorded — deleting would cascade
    those rows away and silently rewrite every affected student's record."""
    await SessionService(session).delete(session_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
