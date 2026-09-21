"""Assignments and submissions (spec §12)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.enrollment import Enrollments
from backend.models.batch import Batch
from backend.models.identity.user import User
from backend.repositories.assignment import AssignmentRepository, SubmissionRepository
from backend.repositories.enrollment import ACTIVE_STATUSES
from backend.schemas.assignment import (
    AssignmentCreateRequest,
    AssignmentUpdateRequest,
    GradeSubmissionRequest,
    SubmitAssignmentRequest,
)
from backend.schemas.base import PageParams
from backend.services import audit_service
from backend.core.notification_types import NotificationType
from backend.services.audit_service import AuditAction
from backend.services.integration_service import WebhookEvent, WebhookService
from backend.services.notification_service import NotificationService
from backend.services.course_service import CourseService
from backend.services.scope import ScopeResolver


class AssignmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.assignments = AssignmentRepository(session)
        self.submissions = SubmissionRepository(session)
        self.courses = CourseService(session)
        self.scopes = ScopeResolver(session)

    # -- assignments ---------------------------------------------------------

    async def list_assignments(
        self,
        params: PageParams,
        *,
        actor: User,
        course_public_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[Assignment], int]:
        course_id = None
        if course_public_id is not None:
            course_id = (await self.courses.get(course_public_id, actor=actor)).id

        scope = await self.scopes.visible_course_ids(actor)
        return await self.assignments.search(params, scope=scope, course_id=course_id)

    async def get(self, public_id: uuid.UUID, *, actor: User) -> Assignment:
        row = await self.assignments.get_by_public_id_full(public_id)
        if row is None:
            raise NotFoundError("Assignment not found.")

        scope = await self.scopes.visible_course_ids(actor)
        if not scope.allows(row.course_id):
            raise NotFoundError("Assignment not found.")
        return row

    async def create(
        self, course_public_id: uuid.UUID, payload: AssignmentCreateRequest, *, actor: User
    ) -> Assignment:
        course = await self.courses.get(course_public_id, actor=actor)

        # Reading an assignment is scoped by `visible_course_ids` and creating one was not, so a tutor could set
        # coursework on a colleague's course and then neither see nor delete it -- `get`, `update` and `delete`
        # all answer 404 for exactly that row -- while its students were notified. Same predicate as the reads,
        # which is the point: a write must not reach further than the read that would show its result.
        #
        # 403 rather than the reads' 404: the course catalogue is deliberately unscoped (see
        # `ScopeResolver.visible_course_ids`), so the course's existence is already public and there is nothing
        # to conceal. What the caller lacks is standing to teach it, and saying so is actionable.
        scope = await self.scopes.visible_course_ids(actor)
        if not scope.allows(course.id):
            raise AuthorizationError("You can only set coursework on a course you teach.")

        row = Assignment(
            course_id=course.id,
            title=payload.title,
            description=payload.description,
            instructions_path=payload.instructions_path,
            due_date=payload.due_date,
            max_score=payload.max_score,
            submission_type=payload.submission_type,
            rubric=payload.rubric,
            allow_late_submissions=payload.allow_late_submissions,
        )
        await self.assignments.add_and_flush(row)

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="assignment",
            entity_id=row.id,
            details={"title": row.title, "course": course.title},
        )

        # The one fan-out in the system, and it is bounded by a course
        # roster. An announcement is the mechanism for anything wider -- see
        # `MAX_FANOUT` in the notification service for where the line is.
        roster = await self.assignments.enrolled_student_ids(course.id)
        notifications = NotificationService(self.session)
        await notifications.notify_many(
            roster,
            type_=NotificationType.ASSIGNMENT_PUBLISHED,
            title=f"New assignment: {row.title}",
            body=f"{course.title} — due {row.due_date:%d %b %Y}.",
            meta={"assignment_id": str(row.public_id), "course_id": str(course.public_id)},
        )
        await notifications.notify_guardians_of(
            roster,
            type_=NotificationType.WARD_ASSIGNMENT_PUBLISHED,
            title=f"New assignment for {{student}}: {row.title}",
            body=f"{course.title} — due {row.due_date:%d %b %Y}.",
            meta={"assignment_id": str(row.public_id), "course_id": str(course.public_id)},
        )

        # One webhook for the event, where the notification above fanned out
        # to the roster: a receiver wants to know the assignment exists, not
        # to be told once per enrolled student.
        await WebhookService(self.session).enqueue(
            WebhookEvent.ASSIGNMENT_PUBLISHED,
            {
                "event": WebhookEvent.ASSIGNMENT_PUBLISHED,
                "assignment_id": str(row.public_id),
                "course_id": str(course.public_id),
                "title": row.title,
                "due_date": row.due_date.isoformat() if row.due_date else None,
            },
        )

        return await self.assignments.get_by_public_id_full(row.public_id)  # type: ignore[return-value]

    async def update(
        self, public_id: uuid.UUID, payload: AssignmentUpdateRequest, *, actor: User
    ) -> Assignment:
        row = await self.get(public_id, actor=actor)
        changes = payload.model_dump(exclude_unset=True)

        new_max = changes.get("max_score")
        if new_max is not None:
            # Lowering max_score below a mark already awarded would leave a
            # submission scoring more than the assignment is worth.
            highest = (
                await self.session.execute(
                    select(AssignmentSubmission.grade)
                    .where(
                        AssignmentSubmission.assignment_id == row.id,
                        AssignmentSubmission.grade.is_not(None),
                    )
                    .order_by(AssignmentSubmission.grade.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if highest is not None and Decimal(new_max) < Decimal(highest):
                raise ConflictError(
                    "max_score cannot be lower than a grade already awarded.",
                    details={"highest_awarded": str(highest), "requested_max": str(new_max)},
                )

        for field, value in changes.items():
            setattr(row, field, value)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="assignment",
            entity_id=row.id,
            details={"fields": sorted(changes)},
        )
        return row

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        row = await self.get(public_id, actor=actor)

        count = await self.assignments.count_submissions(row.id)
        if count:
            # Submissions carry students' work and their marks; deleting the
            # assignment out from under them destroys both.
            raise ConflictError(
                "This assignment already has submissions and cannot be deleted.",
                details={"submissions": count},
            )

        entity_id = row.id
        await self.session.delete(row)
        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="assignment",
            entity_id=entity_id,
        )

    # -- submissions ---------------------------------------------------------

    async def list_submissions(
        self,
        params: PageParams,
        *,
        actor: User,
        assignment_public_id: uuid.UUID | None = None,
        student_public_id: uuid.UUID | None = None,
        graded: bool | None = None,
    ) -> tuple[Sequence[AssignmentSubmission], int]:
        assignment_id = None
        if assignment_public_id is not None:
            assignment_id = (await self.get(assignment_public_id, actor=actor)).id

        student_id = None
        if student_public_id is not None:
            student_id = (await self._load_user(student_public_id)).id

        visibility = await self.scopes.work_visibility(actor)
        return await self.submissions.search(
            params,
            visibility=visibility,
            assignment_id=assignment_id,
            student_id=student_id,
            graded=graded,
        )

    async def get_submission(
        self, public_id: uuid.UUID, *, actor: User
    ) -> AssignmentSubmission:
        row = await self.submissions.get_by_public_id_full(public_id)
        if row is None:
            raise NotFoundError("Submission not found.")

        visibility = await self.scopes.work_visibility(actor)
        if not visibility.unrestricted:
            reachable = (
                row.assignment.course_id in visibility.taught_course_ids
                or row.student_id in visibility.cared_for_student_ids
            )
            if not reachable:
                raise NotFoundError("Submission not found.")
        return row

    async def submit(
        self, assignment_public_id: uuid.UUID, payload: SubmitAssignmentRequest, *, actor: User
    ) -> AssignmentSubmission:
        """Create or replace the caller's own submission.

        The student is always the caller -- there is no `student_id` in the
        request body. Submitting on someone else's behalf is not a feature
        anyone asked for, and accepting a caller-supplied student id would
        make it one.
        """
        assignment = await self.get(assignment_public_id, actor=actor)
        await self._assert_enrolled_in_course(actor, assignment.course_id)

        now = datetime.now(UTC)
        is_late = now > assignment.due_date
        if is_late and not assignment.allow_late_submissions:
            raise ConflictError(
                "The deadline for this assignment has passed.",
                details={"due_date": assignment.due_date.isoformat()},
            )

        existing = await self.submissions.get_for_student(
            assignment_id=assignment.id, student_id=actor.id
        )

        if existing is not None:
            if existing.grade is not None:
                # Replacing work that has already been marked would silently
                # invalidate the grade sitting next to it.
                raise ConflictError(
                    "This submission has already been graded and cannot be replaced."
                )
            existing.content = payload.content
            existing.files = payload.files
            existing.submitted_at = now
            row = existing
        else:
            row = AssignmentSubmission(
                assignment_id=assignment.id,
                student_id=actor.id,
                submitted_at=now,
                content=payload.content,
                files=payload.files,
            )
            await self.submissions.add_and_flush(row)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE if existing is not None else AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="assignment_submission",
            entity_id=row.id,
            details={"assignment": assignment.title, "late": is_late},
        )
        return await self.submissions.get_by_public_id_full(row.public_id)  # type: ignore[return-value]

    async def grade(
        self, public_id: uuid.UUID, payload: GradeSubmissionRequest, *, actor: User
    ) -> AssignmentSubmission:
        row = await self.get_submission(public_id, actor=actor)

        if payload.grade > row.assignment.max_score:
            raise ValidationError(
                "Grade exceeds the assignment's maximum score.",
                details={
                    "max_score": str(row.assignment.max_score),
                    "given": str(payload.grade),
                },
            )

        row.grade = payload.grade
        row.feedback = payload.feedback
        row.graded_by_id = actor.id
        row.graded_at = datetime.now(UTC)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="assignment_submission",
            entity_id=row.id,
            details={"grade": str(payload.grade)},
        )

        notifications = NotificationService(self.session)
        await notifications.notify(
            user_id=row.student_id,
            type_=NotificationType.SUBMISSION_GRADED,
            title=f"Graded: {row.assignment.title}",
            body=f"You scored {payload.grade} out of {row.assignment.max_score}.",
            meta={"assignment_id": str(row.assignment.public_id),
                  "submission_id": str(row.public_id)},
        )
        await notifications.notify_guardians_of(
            [row.student_id],
            type_=NotificationType.WARD_SUBMISSION_GRADED,
            title=f"Graded: {row.assignment.title}",
            body=f"{{student}} scored {payload.grade} out of {row.assignment.max_score}.",
            meta={"assignment_id": str(row.assignment.public_id),
                  "submission_id": str(row.public_id)},
        )

        await WebhookService(self.session).enqueue(
            WebhookEvent.SUBMISSION_GRADED,
            {
                "event": WebhookEvent.SUBMISSION_GRADED,
                "submission_id": str(row.public_id),
                "assignment_id": str(row.assignment.public_id),
                "grade": str(payload.grade),
                "max_score": str(row.assignment.max_score),
            },
        )

        # `graded_by_id` was just reassigned, so the already-loaded `grader`
        # relationship is stale -- the same trap fixed in user/course
        # services. Refresh so the response names the real grader.
        await self.session.flush()
        await self.session.refresh(row, attribute_names=["grader"])
        return row

    # -- helpers -------------------------------------------------------------

    async def _assert_enrolled_in_course(self, student: User, course_id: int) -> None:
        """A student may only submit to a course they are actually taking."""
        stmt = (
            select(Enrollments.enrollment_id)
            .join(Batch, Batch.id == Enrollments.batch_id)
            .where(
                Enrollments.student_id == student.id,
                Batch.course_id == course_id,
                Enrollments.status.in_(ACTIVE_STATUSES),
            )
            .limit(1)
        )
        if (await self.session.execute(stmt)).scalar_one_or_none() is None:
            raise ConflictError("You are not enrolled in this course.")

    async def _load_user(self, public_id: uuid.UUID) -> User:
        stmt = select(User).where(User.public_id == public_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise NotFoundError("User not found.")
        return user
