"""Internal mail (spec §16): compose with To / Cc / Bcc, rich text and attachments; inbox, sent, starred, drafts.

Every route is scoped to the caller. There is no `?user_id=` and no administrative override: a message has its
sender and its recipients as readers and nobody else, and `institution.view_all` deliberately does not widen that.

Nothing here returns an email address or login name. People are a name and a role label, and the recipient
directory the composer searches is limited to the people the caller may write to
(`services/mail_audience.py`). The email copies are sent after the response, by `mail_delivery`.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from backend.api.deps import CurrentUser, require_permissions
from backend.core.config import get_settings
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession, commit_before_responding
from backend.integrations.smtp import SmtpMailer
from backend.schemas.base import Page, PageParams
from backend.schemas.mail import (
    ComposeRequest, DirectoryResponse, MailAttachmentInfo, MailFolder, MailListItem, MailMessageView, MailThread, ReplyOptions, StateRequest,
)
from backend.schemas.messaging import MarkReadResponse, UnreadCountResponse
from backend.services.mail_delivery import deliver_message
from backend.services.mail_service import MailService
from backend.storage import get_storage

router = APIRouter(prefix="/messages", tags=["Messaging"])

_READ = require_permissions(perm(Module.MESSAGE, Action.READ))
_CREATE = require_permissions(perm(Module.MESSAGE, Action.CREATE))
_DELETE = require_permissions(perm(Module.MESSAGE, Action.DELETE))

# Strong references, so a delivery task is not garbage-collected before it finishes.
_deliveries: set[asyncio.Task[None]] = set()


def _mail_enabled() -> bool:
    return SmtpMailer(get_settings().mail).enabled


@router.get("/recipients", response_model=DirectoryResponse, summary="People you may write to (names only)")
async def recipients(
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_CREATE)],
    query: Annotated[str | None, Query(max_length=100, description="Matches names only.")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> DirectoryResponse:
    """The composer's address book: an administrator can write to anybody; a tutor to their students and the
    administrators; a student, guardian or manager to the tutors involved with them and the administrators."""
    return DirectoryResponse(items=await MailService(session).directory(actor, query=query, limit=limit))


@router.get("/unread-count", response_model=UnreadCountResponse, summary="How many conversations have unread messages")
async def unread_count(session: DBSession, actor: Annotated[CurrentUser, Depends(_READ)]) -> UnreadCountResponse:
    return UnreadCountResponse(unread=await MailService(session).unread_count(actor))


@router.post("/read-all", response_model=MarkReadResponse, summary="Mark everything read")
async def read_all(session: DBSession, actor: Annotated[CurrentUser, Depends(_READ)]) -> MarkReadResponse:
    return MarkReadResponse(updated=await MailService(session).mark_all_read(actor))


@router.get("", response_model=Page[MailListItem], summary="List a folder")
async def list_messages(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(_READ)],
    folder: Annotated[MailFolder, Query()] = MailFolder.INBOX,
    q: Annotated[str | None, Query(max_length=100, description="Subject, body and sender name.")] = None,
) -> Page[MailListItem]:
    """One row per conversation (its latest message in this folder), newest first."""
    items, total = await MailService(session).list(actor, folder=folder, query=q, params=params)
    return Page.build(items, total=total, params=params)


@router.get("/threads/{thread_id}", response_model=MailThread, summary="A conversation (marks it read)")
async def get_thread(thread_id: uuid.UUID, session: DBSession, actor: Annotated[CurrentUser, Depends(_READ)]) -> MailThread:
    return await MailService(session).thread(actor, thread_id, mail_enabled=_mail_enabled())


@router.post("", response_model=MailMessageView, status_code=status.HTTP_201_CREATED, summary="Send a message")
async def send_message(
    payload: ComposeRequest, request: Request, session: DBSession, actor: Annotated[CurrentUser, Depends(_CREATE)]
) -> MailMessageView:
    """Recipients are checked against who the caller may write to; the body is sanitised; Bcc stays hidden from
    everybody but the sender. The email copies go out after this returns."""
    service = MailService(session)
    message = await service.save(actor, payload, send=True)
    view = service.view(message, actor)
    # Committed before the delivery task reads it (the request's own commit happens after the response is sent).
    await commit_before_responding(session)
    task = asyncio.create_task(deliver_message(request.app.state.db.session_factory, message.public_id))
    _deliveries.add(task)
    task.add_done_callback(_deliveries.discard)
    return view


@router.post("/drafts", response_model=MailMessageView, summary="Save (or update) a draft")
async def save_draft(payload: ComposeRequest, session: DBSession, actor: Annotated[CurrentUser, Depends(_CREATE)]) -> MailMessageView:
    service = MailService(session)
    return service.view(await service.save(actor, payload, send=False), actor)


@router.post("/attachments", response_model=MailAttachmentInfo, status_code=status.HTTP_201_CREATED, summary="Upload a file to attach")
async def upload_attachment(session: DBSession, actor: Annotated[CurrentUser, Depends(_CREATE)], file: Annotated[UploadFile, File()]) -> MailAttachmentInfo:
    a = await MailService(session).upload_attachment(actor, file)
    return MailAttachmentInfo(public_id=a.public_id, filename=a.filename, content_type=a.content_type, size=a.size)


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an unsent attachment")
async def delete_attachment(attachment_id: uuid.UUID, session: DBSession, actor: Annotated[CurrentUser, Depends(_CREATE)]) -> Response:
    await MailService(session).delete_attachment(actor, attachment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/attachments/{attachment_id}/download", summary="Download an attachment")
async def download_attachment(attachment_id: uuid.UUID, session: DBSession, actor: Annotated[CurrentUser, Depends(_READ)]) -> StreamingResponse:
    """Only the sender and the recipients of the message it was sent with. Always served as a download, never
    rendered in the browser, whatever its type."""
    a = await MailService(session).attachment_for_download(actor, attachment_id)
    safe = a.filename.replace('"', "").replace("\\", "")
    return StreamingResponse(
        await get_storage().open_stream(a.storage_key),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe}"', "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store", "Content-Length": str(a.size)},
    )


@router.get("/{message_id}/reply-options", response_model=ReplyOptions, summary="Who a reply would go to")
async def reply_options(message_id: uuid.UUID, session: DBSession, actor: Annotated[CurrentUser, Depends(_CREATE)]) -> ReplyOptions:
    return await MailService(session).reply_options(actor, message_id)


@router.get("/{message_id}", response_model=MailMessageView, summary="One message (or one of your drafts)")
async def get_message(message_id: uuid.UUID, session: DBSession, actor: Annotated[CurrentUser, Depends(_READ)]) -> MailMessageView:
    return await MailService(session).view_of(actor, message_id, mail_enabled=_mail_enabled())


@router.patch("/{message_id}/state", status_code=status.HTTP_204_NO_CONTENT, summary="Mark read/unread or starred")
async def set_state(message_id: uuid.UUID, payload: StateRequest, session: DBSession, actor: Annotated[CurrentUser, Depends(_READ)]) -> Response:
    await MailService(session).set_state(actor, message_id, read=payload.read, starred=payload.starred)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{message_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a message from your mailbox")
async def remove_message(message_id: uuid.UUID, session: DBSession, actor: Annotated[CurrentUser, Depends(_DELETE)]) -> Response:
    """Removes it from *your* view only; everyone else keeps their copy. A draft is deleted outright."""
    await MailService(session).remove(actor, message_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
