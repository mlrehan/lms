"""Private message and notification queries.

Every statement in here is anchored on the caller's own id. A message has
exactly two legitimate readers and there is no filter to relax for an
administrator, so `user_id` is a required argument rather than an optional
narrowing -- there is no way to call these and accidentally get somebody
else's mailbox.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import Select, and_, case, func, or_, select, update

from backend.models.messaging import UserMessage
from backend.models.notification import Notification
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams
from backend.schemas.messaging import MessageBox


class MessageRepository(BaseRepository[UserMessage]):
    model = UserMessage

    @staticmethod
    def _mine(user_id: int, box: MessageBox) -> Any:
        """Rows this user may see, honouring per-side deletion.

        `is_deleted` is the administrative tombstone and hides the row from
        both parties; `sender_deleted` / `recipient_deleted` hide it from one
        mailbox each, so one person clearing their inbox never removes the
        other person's copy of the same correspondence.
        """
        inbox = and_(
            UserMessage.recipient_id == user_id,
            UserMessage.recipient_deleted.is_(False),
        )
        sent = and_(
            UserMessage.sender_id == user_id,
            UserMessage.sender_deleted.is_(False),
        )
        if box is MessageBox.INBOX:
            side = inbox
        elif box is MessageBox.SENT:
            side = sent
        else:
            side = or_(inbox, sent)
        return and_(UserMessage.is_deleted.is_(False), side)

    def _base(self) -> Select[tuple[UserMessage]]:
        return select(UserMessage)

    async def get_visible(self, public_id: uuid.UUID, *, user_id: int) -> UserMessage | None:
        stmt = self._base().where(
            UserMessage.public_id == public_id,
            self._mine(user_id, MessageBox.ALL),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        user_id: int,
        box: MessageBox = MessageBox.INBOX,
        unread_only: bool = False,
        with_user_id: int | None = None,
        query: str | None = None,
    ) -> tuple[Sequence[UserMessage], int]:
        stmt = self._base().where(self._mine(user_id, box))

        if unread_only:
            # "Unread" is only meaningful for messages addressed to you --
            # your own sent copy is not something you can have failed to read.
            stmt = stmt.where(
                UserMessage.recipient_id == user_id, UserMessage.is_read.is_(False)
            )

        if with_user_id is not None:
            stmt = stmt.where(
                or_(
                    UserMessage.sender_id == with_user_id,
                    UserMessage.recipient_id == with_user_id,
                )
            )

        if query:
            needle = f"%{query.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(func.coalesce(UserMessage.subject, "")).like(needle),
                    func.lower(func.coalesce(UserMessage.body, "")).like(needle),
                )
            )

        stmt = stmt.order_by(UserMessage.created_at.desc(), UserMessage.id.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def unread_count(self, user_id: int) -> int:
        stmt = select(func.count()).select_from(UserMessage).where(
            UserMessage.recipient_id == user_id,
            UserMessage.recipient_deleted.is_(False),
            UserMessage.is_deleted.is_(False),
            UserMessage.is_read.is_(False),
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def conversations(
        self, params: PageParams, *, user_id: int
    ) -> tuple[list[tuple[int, int, int, int]], int]:
        """``[(counterpart_id, last_message_id, total, unread)]`` plus the
        number of distinct correspondents.

        Grouped in the database rather than by walking a page of messages in
        Python: a correspondent's most recent message may sit thousands of
        rows down, so grouping over one page groups over an arbitrary window
        and is quietly wrong for exactly the mailboxes that need this view.
        """
        counterpart = case(
            (UserMessage.sender_id == user_id, UserMessage.recipient_id),
            else_=UserMessage.sender_id,
        ).label("counterpart_id")

        base = (
            select(
                counterpart,
                func.max(UserMessage.id).label("last_id"),
                func.count().label("total"),
                func.count()
                .filter(
                    and_(
                        UserMessage.recipient_id == user_id,
                        UserMessage.is_read.is_(False),
                    )
                )
                .label("unread"),
            )
            .where(self._mine(user_id, MessageBox.ALL))
            .group_by(counterpart)
        )

        total = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(base.subquery())
                )
            ).scalar_one()
        )

        rows = (
            await self.session.execute(
                base.order_by(func.max(UserMessage.id).desc())
                .limit(params.limit)
                .offset(params.offset)
            )
        ).all()
        return [(int(r[0]), int(r[1]), int(r[2]), int(r[3])) for r in rows], total

    async def by_ids(self, ids: Sequence[int]) -> list[UserMessage]:
        if not ids:
            return []
        stmt = self._base().where(UserMessage.id.in_(ids))
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def mark_all_read(self, user_id: int, *, now: datetime) -> int:
        stmt = (
            update(UserMessage)
            .where(
                UserMessage.recipient_id == user_id,
                UserMessage.recipient_deleted.is_(False),
                UserMessage.is_deleted.is_(False),
                UserMessage.is_read.is_(False),
            )
            .values(is_read=True, read_at=now)
        )
        return int((await self.session.execute(stmt)).rowcount or 0)


class NotificationRepository(BaseRepository[Notification]):
    model = Notification

    async def get_own(self, public_id: uuid.UUID, *, user_id: int) -> Notification | None:
        stmt = select(Notification).where(
            Notification.public_id == public_id, Notification.user_id == user_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        user_id: int,
        unread_only: bool = False,
        type_: str | None = None,
    ) -> tuple[Sequence[Notification], int]:
        stmt = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
        if type_:
            stmt = stmt.where(Notification.type == type_)
        stmt = stmt.order_by(Notification.sent_at.desc(), Notification.id.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def unread_count(self, user_id: int) -> int:
        stmt = select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id, Notification.is_read.is_(False)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def mark_all_read(self, user_id: int) -> int:
        stmt = (
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            .values(is_read=True)
        )
        return int((await self.session.execute(stmt)).rowcount or 0)
