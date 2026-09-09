"""Announcement queries.

The audience filter is the interesting part. Targeting lives in three
independently-nullable columns (course, batch, role) where NULL means "not
narrowed by this dimension", so the reader-side predicate is, per dimension,
*"the announcement did not narrow it, or it narrowed it to something I am"*.

Written the other way round -- `course_id IN my_courses` -- an
institution-wide notice (course_id NULL) would reach nobody, which is the
failure mode where the announcement everybody needed is the one nobody saw.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import Select, and_, false, func, or_, select
from sqlalchemy.orm import selectinload

from backend.models.notification import Announcement
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams
from backend.utils.enums import Roles

if TYPE_CHECKING:
    from backend.services.scope import Scope


class AnnouncementRepository(BaseRepository[Announcement]):
    model = Announcement

    def _base(self) -> Select[tuple[Announcement]]:
        return select(Announcement).options(
            selectinload(Announcement.course),
            selectinload(Announcement.batch),
            selectinload(Announcement.author),
        )

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> Announcement | None:
        stmt = self._base().where(Announcement.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        now: datetime,
        audience_filter: bool,
        course_scope: "Scope | None" = None,
        batch_scope: "Scope | None" = None,
        role_names: set[str] | None = None,
        course_id: int | None = None,
        batch_id: int | None = None,
        author_id: int | None = None,
        query: str | None = None,
        include_expired: bool = False,
        include_scheduled: bool = False,
    ) -> tuple[Sequence[Announcement], int]:
        stmt = self._base()

        if not include_scheduled:
            stmt = stmt.where(Announcement.start_at <= now)
        if not include_expired:
            stmt = stmt.where(
                or_(Announcement.end_at.is_(None), Announcement.end_at > now)
            )

        if audience_filter:
            stmt = stmt.where(
                self._reaches(
                    course_scope=course_scope,
                    batch_scope=batch_scope,
                    role_names=role_names or set(),
                )
            )

        if course_id is not None:
            stmt = stmt.where(Announcement.course_id == course_id)
        if batch_id is not None:
            stmt = stmt.where(Announcement.batch_id == batch_id)
        if author_id is not None:
            stmt = stmt.where(Announcement.created_by == author_id)
        if query:
            needle = f"%{query.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Announcement.title).like(needle),
                    func.lower(Announcement.content).like(needle),
                )
            )

        # Pinned first, then most recently published. Pinning is worthless if
        # the pinned item still sorts by date into the middle of the list.
        stmt = stmt.order_by(
            Announcement.pinned.desc(),
            Announcement.start_at.desc(),
            Announcement.id.desc(),
        )
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    @staticmethod
    def _reaches(
        *,
        course_scope: "Scope | None",
        batch_scope: "Scope | None",
        role_names: set[str],
    ):
        clauses = []

        if course_scope is None or course_scope.unrestricted:
            pass  # not narrowed by course
        elif course_scope.ids:
            clauses.append(
                or_(
                    Announcement.course_id.is_(None),
                    Announcement.course_id.in_(course_scope.ids),
                )
            )
        else:
            # No courses at all: only untargeted announcements reach them.
            # Note this is `IS NULL`, not "no filter" -- the empty-scope trap
            # that would otherwise hand this reader every course's notices.
            clauses.append(Announcement.course_id.is_(None))

        if batch_scope is None or batch_scope.unrestricted:
            pass
        elif batch_scope.ids:
            clauses.append(
                or_(
                    Announcement.batch_id.is_(None),
                    Announcement.batch_id.in_(batch_scope.ids),
                )
            )
        else:
            clauses.append(Announcement.batch_id.is_(None))

        if role_names:
            clauses.append(
                or_(
                    Announcement.role_scope.is_(None),
                    Announcement.role_scope.in_([Roles(r) for r in role_names]),
                )
            )
        else:
            clauses.append(Announcement.role_scope.is_(None))

        if not clauses:
            return false()
        return and_(*clauses)
