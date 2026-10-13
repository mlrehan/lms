"""Examinations, invigilators and results (spec §14)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.core.logging import get_logger
from backend.models.batch import Batch
from backend.models.enrollment import Enrollments
from backend.models.exam import Exam, ExamInvigilator, ExamResult
from backend.models.identity.user import User
from backend.repositories.enrollment import ACTIVE_STATUSES
from backend.repositories.exam import ExamRepository, ExamResultRepository
from backend.schemas.base import PageParams
from backend.schemas.exam import (
    ExamCreateRequest,
    ExamResultEntry,
    ExamUpdateRequest,
)
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.batch_service import BatchService
from backend.services.course_service import CourseService
from backend.services.gradebook_service import GradeBookService
from backend.services.assessment_scope import (
    AssessmentScopeResolver,
    AssessmentTarget,
    validate as validate_scope,
)
from backend.core.notification_types import NotificationType
from backend.services.notification_service import NotificationService
from backend.services.scope import ScopeResolver
from backend.utils.enums import GradeComponentType, Roles


logger = get_logger(__name__)


class ExamService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.exams = ExamRepository(session)
        self.results = ExamResultRepository(session)
        self.courses = CourseService(session)
        self.batches = BatchService(session)
        self.scopes = ScopeResolver(session)
        self.targets = AssessmentScopeResolver(session)

    # -- exams ---------------------------------------------------------------

    async def list_exams(
        self, params: PageParams, *, actor: User
    ) -> tuple[Sequence[Exam], int]:
        course_scope = await self.scopes.visible_course_ids(actor)
        batch_scope = await self.scopes.visible_batch_ids(actor)
        invigilating = await self.exams.invigilating_exam_ids(actor.id)
        # Staff who schedule or mark exams see drafts; candidates do not.
        published_only = not (await self._can_manage(actor) or await self._can_mark(actor))

        return await self.exams.search(
            params,
            course_scope=course_scope,
            batch_scope=batch_scope,
            invigilating_exam_ids=invigilating,
            published_only=published_only,
        )

    async def get(self, public_id: uuid.UUID, *, actor: User) -> Exam:
        row = await self.exams.get_by_public_id_full(public_id)
        if row is None:
            raise NotFoundError("Exam not found.")

        if not await self._can_reach(row, actor):
            raise NotFoundError("Exam not found.")

        if not row.is_published and not await self._can_see_unpublished(row, actor):
            raise NotFoundError("Exam not found.")
        return row

    async def create(self, payload: ExamCreateRequest, *, actor: User) -> Exam:
        course_id = None
        if payload.course_id is not None:
            course_id = (await self.courses.get(payload.course_id, actor=actor)).id

        batch_id = None
        if payload.batch_id is not None:
            batch = await self.batches.get(payload.batch_id, actor=actor)
            batch_id = batch.id
            if course_id is not None and batch.course_id != course_id:
                raise ValidationError(
                    "That batch does not belong to the given course.",
                    details={"batch": batch.batch_code},
                )
            if course_id is None:
                # A batch-anchored exam still belongs to that batch's course;
                # filling it in keeps course-level scoping and reporting
                # working without the caller having to say it twice.
                course_id = batch.course_id

        # Exams kept a fourth convention of their own -- nullable course/batch
        # with the scope *inferred* from which was set. They now carry the same
        # explicit `scope` the other two do, resolved by the same service, so
        # one eligibility rule serves all three (§3).
        target = await self.targets.resolve_ids(
            scope=payload.scope,
            course_id=course_id or 0,
            batch_id=batch_id,
            session_id=await self.targets.session_id(payload.session_id),
        )
        validate_scope(target)
        if course_id and target.course_id != course_id:
            raise ValidationError("That batch or session belongs to a different course.")
        course_id = target.course_id or course_id

        row = Exam(
            course_id=course_id,
            batch_id=target.batch_id or batch_id,
            session_id=target.session_id,
            scope=target.scope,
            is_online=payload.is_online,
            weight=payload.weight,
            exam_type=payload.exam_type,
            title=payload.title,
            scheduled_at=payload.scheduled_at,
            duration_minutes=payload.duration_minutes,
            venue_or_link=payload.venue_or_link,
            total_marks=payload.total_marks,
            passing_marks=payload.passing_marks,
            instructions=payload.instructions,
            is_published=False,
        )
        row.invigilators = []
        row.results = []
        await self.exams.add_and_flush(row)

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="exam",
            entity_id=row.id,
            details={"title": row.title, "type": payload.exam_type.value},
        )
        return await self.exams.get_by_public_id_full(row.public_id)  # type: ignore[return-value]

    async def update(
        self, public_id: uuid.UUID, payload: ExamUpdateRequest, *, actor: User
    ) -> Exam:
        row = await self.get(public_id, actor=actor)
        changes = payload.model_dump(exclude_unset=True)

        total = changes.get("total_marks", row.total_marks)
        passing = changes.get("passing_marks", row.passing_marks)
        if Decimal(str(passing)) > Decimal(str(total)):
            raise ConflictError("passing_marks cannot exceed total_marks.")

        if "total_marks" in changes:
            highest = (
                await self.session.execute(
                    select(ExamResult.marks_obtained)
                    .where(
                        ExamResult.exam_id == row.id,
                        ExamResult.marks_obtained.is_not(None),
                    )
                    .order_by(ExamResult.marks_obtained.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if highest is not None and Decimal(str(total)) < Decimal(str(highest)):
                raise ConflictError(
                    "total_marks cannot be lower than a mark already recorded.",
                    details={"highest_recorded": str(highest), "requested_total": str(total)},
                )

        for field, value in changes.items():
            setattr(row, field, value)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="exam",
            entity_id=row.id,
            details={"fields": sorted(changes)},
        )
        return row

    async def set_published(
        self, public_id: uuid.UUID, is_published: bool, *, actor: User
    ) -> Exam:
        row = await self.get(public_id, actor=actor)
        was_published = bool(row.is_published)
        row.is_published = is_published

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="exam",
            entity_id=row.id,
            details={"schedule_published": is_published},
        )

        # Only the transition into being published. Re-saving must not
        # re-announce, and withdrawing a schedule announces nothing: a student
        # told "your exam is scheduled" at the moment it is cancelled is worse
        # served than one told nothing.
        if is_published and not was_published:
            await self._announce_schedule(row)

        return row

    async def _announce_schedule(self, exam: Exam) -> None:
        roster = sorted(await self._eligible_student_ids(exam))
        if not roster:
            return

        where = exam.course.title if exam.course is not None else "your course"
        when = f"{exam.scheduled_at:%d %b %Y, %H:%M}"
        meta = {"exam_id": str(exam.public_id)}

        await NotificationService(self.session).notify_many(
            roster,
            type_=NotificationType.EXAM_SCHEDULED,
            title=f"Exam scheduled: {exam.title}",
            body=f"{where} — {when}.",
            meta=meta,
        )

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        row = await self.get(public_id, actor=actor)

        total, _ = await self.exams.result_counts(row.id)
        if total:
            # `results` cascades on delete, so removing the exam would take
            # every recorded mark with it.
            raise ConflictError(
                "This exam already has recorded results and cannot be deleted.",
                details={"results": total},
            )

        entity_id = row.id
        await self.session.delete(row)
        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="exam",
            entity_id=entity_id,
        )

    # -- invigilators --------------------------------------------------------

    async def set_invigilators(
        self, public_id: uuid.UUID, tutor_public_ids: Sequence[uuid.UUID], *, actor: User
    ) -> Exam:
        """Replace the exam's invigilators.

        An authorization write, like course tutor assignment: an invigilator
        gains sight of the exam (and its candidates) whether or not they
        teach the course.
        """
        exam = await self.get(public_id, actor=actor)
        tutors = await self._resolve_tutors(tutor_public_ids)

        existing = {
            row.tutor_id: row
            for row in (
                await self.session.execute(
                    select(ExamInvigilator).where(ExamInvigilator.exam_id == exam.id)
                )
            )
            .scalars()
            .all()
        }
        desired = {t.id for t in tutors}

        for tutor_id, row in existing.items():
            if tutor_id not in desired:
                await self.session.delete(row)

        for tutor_id in desired - set(existing):
            self.session.add(ExamInvigilator(exam_id=exam.id, tutor_id=tutor_id))

        await self.session.flush()
        # The association rows changed under an already-loaded collection.
        self.session.expire(exam, ["invigilators"])

        audit_service.record(
            self.session,
            action=AuditAction.PERMISSION_CHANGE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="exam",
            entity_id=exam.id,
            details={"invigilators": sorted(t.username for t in tutors)},
        )
        return await self.exams.get_by_public_id_full(public_id)  # type: ignore[return-value]

    # -- results -------------------------------------------------------------

    async def list_results(
        self,
        params: PageParams,
        *,
        actor: User,
        exam_public_id: uuid.UUID | None = None,
        student_public_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[ExamResult], int]:
        exam_id = None
        if exam_public_id is not None:
            exam_id = (await self.get(exam_public_id, actor=actor)).id

        student_id = None
        if student_public_id is not None:
            student_id = (await self._load_user(student_public_id)).id

        visibility = await self.scopes.work_visibility(actor)
        return await self.results.search(
            params,
            visibility=visibility,
            exam_id=exam_id,
            student_id=student_id,
            # Gated on `grade.update` (the marking permission), not
            # `exam.update`: publication exists to withhold results from
            # *students and guardians* until they are released, not from the
            # staff doing the marking. Gating on exam.update meant a Tutor
            # could record a cohort's marks and then be unable to read back
            # what they had just entered.
            include_unpublished=await self._can_mark(actor),
        )

    async def record_results(
        self, public_id: uuid.UUID, entries: Sequence[ExamResultEntry], *, actor: User
    ) -> list[ExamResult]:
        """Record or correct a whole cohort's marks in one call."""
        exam = await self.get(public_id, actor=actor)

        eligible = await self._eligible_student_ids(exam)
        by_public_id = await self._resolve_students([e.student_id for e in entries])

        not_eligible = [
            user.username
            for public_id_, user in by_public_id.items()
            if user.id not in eligible
        ]
        if not_eligible:
            # Refuse the whole mark sheet rather than silently dropping
            # names, for the same reason attendance marking does.
            raise ValidationError(
                "These students are not enrolled in this exam's course or batch.",
                details={"not_enrolled": sorted(not_eligible)},
            )

        over = [
            str(e.student_id)
            for e in entries
            if Decimal(str(e.marks_obtained)) > Decimal(str(exam.total_marks))
        ]
        if over:
            raise ValidationError(
                "Marks exceed the exam's total.",
                details={"total_marks": str(exam.total_marks), "students": sorted(over)},
            )

        existing = await self.results.existing_by_student(exam.id)

        for entry in entries:
            student = by_public_id[entry.student_id]
            row = existing.get(student.id)
            if row is None:
                row = ExamResult(
                    exam_id=exam.id,
                    student_id=student.id,
                    marks_obtained=entry.marks_obtained,
                    grade=entry.grade,
                    remarks=entry.remarks,
                    # Recording a mark is not releasing it -- spec §14 makes
                    # publication a separate, deliberate act.
                    is_published=False,
                )
                self.session.add(row)
            else:
                row.marks_obtained = entry.marks_obtained
                row.grade = entry.grade
                row.remarks = entry.remarks

        await self.session.flush()

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="exam",
            entity_id=exam.id,
            details={"results_recorded": len(entries)},
        )

        rows = await self.results.existing_by_student(exam.id)
        for row in rows.values():
            await self._record_in_gradebook(exam, row)
        return sorted(rows.values(), key=lambda r: r.id)

    async def _record_in_gradebook(self, exam: Exam, result: ExamResult) -> None:
        """Put a recorded exam mark into the grade book straight away (§47).

        The third and last of the marking paths to be wired -- quizzes and
        coursework came first. Until this, an exam mark only reached the grade
        book when somebody pressed Sync, so the grade book disagreed with the
        mark sheet it derives from for as long as nobody did.

        **At recording, not at publication**, which reads backwards against
        §47's wording but is the only choice that keeps the two writers in
        agreement: `_sync_exams` writes every result that has a mark,
        published or not. Holding back here would mean the next sweep
        introduced rows this path had declined to write, and the grade book
        would change without anything being marked. Releasing a mark to the
        student is a separate act and stays that way -- `is_published` governs
        what the student sees, not what the institution has recorded.

        **The row the sweep would have written**, out of the exam's own
        `total_marks`, through the same `record_component`. A course-scoped
        exam has no `batch_id`, and `record_component` then fans the mark out
        across the student's active cohorts of that course, exactly as
        sweeping each batch in turn would.

        Fail-open: the mark has been recorded and must not be lost because a
        derived row could not be written. `sync_batch` is the reconciler.
        """
        if result.marks_obtained is None:
            return
        try:
            await GradeBookService(self.session).record_component(
                student_id=result.student_id,
                course_id=exam.course_id,
                batch_id=exam.batch_id,
                component_type=GradeComponentType.FINAL_EXAM,
                reference_id=result.id,
                score=Decimal(str(result.marks_obtained)),
                max_score=Decimal(str(exam.total_marks)),
            )
        except Exception:  # noqa: BLE001 - a derived row must not undo a mark
            logger.exception(
                "Failed to record exam result in the grade book",
                extra={"exam_result_id": result.id},
            )

    async def publish_results(
        self, public_id: uuid.UUID, is_published: bool, *, actor: User
    ) -> int:
        """Release (or retract) every recorded result for this exam."""
        exam = await self.get(public_id, actor=actor)
        rows = await self.results.existing_by_student(exam.id)

        if not rows:
            raise ConflictError("This exam has no recorded results to publish.")

        for row in rows.values():
            row.is_published = is_published

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="exam",
            entity_id=exam.id,
            details={"results_published": is_published, "count": len(rows)},
        )

        if is_published:
            await self._announce_results(exam, student_ids=sorted(rows.keys()))

        return len(rows)

    async def _announce_results(self, exam: Exam, *, student_ids: Sequence[int]) -> None:
        """Tell the students who actually have a result.

        Not the eligible roster: a student who was absent and has no recorded
        row has nothing to read, and "your result is available" pointing at
        nothing is a worse message than none. Guardians get their own code
        rather than a copy of the student's, because every description in the
        catalogue is written in the second person about its subject.
        """
        if not student_ids:
            return

        where = exam.course.title if exam.course is not None else "your course"
        meta = {"exam_id": str(exam.public_id)}

        notifications = NotificationService(self.session)
        await notifications.notify_many(
            student_ids,
            type_=NotificationType.EXAM_RESULT_PUBLISHED,
            title=f"Result published: {exam.title}",
            body=f"{where} — your mark is now available.",
            meta=meta,
        )
        await notifications.notify_guardians_of(
            student_ids,
            type_=NotificationType.WARD_EXAM_RESULT_PUBLISHED,
            title=f"Result published for {{student}}: {exam.title}",
            body=f"{where} — the mark is now available.",
            meta=meta,
        )

    # -- helpers -------------------------------------------------------------

    async def _eligible_student_ids(self, exam: Exam) -> set[int]:
        """Students who may be marked for this exam.

        Was a hand-rolled copy of the same join assignments and quizzes each
        had their own version of -- and it quietly differed: a course-wide exam
        included students from **closed** batches, because the local copy never
        filtered on `Batch.is_active`. Last year's cohort appeared on this
        year's mark sheet.

        Now the one shared resolver, so a fix in one place is a fix everywhere.
        """
        return await self.targets.eligible_student_ids(AssessmentTarget.of(exam))

    async def _can_reach(self, exam: Exam, actor: User) -> bool:
        if ScopeResolver.is_unrestricted(actor):
            return True

        course_scope = await self.scopes.visible_course_ids(actor)
        if exam.course_id is not None and course_scope.allows(exam.course_id):
            return True

        batch_scope = await self.scopes.visible_batch_ids(actor)
        if exam.batch_id is not None and batch_scope.allows(exam.batch_id):
            return True

        # Invigilating is its own route in: a tutor supervising an exam for a
        # course they do not teach must still be able to open it.
        return exam.id in await self.exams.invigilating_exam_ids(actor.id)

    async def _can_manage(self, actor: User) -> bool:
        """Holds the exam-administration permission (scheduling, publishing)."""
        from backend.api.deps import resolve_permissions
        from backend.core.permissions import Action, Module, perm

        return perm(Module.EXAM, Action.UPDATE) in resolve_permissions(actor)

    async def _can_mark(self, actor: User) -> bool:
        """Holds the marking permission -- Tutors included, unlike
        `_can_manage`. Entering marks and reading back unpublished marks are
        the same job."""
        from backend.api.deps import resolve_permissions
        from backend.core.permissions import Action, Module, perm

        return perm(Module.GRADE, Action.UPDATE) in resolve_permissions(actor)

    async def _can_see_unpublished(self, exam: Exam, actor: User) -> bool:
        """An unpublished exam is hidden from candidates, not from staff.

        Invigilators are included deliberately: being assigned to supervise
        an exam that has not been announced yet is exactly when someone needs
        to see it on their own duty roster, and excluding them meant an
        assignment they could not open.
        """
        if await self._can_manage(actor) or await self._can_mark(actor):
            return True
        return exam.id in await self.exams.invigilating_exam_ids(actor.id)

    async def _resolve_tutors(self, public_ids: Sequence[uuid.UUID]) -> list[User]:
        if not public_ids:
            return []
        stmt = select(User).where(User.public_id.in_(list(public_ids)))
        found = list((await self.session.execute(stmt)).scalars().unique().all())

        missing = set(public_ids) - {u.public_id for u in found}
        if missing:
            raise ValidationError(
                "Unknown user(s).",
                details={"unknown_users": sorted(str(m) for m in missing)},
            )

        not_tutors = [
            u.username
            for u in found
            if not any((r.name or "").upper() == Roles.TUTOR.value for r in (u.roles or []))
        ]
        if not_tutors:
            raise ValidationError(
                "These users do not hold the TUTOR role.",
                details={"not_tutors": sorted(not_tutors)},
            )
        return found

    async def _resolve_students(
        self, public_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, User]:
        stmt = select(User).where(User.public_id.in_(list(public_ids)))
        found = {u.public_id: u for u in (await self.session.execute(stmt)).scalars().unique()}

        missing = set(public_ids) - set(found)
        if missing:
            raise ValidationError(
                "Unknown user(s).",
                details={"unknown_users": sorted(str(m) for m in missing)},
            )
        return found

    async def _load_user(self, public_id: uuid.UUID) -> User:
        stmt = select(User).where(User.public_id == public_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise NotFoundError("User not found.")
        return user
