"""Notification tray endpoints (spec §16).

Read and acknowledge only. There is deliberately no create endpoint: a
notification is emitted by the system as a consequence of something
happening, and an API that lets a client place arbitrary text into somebody
else's tray is a phishing surface carrying the institution's branding.
Services call `NotificationService.emit` inside the same transaction as the
event they are announcing.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.notification import Notification
from backend.schemas.base import Page, PageParams
from backend.schemas.messaging import (
    MarkReadResponse,
    NotificationResponse,
    UnreadCountResponse,
)
from backend.core.notification_types import CATEGORIES
from backend.schemas.notification import (
    NotificationPreferenceResponse,
    NotificationSoundResponse,
    NotificationPreferencesResponse,
    PreferenceResetResponse,
    SetNotificationPreferenceRequest,
    SetNotificationSoundRequest,
)
from backend.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _response(notification: Notification) -> NotificationResponse:
    return NotificationResponse(
        public_id=notification.public_id,
        channel=notification.channel,
        type=notification.type,
        title=notification.title,
        body=notification.body,
        meta=notification.meta,
        is_read=notification.is_read,
        sent_at=notification.sent_at,
    )


@router.get("", response_model=Page[NotificationResponse], summary="List your notifications")
async def list_notifications(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.NOTIFICATION, Action.READ)))
    ],
    unread_only: Annotated[bool, Query()] = False,
    type: Annotated[str | None, Query(max_length=50, description="e.g. message_received")] = None,
) -> Page[NotificationResponse]:
    rows, total = await NotificationService(session).list_own(
        params, actor=actor, unread_only=unread_only, type_=type
    )
    return Page.build([_response(r) for r in rows], total=total, params=params)


@router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
    summary="Count your unread notifications",
)
async def unread_count(
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.NOTIFICATION, Action.READ)))
    ],
) -> UnreadCountResponse:
    return UnreadCountResponse(
        unread=await NotificationService(session).unread_count(actor=actor)
    )


@router.post(
    "/read-all", response_model=MarkReadResponse, summary="Mark every notification read"
)
async def mark_all_read(
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.NOTIFICATION, Action.UPDATE)))
    ],
) -> MarkReadResponse:
    return MarkReadResponse(
        updated=await NotificationService(session).mark_all_read(actor=actor)
    )


@router.get(
    "/preferences",
    response_model=NotificationPreferencesResponse,
    summary="What you are notified about",
)
async def list_preferences(
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.NOTIFICATION, Action.READ)))
    ],
) -> NotificationPreferencesResponse:
    """Every registered type with your setting — built from the catalogue,
    not from your stored rows, so a type added since you last opened this
    screen appears (switched on) rather than being invisible.

    Security notices come back `mandatory: true` and always enabled: a
    warning an attacker could silence by flipping a preference is worse than
    no warning, because it is believed to be working.
    """
    rows = await NotificationService(session).preferences(actor=actor)
    return NotificationPreferencesResponse(
        categories=list(CATEGORIES),
        preferences=[
            NotificationPreferenceResponse(
                type=kind.code,
                category=kind.category,
                description=kind.description,
                enabled=enabled,
                mandatory=kind.mandatory,
            )
            for kind, enabled in rows
        ],
    )


@router.put(
    "/preferences/{notification_type}",
    response_model=NotificationPreferenceResponse,
    summary="Turn one notification type on or off",
)
async def set_preference(
    notification_type: Annotated[str, Path(max_length=50)],
    payload: SetNotificationPreferenceRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.NOTIFICATION, Action.UPDATE)))
    ],
) -> NotificationPreferenceResponse:
    """Switching a type back on **deletes** the row rather than storing
    `enabled=true`: "on" is the absence of an exception, so there is one
    representation of one state and the table stays a list of opt-outs.

    Refuses a mandatory type with 422 rather than accepting the call and
    ignoring it — a setting that reports success and changes nothing is the
    decorative-field pattern applied to a security control.
    """
    kind, enabled = await NotificationService(session).set_preference(
        actor=actor, type_=notification_type, enabled=payload.enabled
    )
    return NotificationPreferenceResponse(
        type=kind.code,
        category=kind.category,
        description=kind.description,
        enabled=enabled,
        mandatory=kind.mandatory,
    )


@router.delete(
    "/preferences",
    response_model=PreferenceResetResponse,
    summary="Restore every notification to its default",
)
async def reset_preferences(
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.NOTIFICATION, Action.UPDATE)))
    ],
) -> PreferenceResetResponse:
    """Clears your opt-outs, which is the same thing as switching everything
    back on."""
    return PreferenceResetResponse(
        cleared=await NotificationService(session).reset_preferences(actor=actor)
    )


@router.post(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    summary="Mark one notification read",
)
async def mark_read(
    notification_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.NOTIFICATION, Action.UPDATE)))
    ],
) -> NotificationResponse:
    """404 for somebody else's notification — the lookup is scoped by user id
    in the query itself, so another person's tray is indistinguishable from
    an id that never existed."""
    return _response(
        await NotificationService(session).mark_read(notification_id, actor=actor)
    )


@router.put(
    "/sound",
    response_model=NotificationSoundResponse,
    summary="How loudly to announce a notification",
)
async def set_notification_sound(
    payload: SetNotificationSoundRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.NOTIFICATION, Action.UPDATE)))
    ],
) -> NotificationSoundResponse:
    """A personal interface preference, kept beside the timezone rather than in
    `notification_preferences` -- that table records which *types* somebody has
    switched off, and cannot express "keep them all, just stop chiming".

    What the browser will and will not allow is not ours to decide and is not
    worked around here: a page may not play sound until the person has
    interacted with it, and the volume belongs to the device. `prominent` is a
    longer, more insistent tone, not a louder one.
    """
    actor.notification_sound = payload.sound
    return NotificationSoundResponse(sound=payload.sound)
