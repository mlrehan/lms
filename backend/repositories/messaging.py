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

from backend.models.notification import Notification
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams


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
