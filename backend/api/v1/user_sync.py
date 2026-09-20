"""Manual trigger and history for the LAIT user synchronisation.

Registered *before* `users.router` in `api/router.py`: FastAPI matches in
definition order and `/users/{user_id}` would otherwise swallow `/users/sync`
and reject "sync" as a malformed UUID.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import func, select

from backend.api.deps import CurrentUser, require_permissions
from backend.core.config import get_settings
from backend.core.errors import NotFoundError
from backend.core.logging import get_logger
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.user_sync import UserSyncRun
from backend.schemas.base import Page, PageParams
from backend.schemas.user import SyncRunResponse
from backend.services.lait_sync_service import LaitSyncService

logger = get_logger("lait.sync.api")
router = APIRouter(prefix="/users/sync", tags=["Users"])

# asyncio holds only a weak reference to a task; without this the run can be
# garbage-collected mid-flight and vanish without an error.
_running: set[asyncio.Task[None]] = set()

_SYNC = Annotated[CurrentUser, Depends(require_permissions(perm(Module.USER, Action.SYNC)))]


@router.post(
    "",
    response_model=SyncRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a synchronisation from LAIT now",
)
async def start_sync(request: Request, actor: _SYNC, dry_run: bool = False) -> SyncRunResponse:
    """Returns at once with the run; poll `GET /users/sync/runs/{id}` for the
    outcome. A run already in progress answers 409."""
    service = LaitSyncService(request.app.state.db.session_factory, get_settings())
    run = await service.start(trigger_type="MANUAL", triggered_by_user_id=actor.id, dry_run=dry_run)

    task = asyncio.create_task(_execute(service, run.id))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return SyncRunResponse.model_validate(run)


async def _execute(service: LaitSyncService, run_id: int) -> None:
    try:
        await service.execute(run_id)
    except Exception:  # noqa: BLE001 - execute() finalises its own row; this is a last resort
        logger.exception("LAIT sync task failed outside its own handling")


@router.get("/runs", response_model=Page[SyncRunResponse], summary="Synchronisation history")
async def list_runs(
    session: DBSession, params: Annotated[PageParams, Depends()], actor: _SYNC
) -> Page[SyncRunResponse]:
    total = (await session.execute(select(func.count()).select_from(UserSyncRun))).scalar_one()
    rows = (
        await session.execute(
            select(UserSyncRun).order_by(UserSyncRun.started_at.desc()).limit(params.limit).offset(params.offset)
        )
    ).scalars().all()
    return Page.build([SyncRunResponse.model_validate(r) for r in rows], total=total, params=params)


@router.get("/runs/{run_id}", response_model=SyncRunResponse, summary="One synchronisation run")
async def get_run(run_id: uuid.UUID, session: DBSession, actor: _SYNC) -> SyncRunResponse:
    run = (await session.execute(select(UserSyncRun).where(UserSyncRun.public_id == run_id))).scalar_one_or_none()
    if run is None:
        raise NotFoundError("Synchronisation run not found.")
    return SyncRunResponse.model_validate(run)
