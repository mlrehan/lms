"""Enrollment lifecycle (spec §7): enroll, transfer, withdraw, re-enroll."""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.models.batch import Batch
from backend.models.enrollment import Enrollments
from backend.models.identity.user import User
from backend.models.organization import (
    ManagedStudent,
    OrganizationManager,
    OrganizationMembership,
)
from backend.repositories.batch import BatchRepository
from backend.repositories.enrollment import ACTIVE_STATUSES, EnrollmentRepository
from backend.schemas.base import PageParams
from backend.core.notification_types import NotificationType
from backend.services.notification_service import NotificationService
from backend.services import audit_service
from backend.core.notification_types import NotificationType
from backend.services.audit_service import AuditAction
from backend.services.integration_service import WebhookEvent, WebhookService
from backend.services.notification_service import NotificationService
from backend.services.scope import ScopeResolver
from backend.utils.enums import (
    CourseStatus,
    EnrollmentStatus,
    OrganizationMembershipStatus,
    Roles,
)

# Spec §7: Pending -> Confirmed -> Completed, with Dropped/Cancelled as exits.
#
# CANCELLED is reachable only from PENDING: cancelling is "this never
# started", while a confirmed student who leaves has DROPPED. Collapsing the
# two would lose the distinction between someone who never attended and
# someone who withdrew part-way, which matters for both refunds and reporting.
_ALLOWED_TRANSITIONS: dict[EnrollmentStatus, frozenset[EnrollmentStatus]] = {
    EnrollmentStatus.PENDING: frozenset(
        {EnrollmentStatus.CONFIRMED, EnrollmentStatus.CANCELLED, EnrollmentStatus.DROPPED}
    ),
    EnrollmentStatus.CONFIRMED: frozenset(
        {EnrollmentStatus.COMPLETED, EnrollmentStatus.DROPPED}
    ),
    EnrollmentStatus.COMPLETED: frozenset(),
    EnrollmentStatus.DROPPED: frozenset(),
    EnrollmentStatus.CANCELLED: frozenset(),
}

# A batch can only be joined while its course is actually offering places.
_ENROLLABLE_COURSE_STATUSES = (CourseStatus.PUBLISHED, CourseStatus.RUNNING)


class EnrollmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.enrollments = EnrollmentRepository(session)
        self.batches = BatchRepository(session)
        self.scopes = ScopeResolver(session)

    # -- reads ---------------------------------------------------------------

    async def list_enrollments(
        self,
        params: PageParams,
        *,
        actor: User,
        batch_public_id: uuid.UUID | None = None,
        student_public_id: uuid.UUID | None = None,
        tutor_public_id: uuid.UUID | None = None,
        status: EnrollmentStatus | None = None,
    ) -> tuple[Sequence[Enrollments], int]:
        batch_id = None
        if batch_public_id is not None:
            batch = await self.batches.get_by_public_id_full(batch_public_id)
            if batch is None:
                raise NotFoundError("Batch not found.")
            batch_id = batch.id

        student_id = None
        if student_public_id is not None:
            student = await self._load_user(student_public_id)
            student_id = student.id

        tutor_id = None
        if tutor_public_id is not None:
            tutor = await self._load_user(tutor_public_id)
            tutor_id = tutor.id

        visibility = await self.scopes.enrollment_visibility(actor)
        return await self.enrollments.search(
            params,
            visibility=visibility,
            batch_id=batch_id,
            student_id=student_id,
            tutor_id=tutor_id,
            status=status,
        )

    async def get(self, public_id: uuid.UUID, *, actor: User) -> Enrollments:
        enrollment = await self.enrollments.get_by_public_id_full(public_id)
        if enrollment is None:
            raise NotFoundError("Enrollment not found.")

        visibility = await self.scopes.enrollment_visibility(actor)
        if not visibility.unrestricted:
            reachable = (
                enrollment.batch_id in visibility.taught_batch_ids
                or enrollment.student_id in visibility.cared_for_student_ids
            )
            if not reachable:
                raise NotFoundError("Enrollment not found.")
        return enrollment

    # -- enrol ---------------------------------------------------------------

    async def enroll(
        self,
        *,
        student_public_id: uuid.UUID,
        batch_public_id: uuid.UUID,
        confirmed: bool,
        actor: User,
    ) -> Enrollments:
        student = await self._load_user(student_public_id)
        self._assert_is_student(student)

        # Resolved here, before anything is read about the batch or the existing enrolments, because the
        # refusals below describe real rows: "already enrolled in this batch" told a Corporate Manager that a
        # student they cannot see is in a batch they cannot see, which `GET /users/{id}` and `GET /batches/{id}`
        # both answer 404 to. Ownership first means a caller only ever learns about their own roster.
        organization_id = await self._sponsoring_organization(actor=actor, student=student)

        batch = await self.batches.get_by_public_id_full(batch_public_id)
        if batch is None:
            raise NotFoundError("Batch not found.")

        if not batch.is_active:
            raise ConflictError("This batch is not accepting enrollments.")

        course = batch.course
        if course is not None and course.status not in _ENROLLABLE_COURSE_STATUSES:
            raise ConflictError(
                "This course is not currently open for enrollment.",
                details={"course_status": course.status.value},
            )

        existing = await self.enrollments.get_active(student_id=student.id, batch_id=batch.id)
        if existing is not None:
            # Re-enrolling after DROPPED/CANCELLED is allowed and creates a
            # fresh row -- only a *live* duplicate is refused. The partial
            # unique index enforces the same rule at the database level.
            raise ConflictError("This student is already enrolled in this batch.")

        await self._reserve_seat(batch)

        enrollment = Enrollments(
            student_id=student.id,
            batch_id=batch.id,
            status=EnrollmentStatus.CONFIRMED if confirmed else EnrollmentStatus.PENDING,
            enrolled_by=actor.id,
            organization_id=organization_id,
        )
        await self.enrollments.add_and_flush(enrollment)

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="enrollment",
            entity_id=enrollment.enrollment_id,
            details={
                "student": student.username,
                "batch": batch.batch_code,
                "status": enrollment.status.value,
                "organization_sponsored": organization_id is not None,
            },
        )
        # The student is told, in the same transaction as the enrolment
        # itself: a tray saying "you were enrolled" for a row that rolled
        # back is worse than silence.
        notifications = NotificationService(self.session)
        await notifications.notify(
            user_id=student.id,
            type_=NotificationType.ENROLLED_IN_BATCH,
            title=f"Enrolled in {batch.batch_code}",
            body=f"You were enrolled in {batch.batch_code} ({enrollment.status.value.lower()}).",
            meta={"batch_id": str(batch.public_id), "status": enrollment.status.value},
        )
        await notifications.notify_guardians_of(
            [student.id],
            type_=NotificationType.WARD_ENROLLED_IN_BATCH,
            title=f"{{student}} was enrolled in {batch.batch_code}",
            body=f"{batch.batch_code} ({enrollment.status.value.lower()}).",
            meta={"batch_id": str(batch.public_id), "status": enrollment.status.value},
        )

        await WebhookService(self.session).enqueue(
            WebhookEvent.ENROLLMENT_CREATED,
            {
                "event": WebhookEvent.ENROLLMENT_CREATED,
                "enrollment_id": str(enrollment.public_id),
                "student_id": str(student.public_id),
                "batch_id": str(batch.public_id),
                "status": enrollment.status.value,
            },
        )

        return await self.enrollments.get_by_public_id_full(enrollment.public_id)  # type: ignore[return-value]

    async def _reserve_seat(self, batch: Batch) -> None:
        """Check capacity under a row lock.

        Capacity is a read-modify-write: count the occupants, decide, insert.
        Without serialising on the batch row, two simultaneous enrollments
        both see the last free seat and both take it. `lock_for_enrollment`
        holds a `FOR UPDATE` lock on this batch only, so enrollments into
        *other* batches are unaffected.
        """
        if batch.capacity is None:
            return

        locked = await self.batches.lock_for_enrollment(batch.id)
        if locked is None:
            raise NotFoundError("Batch not found.")

        occupied = await self.batches.occupied_seats(batch.id)
        if occupied >= locked.capacity:
            raise ConflictError(
                "This batch is full.",
                details={"capacity": locked.capacity, "enrolled": occupied},
            )

    async def _sponsoring_organization(self, *, actor: User, student: User) -> int | None:
        """Which organization, if any, is sponsoring this enrollment.

        Two separate questions, and they used to be one:

        * **May this manager enrol this student?** Their roster says so, and
          only their roster -- `manager_students`, the same table everything
          else about a manager's reach reads. Enrolling somebody who is not
          yours is refused rather than absorbed, exactly as before; the
          message now names the real relationship instead of the company.
        * **Who is paying?** The student's own current employment. Still
          derived, never accepted from the request body -- a caller-supplied
          organization_id would let anyone attribute an enrollment to a
          company they have nothing to do with.

        A managed student with no employment on file is enrolled **unsponsored**
        rather than refused. That combination could not happen before and is
        ordinary now: the link is what the manager has, and a company is a
        separate fact that may simply not be recorded.
        """
        if not await self._is_corporate_manager(actor):
            return None

        managed = await self.session.execute(
            select(ManagedStudent.id).where(
                ManagedStudent.manager_id == actor.id,
                ManagedStudent.student_id == student.id,
            )
        )
        if managed.scalar_one_or_none() is None:
            raise ConflictError("This student is not one of yours to enrol.")

        membership = (
            await self.session.execute(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == student.id,
                    OrganizationMembership.status.in_(
                        (
                            OrganizationMembershipStatus.INVITED,
                            OrganizationMembershipStatus.ACTIVE,
                            OrganizationMembershipStatus.SUSPENDED,
                        )
                    ),
                )
            )
        ).scalar_one_or_none()

        return membership.organization_id if membership else None

    async def _is_corporate_manager(self, actor: User) -> bool:
        """Whether this caller enrols people as a manager at all.

        Asked by appointment rather than by role name, so the answer stays
        true for a custom role doing the same job -- and so an administrator
        enrolling somebody is never put through the roster check, which is
        not their constraint.
        """
        stmt = select(OrganizationManager.id).where(
            OrganizationManager.user_id == actor.id,
            OrganizationManager.is_active.is_(True),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    # -- lifecycle -----------------------------------------------------------

    async def set_status(
        self, public_id: uuid.UUID, new_status: EnrollmentStatus, *, actor: User
    ) -> Enrollments:
        enrollment = await self.get(public_id, actor=actor)
        current = enrollment.status

        if new_status == current:
            return enrollment

        allowed = _ALLOWED_TRANSITIONS.get(current, frozenset())
        if new_status not in allowed:
            raise ConflictError(
                f"A {current.value} enrollment cannot become {new_status.value}.",
                details={
                    "current_status": current.value,
                    "allowed_transitions": sorted(s.value for s in allowed),
                },
            )

        enrollment.status = new_status
        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="enrollment",
            entity_id=enrollment.enrollment_id,
            details={"status": f"{current.value} -> {new_status.value}"},
        )

        # The early return above means this is only ever a real transition --
        # setting a status to what it already is notifies nobody.
        batch = enrollment.batch
        await NotificationService(self.session).notify(
            user_id=enrollment.student_id,
            type_=NotificationType.ENROLLMENT_STATUS_CHANGED,
            title="Your enrollment status changed",
            body=(
                f"{batch.batch_code if batch is not None else 'Your batch'} — "
                f"now {new_status.value.lower()}."
            ),
            meta={"enrollment_id": str(enrollment.public_id)},
        )
        return enrollment

    async def transfer(
        self, public_id: uuid.UUID, *, target_batch_public_id: uuid.UUID, actor: User
    ) -> Enrollments:
        """Move a student to another batch, preserving history.

        The original enrollment is closed as DROPPED and a *new* row created
        pointing back at it through `previous_enrollment_id`. Rewriting the
        original's `batch_id` in place would be simpler and would erase the
        fact that the student was ever in the first batch -- along with the
        context for the attendance and grades recorded there.
        """
        source = await self.get(public_id, actor=actor)

        if source.status not in ACTIVE_STATUSES:
            raise ConflictError(
                "Only a pending or confirmed enrollment can be transferred.",
                details={"current_status": source.status.value},
            )

        target = await self.batches.get_by_public_id_full(target_batch_public_id)
        if target is None:
            raise NotFoundError("Batch not found.")
        if target.id == source.batch_id:
            raise ConflictError("The student is already in that batch.")
        if not target.is_active:
            raise ConflictError("The target batch is not accepting enrollments.")

        if await self.enrollments.get_active(student_id=source.student_id, batch_id=target.id):
            raise ConflictError("This student is already enrolled in the target batch.")

        await self._reserve_seat(target)

        source_status = source.status
        source.status = EnrollmentStatus.DROPPED

        moved = Enrollments(
            student_id=source.student_id,
            batch_id=target.id,
            status=source_status,
            enrolled_by=actor.id,
            organization_id=source.organization_id,
            is_transfer=True,
            previous_enrollment_id=source.enrollment_id,
        )
        await self.enrollments.add_and_flush(moved)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="enrollment",
            entity_id=moved.enrollment_id,
            details={
                "transferred_from_enrollment_id": source.enrollment_id,
                "target_batch": target.batch_code,
            },
        )
        return await self.enrollments.get_by_public_id_full(moved.public_id)  # type: ignore[return-value]

    # -- helpers -------------------------------------------------------------

    async def _load_user(self, public_id: uuid.UUID) -> User:
        stmt = select(User).where(User.public_id == public_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise NotFoundError("User not found.")
        return user

    @staticmethod
    def _assert_is_student(user: User) -> None:
        if not any((r.name or "").upper() == Roles.STUDENT.value for r in (user.roles or [])):
            raise ValidationError(
                "Only users holding the STUDENT role can be enrolled.",
                details={"username": user.username},
            )
