"""Registering a device for notifications that arrive with the tab closed.

Everything here is scoped to the caller and takes no user id: there is no
parameter that could point at somebody else's device list, which is the only
reason these routes need no ownership check beyond authentication.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from backend.api.deps import AppSettings, CurrentUser, UserAgent, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.schemas.push import (
    PushDeviceResponse,
    PushKeyResponse,
    PushSubscribeRequest,
    PushUnsubscribeRequest,
)
from backend.services.push_service import PushService

router = APIRouter(prefix="/push", tags=["Push"])

_READ = require_permissions(perm(Module.NOTIFICATION, Action.READ))


@router.get("/key", response_model=PushKeyResponse, summary="The key a browser needs to subscribe")
async def push_key(
    settings: AppSettings,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> PushKeyResponse:
    """`enabled: false` is the honest answer for a deployment with no VAPID
    keys. The console hides the Subscribe control rather than offering one that
    would succeed in the browser and then never deliver anything."""
    push = settings.push
    return PushKeyResponse(
        enabled=push.configured,
        public_key=push.vapid_public_key or None,
    )


@router.post(
    "/subscriptions",
    response_model=PushDeviceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register this device",
)
async def subscribe(
    payload: PushSubscribeRequest,
    session: DBSession,
    settings: AppSettings,
    user_agent: UserAgent,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> PushDeviceResponse:
    row = await PushService(session, settings.push).register(
        user_id=actor.id,
        endpoint=payload.endpoint,
        p256dh=payload.p256dh,
        auth=payload.auth,
        user_agent=user_agent,
    )
    await session.flush()
    return PushDeviceResponse(
        public_id=str(row.public_id),
        user_agent=row.user_agent,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
    )


@router.post(
    "/unsubscribe",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop pushing to this device",
)
async def unsubscribe(
    payload: PushUnsubscribeRequest,
    session: DBSession,
    settings: AppSettings,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> Response:
    """Scoped to the caller's own rows. A push endpoint travels in every
    subscribe call and is not a secret, so an unscoped delete would let anyone
    who had seen one silence that device."""
    await PushService(session, settings.push).unregister(
        user_id=actor.id, endpoint=payload.endpoint
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/subscriptions",
    response_model=list[PushDeviceResponse],
    summary="Devices registered for my notifications",
)
async def my_devices(
    session: DBSession,
    settings: AppSettings,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> list[PushDeviceResponse]:
    rows = await PushService(session, settings.push).list_for(actor.id)
    return [
        PushDeviceResponse(
            public_id=str(r.public_id),
            user_agent=r.user_agent,
            created_at=r.created_at,
            last_used_at=r.last_used_at,
        )
        for r in rows
    ]
