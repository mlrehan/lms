"""Official academic records (spec §5).

A transcript is not a view of a student's marks. It is a **statement about what
was true when it was issued**, and everything unusual about this service
follows from that:

**It stores its figures instead of deriving them.** Everywhere else in this
system a number is computed on read, because a stored copy falls out of step
(§23). Here the opposite is right: a transcript that silently restated itself
when a tutor corrected a register, or when the institution changed its
weighting policy, would invalidate a document somebody has already relied on --
a job reference, an appeal, a visa application. So the percentage, the marks,
the attendance, the grade and the per-component breakdown are written down, and
`scheme_name` records which policy produced them.

**Published marks only, structurally.** `PerformanceService.for_transcript`
takes no actor, so there is no argument anybody can get wrong. Routing this
through the ordinary actor-aware path would have been the obvious thing to do
and would have put draft marks on official documents for the Super Admin --
the very person most likely to be issuing them. §5's "Draft marks must never
appear" is enforced by the shape of the call.

**A finalised transcript is not regenerated.** Re-issuing is a deliberate act
with its own audit entry, not a side effect of somebody pressing "generate" on
a batch.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, NotFoundError
from backend.models.batch import Batch
from backend.models.enrollment import Enrollments
from backend.models.gradebook import Transcript
from backend.models.identity.user import User
from backend.repositories.enrollment import ACTIVE_STATUSES
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.performance_service import PerformanceService, StudentPerformance
from backend.services.scope import ScopeResolver

_ZERO = Decimal("0")


class TranscriptService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.performance = PerformanceService(session)
        self.scopes = ScopeResolver(session)

    # -- reading -------------------------------------------------------------

    async def for_student(
        self, *, student_id: int, batch_id: int, actor: User
    ) -> Transcript | None:
        """A student's transcript for one batch, if one has been issued.

        Scoped by `visible_student_ids`, the same rule every other academic
        read uses -- a guardian sees their ward's, a manager their employee's,
        a student their own, and nobody sees a stranger's.
        """
        await self.performance.assert_may_view(actor=actor, student_id=student_id)
        return (
            await self.session.execute(
                select(Transcript).where(
                    Transcript.student_id == student_id, Transcript.batch_id == batch_id
                )
            )
        ).scalar_one_or_none()

    async def list_for_batch(self, *, batch_id: int, actor: User) -> Sequence[Transcript]:
        rows = list(
            (
                await self.session.execute(
                    select(Transcript).where(Transcript.batch_id == batch_id)
                )
            )
            .scalars()
            .unique()
            .all()
        )
        scope = await self.scopes.visible_student_ids(actor)
        # Filtered rather than refused: a tutor opening a batch should see the
        # transcripts of their own students, not an error because somebody
        # else's is in the list.
        return [r for r in rows if scope.allows(r.student_id)]

    # -- issuing -------------------------------------------------------------

    async def generate(
        self, *, student_id: int, batch_id: int, actor: User, reissue: bool = False
    ) -> Transcript:
        """Compute and record one student's official result.

        `reissue` is required to touch a finalised transcript. Without it a
        routine "generate for this batch" would quietly rewrite records that
        have already been handed out.
        """
        batch = (
            await self.session.execute(select(Batch).where(Batch.id == batch_id))
        ).scalar_one_or_none()
        if batch is None:
            raise NotFoundError("Batch not found.")

        existing = await self._existing(student_id=student_id, batch_id=batch_id)
        if existing is not None and existing.is_final and not reissue:
            raise ConflictError(
                "This transcript has been finalised. Re-issue it explicitly if the "
                "record genuinely needs to change.",
                details={
                    "issued_at": existing.issued_at.isoformat()
                    if existing.issued_at
                    else None
                },
            )

        # Published marks only. No actor is passed, deliberately -- see this
        # module's docstring.
        result = await self.performance.for_transcript(
            student_id=student_id, batch_id=batch_id
        )
        return await self._issue(
            batch=batch,
            student_id=student_id,
            result=result,
            existing=existing,
            actor=actor,
        )

    async def _existing(self, *, student_id: int, batch_id: int) -> Transcript | None:
        return (
            await self.session.execute(
                select(Transcript).where(
                    Transcript.student_id == student_id,
                    Transcript.batch_id == batch_id,
                )
            )
        ).scalar_one_or_none()

    async def _issue(
        self,
        *,
        batch: Batch,
        student_id: int,
        result: StudentPerformance,
        existing: Transcript | None,
        actor: User,
    ) -> Transcript:
        """Write an already-computed result down, and audit it.

        Separate from `generate` so the batch run can make its skip decisions
        *before* paying for an evaluation, and still write through exactly this
        code. The earlier shape had the batch loop evaluate every student, then
        call `generate`, which evaluated them again -- twice the retrieval work
        per student, and the first of the two calls not actually deciding
        anything, so an edit to it would have been silent.
        """
        row = existing or Transcript(
            student_id=student_id,
            course_id=batch.course_id,
            batch_id=batch.id,
            generated_at=datetime.now(UTC),
        )
        self._write(row, result)
        row.generated_at = datetime.now(UTC)

        if existing is None:
            self.session.add(row)
        await self.session.flush()

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE if existing is not None else AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="transcript",
            entity_id=row.id,
            details={
                "student_id": student_id,
                "batch": batch.batch_code,
                "final_percentage": str(row.final_percentage)
                if row.final_percentage
                else None,
                "grade": row.overall_grade,
                "reissue": bool(existing is not None and existing.is_final),
                "scheme": row.scheme_name,
            },
        )
        return row

    @staticmethod
    def _write(row: Transcript, result: StudentPerformance) -> None:
        """Copy the computed result onto the record.

        `final_percentage` is only set when the engine produced one -- that is,
        when every weighted component has been assessed (§38). A transcript
        showing a mid-course standing as though it were a final result is the
        single most misleading thing this module could produce, so the column
        stays null and the document says the course is incomplete.
        """
        p = result.performance
        row.final_percentage = p.final_percentage
        row.overall_grade = p.grade
        row.gpa = p.gpa
        row.is_pass = p.is_pass
        row.scheme_name = result.scheme_name
        row.sessions_total = result.sessions_total
        row.sessions_attended = result.sessions_attended
        row.attendance_percentage = result.attendance_percentage

        # The marks behind the percentage, summed across every counted
        # component, so the document can state "620 of 700" as well as "88.6%".
        earned = sum(
            ((c.percentage or _ZERO) * c.weight_percentage / Decimal("100"))
            for c in p.components
            if c.counted
        )
        row.total_marks_earned = earned.quantize(Decimal("0.01")) if p.components else None
        row.total_marks_possible = p.assessed_weight

        # §37's breakdown, frozen. A student querying this in three years is
        # shown the arithmetic that produced their grade, not a fresh sum
        # against whatever the scheme says today.
        row.breakdown = [
            {
                "component": c.component_type.value,
                "label": c.label,
                "percentage": str(c.percentage) if c.percentage is not None else None,
                "weight": str(c.weight_percentage),
                "contribution": str(c.contribution) if c.contribution is not None else None,
                "counted": c.counted,
                "reason": c.excluded_reason or None,
            }
            for c in p.components
        ]

    async def generate_for_batch(self, *, batch_id: int, actor: User) -> dict[str, int]:
        """Issue for every actively enrolled student.

        Finalised transcripts are **skipped, not refused**: an administrator
        re-running a batch should not be blocked by the three students whose
        records are already closed, and silently rewriting them would be worse
        than either. That check comes first, before any evaluation, so a batch
        of closed records costs nothing to re-run.
        """
        batch = (
            await self.session.execute(select(Batch).where(Batch.id == batch_id))
        ).scalar_one_or_none()
        if batch is None:
            raise NotFoundError("Batch not found.")

        students = (
            (
                await self.session.execute(
                    select(Enrollments.student_id).where(
                        Enrollments.batch_id == batch_id,
                        Enrollments.status.in_(ACTIVE_STATUSES),
                    )
                )
            )
            .scalars()
            .all()
        )

        stats = {"issued": 0, "updated": 0, "skipped_final": 0, "skipped_no_marks": 0}
        for student_id in sorted(set(students)):
            existing = await self._existing(student_id=student_id, batch_id=batch_id)
            if existing is not None and existing.is_final:
                stats["skipped_final"] += 1
                continue

            try:
                result = await self.performance.for_transcript(
                    student_id=student_id, batch_id=batch_id
                )
            except NotFoundError:
                continue

            if result.performance.unconfigured or not result.performance.components:
                # No scheme, or nothing to report. Issuing an empty transcript
                # would be worse than issuing none: it looks like a student who
                # achieved nothing.
                stats["skipped_no_marks"] += 1
                continue

            await self._issue(
                batch=batch,
                student_id=student_id,
                result=result,
                existing=existing,
                actor=actor,
            )
            stats["updated" if existing is not None else "issued"] += 1

        return stats

    async def finalise(self, public_id: uuid.UUID, *, actor: User) -> Transcript:
        """Close the record and record who stood behind it (§5).

        A finalised transcript is what the institution is prepared to defend,
        so `issued_by` is not decoration -- it is the verification §5 asks for.
        """
        row = (
            await self.session.execute(
                select(Transcript).where(Transcript.public_id == public_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Transcript not found.")

        if row.final_percentage is None:
            # A course still in progress has no final result to certify, and a
            # document that certifies a mid-course standing as final is the
            # error §38 exists to prevent.
            raise ConflictError(
                "This course is not complete, so there is no final result to issue."
            )

        row.is_final = True
        row.issued_at = datetime.now(UTC)
        row.issued_by = actor.id

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="transcript",
            entity_id=row.id,
            details={"finalised": True, "grade": row.overall_grade},
        )
        return row

    async def reopen(self, public_id: uuid.UUID, *, actor: User) -> Transcript:
        """Withdraw certification so the record can be regenerated.

        `issued_at` and `issued_by` are **cleared**, not kept. Leaving them
        would say the document is still certified by somebody who has just
        withdrawn it -- and the audit row below is where the history lives, so
        nothing is lost by clearing them.
        """
        row = (
            await self.session.execute(
                select(Transcript).where(Transcript.public_id == public_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Transcript not found.")

        previous_issuer = row.issued_by
        row.is_final = False
        row.issued_at = None
        row.issued_by = None

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="transcript",
            entity_id=row.id,
            details={"finalised": False, "previously_issued_by": previous_issuer},
        )
        return row
