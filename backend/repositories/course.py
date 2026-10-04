"""Course queries."""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import false, Select, func, or_, select
from sqlalchemy.orm import selectinload

from backend.models.administration import CourseTag
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course, TutorCourse
from backend.models.enrollment import Enrollments
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams
from backend.utils.enums import CourseStatus, EnrollmentStatus

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
        may_browse: bool = True,
    ) -> Select[tuple[Course]]:
        """Apply catalogue visibility.

        Two separate questions, and conflating them was the bug:

        * **Which courses may this person reach at all?** `course.view_all`
          answers it. The catalogue is deliberately browsable by a Corporate
          Manager -- they could not otherwise find a course to enrol
          employees into -- and by students and guardians, for whom it is
          already public on the institution's website. A **tutor** holds
          `course.read` without it, so they reach the courses assigned to
          them and no others. Previously every holder of `course.read` could
          list all 28 courses while teaching four.
        * **Which of those are ready to be seen?** The status filter, which
          still applies, with an exception so an assigned tutor can open
          their own course while it is still a draft.
        """
        if unrestricted:
            return stmt

        public = Course.status.in_(PUBLIC_STATUSES)

        if not may_browse:
            # No catalogue: assigned courses only, at any status. A tutor with
            # no assignments sees nothing, which is the honest answer rather
            # than a silently empty-looking catalogue.
            if not tutor_course_ids:
                return stmt.where(false())
            return stmt.where(Course.id.in_(tutor_course_ids))

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
        may_browse: bool = True,
        query: str | None = None,
        status: CourseStatus | None = None,
        level: str | None = None,
        category_id: int | None = None,
        department_id: int | None = None,
        tag_id: int | None = None,
        tutor_user_id: int | None = None,
        student_user_id: int | None = None,
    ) -> tuple[Sequence[Course], int]:
        stmt = self._visible(
            self._base(),
            unrestricted=unrestricted,
            tutor_course_ids=tutor_course_ids,
            may_browse=may_browse,
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
        if tutor_user_id is not None:
            # A tutor's courses are the ones they are assigned to *or* actually teach a session
            # of: synced batches carry the tutor on their sessions and never fill `tutor_courses`.
            stmt = stmt.where(
                or_(
                    Course.id.in_(select(TutorCourse.course_id).where(TutorCourse.tutor_id == tutor_user_id)),
                    Course.id.in_(
                        select(Batch.course_id)
                        .join(BatchSession, BatchSession.batch_id == Batch.id)
                        .where(BatchSession.tutor_id == tutor_user_id)
                    ),
                )
            )
        if student_user_id is not None:
            stmt = stmt.where(
                Course.id.in_(
                    select(Batch.course_id)
                    .join(Enrollments, Enrollments.batch_id == Batch.id)
                    .where(
                        Enrollments.student_id == student_user_id,
                        Enrollments.status.in_(
                            (EnrollmentStatus.PENDING, EnrollmentStatus.CONFIRMED, EnrollmentStatus.COMPLETED)
                        ),
                    )
                )
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
