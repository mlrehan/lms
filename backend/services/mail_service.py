"""Internal mail: composing, sending, listing, reading and removing messages.

What is enforced here, in one place:

* **Who may be written to** -- `MailAudience`, read from live data on every send; an out-of-audience recipient
  is refused, and refused identically whether or not that person exists.
* **What a body may contain** -- `mail_html.sanitize_html`; the stored HTML is what every reader gets.
* **Who may see what** -- a message is visible to its sender and its recipients only. **Bcc** recipients are
  disclosed to the sender alone (a Bcc'd person is told only that *they* were Bcc'd). Removing a message hides it
  from the remover's own mailbox and no one else's.
* **Attachments** -- limited in count and size, refused if they look like programs, named safely, and served only
  to the sender and the recipients of the message they were sent with.

Delivering the email copies is a separate step (`mail_delivery`), run after the message is committed, so a slow
or broken mail server can never fail or delay sending a message inside the LMS.
"""

from __future__ import annotations

import mimetypes
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Sequence

from fastapi import UploadFile
from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.models.identity.user import User
from backend.models.mail import MailAttachment, MailMessage, MailRecipient
from backend.schemas.base import PageParams
from backend.schemas.mail import (
    ComposeRequest, MailAttachmentInfo, MailDelivery, MailFolder, MailListItem, MailMessageView, MailPerson, MailThread, ReplyOptions,
)
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.mail_audience import MAX_RECIPIENTS, MailAudience, display_name, role_label
from backend.services.mail_html import clean_subject, sanitize_html, snippet, to_text
from backend.core.notification_types import NotificationType
from backend.services.notification_service import NotificationService
from backend.storage import get_storage
from backend.storage.base import build_key
from backend.utils.enums import UserStatus

