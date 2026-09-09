"""Private messaging and per-user notifications (spec §16).

**Who may write to whom is the whole security question here**, and it is not
answerable by a permission. `message.create` is held by every role, because
every role has somebody they legitimately need to contact; what it cannot say
is *which* people. Left unanswered, a single grant turns the user directory
into an address book: one student could message all 10,000 others, which is
how a platform becomes a spam vector and how a guardian ends up contacting
another family's child.

The rule implemented in :meth:`MessageService._assert_can_correspond` is
symmetric and derived from relationships that already exist in the schema:

* An unrestricted caller (`institution.view_all` -- Super Admin,
  Administrator) may write to anyone. Administration has to be able to reach
  people.
* Anyone may write **to** an unrestricted user. A student who cannot contact
  the office has no route to report a problem, and an inbox the institution
  publishes is not a directory it leaks.
* Otherwise the two must already be connected: either the recipient is in the
  sender's scope (a tutor's student, a guardian's ward, a manager's employee)
  **or** the sender is in the recipient's scope (the student writing back to
  their tutor, the ward to their guardian). The reverse direction has to be
  checked explicitly -- omitting it would make every relationship in the
  product one-way, with only the more powerful party able to open a
  conversation.

**Reading is stricter than seeing.** Nothing in here relaxes for an
administrator: `institution.view_all` is a grant over institutional records
-- enrollments, attendance, grades -- and a private message between two
people is not one of those. An administrator who needs message content for an
investigation goes through the audit trail and a deliberate act, not through
an ordinary list endpoint.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.identity.user import User
from backend.models.messaging import UserMessage
from backend.models.notification import Notification
from backend.repositories.messaging import MessageRepository, NotificationRepository
from backend.schemas.base import PageParams
from backend.schemas.messaging import MessageBox, SendMessageRequest
from backend.services import audit_service
from backend.core.notification_types import NotificationType
from backend.services.audit_service import AuditAction
from backend.services.notification_service import NotificationService
from backend.services.scope import ScopeResolver
from backend.utils.enums import NotificationChannel, UserStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MessageService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.messages = MessageRepository(session)
        self.scopes = ScopeResolver(session)
        self.notifications = NotificationService(session)

    # -- reads ---------------------------------------------------------------

    async def list_messages(
        self,
        params: PageParams,
        *,
        actor: User,
        box: MessageBox = MessageBox.INBOX,
        unread_only: bool = False,
        with_user: uuid.UUID | None = None,
        query: str | None = None,
    ) -> tuple[Sequence[UserMessage], int]:
        with_user_id = None
        if with_user is not None:
            with_user_id = (await self._load_user(with_user)).id

        return await self.messages.search(
            params,
            user_id=actor.id,
            box=box,
            unread_only=unread_only,
            with_user_id=with_user_id,
            query=query,
        )

    async def conversations(
        self, params: PageParams, *, actor: User
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = await self.messages.conversations(params, user_id=actor.id)
        if not rows:
            return [], total

        last_messages = {
            m.id: m for m in await self.messages.by_ids([r[1] for r in rows])
        }
        counterparts = await self._load_users_by_id({r[0] for r in rows})

        summaries: list[dict[str, Any]] = []
        for counterpart_id, last_id, count, unread in rows:
            counterpart = counterparts.get(counterpart_id)
            message = last_messages.get(last_id)
            if counterpart is None or message is None:
                # The correspondent's account was hard-deleted out from under
                # a surviving row. Skipping is right: a conversation with
                # nobody cannot be opened, and rendering a blank name in the
                # mailbox is worse than not listing it.
                continue
            summaries.append(
                {
                    "counterpart": counterpart,
                    "last_message": message,
                    "unread_count": unread,
                    "total_messages": count,
                }
            )
        return summaries, total

    async def get(self, public_id: uuid.UUID, *, actor: User) -> UserMessage:
        message = await self.messages.get_visible(public_id, user_id=actor.id)
        if message is None:
            raise NotFoundError("Message not found.")
        return message

    async def unread_count(self, *, actor: User) -> int:
        return await self.messages.unread_count(actor.id)

    # -- writes --------------------------------------------------------------

    async def send(self, payload: SendMessageRequest, *, actor: User) -> UserMessage:
        recipient = await self._load_user(payload.recipient_id)

        if recipient.id == actor.id:
            raise ValidationError("You cannot send a message to yourself.")
        if recipient.status is not UserStatus.ACTIVE:
            # Not "this account is suspended": whether a given account is
            # suspended is not a fact to hand to whoever asks. It reads the
            # same as an address that does not exist.
            raise NotFoundError("Recipient not found.")

        await self._assert_can_correspond(actor, recipient)

        course_id = await self._resolve_course(payload.course_id)
        batch_id = await self._resolve_batch(payload.batch_id)

        message = UserMessage(
            sender_id=actor.id,
            recipient_id=recipient.id,
            course_id=course_id,
            batch_id=batch_id,
            subject=payload.subject,
            body=payload.body,
            is_read=False,
            is_deleted=False,
            sender_deleted=False,
            recipient_deleted=False,
        )
        await self.messages.add_and_flush(message)

        self.notifications.emit(
            user_id=recipient.id,
            type_=NotificationType.MESSAGE_RECEIVED,
            title=f"New message from {actor.full_name or actor.username}",
            # The subject only -- never the body. A notification is rendered
            # in places a message is not (a tray, a digest email), and
            # copying private correspondence into them widens where it lives
            # without anybody choosing to.
            body=payload.subject or "(no subject)",
            meta={"message_id": str(message.public_id), "from": actor.username},
        )

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="user_message",
            entity_id=message.id,
            # Recipient and subject, not the body: an audit trail that
            # duplicates message content is a second copy of every private
            # conversation, held for longer and read by more people.
            details={"to": recipient.username, "subject": payload.subject},
        )

        # Re-read rather than returning the instance just constructed. A new
        # object's relationships are unloaded, and `flush` does not populate
        # them -- the API layer's first `message.sender` would then be a lazy
        # load inside a running event loop, which surfaces as
        # `MissingGreenlet`. Fetching through the repository runs the eager
        # loaders that fill sender/recipient/course/batch.
        return await self.messages.get_visible(message.public_id, user_id=actor.id)  # type: ignore[return-value]

    async def mark_read(self, public_id: uuid.UUID, *, actor: User) -> UserMessage:
        message = await self.get(public_id, actor=actor)
        if message.recipient_id != actor.id:
            raise ValidationError("Only the recipient can mark a message as read.")
        if not message.is_read:
            message.is_read = True
            message.read_at = _now()
        return message

    async def mark_all_read(self, *, actor: User) -> int:
        return await self.messages.mark_all_read(actor.id, now=_now())

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        """Remove the message from **this** caller's mailbox only.

        The row survives while the other party still holds it; it is purged
        only once both sides have let it go. Anything else lets one
        participant destroy the other's copy of a shared record.
        """
        message = await self.get(public_id, actor=actor)

        if message.sender_id == actor.id:
            message.sender_deleted = True
        if message.recipient_id == actor.id:
            message.recipient_deleted = True

        if message.sender_deleted and message.recipient_deleted:
            message.is_deleted = True

        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="user_message",
            entity_id=message.id,
            details={"side": "sender" if message.sender_id == actor.id else "recipient"},
        )

    # -- correspondence policy ----------------------------------------------

    async def _assert_can_correspond(self, actor: User, recipient: User) -> None:
        if ScopeResolver.is_unrestricted(actor):
            return
        if ScopeResolver.is_unrestricted(recipient):
            return

        forward = await self.scopes.visible_student_ids(actor)
        if forward.allows(recipient.id):
            return

        # The reverse direction, and it has to be asked explicitly. A student
        # is not in their tutor's *care* set from the student's own side, so
        # checking only `forward` would let a tutor open a conversation and
        # leave the student unable to start one.
        reverse = await self.scopes.visible_student_ids(recipient)
        if reverse.allows(actor.id):
            return

        raise AuthorizationError(
            "You are not connected to this person and cannot message them.",
        )

    # -- helpers -------------------------------------------------------------

    async def _load_user(self, public_id: uuid.UUID) -> User:
        stmt = select(User).where(User.public_id == public_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise NotFoundError("Recipient not found.")
        return user

    async def _load_users_by_id(self, ids: set[int]) -> dict[int, User]:
        if not ids:
            return {}
        stmt = select(User).where(User.id.in_(ids))
        return {u.id: u for u in (await self.session.execute(stmt)).scalars().unique().all()}

    async def _resolve_course(self, public_id: uuid.UUID | None) -> int | None:
        if public_id is None:
            return None
        stmt = select(Course.id).where(Course.public_id == public_id)
        course_id = (await self.session.execute(stmt)).scalar_one_or_none()
        if course_id is None:
            raise NotFoundError("Course not found.")
        return int(course_id)

    async def _resolve_batch(self, public_id: uuid.UUID | None) -> int | None:
        if public_id is None:
            return None
        stmt = select(Batch.id).where(Batch.public_id == public_id)
        batch_id = (await self.session.execute(stmt)).scalar_one_or_none()
        if batch_id is None:
            raise NotFoundError("Batch not found.")
        return int(batch_id)
