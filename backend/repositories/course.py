"""Course queries."""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from backend.models.administration import CourseTag
from backend.models.batch import Batch
from backend.models.course import Course
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams
from backend.utils.enums import CourseStatus

# What an ordinary caller may see in the catalogue. A DRAFT course is not
# ready to be advertised, and an ARCHIVED one has been withdrawn -- neither
# belongs in a student's or a corporate manager's browse list.
PUBLIC_STATUSES = (CourseStatus.PUBLISHED, CourseStatus.RUNNING, CourseStatus.COMPLETED)


class CourseRepository(BaseRepository[Course]):
    model = Course

    def _base(self) -> Select[tuple[Course]]:
        return (
            select(Course)
            .options(
                selectinload(Course.tutors),
                selectinload(Course.category),
                selectinload(Course.department),
                selectinload(Course.tags),
            )
            .where(Course.is_deleted.is_(False))
        )

    def _visible(
        self,
        stmt: Select[tuple[Course]],
        *,
        unrestricted: bool,
        tutor_course_ids: set[int],
    ) -> Select[tuple[Course]]:
        """Apply catalogue visibility.

        Note this is *status* visibility, not row-ownership scoping: the
        catalogue is deliberately browsable by anyone with `course.read`, or
        a Corporate Manager could never find a course to enrol employees
        into. The only thing hidden is what is not ready to be seen -- plus
        an exception so an assigned tutor can still see their own course
        while it is still a draft.
        """
        if unrestricted:
            return stmt

        public = Course.status.in_(PUBLIC_STATUSES)
        if tutor_course_ids:
            return stmt.where(or_(public, Course.id.in_(tutor_course_ids)))
        return stmt.where(public)

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> Course | None:
        stmt = self._base().where(Course.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_title(self, title: str) -> Course | None:
        stmt = select(Course).where(
            func.lower(Course.title) == title.strip().lower(),
            Course.is_deleted.is_(False),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_code(self, code: str) -> Course | None:
        stmt = select(Course).where(
            func.lower(Course.code) == code.strip().lower(),
            Course.is_deleted.is_(False),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        unrestricted: bool,
        tutor_course_ids: set[int],
        query: str | None = None,
        status: CourseStatus | None = None,
        level: str | None = None,
        category_id: int | None = None,
        department_id: int | None = None,
        tag_id: int | None = None,
    ) -> tuple[Sequence[Course], int]:
        stmt = self._visible(
            self._base(), unrestricted=unrestricted, tutor_course_ids=tutor_course_ids
        )

        if status is not None:
            stmt = stmt.where(Course.status == status)
        if level:
            stmt = stmt.where(Course.level == level)
        if category_id is not None:
            stmt = stmt.where(Course.category_id == category_id)
        if department_id is not None:
            stmt = stmt.where(Course.department_id == department_id)
        if tag_id is not None:
            # Membership, not a join: joining `course_tags` would multiply
            # rows once a course carries several tags, and `paginate` counts
            # what the statement returns.
            stmt = stmt.where(
                Course.id.in_(select(CourseTag.course_id).where(CourseTag.tag_id == tag_id))
            )
        if query:
            like = f"%{query.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Course.title).like(like),
                    func.lower(Course.code).like(like),
                    func.lower(Course.description).like(like),
                )
            )

        stmt = stmt.order_by(Course.title)
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def count_batches(self, course_id: int) -> int:
        stmt = select(func.count()).select_from(Batch).where(Batch.course_id == course_id)
        return int((await self.session.execute(stmt)).scalar_one())