MAX_ATTACHMENTS = 10
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 25 * 1024 * 1024
# Programs and scripts: the same families a mail provider refuses, since an attachment is opened by people who
# were told it came from their tutor.
BLOCKED_EXTENSIONS = frozenset(
    "ade adp app bat bin chm cmd com cpl dll dmg exe hta ins isp jar js jse lib lnk mde msc msi msp mst nsh pif ps1 ps2 reg scr sct sh shb sys vb vbe vbs vxd wsc wsf wsh".split()
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _person(user: User) -> MailPerson:
    return MailPerson(public_id=user.public_id, name=display_name(user), role=role_label(user))


def safe_filename(raw: str | None) -> str:
    """A bare, printable file name: no path, no control or bidirectional characters, never empty."""
    name = os.path.basename((raw or "").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f\x7f‪-‮⁦-⁩]", "", name).strip(" .")
    return (name or "attachment")[:200]


class MailService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audience = MailAudience(session)

    # -- directory -----------------------------------------------------------

    async def directory(self, actor: User, *, query: str | None, limit: int = 20) -> list[MailPerson]:
        return [MailPerson(public_id=p.public_id, name=p.name, role=p.role) for p in await self.audience.search(actor, query=query, limit=limit)]  # type: ignore[arg-type]

    async def reply_options(self, actor: User, public_id: uuid.UUID) -> ReplyOptions:
        """Who "Reply" and "Reply all" would address. Bcc'd people are never included (only the sender knows them), and
        nobody the caller may not write to is offered, so the composer never proposes something the server would refuse."""
        message = await self._visible_message(actor, public_id)
        allowed = await self.audience.allowed_ids(actor)

        def ok(user: User) -> bool:
            return user.id != actor.id and user.status == UserStatus.ACTIVE and (allowed is None or user.id in allowed)

        to = [r.user for r in message.recipients if r.kind == "TO"]
        cc = [r.user for r in message.recipients if r.kind == "CC"]
        sender = message.sender
        # Replying to your own message means "follow up with the same people".
        primary = [sender] if sender.id != actor.id else to
        reply = [u for u in primary if ok(u)]
        all_to = [u for u in ([sender] if sender.id != actor.id else []) + to if ok(u)]
        seen = {u.id for u in all_to}
        all_cc = [u for u in cc if ok(u) and u.id not in seen]
        return ReplyOptions(reply=[_person(u) for u in reply], reply_all_to=[_person(u) for u in all_to], reply_all_cc=[_person(u) for u in all_cc])

    # -- compose / send ------------------------------------------------------

    async def _load_mine(self, actor: User, public_id: uuid.UUID, *, draft: bool | None = None) -> MailMessage:
        message = (await self.session.execute(select(MailMessage).where(MailMessage.public_id == public_id, MailMessage.sender_id == actor.id))).scalar_one_or_none()
        if message is None or (draft is not None and message.is_draft is not draft):
            raise NotFoundError("Message not found.")
        return message

    async def _visible_message(self, actor: User, public_id: uuid.UUID) -> MailMessage:
        """A sent message the actor took part in and has not removed -- what a reply may answer."""
        message = (await self.session.execute(select(MailMessage).where(MailMessage.public_id == public_id, MailMessage.is_draft.is_(False)))).scalar_one_or_none()
        if message is not None:
            mine = message.sender_id == actor.id and not message.sender_deleted
            received = any(r.user_id == actor.id and not r.is_deleted for r in message.recipients)
            if mine or received:
                return message
        raise NotFoundError("Message not found.")

    async def save(self, actor: User, payload: ComposeRequest, *, send: bool) -> MailMessage:
        draft = await self._load_mine(actor, payload.draft_id, draft=True) if payload.draft_id else None

        # Who: one row per person, and if somebody is in more than one field the most visible one wins.
        kinds: dict[uuid.UUID, str] = {}
        for kind, ids in (("BCC", payload.bcc), ("CC", payload.cc), ("TO", payload.to)):
            for pid in ids:
                kinds[pid] = kind
        if len(kinds) > MAX_RECIPIENTS:
            raise ValidationError(f"A message can go to at most {MAX_RECIPIENTS} people.")
        people = await self.audience.resolve(actor, list(kinds))

        parent = await self._visible_message(actor, payload.reply_to_id) if payload.reply_to_id else None

        subject = clean_subject(payload.subject)
        body_html = sanitize_html(payload.body_html)
        body_text = to_text(body_html)

        attachments = await self._claim_attachments(actor, payload.attachment_ids, message=draft)
        if send:
            if not kinds:
                raise ValidationError("Add at least one recipient.")
            if not (subject or body_text or attachments):
                raise ValidationError("Write something, or attach a file, before sending.")

        message = draft or MailMessage(sender_id=actor.id, thread_id=uuid.uuid4(), is_draft=True, recipients=[], attachments=[])
        if draft is None:
            self.session.add(message)
        if parent is not None:
            message.thread_id, message.parent_id = parent.thread_id, parent.id
        message.subject, message.body_html, message.body_text = subject, body_html, body_text
        message.email_copy_requested = payload.email_copy
        await self.session.flush()

        # Replace the recipients and reconcile the attachments with what was asked for.
        await self.session.execute(delete(MailRecipient).where(MailRecipient.message_id == message.id))
        self.session.add_all([MailRecipient(message_id=message.id, user_id=people[pid].id, kind=kind) for pid, kind in kinds.items()])
        keep = {a.id for a in attachments}
        for old in list(message.attachments):
            if old.id not in keep:
                await self._drop_file(old)
        for a in attachments:
            a.message_id = message.id

        if send:
            message.is_draft, message.sent_at = False, _now()
            audit_service.record(self.session, action=AuditAction.CREATE, actor_user_id=actor.id, actor_email=actor.email, entity_type="mail_message", entity_id=message.id,
                                 details={"recipients": len(kinds), "attachments": len(attachments), "reply": parent is not None})

            # `MESSAGE_RECEIVED` was in the catalogue and shown as a preference toggle that defaults to on, but
            # nothing ever raised it -- so the switch governed nothing. Bcc recipients are notified too: being
            # hidden from the other recipients is not a reason to be hidden from yourself.
            await NotificationService(self.session).notify_many(
                [people[pid].id for pid in kinds],
                type_=NotificationType.MESSAGE_RECEIVED,
                title=f"New message from {display_name(actor)}",
                body=subject or snippet(body_text) or "(no subject)",
                meta={"message_id": str(message.public_id), "thread_id": str(message.thread_id)},
            )
        await self.session.flush()
        await self.session.refresh(message, attribute_names=["recipients", "attachments"])
        return message

    # -- attachments ---------------------------------------------------------

    async def _claim_attachments(self, actor: User, public_ids: Sequence[uuid.UUID], *, message: MailMessage | None) -> list[MailAttachment]:
        if not public_ids:
            return []
        rows = list((await self.session.execute(select(MailAttachment).where(MailAttachment.public_id.in_(set(public_ids))))).scalars())
        found = {a.public_id: a for a in rows}
        claimed: list[MailAttachment] = []
        for pid in public_ids:
            a = found.get(pid)
            # Yours, and not already sent with some other message.
            if a is None or a.uploader_id != actor.id or (a.message_id is not None and (message is None or a.message_id != message.id)):
                raise NotFoundError("Attachment not found.")
            claimed.append(a)
        if len(claimed) > MAX_ATTACHMENTS:
            raise ValidationError(f"A message can carry at most {MAX_ATTACHMENTS} attachments.")
        if sum(a.size for a in claimed) > MAX_TOTAL_ATTACHMENT_BYTES:
            raise ValidationError(f"Attachments can total at most {MAX_TOTAL_ATTACHMENT_BYTES // (1024 * 1024)} MB.")
        return claimed

    async def upload_attachment(self, actor: User, upload: UploadFile) -> MailAttachment:
        name = safe_filename(upload.filename)
        extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if extension in BLOCKED_EXTENSIONS:
            raise ValidationError("Programs and scripts cannot be attached.")
        data = await upload.read(MAX_ATTACHMENT_BYTES + 1)  # bounded: never buffer an unbounded body
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise ValidationError(f"Each attachment can be at most {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB.")
        if not data:
            raise ValidationError("That file is empty.")
        # The type comes from the name, not from what the client claims: a client can label anything anything.
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        key = build_key(prefix=f"mail/{actor.public_id}/{uuid.uuid4().hex}", filename=name)
        await get_storage().save(key, data, content_type=content_type)
        attachment = MailAttachment(uploader_id=actor.id, filename=name, content_type=content_type[:100], size=len(data), storage_key=key)
        self.session.add(attachment)
        await self.session.flush()
        return attachment

    async def _drop_file(self, attachment: MailAttachment) -> None:
        try:
            await get_storage().delete(attachment.storage_key)
        except Exception:  # noqa: BLE001 -- a missing file must not block removing the row
            pass
        await self.session.delete(attachment)

    async def delete_attachment(self, actor: User, public_id: uuid.UUID) -> None:
        a = (await self.session.execute(select(MailAttachment).where(MailAttachment.public_id == public_id, MailAttachment.uploader_id == actor.id))).scalar_one_or_none()
        if a is None:
            raise NotFoundError("Attachment not found.")
        if a.message_id is not None:
            message = (await self.session.execute(select(MailMessage).where(MailMessage.id == a.message_id))).scalar_one()
            if not message.is_draft:
                raise ConflictError("That attachment was already sent and cannot be removed.")
        await self._drop_file(a)

    async def attachment_for_download(self, actor: User, public_id: uuid.UUID) -> MailAttachment:
        a = (await self.session.execute(select(MailAttachment).where(MailAttachment.public_id == public_id))).scalar_one_or_none()
        if a is None:
            raise NotFoundError("Attachment not found.")
        if a.uploader_id == actor.id:
            return a
        if a.message_id is not None:
            message = (await self.session.execute(select(MailMessage).where(MailMessage.id == a.message_id, MailMessage.is_draft.is_(False)))).scalar_one_or_none()
            if message is not None and any(r.user_id == actor.id and not r.is_deleted for r in message.recipients):
                return a
        raise NotFoundError("Attachment not found.")

    # -- reading -------------------------------------------------------------

    def view(self, message: MailMessage, viewer: User, *, delivery: MailDelivery | None = None) -> MailMessageView:
        mine = message.sender_id == viewer.id
        row = next((r for r in message.recipients if r.user_id == viewer.id), None)
        by_kind = lambda kind: [_person(r.user) for r in message.recipients if r.kind == kind]  # noqa: E731
        return MailMessageView(
            public_id=message.public_id, thread_id=message.thread_id, parent_id=None, subject=message.subject, body_html=message.body_html,
            sender=_person(message.sender), to=by_kind("TO"), cc=by_kind("CC"),
            # Bcc is the sender's alone; a Bcc'd reader learns only that they themselves were Bcc'd.
            bcc=by_kind("BCC") if mine else [], you_were_bcc=bool(row and row.kind == "BCC" and not mine),
            sent_at=message.sent_at, is_draft=message.is_draft,
            is_read=True if mine else bool(row and row.is_read), is_starred=message.sender_starred if mine else bool(row and row.is_starred), is_mine=mine,
            attachments=[MailAttachmentInfo(public_id=a.public_id, filename=a.filename, content_type=a.content_type, size=a.size) for a in message.attachments],
            delivery=delivery if mine else None,
        )

    def _delivery(self, message: MailMessage, enabled: bool) -> MailDelivery:
        counts = {"SENT": 0, "FAILED": 0, "SKIPPED": 0, "PENDING": 0}
        failures: list[str] = []
        for r in message.recipients:
            counts[r.email_status] = counts.get(r.email_status, 0) + 1
            if r.email_status == "FAILED":
                failures.append(display_name(r.user))
        return MailDelivery(enabled=enabled, sent=counts["SENT"], failed=counts["FAILED"], skipped=counts["SKIPPED"], pending=counts["PENDING"],
                            copy_to_me=message.email_copy_status if message.email_copy_requested else None, failures=failures)

    async def view_of(self, actor: User, public_id: uuid.UUID, *, mail_enabled: bool) -> MailMessageView:
        """One message the actor may read, or one of their own drafts."""
        message = (await self.session.execute(select(MailMessage).where(MailMessage.public_id == public_id))).scalar_one_or_none()
        if message is None:
            raise NotFoundError("Message not found.")
        mine = message.sender_id == actor.id
        if message.is_draft and not mine:
            raise NotFoundError("Message not found.")
        if not mine and not any(r.user_id == actor.id and not r.is_deleted for r in message.recipients):
            raise NotFoundError("Message not found.")
        if mine and message.sender_deleted:
            raise NotFoundError("Message not found.")
        return self.view(message, actor, delivery=self._delivery(message, mail_enabled) if mine and not message.is_draft else None)

    async def thread(self, actor: User, thread_id: uuid.UUID, *, mail_enabled: bool) -> MailThread:
        visible = or_(
            and_(MailMessage.sender_id == actor.id, MailMessage.sender_deleted.is_(False)),
            exists().where(MailRecipient.message_id == MailMessage.id, MailRecipient.user_id == actor.id, MailRecipient.is_deleted.is_(False)),
        )
        messages = list((await self.session.execute(
            select(MailMessage).where(MailMessage.thread_id == thread_id, MailMessage.is_draft.is_(False), visible).order_by(MailMessage.sent_at, MailMessage.id)
        )).scalars().unique())
        if not messages:
            raise NotFoundError("Conversation not found.")
        # Opening a conversation reads it.
        await self.session.execute(
            update(MailRecipient).where(MailRecipient.user_id == actor.id, MailRecipient.is_read.is_(False), MailRecipient.message_id.in_([m.id for m in messages]))
            .values(is_read=True, read_at=_now())
        )
        views = []
        for m in messages:
            if m.sender_id != actor.id:
                for r in m.recipients:
                    if r.user_id == actor.id:
                        r.is_read = True
            views.append(self.view(m, actor, delivery=self._delivery(m, mail_enabled) if m.sender_id == actor.id else None))
        return MailThread(thread_id=thread_id, subject=messages[0].subject or "(no subject)", messages=views)

    # -- lists ---------------------------------------------------------------

    def _folder_filter(self, actor: User, folder: MailFolder):  # noqa: ANN202
        received = exists().where(MailRecipient.message_id == MailMessage.id, MailRecipient.user_id == actor.id, MailRecipient.is_deleted.is_(False))
        if folder == MailFolder.INBOX:
            return and_(MailMessage.is_draft.is_(False), received)
        if folder == MailFolder.SENT:
            return and_(MailMessage.is_draft.is_(False), MailMessage.sender_id == actor.id, MailMessage.sender_deleted.is_(False))
        if folder == MailFolder.DRAFTS:
            return and_(MailMessage.is_draft.is_(True), MailMessage.sender_id == actor.id, MailMessage.sender_deleted.is_(False))
        starred_in = exists().where(MailRecipient.message_id == MailMessage.id, MailRecipient.user_id == actor.id, MailRecipient.is_deleted.is_(False), MailRecipient.is_starred.is_(True))
        starred_out = and_(MailMessage.sender_id == actor.id, MailMessage.sender_deleted.is_(False), MailMessage.sender_starred.is_(True))
        return and_(MailMessage.is_draft.is_(False), or_(starred_in, starred_out))

    async def list(self, actor: User, *, folder: MailFolder, query: str | None, params: PageParams) -> tuple[list[MailListItem], int]:
        where = self._folder_filter(actor, folder)
        term = (query or "").strip().lower()
        if term:
            like = f"%{term}%"
            sender_match = exists().where(User.id == MailMessage.sender_id, func.lower(func.concat_ws(" ", User.first_name, User.last_name)).like(like))
            where = and_(where, or_(func.lower(MailMessage.subject).like(like), func.lower(MailMessage.body_text).like(like), sender_match))

        if folder == MailFolder.DRAFTS:
            page_ids = (await self.session.execute(select(MailMessage.id).where(where).order_by(MailMessage.updated_at.desc(), MailMessage.id.desc()).limit(params.limit).offset(params.offset))).scalars().all()
            total = int((await self.session.execute(select(func.count()).select_from(MailMessage).where(where))).scalar_one())
        else:
            # One row per conversation: its latest message among those this folder shows.
            ranked = (
                select(MailMessage.id.label("id"), MailMessage.sent_at.label("sent_at"),
                       func.row_number().over(partition_by=MailMessage.thread_id, order_by=(MailMessage.sent_at.desc(), MailMessage.id.desc())).label("rn"))
                .where(where).subquery()
            )
            total = int((await self.session.execute(select(func.count()).select_from(ranked).where(ranked.c.rn == 1))).scalar_one())
            page_ids = (await self.session.execute(select(ranked.c.id).where(ranked.c.rn == 1).order_by(ranked.c.sent_at.desc(), ranked.c.id.desc()).limit(params.limit).offset(params.offset))).scalars().all()
        if not page_ids:
            return [], total

        by_id = {m.id: m for m in (await self.session.execute(select(MailMessage).where(MailMessage.id.in_(page_ids)))).scalars().unique()}
        ordered = [by_id[i] for i in page_ids if i in by_id]
        threads = {m.thread_id for m in ordered}

        counts = dict((await self.session.execute(
            select(MailMessage.thread_id, func.count()).where(MailMessage.thread_id.in_(threads), MailMessage.is_draft.is_(False),
                or_(and_(MailMessage.sender_id == actor.id, MailMessage.sender_deleted.is_(False)),
                    exists().where(MailRecipient.message_id == MailMessage.id, MailRecipient.user_id == actor.id, MailRecipient.is_deleted.is_(False)))).group_by(MailMessage.thread_id)
        )).all())
        unread = {t for (t,) in (await self.session.execute(
            select(MailMessage.thread_id).join(MailRecipient, MailRecipient.message_id == MailMessage.id)
            .where(MailMessage.thread_id.in_(threads), MailRecipient.user_id == actor.id, MailRecipient.is_read.is_(False), MailRecipient.is_deleted.is_(False), MailMessage.is_draft.is_(False)).distinct()
        )).all()}

        items = []
        for m in ordered:
            v = self.view(m, actor)
            names = [p.name for p in (v.to + v.cc + v.bcc)]
            summary = "" if not names else (", ".join(names[:2]) + (f" +{len(names) - 2}" if len(names) > 2 else ""))
            items.append(MailListItem(
                public_id=m.public_id, thread_id=m.thread_id, subject=m.subject or ("(no subject)" if not m.is_draft else "(draft)"), snippet=snippet(m.body_text),
                sender=v.sender, recipients_summary=summary or ("(no recipients)" if m.is_draft else ""), sent_at=m.sent_at, updated_at=m.updated_at,
                is_read=(m.thread_id not in unread) if not m.is_draft else True, is_starred=v.is_starred, is_draft=m.is_draft, has_attachments=bool(m.attachments),
                thread_count=int(counts.get(m.thread_id, 1)), is_mine=v.is_mine,
            ))
        return items, total

    async def unread_count(self, actor: User) -> int:
        return int((await self.session.execute(
            select(func.count()).select_from(MailRecipient).join(MailMessage, MailMessage.id == MailRecipient.message_id)
            .where(MailRecipient.user_id == actor.id, MailRecipient.is_read.is_(False), MailRecipient.is_deleted.is_(False), MailMessage.is_draft.is_(False))
        )).scalar_one())

    # -- state ---------------------------------------------------------------

    async def _mine_or_received(self, actor: User, public_id: uuid.UUID) -> tuple[MailMessage, MailRecipient | None]:
        message = (await self.session.execute(select(MailMessage).where(MailMessage.public_id == public_id))).scalar_one_or_none()
        if message is None:
            raise NotFoundError("Message not found.")
        row = next((r for r in message.recipients if r.user_id == actor.id and not r.is_deleted), None)
        if message.sender_id == actor.id and not message.sender_deleted:
            return message, row
        if row is not None and not message.is_draft:
            return message, row
        raise NotFoundError("Message not found.")

    async def set_state(self, actor: User, public_id: uuid.UUID, *, read: bool | None, starred: bool | None) -> None:
        message, row = await self._mine_or_received(actor, public_id)
        if starred is not None:
            if message.sender_id == actor.id:
                message.sender_starred = starred
            if row is not None:
                row.is_starred = starred
        if read is not None and row is not None:
            row.is_read, row.read_at = read, (_now() if read else None)

    async def remove(self, actor: User, public_id: uuid.UUID) -> None:
        message, row = await self._mine_or_received(actor, public_id)
        if message.is_draft:
            for a in list(message.attachments):
                await self._drop_file(a)
            await self.session.delete(message)
            return
        if message.sender_id == actor.id:
            message.sender_deleted = True
        if row is not None:
            row.is_deleted = True

    async def mark_all_read(self, actor: User) -> int:
        sent_ids = select(MailMessage.id).where(MailMessage.is_draft.is_(False))
        result = await self.session.execute(
            update(MailRecipient).where(MailRecipient.user_id == actor.id, MailRecipient.is_read.is_(False), MailRecipient.message_id.in_(sent_ids)).values(is_read=True, read_at=_now())
        )
        return int(result.rowcount or 0)
