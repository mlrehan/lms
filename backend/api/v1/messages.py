"""Private message endpoints (spec §16).

Every route here is implicitly scoped to the caller: there is no
`?user_id=` and no administrative override, because a private message has
exactly two legitimate readers. See `services/message_service.py` for why
`institution.view_all` deliberately does not widen this surface.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.identity.user import User
from backend.models.messaging import UserMessage
from backend.schemas.base import Page, PageParams
from backend.schemas.messaging import (
    ConversationResponse,
    MarkReadResponse,
    MessageBox,
    MessageResponse,
    PartyRef,
    SendMessageRequest,
    UnreadCountResponse,
)
from backend.services.message_service import MessageService

router = APIRouter(prefix="/messages", tags=["Messaging"])

_SNIPPET_CHARS = 160


def _party(user: User) -> PartyRef:
    return PartyRef(
        public_id=user.public_id, username=user.username, full_name=user.full_name
    )


def _response(message: UserMessage) -> MessageResponse:
    return MessageResponse(
        public_id=message.public_id,
        sender=_party(message.sender),
        recipient=_party(message.recipient),
        course_id=message.course.public_id if message.course else None,
        batch_id=message.batch.public_id if message.batch else None,
        subject=message.subject,
        body=message.body,
        is_read=message.is_read,
        read_at=message.read_at,
        created_at=message.created_at,
    )


@router.get("", response_model=Page[MessageResponse], summary="List your messages")
async def list_messages(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.MESSAGE, Action.READ)))
    ],
    box: Annotated[MessageBox, Query(description="inbox, sent, or all")] = MessageBox.INBOX,
    unread_only: Annotated[bool, Query()] = False,
    with_user: Annotated[uuid.UUID | None, Query(description="One correspondent.")] = None,
    q: Annotated[str | None, Query(max_length=100, description="Search subject and body.")] = None,
) -> Page[MessageResponse]:
    rows, total = await MessageService(session).list_messages(
        params, actor=actor, box=box, unread_only=unread_only, with_user=with_user, query=q
    )
    return Page.build([_response(r) for r in rows], total=total, params=params)


@router.get(
    "/conversations",
    response_model=Page[ConversationResponse],
    summary="List your correspondents",
)
async def list_conversations(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.MESSAGE, Action.READ)))
    ],
) -> Page[ConversationResponse]:
    """One row per person you have exchanged messages with, most recent
    first, with that thread's unread count — a mailbox landing page without
    the client having to group a page of messages itself."""
    rows, total = await MessageService(session).conversations(params, actor=actor)
    items = [
        ConversationResponse(
            counterpart=_party(row["counterpart"]),
            last_message_id=row["last_message"].public_id,
            last_message_at=row["last_message"].created_at,
            last_subject=row["last_message"].subject,
            last_snippet=(row["last_message"].body or "")[:_SNIPPET_CHARS] or None,
            unread_count=row["unread_count"],
            total_messages=row["total_messages"],
        )
        for row in rows
    ]
    return Page.build(items, total=total, params=params)


@router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
    summary="Count your unread messages",
)
async def unread_count(
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.MESSAGE, Action.READ)))
    ],
) -> UnreadCountResponse:
    return UnreadCountResponse(unread=await MessageService(session).unread_count(actor=actor))


@router.post(
    "",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a message",
)
async def send_message(
    payload: SendMessageRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.MESSAGE, Action.CREATE)))
    ],
) -> MessageResponse:
    """Refused with 403 unless you and the recipient are already connected —
    a tutor and their student, a guardian and their ward, a manager and their
    employee, or anyone writing to the administration. `message.create` says
    you may send; it cannot say to whom, and without that second check one
    grant turns the user directory into an address book."""
    return _response(await MessageService(session).send(payload, actor=actor))


@router.post(
    "/read-all", response_model=MarkReadResponse, summary="Mark every message read"
)
async def mark_all_read(
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.MESSAGE, Action.READ)))
    ],
) -> MarkReadResponse:
    return MarkReadResponse(updated=await MessageService(session).mark_all_read(actor=actor))


@router.get("/{message_id}", response_model=MessageResponse, summary="Get one message")
async def get_message(
    message_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.MESSAGE, Action.READ)))
    ],
) -> MessageResponse:
    return _response(await MessageService(session).get(message_id, actor=actor))


@router.post(
    "/{message_id}/read", response_model=MessageResponse, summary="Mark one message read"
)
async def mark_read(
    message_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.MESSAGE, Action.READ)))
    ],
) -> MessageResponse:
    """Marking read is an explicit act, not a side effect of `GET`: a client
    that prefetches a list would otherwise silently clear the unread state of
    messages nobody opened."""
    return _response(await MessageService(session).mark_read(message_id, actor=actor))


@router.delete(
    "/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a message from your mailbox",
)
async def delete_message(
    message_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.MESSAGE, Action.DELETE)))
    ],
) -> Response:
    """Removes it from **your** side only. The other participant keeps their
    copy until they delete it too."""
    await MessageService(session).delete(message_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
