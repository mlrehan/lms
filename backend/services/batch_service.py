"""Batch management (spec §6)."""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.models.administration import AcademicYear, Semester
from backend.models.batch import Batch
from backend.models.identity.user import User
from backend.repositories.batch import BatchRepository
from backend.repositories.enrollment import EnrollmentRepository
from backend.schemas.base import PageParams
from backend.schemas.batch import BatchCreateRequest, BatchUpdateRequest
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.course_service import CourseService
from backend.services.scope import ScopeResolver


class BatchService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.batches = BatchRepository(session)
        self.enrollments = EnrollmentRepository(session)
        self.courses = CourseService(session)
        self.scopes = ScopeResolver(session)

    # -- reads ---------------------------------------------------------------

    async def list_batches(
        self,
        params: PageParams,
        *,
        actor: User,
        course_public_id: uuid.UUID | None = None,
        is_active: bool | None = None,
    ) -> tuple[Sequence[Batch], int]:
        """Row-scoped: a Tutor sees the batches they teach, a Student the
        batch they are enrolled in, a Guardian/Manager the batches of the
        people they are responsible for."""
        course_id = None
        if course_public_id is not None:
            course = await self.courses.get(course_public_id, actor=actor)
            course_id = course.id

        scope = await self.scopes.visible_batch_ids(actor)
        return await self.batches.search(
            params, scope=scope, course_id=course_id, is_active=is_active
        )

    async def get(self, public_id: uuid.UUID, *, actor: User) -> Batch:
        batch = await self.batches.get_by_public_id_full(public_id)
        if batch is None:
            raise NotFoundError("Batch not found.")

        scope = await self.scopes.visible_batch_ids(actor)
        if not scope.allows(batch.id):
            raise NotFoundError("Batch not found.")
        return batch

    async def seat_counts(self, batch: Batch) -> tuple[int, int | None]:
        """Return ``(occupied, remaining)``; remaining is None when uncapped."""
        occupied = await self.batches.occupied_seats(batch.id)
        remaining = None if batch.capacity is None else max(batch.capacity - occupied, 0)
        return occupied, remaining

    # -- writes --------------------------------------------------------------

    async def create(
        self, course_public_id: uuid.UUID, payload: BatchCreateRequest, *, actor: User
    ) -> Batch:
        course = await self.courses.get(course_public_id, actor=actor)

        if await self.batches.get_by_code(payload.batch_code):
            raise ConflictError("A batch with that code already exists.")

        year_id, semester_id = await self._resolve_calendar(
            academic_year_id=payload.academic_year_id, semester_id=payload.semester_id
        )

        batch = Batch(
            course_id=course.id,
            batch_code=payload.batch_code,
            academic_year_id=year_id,
            semester_id=semester_id,
            capacity=payload.capacity,
            duration_hours=payload.duration_hours,
            number_of_sessions=payload.number_of_sessions,
            start_date=payload.start_date,
            end_date=payload.end_date,
            notes=payload.notes,
            is_active=True,
        )
        await self.batches.add_and_flush(batch)

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="batch",
            entity_id=batch.id,
            details={"batch_code": batch.batch_code, "course": course.title},
        )
        # A freshly-constructed instance has its scalar relationships marked
        # *loaded as None*, not unloaded -- so the re-read below hands back
        # the same identity-map object and leaves them None, and the response
        # reports an unscheduled batch that the database has scheduled
        # correctly. Expiring them is what makes the re-read repopulate; the
        # same trap `set_tutors` was fixed for, one relationship kind over.
        self.session.expire(batch, ["academic_year", "semester"])
        return await self.batches.get_by_public_id_full(batch.public_id)  # type: ignore[return-value]


    async def _resolve_calendar(
        self,
        *,
        academic_year_id: uuid.UUID | None,
        semester_id: uuid.UUID | None,
        current_year_id: int | None = None,
    ) -> tuple[int | None, int | None]:
        """Resolve the calendar placement, refusing a semester that is not in
        the named year.

        A batch scheduled into "2025-2026" and "Spring 2019" is describable in
        the schema -- both columns are independent nullable foreign keys -- and
        is nonsense. Nothing else can catch it: the database sees two valid
        references, and the request alone does not know which year the
        semester belongs to.

        Naming only the semester adopts its year, so the caller cannot create
        that contradiction by omission either.
        """
        year_pk: int | None = current_year_id
        if academic_year_id is not None:
            year_pk = (
                await self.session.execute(
                    select(AcademicYear.id).where(AcademicYear.public_id == academic_year_id)
                )
            ).scalar_one_or_none()
            if year_pk is None:
                raise NotFoundError("Academic year not found.")

        if semester_id is None:
            return year_pk, None

        semester = (
            await self.session.execute(
                select(Semester).where(Semester.public_id == semester_id)
            )
        ).scalar_one_or_none()
        if semester is None:
            raise NotFoundError("Semester not found.")

        if year_pk is not None and semester.academic_year_id != year_pk:
            raise ValidationError("That semester does not belong to that academic year.")

        return semester.academic_year_id, semester.id

    async def update(
        self, public_id: uuid.UUID, payload: BatchUpdateRequest, *, actor: User
    ) -> Batch:
        batch = await self.get(public_id, actor=actor)
        changes = payload.model_dump(exclude_unset=True)

        # Calendar links carry public UUIDs while the columns hold integer
        # primary keys, so they are resolved out of `changes` before the
        # blind `setattr` loop further down can write one into the other.
        clear_year = changes.pop("clear_academic_year", False)
        clear_semester = changes.pop("clear_semester", False)
        year_public = changes.pop("academic_year_id", None)
        semester_public = changes.pop("semester_id", None)

        if clear_year:
            # Clearing the year clears the semester with it: a batch sitting
            # in "Fall" of no particular year is not a state worth having.
            batch.academic_year_id = None
            batch.semester_id = None
        elif year_public is not None or semester_public is not None:
            year_id, semester_id = await self._resolve_calendar(
                academic_year_id=year_public,
                semester_id=semester_public,
                current_year_id=batch.academic_year_id,
            )
            batch.academic_year_id = year_id
            batch.semester_id = semester_id
        if clear_semester and not clear_year:
            batch.semester_id = None

        new_code = changes.get("batch_code")
        if new_code and new_code.lower() != (batch.batch_code or "").lower():
            if await self.batches.get_by_code(new_code):
                raise ConflictError("A batch with that code already exists.")

        new_capacity = changes.get("capacity")
        if new_capacity is not None:
            occupied = await self.batches.occupied_seats(batch.id)
            if new_capacity < occupied:
                # Lowering capacity below the number of people already in the
                # batch would leave it permanently over-subscribed with no
                # way to describe who should not be there.
                raise ConflictError(
                    "Capacity cannot be lower than the number of students already enrolled.",
                    details={"enrolled": occupied, "requested_capacity": new_capacity},
                )

        # `start_date`/`end_date` are validated pairwise in the schema, but a
        # PATCH may send only one of them -- re-check against the stored value
        # so a lone `end_date` cannot be moved before the existing start.
        start = changes.get("start_date", batch.start_date)
        end = changes.get("end_date", batch.end_date)
        if start and end and end < start:
            raise ConflictError("end_date cannot be earlier than start_date.")

        for field, value in changes.items():
            setattr(batch, field, value)

        # The foreign keys moved but the loaded `academic_year`/`semester`
        # objects did not, so the response would name where the batch used
        # to be scheduled.
        self.session.expire(batch, ["academic_year", "semester"])

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="batch",
            entity_id=batch.id,
            details={"fields": sorted(changes)},
        )
        return batch

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        batch = await self.get(public_id, actor=actor)

        occupied = await self.batches.occupied_seats(batch.id)
        if occupied:
            raise ConflictError(
                "This batch still has active enrollments. Deactivate it instead.",
                details={"enrolled": occupied},
            )

        entity_id = batch.id
        # `Batch` has no soft-delete mixin, and an empty batch carries no
        # history worth a tombstone -- attendance and enrollment rows are
        # what would need preserving, and there are none.
        await self.session.delete(batch)

        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="batch",
            entity_id=entity_id,
        )
