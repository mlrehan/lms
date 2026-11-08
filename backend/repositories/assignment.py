"""Assignment and submission queries."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.batch import Batch
from backend.models.enrollment import Enrollments
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams
from backend.utils.enums import AssessmentState, EnrollmentStatus, SubmissionState

if TYPE_CHECKING:
    from backend.services.assessment_access import AssessmentVisibility
    from backend.services.scope import Scope, WorkVisibility


class AssignmentRepository(BaseRepository[Assignment]):
    model = Assignment

    def _base(self) -> Select[tuple[Assignment]]:
        # A withdrawn assignment is gone from every read, including a lookup by
        # an old link; its submissions and marks stay in their own tables.
        return (
            select(Assignment)
            .options(selectinload(Assignment.course))
            .where(Assignment.deleted_at.is_(None))
        )

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> Assignment | None:
        stmt = self._base().where(Assignment.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        scope: "Scope | None" = None,
        visibility: "AssessmentVisibility | None" = None,
        course_id: int | None = None,
        query: str | None = None,
        published_only: bool = False,
    ) -> tuple[Sequence[Assignment], int]:
        stmt = self._base()
        if scope is not None:
            stmt = scope.apply(stmt, Assignment.course_id)
        if visibility is not None:
            stmt = visibility.apply(
                stmt,
                course_column=Assignment.course_id,
                creator_column=Assignment.created_by,
                deleted_column=Assignment.deleted_at,
                model=Assignment,
            )
        if published_only:
            stmt = stmt.where(Assignment.state == AssessmentState.PUBLISHED)
        if course_id is not None:
            stmt = stmt.where(Assignment.course_id == course_id)
        if query:
            needle = f"%{query.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Assignment.title).like(needle),
                    func.lower(func.coalesce(Assignment.description, "")).like(needle),
                )
            )
        stmt = stmt.order_by(Assignment.due_date.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def enrolled_student_ids(self, course_id: int) -> list[int]:
        """Students currently holding a seat on any batch of this course.

        DROPPED and CANCELLED enrolments are excluded: telling somebody who
        left the course about its new assignment is noise they cannot act on.
        """
        stmt = (
            select(Enrollments.student_id)
            .join(Batch, Enrollments.batch_id == Batch.id)
            .where(
                Batch.course_id == course_id,
                Enrollments.status.in_(
                    (EnrollmentStatus.CONFIRMED, EnrollmentStatus.PENDING)
                ),
            )
            .distinct()
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_submissions(self, assignment_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(AssignmentSubmission)
            .where(AssignmentSubmission.assignment_id == assignment_id)
        )
        return int((await self.session.execute(stmt)).scalar_one())


class SubmissionRepository(BaseRepository[AssignmentSubmission]):
    model = AssignmentSubmission

    def _base(self) -> Select[tuple[AssignmentSubmission]]:
        return select(AssignmentSubmission).options(
            selectinload(AssignmentSubmission.assignment),
            selectinload(AssignmentSubmission.student),
            selectinload(AssignmentSubmission.grader),
        )

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> AssignmentSubmission | None:
        stmt = self._base().where(AssignmentSubmission.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_for_student(
        self, *, assignment_id: int, student_id: int
    ) -> AssignmentSubmission | None:
        stmt = self._base().where(
            AssignmentSubmission.assignment_id == assignment_id,
            AssignmentSubmission.student_id == student_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_assignment(self, assignment_id: int) -> list[AssignmentSubmission]:
        """Every submission for one assignment.

        Unpaged on purpose: this backs the publish-results action, which must
        act on the whole set or leave some students released and others not.
        Bounded by a batch roster, which is the same bound the notification
        fan-out already accepts.
        """
        stmt = self._base().where(AssignmentSubmission.assignment_id == assignment_id)
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def search(
        self,
        params: PageParams,
        *,
        visibility: "WorkVisibility",
        assessments: "AssessmentVisibility | None" = None,
        assignment_id: int | None = None,
        student_id: int | None = None,
        graded: bool | None = None,
        state: SubmissionState | None = None,
    ) -> tuple[Sequence[AssignmentSubmission], int]:
        # The course side of the visibility check needs the assignment's
        # course, which lives one join away.
        stmt = self._base().join(
            Assignment, Assignment.id == AssignmentSubmission.assignment_id
        )
        stmt = visibility.apply(
            stmt,
            course_column=Assignment.course_id,
            student_column=AssignmentSubmission.student_id,
        ).where(Assignment.deleted_at.is_(None))
        if assessments is not None:
            # A colleague's assignment in a course this tutor also teaches:
            # its submissions are the colleague's to see, not theirs.
            stmt = assessments.exclude_colleagues(
                stmt, course_column=Assignment.course_id, creator_column=Assignment.created_by
            )

        if assignment_id is not None:
            stmt = stmt.where(AssignmentSubmission.assignment_id == assignment_id)
        if student_id is not None:
            stmt = stmt.where(AssignmentSubmission.student_id == student_id)
        if graded is True:
            stmt = stmt.where(AssignmentSubmission.grade.is_not(None))
        elif graded is False:
            stmt = stmt.where(AssignmentSubmission.grade.is_(None))
        if state is not None:
            # "Graded" alone cannot say whether the student has seen the mark;
            # releasing is a separate step, and the screen has to count what
            # is still waiting for it.
            stmt = stmt.where(AssignmentSubmission.state == state)

        stmt = stmt.order_by(AssignmentSubmission.submitted_at.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]
