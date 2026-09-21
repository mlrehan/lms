"""Google Calendar: connect, disconnect, sync, history.

Registered before `integrations.router` so `/integrations/google/...` is matched here rather
than by a path parameter there.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select

from backend.api.deps import CurrentUser, require_permissions
from backend.core.config import get_settings
from backend.core.errors import NotFoundError
from backend.core.logging import get_logger
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.integrations import google_events as ge
from backend.models.batch import Batch, BatchSession
from backend.models.user_sync import UserSyncRun
from backend.schemas.base import Page, PageParams
from backend.schemas.google import (
    GoogleBatchResponse, GoogleCallbackRequest, GoogleChangeRequestResponse, GoogleConnectResponse, GoogleStatusResponse,
)
from backend.schemas.user import SyncRunResponse
from backend.services.google_calendar_service import GoogleCalendarSyncService, GoogleConnectionService
from backend.services.google_change_service import GoogleChangeService

logger = get_logger("google.calendar.api")
router = APIRouter(prefix="/integrations/google", tags=["Google Calendar"])

_running: set[asyncio.Task[None]] = set()

_READ = Annotated[CurrentUser, Depends(require_permissions(perm(Module.GOOGLE, Action.READ)))]
_CONNECT = Annotated[CurrentUser, Depends(require_permissions(perm(Module.GOOGLE, Action.UPDATE)))]
_SYNC = Annotated[CurrentUser, Depends(require_permissions(perm(Module.GOOGLE, Action.SYNC)))]


@router.get("/status", response_model=GoogleStatusResponse, summary="Google Calendar connection status")
async def get_status(session: DBSession, actor: _READ) -> GoogleStatusResponse:
    return GoogleStatusResponse(**await GoogleConnectionService(session, get_settings()).status())


@router.post("/connect", response_model=GoogleConnectResponse, summary="Start signing in with Google")
async def connect(session: DBSession, actor: _CONNECT) -> GoogleConnectResponse:
    """Returns the Google consent URL. Super Admin only: it decides whose calendar holds the schedule."""
    return GoogleConnectResponse(url=GoogleConnectionService(session, get_settings()).authorize_url(actor))


@router.post("/callback", response_model=GoogleStatusResponse, summary="Finish signing in with Google")
async def callback(payload: GoogleCallbackRequest, session: DBSession, actor: _CONNECT) -> GoogleStatusResponse:
    """The console's callback page forwards Google's `code` and `state` here, with the caller's session."""
    service = GoogleConnectionService(session, get_settings())
    await service.complete(payload.code, payload.state, actor)
    return GoogleStatusResponse(**await service.status())


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT, summary="Disconnect Google")
async def disconnect(session: DBSession, actor: _CONNECT) -> Response:
    """Revokes the grant at Google. Existing calendars stay in Google; they just stop being updated."""
    await GoogleConnectionService(session, get_settings()).disconnect(actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sync", response_model=SyncRunResponse, status_code=status.HTTP_202_ACCEPTED, summary="Push the schedule to Google now")
async def start_sync(
    request: Request, session: DBSession, actor: _SYNC, dry_run: bool = False, batch_id: uuid.UUID | None = None,
) -> SyncRunResponse:
    """Returns at once; poll `GET /integrations/google/runs/{id}`. A run already in progress answers 409.
    `dry_run=true` reports what would change and writes nothing."""
    batch_ids: list[int] | None = None
    if batch_id is not None:
        pk = (await session.execute(select(Batch.id).where(Batch.public_id == batch_id))).scalar_one_or_none()
        if pk is None:
            raise NotFoundError("Batch not found.")
        batch_ids = [pk]
    service = GoogleCalendarSyncService(request.app.state.db.session_factory, get_settings())
    run = await service.start(trigger_type="MANUAL", triggered_by_user_id=actor.id, dry_run=dry_run)
    task = asyncio.create_task(_execute(service, run.id, batch_ids))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return SyncRunResponse.model_validate(run)


async def _execute(service: GoogleCalendarSyncService, run_id: int, batch_ids: list[int] | None) -> None:
    try:
        await service.execute(run_id, batch_ids=batch_ids)
    except Exception:  # noqa: BLE001 - execute() finalises its own row
        logger.exception("Google sync task failed outside its own handling")


@router.get("/runs", response_model=Page[SyncRunResponse], summary="Google synchronisation history")
async def list_runs(session: DBSession, params: Annotated[PageParams, Depends()], actor: _READ) -> Page[SyncRunResponse]:
    where = UserSyncRun.kind == "GOOGLE"
    total = (await session.execute(select(func.count()).select_from(UserSyncRun).where(where))).scalar_one()
    rows = (await session.execute(select(UserSyncRun).where(where).order_by(UserSyncRun.started_at.desc()).limit(params.limit).offset(params.offset))).scalars().all()
    return Page.build([SyncRunResponse.model_validate(r) for r in rows], total=total, params=params)


@router.get("/runs/{run_id}", response_model=SyncRunResponse, summary="One Google synchronisation run")
async def get_run(run_id: uuid.UUID, session: DBSession, actor: _READ) -> SyncRunResponse:
    run = (await session.execute(select(UserSyncRun).where(UserSyncRun.public_id == run_id, UserSyncRun.kind == "GOOGLE"))).scalar_one_or_none()
    if run is None:
        raise NotFoundError("Synchronisation run not found.")
    return SyncRunResponse.model_validate(run)


@router.get("/batches/{batch_id}", response_model=GoogleBatchResponse, summary="A batch's Google calendar")
async def get_batch(batch_id: uuid.UUID, session: DBSession, actor: _READ) -> GoogleBatchResponse:
    row = (await session.execute(select(Batch.id, Batch.google_calendar_id, Batch.google_synced_at).where(Batch.public_id == batch_id))).first()
    if row is None:
        raise NotFoundError("Batch not found.")
    total = (await session.execute(select(func.count()).select_from(BatchSession).where(BatchSession.batch_id == row.id, BatchSession.cancelled_at.is_(None)))).scalar_one()
    mirrored = (await session.execute(select(func.count()).select_from(BatchSession).where(BatchSession.batch_id == row.id, BatchSession.google_event_id.is_not(None)))).scalar_one()
    return GoogleBatchResponse(
        batch_id=batch_id, has_calendar=row.google_calendar_id is not None,
        calendar_url=ge.calendar_url(row.google_calendar_id) if row.google_calendar_id else None,
        last_synced_at=row.google_synced_at, sessions=total, sessions_in_google=mirrored,
    )


# ---------------------------------------------------------- changes made in Google

_DECIDE = Annotated[
    CurrentUser,
    Depends(require_permissions(perm(Module.GOOGLE, Action.SYNC), perm(Module.ENROLLMENT, Action.CREATE), perm(Module.ENROLLMENT, Action.UPDATE))),
]


@router.get("/changes", response_model=Page[GoogleChangeRequestResponse], summary="Enrolment changes proposed from Google Calendar")
async def list_changes(
    session: DBSession, params: Annotated[PageParams, Depends()], actor: _READ, change_status: Annotated[str | None, Query(alias="status", pattern="^(PENDING|APPROVED|REJECTED|SUPERSEDED)$")] = None,
) -> Page[GoogleChangeRequestResponse]:
    """A guest added to or removed from an event in Google is a *proposal*. It waits here until a person decides."""
    items, total = await GoogleChangeService(session).list(status=change_status, limit=params.limit, offset=params.offset)
    return Page.build([GoogleChangeRequestResponse(**i) for i in items], total=total, params=params)


@router.post("/changes/{change_id}/approve", response_model=GoogleChangeRequestResponse, summary="Approve a proposed enrolment change")
async def approve_change(change_id: uuid.UUID, session: DBSession, actor: _DECIDE) -> GoogleChangeRequestResponse:
    """Applied through the ordinary enrolment rules. If they refuse (batch full, batch closed) the request
    stays PENDING and `last_error` says why."""
    service = GoogleChangeService(session)
    await service.approve(change_id, actor=actor)
    await session.flush()
    return await _one(session, service, change_id)


@router.post("/changes/{change_id}/reject", response_model=GoogleChangeRequestResponse, summary="Reject a proposed enrolment change")
async def reject_change(change_id: uuid.UUID, session: DBSession, actor: _SYNC) -> GoogleChangeRequestResponse:
    service = GoogleChangeService(session)
    await service.reject(change_id, actor=actor)
    await session.flush()
    return await _one(session, service, change_id)


async def _one(session, service: GoogleChangeService, change_id: uuid.UUID) -> GoogleChangeRequestResponse:  # noqa: ANN001
    items, _ = await service.list(status=None, limit=500, offset=0)
    for item in items:
        if item["public_id"] == change_id:
            return GoogleChangeRequestResponse(**item)
    raise NotFoundError("Change request not found.")
