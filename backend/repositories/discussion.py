"""Course discussion and reply queries."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from backend.models.messaging import CourseDiscussion, DiscussionReply
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams

if TYPE_CHECKING:
    from backend.services.scope import Scope


class DiscussionRepository(BaseRepository[CourseDiscussion]):
    model = CourseDiscussion

    def _base(self) -> Select[tuple[CourseDiscussion]]:
        return select(CourseDiscussion).options(
            selectinload(CourseDiscussion.course),
            selectinload(CourseDiscussion.author),
        )

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> CourseDiscussion | None:
        stmt = self._base().where(CourseDiscussion.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        course_scope: "Scope",
        course_id: int | None = None,
        query: str | None = None,
    ) -> tuple[Sequence[CourseDiscussion], int]:
        stmt = course_scope.apply(self._base(), CourseDiscussion.course_id)

        if course_id is not None:
            stmt = stmt.where(CourseDiscussion.course_id == course_id)
        if query:
            needle = f"%{query.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(CourseDiscussion.title).like(needle),
                    func.lower(CourseDiscussion.body).like(needle),
                )
            )

        stmt = stmt.order_by(
            CourseDiscussion.is_pinned.desc(),
            CourseDiscussion.created_at.desc(),
            CourseDiscussion.id.desc(),
        )
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def reply_counts(self, discussion_ids: Sequence[int]) -> dict[int, int]:
        """Counts for a whole page in one query.

        A per-row `len(discussion.replies)` would be one query per thread and
        would load every reply body to arrive at an integer.
        """
        if not discussion_ids:
            return {}
        stmt = (
            select(DiscussionReply.discussion_id, func.count())
            .where(DiscussionReply.discussion_id.in_(discussion_ids))
            .group_by(DiscussionReply.discussion_id)
        )
        return {int(row[0]): int(row[1]) for row in (await self.session.execute(stmt)).all()}

    async def has_replies_by_others(self, discussion_id: int, *, author_id: int) -> bool:
        stmt = (
            select(func.count())
            .select_from(DiscussionReply)
            .where(
                DiscussionReply.discussion_id == discussion_id,
                DiscussionReply.author_id != author_id,
            )
        )
        return int((await self.session.execute(stmt)).scalar_one()) > 0


class DiscussionReplyRepository(BaseRepository[DiscussionReply]):
    model = DiscussionReply

    def _base(self) -> Select[tuple[DiscussionReply]]:
        return select(DiscussionReply).options(selectinload(DiscussionReply.author))

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> DiscussionReply | None:
        stmt = self._base().where(DiscussionReply.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def for_discussion(
        self, params: PageParams, *, discussion_id: int
    ) -> tuple[Sequence[DiscussionReply], int]:
        stmt = (
            self._base()
            .where(DiscussionReply.discussion_id == discussion_id)
            # Oldest first: a thread is read in the order it was written.
            .order_by(DiscussionReply.created_at.asc(), DiscussionReply.id.asc())
        )
        return await self.paginate(stmt, params)  # type: ignore[return-value]
