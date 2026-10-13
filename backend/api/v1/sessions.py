"""Class session endpoints (spec §8).

Creation is nested under a batch (`/batches/{id}/sessions`) because a session
cannot exist without one; everything else addresses the session directly.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from backend.core.privacy import visible_username
from backend.api.deps import CurrentUser, require_permissions
from backend.core.errors import ValidationError
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession, commit_before_responding
from backend.models.batch import BatchSession
from backend.schemas.base import Page, PageParams
from backend.schemas.session_plan import PlanRequest, PlanResponse, ReplaceRequest, ReplaceResponse
from backend.api.streaming import stream_for_playback
from backend.schemas.session import (
    CalendarResponse,
    CalendarSession,
    SessionCreateRequest,
    SessionJoinResponse,
    SessionOverview,
    SessionRecordingAttachRequest,
    SessionRecordingResponse,
    SessionResponse,
    SessionSummary,
    SessionUpdateRequest,
)
from backend.services.session_overview_service import SessionOverviewService
from backend.services.session_plan_service import SessionPlanService
from backend.services.session_service import SessionService

router = APIRouter(tags=["Sessions"])


def _response(
    s: BatchSession,
    *,
    service: SessionService,
    actor: CurrentUser,
    attendance_recorded: bool = False,
) -> SessionResponse:
    """One session, with the meeting link withheld from anyone who is not
    entitled to hold it outright.

    A student's client gets the *window* and a boolean, never the URL: that is
    what makes "the Join button is greyed out until 30 minutes before" a rule
    instead of a decoration. They obtain the link from `POST .../join`, one
    admission at a time, and every one is audited.
    """
    manage = service.can_manage(actor)
    state = service.join_state(s, actor=actor)
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
        tutor_username=visible_username(s.tutor),
        meeting_link=s.meeting_link if manage else None,
        recording_link=s.recording_link if manage else None,
        can_manage=manage,
        tutor_notes=s.tutor_notes,
        student_notes=s.student_notes,
        attendance_recorded=attendance_recorded,
        join_opens_at=state.opens_at,
        join_closes_at=state.closes_at,
        can_join_now=state.can_join_now,
        has_recording=bool(s.recording_resource_id) or bool(s.recording_link),
    )


def _summary(s: BatchSession, *, service: SessionService, actor: CurrentUser) -> SessionSummary:
    """A timetable row. Same withholding rule as `_response`, and the same
    single source for whether the door is open."""
    state = service.join_state(s, actor=actor)
    return SessionSummary(
        public_id=s.public_id,
        session_start_time=s.session_start_time,
        session_end_time=s.session_end_time,
        duration_minutes=s.duration_minutes,
        platform=s.platform,
        classroom=s.classroom,
        join_opens_at=state.opens_at,
        join_closes_at=state.closes_at,
        can_join_now=state.can_join_now,
        has_recording=bool(s.recording_resource_id) or bool(s.recording_link),
    )


_CALENDAR_CAP = 3000


@router.get("/sessions/calendar", response_model=CalendarResponse, summary="Sessions in a date window, for the calendar")
async def session_calendar(
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.SESSION, Action.READ)))],
    start: Annotated[datetime, Query(alias="from")],
    end: Annotated[datetime, Query(alias="to")],
    batch_id: Annotated[uuid.UUID | None, Query()] = None,
) -> CalendarResponse:
    """Everything the caller may see between `from` and `to`, in one request and without paging.

    The scope is the same row-level one the session list uses: a tutor sees the batches they teach, a
    student the batch they are enrolled in, a guardian or corporate manager the people in their care.
    Declared before `/sessions/{session_id}` so "calendar" is not parsed as an id.
    """
    if end <= start or end - start > timedelta(days=400):
        raise ValidationError("The window must be positive and at most 400 days.")
    service = SessionService(session)
    rows = await service.calendar(actor=actor, start=start, end=end, batch_public_id=batch_id, limit=_CALENDAR_CAP + 1)
    manage = service.can_manage(actor)
    items = []
    for s in rows[:_CALENDAR_CAP]:
        began = s.session_start_time if s.session_start_time.tzinfo else s.session_start_time.replace(tzinfo=timezone.utc)
        finish = s.session_end_time or began + timedelta(minutes=s.duration_minutes or 60)
        items.append(CalendarSession(
            public_id=s.public_id, batch_id=s.batch.public_id, batch_code=s.batch.batch_code,
            course_title=s.batch.course.title if s.batch.course else None,
            tutor_id=s.tutor.public_id, tutor_name=" ".join(p for p in (s.tutor.first_name, s.tutor.last_name) if p) or visible_username(s.tutor),
            session_start_time=began, session_end_time=finish, platform=s.platform, classroom=s.classroom,
            meeting_link=s.meeting_link if manage else None,
            can_join_now=service.join_state(s, actor=actor).can_join_now,
            origin=s.origin,
        ))
    return CalendarResponse(items=items, truncated=len(rows) > _CALENDAR_CAP)


@router.get("/sessions", response_model=Page[SessionSummary], summary="List sessions")
async def list_sessions(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.SESSION, Action.READ)))],
    batch_id: Annotated[uuid.UUID | None, Query()] = None,
    starts_after: Annotated[datetime | None, Query()] = None,
    starts_before: Annotated[datetime | None, Query()] = None,
    tutor_id: Annotated[uuid.UUID | None, Query(description="Sessions this person takes.")] = None,
    student_id: Annotated[uuid.UUID | None, Query(description="Sessions of batches this person is enrolled in.")] = None,
    mine_only: Annotated[bool, Query(description="Only sessions I am the tutor for.")] = False,
) -> Page[SessionSummary]:
    """Row-scoped through the batch: a Tutor sees sessions of batches they
    teach, a Student those of the batch they are enrolled in, a Guardian or
    Corporate Manager those of the people in their care.

    `mine_only=true` gives a tutor their own timetable — spec §17's "Today's
    classes" — by narrowing to sessions where they are the assigned tutor.
    """
    service = SessionService(session)
    rows, total = await service.list_sessions(
        params,
        actor=actor,
        batch_public_id=batch_id,
        starts_after=starts_after,
        starts_before=starts_before,
        tutor_public_id=tutor_id,
        student_public_id=student_id,
        mine_only=mine_only,
    )
    return Page.build([_summary(r, service=service, actor=actor) for r in rows], total=total, params=params)


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
    service = SessionService(session)
    return _response(await service.create(batch_id, payload, actor=actor), service=service, actor=actor)


@router.post("/batches/{batch_id}/session-plan", response_model=PlanResponse, summary="Propose a batch's sessions (changes nothing)")
async def session_plan(
    batch_id: uuid.UUID,
    payload: PlanRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.SESSION, Action.CREATE)))],
) -> PlanResponse:
    """Generates the sessions from the batch's training days, times and duration in the zone given, or from the
    sessions it already has. Nothing is written: this is the preview an administrator reviews and adjusts."""
    return await SessionPlanService(session).preview(batch_id, payload, actor=actor)


@router.post("/batches/{batch_id}/sessions/replace", response_model=ReplaceResponse, summary="Create these sessions, replacing the unprotected ones")
async def replace_sessions(
    batch_id: uuid.UUID,
    payload: ReplaceRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.SESSION, Action.CREATE), perm(Module.SESSION, Action.DELETE)))],
) -> ReplaceResponse:
    """All or nothing. Sessions that hold attendance, a recording or notes are kept; the rest are replaced only
    with `confirm_replace`; a tutor double-booking refuses the whole request and lists every clash."""
    result = await SessionPlanService(session).replace(batch_id, payload, actor=actor)
    await commit_before_responding(session)  # the Google push that follows must see the new sessions
    return result


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
    service = SessionService(session)
    rows, total = await service.list_sessions(params, actor=actor, batch_public_id=batch_id)
    return Page.build([_summary(r, service=service, actor=actor) for r in rows], total=total, params=params)


@router.get("/sessions/{session_id}/overview", response_model=SessionOverview, summary="Everything about one session, for the calendar")
async def session_overview(
    session_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.SESSION, Action.READ)))],
) -> SessionOverview:
    """Course, batch, tutor, session number, and the roster the caller is entitled to see.

    The roster follows enrolment visibility: administrators see everyone, a tutor their batch, a student
    themselves, a guardian their wards, a corporate manager their employees. Contact details and each
    student's guardians and managers are limited to administrators and the batch's tutors.
    """
    return SessionOverview.model_validate(await SessionOverviewService(session).overview(session_id, actor=actor))


@router.post(
    "/sessions/{session_id}/join",
    response_model=SessionJoinResponse,
    summary="Join a class",
)
async def join_session(
    session_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.SESSION, Action.READ)))],
) -> SessionJoinResponse:
    """Hands out the meeting link, to someone entitled to it, right now.

    The window opens thirty minutes before the start and closes at the end.
    Outside it the request is refused with a 409 naming both times, unless the
    caller holds `session.override` -- in which case the join happens and is
    recorded as having been outside the window.

    A POST rather than a GET because it is an act, not a property: it writes an
    audit row, and must not be something a prefetch or a cache repeats on the
    caller's behalf.
    """
    ticket = await SessionService(session).join(session_id, actor=actor)
    row = ticket.session
    await commit_before_responding(session)  # the audit row outlives the response
    return SessionJoinResponse(
        meeting_link=ticket.meeting_link,
        platform=row.platform,
        classroom=row.classroom,
        session_start_time=row.session_start_time,
        session_end_time=row.session_end_time,
        join_opens_at=ticket.window.opens_at,
        join_closes_at=ticket.window.closes_at,
        joined_outside_window=ticket.overridden,
    )


@router.get(
    "/sessions/{session_id}/recording",
    response_model=SessionRecordingResponse,
    summary="Where to play a class back",
)
async def get_session_recording(
    session_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.SESSION, Action.READ)))],
) -> SessionRecordingResponse:
    """`playback_url` (stored in the LMS) and `embed_url` (on the provider)
    are both paths on this API that re-check permission on every request. The
    provider's own link is returned in the clear only to callers who may edit
    the session -- it works outside the LMS and past every check in it."""
    view = await SessionService(session).recording(session_id, actor=actor, audit=True)
    await commit_before_responding(session)  # the audit row outlives the response
    return SessionRecordingResponse(
        playback_url=view.playback_url,
        embed_url=view.embed_url,
        external_url=view.external_url,
        name=view.resource.name if view.resource else None,
        mime_type=view.resource.mime_type if view.resource else None,
        size=view.resource.size if view.resource else None,
    )


@router.get(
    "/sessions/{session_id}/recording/stream",
    summary="Play a class recording",
    response_class=Response,
)
async def stream_session_recording(
    session_id: uuid.UUID,
    request: Request,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.SESSION, Action.READ)))],
) -> Response:
    """The bytes, served inline and seekable, never as a download and never as
    a URL that works without this check.

    Re-authorised on every request, so a student removed from the batch loses
    the recording mid-scrub rather than at the end of a token's life.
    """
    _, resource = await SessionService(session).resolve_recording_stream(
        session_id, actor=actor
    )
    return await stream_for_playback(
        request,
        resource.path or "",
        filename=resource.name,
        mime_type=resource.mime_type,
    )


@router.get(
    "/sessions/{session_id}/recording/embed",
    summary="Watch a class recording that lives on the provider",
    response_class=Response,
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
)
async def embed_session_recording(
    session_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.SESSION, Action.READ)))],
) -> Response:
    """Re-authorise, then hand the browser on to the provider's player.

    The session page frames this path, never the provider's URL, so the link
    is absent from every API payload and from the page's own DOM, and the only
    route to it checks on each request that this caller still has the class.

    It is a redirect rather than a proxy because the media behind a provider's
    player is bound to that provider's session: the signed URL Zoom's player
    uses refuses our server outright, so there are no bytes for us to serve.
    Stated plainly, because it bounds what this can promise -- the player on
    the other side is the provider's, including whatever download control they
    offer. A recording that must not be downloadable at all belongs in the
    library, where `playback_url` serves the bytes under our own rules.
    """
    link = await SessionService(session).resolve_recording_embed(session_id, actor=actor)
    return Response(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={
            "Location": link,
            # The URL earned one admission, for this caller, now. A cache
            # between us and them must not be able to repeat it.
            "Cache-Control": "private, no-store",
            # Do not hand the provider the LMS URL the viewer came from.
            "Referrer-Policy": "no-referrer",
        },
    )


@router.put(
    "/sessions/{session_id}/recording",
    response_model=SessionResponse,
    summary="Publish a recording to the class",
)
async def attach_session_recording(
    session_id: uuid.UUID,
    payload: SessionRecordingAttachRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.SESSION, Action.UPDATE)))],
) -> SessionResponse:
    """Links a file already in the library, rather than taking a second upload.

    The uploader needs EDIT on that file: attaching makes it playable by the
    whole batch, so the bar is "this is yours to publish", not "you happen to
    have been shown it".
    """
    service = SessionService(session)
    row = await service.attach_recording(session_id, resource_public_id=payload.resource_id, actor=actor)
    return _response(row, service=service, actor=actor)


@router.delete(
    "/sessions/{session_id}/recording",
    response_model=SessionResponse,
    summary="Withdraw the class recording",
)
async def detach_session_recording(
    session_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.SESSION, Action.UPDATE)))],
) -> SessionResponse:
    """The file stays in the library -- taking a recording down is not a reason
    to delete someone's upload."""
    service = SessionService(session)
    row = await service.detach_recording(session_id, actor=actor)
    return _response(row, service=service, actor=actor)


@router.get("/sessions/{session_id}", response_model=SessionResponse, summary="Get one session")
async def get_session(
    session_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.SESSION, Action.READ)))],
) -> SessionResponse:
    service = SessionService(session)
    row = await service.get(session_id, actor=actor)
    marked = await service.sessions.count_attendance(row.id)
    return _response(row, service=service, actor=actor, attendance_recorded=marked > 0)


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
    service = SessionService(session)
    return _response(await service.update(session_id, payload, actor=actor), service=service, actor=actor)


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
