"""The "Sync All Data" button, its progress, its history and its schedule.

Registered *before* `users.router` and `courses.router` would matter if it
shared their prefixes; it does not -- these live under `/sync` of their own,
because the operation spans users, courses, batches, sessions and enrolments
and belongs to none of them.

**Gated on the three permissions the pipeline actually exercises**:
`user.sync`, `course.sync` and `managed_student.create`, all three required.
That is the honest gate -- it is exactly the authority the steps use, and it
is no more permissive than the two "Sync now" buttons the console already
has, which Administrators can already press individually. Gating on the role
name instead would be the console's first exception to "gate on what a caller
may do, never on what they are called".

**The work does not run in the request.** The route answers 202 with the run,
and the pipeline continues in a background task held by this module -- the
same shape `users/sync` and `courses/sync` already use. Closing the browser,
navigating away or signing out does not touch it.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select

from backend.api.deps import CurrentUser, require_permissions, resolve_permissions
from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.sync_pipeline import SyncPipelineRun
from backend.schemas.administration import SettingWriteRequest
from backend.schemas.base import Page, PageParams
from backend.schemas.sync_pipeline import (
    SyncPipelineResponse,
    SyncPipelineStatusResponse,
    SyncScheduleRequest,
)
from backend.services.setting_service import SettingService
from backend.services.sync_pipeline_service import SyncPipelineService, latest_runs
from backend.services.sync_schedule import (
    SETTING_ENABLED,
    SETTING_INTERVAL_HOURS,
    read_schedule,
)

logger = get_logger("sync.pipeline.api")
router = APIRouter(prefix="/sync", tags=["Integrations"])

# asyncio keeps only a weak reference to a task; hold it or the pipeline can be
# collected mid-flight and vanish without an error.
_running: set[asyncio.Task[None]] = set()

_SYNC = Annotated[
    CurrentUser,
    Depends(
        require_permissions(
            perm(Module.USER, Action.SYNC),
            perm(Module.COURSE, Action.SYNC),
            perm(Module.MANAGED_STUDENT, Action.CREATE),
        )
    ),
]


def _service(request: Request) -> SyncPipelineService:
    return SyncPipelineService(request.app.state.db.session_factory, get_settings())


async def _status_payload(request: Request, *, can_configure: bool) -> SyncPipelineStatusResponse:
    """The dashboard payload, read through sessions of its own.

    Taking its own session is what lets the schedule handler reuse it after
    committing the request's session.
    """
    service = _service(request)
    factory = request.app.state.db.session_factory

    running = await service.current()
    last_ok = await service.last_successful()
    latest = running
    async with factory() as session:
        if latest is None:
            latest = (
                await session.execute(
                    select(SyncPipelineRun).order_by(SyncPipelineRun.started_at.desc()).limit(1)
                )
            ).scalar_one_or_none()
        schedule = await read_schedule(session)

    return SyncPipelineStatusResponse(
        running=SyncPipelineResponse.model_validate(running) if running else None,
        latest=SyncPipelineResponse.model_validate(latest) if latest else None,
        last_successful_at=last_ok.finished_at if last_ok else None,
        schedule_enabled=schedule.enabled,
        schedule_interval_hours=schedule.interval_hours,
        can_configure_schedule=can_configure,
    )


def _spawn(service: SyncPipelineService, run_id: int) -> None:
    async def go() -> None:
        try:
            await service.execute(run_id)
        except Exception:  # noqa: BLE001 - execute() finalises its own rows; last resort
            logger.exception("Sync pipeline failed outside its own handling")

    task = asyncio.create_task(go())
    _running.add(task)
    task.add_done_callback(_running.discard)


@router.post(
    "/all",
    response_model=SyncPipelineResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run every synchronisation, in dependency order",
    responses={status.HTTP_409_CONFLICT: {"description": "A synchronisation is already running."}},
)
async def start_all(request: Request, actor: _SYNC) -> SyncPipelineResponse:
    """Starts users → managers → courses → batches → sessions → enrolments.

    Answers at once; poll `GET /sync/all/status`. A second press while one is
    running is refused with 409 by a database index, not by a check here.
    """
    service = _service(request)
    run = await service.start(trigger_type="MANUAL", triggered_by_user_id=actor.id)
    _spawn(service, run.id)
    return SyncPipelineResponse.model_validate(run)


@router.post(
    "/all/{run_id}/retry",
    response_model=SyncPipelineResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run the steps of a past run that did not succeed",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "No such run."},
        status.HTTP_409_CONFLICT: {"description": "Still running, or nothing to retry."},
    },
)
async def retry_run(request: Request, run_id: uuid.UUID, actor: _SYNC) -> SyncPipelineResponse:
    """Steps that already completed are left alone; the rest run again."""
    service = _service(request)
    run = await service.retry(run_id, triggered_by_user_id=actor.id)
    _spawn(service, run.id)
    return SyncPipelineResponse.model_validate(run)


@router.get(
    "/all/status",
    response_model=SyncPipelineStatusResponse,
    summary="What the dashboard panel shows",
)
async def pipeline_status(
    request: Request, actor: _SYNC
) -> SyncPipelineStatusResponse:
    """The run in flight, the most recent run, the last success, and the schedule."""
    return await _status_payload(
        request,
        can_configure=perm(Module.SETTING, Action.UPDATE) in resolve_permissions(actor),
    )


@router.get(
    "/all/runs",
    response_model=Page[SyncPipelineResponse],
    summary="Synchronisation history",
)
async def list_pipeline_runs(
    session: DBSession, params: Annotated[PageParams, Depends()], actor: _SYNC
) -> Page[SyncPipelineResponse]:
    rows, total = await latest_runs(session, limit=params.limit, offset=params.offset)
    return Page.build(
        [SyncPipelineResponse.model_validate(r) for r in rows], total=total, params=params
    )


@router.get(
    "/all/runs/{run_id}",
    response_model=SyncPipelineResponse,
    summary="One synchronisation run",
)
async def get_pipeline_run(
    request: Request, run_id: uuid.UUID, actor: _SYNC
) -> SyncPipelineResponse:
    run = await _service(request).by_public_id(run_id)
    return SyncPipelineResponse.model_validate(run)


@router.put(
    "/all/schedule",
    response_model=SyncPipelineStatusResponse,
    summary="Turn automatic synchronisation on or off, and set its frequency",
)
async def set_schedule(
    request: Request,
    payload: SyncScheduleRequest,
    session: DBSession,
    # Changing a schedule is changing a system setting, so it carries that
    # permission too -- which by design not even an Administrator holds.
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.SETTING, Action.UPDATE)))
    ],
) -> SyncPipelineStatusResponse:
    """Stored in the existing system-settings table, so one screen still shows
    every setting this deployment has, and the worker reads it without a
    restart."""
    service = SettingService(session)
    await service.put(
        SETTING_ENABLED,
        SettingWriteRequest(
            value="true" if payload.enabled else "false",
            description="Automatic LAIT synchronisation: true or false.",
        ),
        actor=actor,
    )
    await service.put(
        SETTING_INTERVAL_HOURS,
        SettingWriteRequest(
            value=str(payload.interval_hours),
            description="Hours between automatic LAIT synchronisations.",
        ),
        actor=actor,
    )
    await session.commit()

    # A fresh session: the request's own has just been committed, and reading
    # from it again raises "Can't operate on closed transaction".
    return await _status_payload(request, can_configure=True)


__all__ = ["router"]
