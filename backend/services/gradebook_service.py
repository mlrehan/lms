"""Grade book aggregation and transcripts (spec §15).

The grade book is a *derived* store: `sync` recomputes entries from the marks
already recorded against assignments, quizzes, exams and attendance, so those
services stay unaware of it. Wiring a `GradeBookEntry` write into each of
them instead would scatter the same aggregation rule across four places and
guarantee they drift.

**Sync is idempotent by construction**, resting on the two partial unique
indexes on `gradebook_entries`: a re-run corrects the existing entry for a
source row rather than appending a second. Without that, every re-sync would
double a student's marks and the computed GPA would drift further from
reality on each run.

**Per-component weighting is not configurable.** Every synced entry carries
`weight = 1`, so the weighted average is currently a straight average across
components; only manually-created entries can set a different weight. A real
weighting policy ("coursework is 40% of the final mark") needs a table to
store it in, which no model provides -- see the known-gaps list.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.privacy import visible_username
from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.attendance import Attendance
from backend.models.batch import Batch, BatchSession
from backend.models.enrollment import Enrollments
from backend.models.exam import Exam, ExamResult
from backend.models.gradebook import GradeBand, GradeBookEntry, Transcript
from backend.models.identity.user import User
from backend.models.quiz import Quiz, QuizAttempt
from backend.repositories.enrollment import ACTIVE_STATUSES
from backend.repositories.gradebook import (
    GradeBandRepository,
    GradeBookRepository,
    TranscriptRepository,
)
from backend.schemas.base import PageParams
from backend.schemas.gradebook import (
    GradeBandCreateRequest,
    GradeBandUpdateRequest,
    GradeBookEntryCreateRequest,
    GradeBookEntryUpdateRequest,
)
from backend.core.notification_types import NotificationType
from backend.services.notification_service import NotificationService
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.batch_service import BatchService
from backend.services.scope import ScopeResolver
from backend.utils.enums import AttendanceStatus, GradeComponentType

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


class GradeBookService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.entries = GradeBookRepository(session)
        self.bands = GradeBandRepository(session)
        self.transcripts = TranscriptRepository(session)
        self.batches = BatchService(session)
        self.scopes = ScopeResolver(session)

    # -- grade bands ---------------------------------------------------------

    async def list_bands(self) -> list[GradeBand]:
        return await self.bands.list_all()

    async def create_band(self, payload: GradeBandCreateRequest, *, actor: User) -> GradeBand:
        if await self.bands.get_by_letter(payload.letter_grade):
            raise ConflictError("A band with that letter grade already exists.")

        clash = await self.bands.overlapping(
            min_score=payload.min_score, max_score=payload.max_score
        )
        if clash is not None:
            raise ConflictError(
                "That range overlaps an existing band.",
                details={
                    "conflicting_grade": clash.letter_grade,
                    "conflicting_range": f"{clash.min_score}-{clash.max_score}",
                },
            )

        band = GradeBand(
            min_score=payload.min_score,
            max_score=payload.max_score,
            letter_grade=payload.letter_grade,
            gpa_points=payload.gpa_points,
        )
        self.session.add(band)
        await self.session.flush()

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="grade_band",
            entity_id=band.id,
            details={"letter": band.letter_grade},
        )
        return band

    async def update_band(
        self, band_id: int, payload: GradeBandUpdateRequest, *, actor: User
    ) -> GradeBand:
        band = await self.bands.get(band_id)
        if band is None:
            raise NotFoundError("Grade band not found.")

        changes = payload.model_dump(exclude_unset=True)
        new_min = changes.get("min_score", band.min_score)
        new_max = changes.get("max_score", band.max_score)
        if Decimal(str(new_min)) > Decimal(str(new_max)):
            raise ConflictError("min_score cannot exceed max_score.")

        if "letter_grade" in changes:
            other = await self.bands.get_by_letter(changes["letter_grade"])
            if other is not None and other.id != band.id:
                raise ConflictError("A band with that letter grade already exists.")

        clash = await self.bands.overlapping(
            min_score=Decimal(str(new_min)),
            max_score=Decimal(str(new_max)),
            exclude_id=band.id,
        )
        if clash is not None:
            raise ConflictError(
                "That range overlaps an existing band.",
                details={"conflicting_grade": clash.letter_grade},
            )

        for field, value in changes.items():
            setattr(band, field, value)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="grade_band",
            entity_id=band.id,
            details={"fields": sorted(changes)},
        )
        return band

    async def delete_band(self, band_id: int, *, actor: User) -> None:
        band = await self.bands.get(band_id)
        if band is None:
            raise NotFoundError("Grade band not found.")

        letter = band.letter_grade
        await self.session.delete(band)
        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="grade_band",
            entity_id=band_id,
            details={"letter": letter},
        )

    # -- entries -------------------------------------------------------------

    async def list_entries(
        self,
        params: PageParams,
        *,
        actor: User,
        batch_public_id: uuid.UUID | None = None,
        student_public_id: uuid.UUID | None = None,
        component_type: GradeComponentType | None = None,
    ) -> tuple[Sequence[GradeBookEntry], int]:
        batch_id = None
        if batch_public_id is not None:
            batch_id = (await self.batches.get(batch_public_id, actor=actor)).id

        student_id = None
        if student_public_id is not None:
            student_id = (await self._load_user(student_public_id)).id

        visibility = await self.scopes.enrollment_visibility(actor)
        return await self.entries.search(
            params,
            visibility=visibility,
            batch_id=batch_id,
            student_id=student_id,
            component_type=component_type,
        )

    async def get_entry(self, public_id: uuid.UUID, *, actor: User) -> GradeBookEntry:
        row = await self.entries.get_by_public_id_full(public_id)
        if row is None:
            raise NotFoundError("Grade book entry not found.")

        visibility = await self.scopes.enrollment_visibility(actor)
        if not visibility.unrestricted:
            reachable = (
                row.batch_id in visibility.taught_batch_ids
                or row.student_id in visibility.cared_for_student_ids
            )
            if not reachable:
                raise NotFoundError("Grade book entry not found.")
        return row

    async def create_entry(
        self, batch_public_id: uuid.UUID, payload: GradeBookEntryCreateRequest, *, actor: User
    ) -> GradeBookEntry:
        batch = await self.batches.get(batch_public_id, actor=actor)
        student = await self._load_user(payload.student_id)

        if student.id not in await self._enrolled_student_ids(batch.id):
            raise ValidationError(
                "That student is not enrolled in this batch.",
                details={"username": student.username},
            )

        existing = await self.entries.find_one(
            student_id=student.id,
            batch_id=batch.id,
            component_type=payload.component_type,
            reference_id=None,
        )
        if existing is not None:
            # The unsourced partial unique index allows exactly one manual
            # entry per component; a second would be refused by the database.
            raise ConflictError(
                "A manual entry already exists for that component; update it instead.",
                details={"entry_id": str(existing.public_id)},
            )

        row = GradeBookEntry(
            student_id=student.id,
            batch_id=batch.id,
            component_type=payload.component_type,
            reference_id=None,
            score=payload.score,
            max_score=payload.max_score,
            weight=payload.weight,
            recorded_at=datetime.now(UTC),
        )
        self.session.add(row)
        await self.session.flush()

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="gradebook_entry",
            entity_id=row.id,
            details={"student": student.username, "component": payload.component_type.value},
        )
        await self._announce_mark(row, student_id=student.id, batch=batch)
        return await self.entries.get_by_public_id_full(row.public_id)  # type: ignore[return-value]

    async def update_entry(
        self, public_id: uuid.UUID, payload: GradeBookEntryUpdateRequest, *, actor: User
    ) -> GradeBookEntry:
        row = await self.get_entry(public_id, actor=actor)

        if row.reference_id is not None:
            # A synced entry is derived data: editing it here would be silently
            # reverted by the next sync, which is worse than refusing.
            raise ConflictError(
                "This entry is derived from a marked submission, attempt or result. "
                "Change the underlying mark instead.",
                details={"component": row.component_type.value},
            )

        changes = payload.model_dump(exclude_unset=True)
        score = Decimal(str(changes.get("score", row.score)))
        max_score = Decimal(str(changes.get("max_score", row.max_score)))
        if score > max_score:
            raise ConflictError("score cannot exceed max_score.")

        for field, value in changes.items():
            setattr(row, field, value)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="gradebook_entry",
            entity_id=row.id,
            details={"fields": sorted(changes)},
        )
        if "score" in changes:
            # Only a changed mark is worth telling someone about. Correcting a
            # weight or a maximum does not change what they scored.
            await self._announce_mark(row, student_id=row.student_id, batch=row.batch)
        return row

    async def _announce_mark(self, row: GradeBookEntry, *, student_id: int, batch: Batch | None) -> None:
        """Tell a student about a mark that has no other announcement.

        **Manual entries only, and that is the whole point.** Every *synced*
        entry already has an emitter at its source -- a graded submission, a
        published exam result -- so announcing it again here would notify the
        same student twice for one mark, from two services that do not know
        about each other. `reference_id is None` is exactly the set of marks a
        tutor typed straight into the grade book, which nothing else can
        announce. This is spec §23's single-source-of-truth rule applied to
        notifications rather than to data.

        Guarded rather than assumed: `update_entry` already refuses a synced
        row, but this is reached from two call sites and a third would not
        have that protection.
        """
        if row.reference_id is not None:
            return

        where = batch.batch_code if batch is not None else "your batch"
        await NotificationService(self.session).notify(
            user_id=student_id,
            type_=NotificationType.GRADE_RECORDED,
            title=f"Mark recorded: {row.component_type.value.replace('_', ' ').title()}",
            body=f"{where} — {row.score} of {row.max_score}.",
            meta={"batch_id": str(batch.public_id) if batch is not None else None},
        )

    async def delete_entry(self, public_id: uuid.UUID, *, actor: User) -> None:
        row = await self.get_entry(public_id, actor=actor)

        if row.reference_id is not None:
            raise ConflictError(
                "This entry is derived and would reappear on the next sync. "
                "Change the underlying mark instead."
            )

        entity_id = row.id
        await self.session.delete(row)
        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="gradebook_entry",
            entity_id=entity_id,
        )

    # -- sync ----------------------------------------------------------------

    async def sync_batch(self, batch_public_id: uuid.UUID, *, actor: User) -> dict[str, int]:
        """Rebuild derived entries for every student enrolled in the batch."""
        batch = await self.batches.get(batch_public_id, actor=actor)
        students = await self._enrolled_student_ids(batch.id)

        stats = {"created": 0, "updated": 0, "unchanged": 0, "skipped_ungraded": 0}
        if not students:
            return {**stats, "students_covered": 0}

        await self._sync_assignments(batch, students, stats)
        await self._sync_quizzes(batch, students, stats)
        await self._sync_exams(batch, students, stats)
        await self._sync_attendance(batch, students, stats)
        await self.session.flush()

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="batch",
            entity_id=batch.id,
            details={"gradebook_sync": stats},
        )
        return {**stats, "students_covered": len(students)}

    async def record_component(
        self,
        *,
        student_id: int,
        course_id: int,
        component_type: GradeComponentType,
        reference_id: int,
        score: Decimal,
        max_score: Decimal,
        batch_id: int | None = None,
    ) -> int:
        """Write one marked result straight into the grade book.

        §47 says a published result "automatically enters the Gradebook". It
        did not: `sync_batch` was the only writer and somebody had to press
        it, so the grade book was a materialised view that drifted from the
        moment anything was marked until a human noticed.

        **The same rows `sync_batch` would have written**, through the same
        `_upsert`, so running the sweep afterwards finds them unchanged rather
        than fighting them. `sync_batch` stays as the reconciler -- it is the
        only thing that can repair a write this method lost.

        **No audit record.** The grading action that triggered this is already
        audited; a second entry per mark would bury that log under its own
        side effects. `sync_batch` keeps its audit because an operator chose
        to run it.

        Returns the number of entries written, for the caller's logs.
        """
        if batch_id is not None:
            batch_ids = [batch_id]
        else:
            # Every active batch of the course the student is enrolled in --
            # which is exactly what `sync_batch` does when it sweeps each
            # batch in turn. A student in two cohorts of one course gets the
            # mark in both, and changing that here would make the automatic
            # and manual paths disagree.
            batch_ids = list(
                (
                    await self.session.execute(
                        select(Enrollments.batch_id)
                        .join(Batch, Batch.id == Enrollments.batch_id)
                        .where(
                            Enrollments.student_id == student_id,
                            Enrollments.status.in_(ACTIVE_STATUSES),
                            Batch.course_id == course_id,
                            Batch.is_active.is_(True),
                        )
                    )
                ).scalars()
            )

        stats = {"created": 0, "updated": 0, "unchanged": 0, "skipped_ungraded": 0}
        for target in batch_ids:
            await self._upsert(
                student_id=student_id,
                batch_id=target,
                component_type=component_type,
                reference_id=reference_id,
                score=score,
                max_score=max_score,
                stats=stats,
            )
        return stats["created"] + stats["updated"]

    async def _upsert(
        self,
        *,
        student_id: int,
        batch_id: int,
        component_type: GradeComponentType,
        reference_id: int | None,
        score: Decimal,
        max_score: Decimal,
        stats: dict[str, int],
    ) -> None:
        existing = await self.entries.find_one(
            student_id=student_id,
            batch_id=batch_id,
            component_type=component_type,
            reference_id=reference_id,
        )

        if existing is None:
            self.session.add(
                GradeBookEntry(
                    student_id=student_id,
                    batch_id=batch_id,
                    component_type=component_type,
                    reference_id=reference_id,
                    score=score,
                    max_score=max_score,
                    weight=Decimal("1"),
                    recorded_at=datetime.now(UTC),
                )
            )
            stats["created"] += 1
            return

        if (
            Decimal(str(existing.score)) == score
            and Decimal(str(existing.max_score)) == max_score
        ):
            stats["unchanged"] += 1
            return

        existing.score = score
        existing.max_score = max_score
        existing.recorded_at = datetime.now(UTC)
        stats["updated"] += 1

    async def _sync_assignments(
        self, batch: Batch, students: set[int], stats: dict[str, int]
    ) -> None:
        stmt = (
            select(AssignmentSubmission, Assignment)
            .join(Assignment, Assignment.id == AssignmentSubmission.assignment_id)
            .where(
                Assignment.course_id == batch.course_id,
                AssignmentSubmission.student_id.in_(students),
            )
        )
        for submission, assignment in (await self.session.execute(stmt)).all():
            if submission.grade is None:
                # Ungraded work is absent from the grade book, not a zero --
                # a zero would drag the student's average down for work the
                # tutor simply has not marked yet.
                stats["skipped_ungraded"] += 1
                continue
            await self._upsert(
                student_id=submission.student_id,
                batch_id=batch.id,
                component_type=GradeComponentType.ASSIGNMENT,
                reference_id=submission.id,
                score=Decimal(str(submission.grade)),
                max_score=Decimal(str(assignment.max_score)),
                stats=stats,
            )

    async def _sync_quizzes(
        self, batch: Batch, students: set[int], stats: dict[str, int]
    ) -> None:
        stmt = (
            select(QuizAttempt)
            .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
            .where(
                Quiz.course_id == batch.course_id,
                QuizAttempt.student_id.in_(students),
                QuizAttempt.finished_at.is_not(None),
            )
        )
        for attempt in (await self.session.execute(stmt)).scalars().all():
            if attempt.score is None:
                # Still awaiting manual marking of a short-answer or essay.
                stats["skipped_ungraded"] += 1
                continue
            # `QuizAttempt.score` is already a percentage (see quiz_service),
            # so the denominator is 100 rather than the quiz's raw points.
            await self._upsert(
                student_id=attempt.student_id,
                batch_id=batch.id,
                component_type=GradeComponentType.QUIZ,
                reference_id=attempt.id,
                score=Decimal(str(attempt.score)),
                max_score=_HUNDRED,
                stats=stats,
            )

    async def _sync_exams(
        self, batch: Batch, students: set[int], stats: dict[str, int]
    ) -> None:
        stmt = (
            select(ExamResult, Exam)
            .join(Exam, Exam.id == ExamResult.exam_id)
            .where(
                ExamResult.student_id.in_(students),
                (Exam.batch_id == batch.id) | (Exam.course_id == batch.course_id),
            )
        )
        for result, exam in (await self.session.execute(stmt)).all():
            if result.marks_obtained is None:
                stats["skipped_ungraded"] += 1
                continue
            await self._upsert(
                student_id=result.student_id,
                batch_id=batch.id,
                component_type=GradeComponentType.FINAL_EXAM,
                reference_id=result.id,
                score=Decimal(str(result.marks_obtained)),
                max_score=Decimal(str(exam.total_marks)),
                stats=stats,
            )

    async def _sync_attendance(
        self, batch: Batch, students: set[int], stats: dict[str, int]
    ) -> None:
        """One entry per student, summarising the whole batch.

        Attendance has no single source row to key on, so this is the
        reference-less component the second partial unique index exists for.
        Excused absences leave the denominator, matching the rate reported by
        `/attendance/summary` -- two different numbers for the same thing
        would be worse than either.
        """
        stmt = (
            select(Attendance.student_id, Attendance.status, func.count())
            .join(BatchSession, BatchSession.id == Attendance.session_id)
            .where(
                BatchSession.batch_id == batch.id,
                Attendance.student_id.in_(students),
            )
            .group_by(Attendance.student_id, Attendance.status)
        )
        tally: dict[int, dict[AttendanceStatus, int]] = {}
        for student_id, status, count in (await self.session.execute(stmt)).all():
            tally.setdefault(student_id, {})[status] = int(count)

        for student_id, counts in tally.items():
            present = counts.get(AttendanceStatus.PRESENT, 0)
            late = counts.get(AttendanceStatus.LATE, 0)
            absent = counts.get(AttendanceStatus.ABSENT, 0)
            excused = counts.get(AttendanceStatus.EXCUSED, 0)
            assessable = present + late + absent
            if assessable == 0:
                # Only excused absences: no meaningful attendance figure, and
                # a zero would be a fabricated penalty.
                stats["skipped_ungraded"] += 1
                continue
            await self._upsert(
                student_id=student_id,
                batch_id=batch.id,
                component_type=GradeComponentType.ATTENDANCE,
                reference_id=None,
                score=Decimal(present + late),
                max_score=Decimal(assessable),
                stats=stats,
            )

    # -- summary -------------------------------------------------------------

    async def summarise(
        self, *, batch_public_id: uuid.UUID, student_public_id: uuid.UUID, actor: User
    ) -> dict:
        batch = await self.batches.get(batch_public_id, actor=actor)
        student = await self._load_user(student_public_id)

        visibility = await self.scopes.enrollment_visibility(actor)
        if not visibility.unrestricted:
            reachable = (
                batch.id in visibility.taught_batch_ids
                or student.id in visibility.cared_for_student_ids
            )
            if not reachable:
                raise NotFoundError("Grade book not found.")

        rows = await self.entries.for_student_in_batch(
            student_id=student.id, batch_id=batch.id
        )
        components, weighted = self._aggregate(rows)

        band = await self.bands.for_percentage(weighted) if weighted is not None else None
        return {
            "student_id": student.public_id,
            "student_username": visible_username(student),
            "batch_id": batch.public_id,
            "batch_code": batch.batch_code,
            "components": components,
            "weighted_percentage": weighted,
            "letter_grade": band.letter_grade if band else None,
            "gpa_points": band.gpa_points if band else None,
        }

    @staticmethod
    def _aggregate(
        rows: Sequence[GradeBookEntry],
    ) -> tuple[list[dict], Decimal | None]:
        """Group entries by component, then take a weighted mean of the
        component percentages.

        Averaging *component percentages* rather than pooling all raw points
        stops one component with large numbers (a 100-mark exam) from
        drowning out another with small ones (a 10-point quiz) purely because
        of the scale its marks happen to use.
        """
        by_component: dict[GradeComponentType, list[GradeBookEntry]] = {}
        for row in rows:
            by_component.setdefault(row.component_type, []).append(row)

        components: list[dict] = []
        weighted_sum = _ZERO
        weight_total = _ZERO

        for component, entries in by_component.items():
            earned = sum((Decimal(str(e.score)) for e in entries), _ZERO)
            available = sum((Decimal(str(e.max_score)) for e in entries), _ZERO)
            weight = max((Decimal(str(e.weight)) for e in entries), default=Decimal("1"))

            percentage = (
                (earned / available * _HUNDRED).quantize(Decimal("0.01"))
                if available > 0
                else None
            )
            components.append(
                {
                    "component_type": component,
                    "entries": len(entries),
                    "earned": earned,
                    "available": available,
                    "percentage": percentage,
                    "weight": weight,
                }
            )
            if percentage is not None:
                weighted_sum += percentage * weight
                weight_total += weight

        components.sort(key=lambda c: c["component_type"].value)
        weighted = (
            (weighted_sum / weight_total).quantize(Decimal("0.01"))
            if weight_total > 0
            else None
        )
        return components, weighted

    # -- transcripts ---------------------------------------------------------

    async def list_transcripts(
        self,
        params: PageParams,
        *,
        actor: User,
        batch_public_id: uuid.UUID | None = None,
        student_public_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[Transcript], int]:
        batch_id = None
        if batch_public_id is not None:
            batch_id = (await self.batches.get(batch_public_id, actor=actor)).id

        student_id = None
        if student_public_id is not None:
            student_id = (await self._load_user(student_public_id)).id

        visibility = await self.scopes.enrollment_visibility(actor)
        return await self.transcripts.search(
            params,
            visibility=visibility,
            batch_id=batch_id,
            student_id=student_id,
            include_provisional=await self._can_mark(actor),
        )

    async def get_transcript(self, public_id: uuid.UUID, *, actor: User) -> Transcript:
        row = await self.transcripts.get_by_public_id_full(public_id)
        if row is None:
            raise NotFoundError("Transcript not found.")

        visibility = await self.scopes.enrollment_visibility(actor)
        if not visibility.unrestricted:
            reachable = (
                row.batch_id in visibility.taught_batch_ids
                or row.student_id in visibility.cared_for_student_ids
            )
            if not reachable:
                raise NotFoundError("Transcript not found.")

        if not row.is_final and not await self._can_mark(actor):
            raise NotFoundError("Transcript not found.")
        return row

    # Transcript *generation* deliberately does not live here any more.
    #
    # It used to: an aggregation over `gradebook_entries` at a flat weight,
    # with no publication filter -- so a draft mark could reach an official
    # document, which is precisely what §5 forbids. `TranscriptService` is now
    # the one implementation, built on the weighted engine and on
    # `PerformanceService.for_transcript`, which takes no actor and therefore
    # cannot be asked for unreleased marks. Two answers to "what is this
    # student's official result" is the duplication §45 warns about.

    # -- helpers -------------------------------------------------------------

    async def _enrolled_student_ids(self, batch_id: int) -> set[int]:
        stmt = select(Enrollments.student_id).where(
            Enrollments.batch_id == batch_id,
            Enrollments.status.in_(ACTIVE_STATUSES),
        )
        return set((await self.session.execute(stmt)).scalars().all())

    async def _can_mark(self, actor: User) -> bool:
        from backend.api.deps import resolve_permissions
        from backend.core.permissions import Action, Module, perm

        return perm(Module.GRADE, Action.UPDATE) in resolve_permissions(actor)

    async def _load_user(self, public_id: uuid.UUID) -> User:
        stmt = select(User).where(User.public_id == public_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise NotFoundError("User not found.")
        return user
