"""A tutor's per-session assessment of how a student took part (spec §11).

**This is the write path the engine has been waiting for.** `PRACTICAL` has been
a weighted component since the grade book was built, `PerformanceService` has
read `class_performance_marks` since the calculation engine landed, and nothing
anywhere produced a row. The consequence was not cosmetic: the default scheme
gives class performance 10% of the mark, an unassessed component is excluded
from the total rather than counted as zero (§38), and a result is only *final*
once every weighted component has been assessed -- so under the seeded scheme no
transcript could ever be completed. A decorative table made the whole of §5
unreachable.

**Who may record one.** The session's *assigned tutor*, or somebody holding
`institution.view_all` -- the academic office, correcting a record. The rule is
deliberately the same one attendance uses, because it answers the same question:
a class-performance mark is a statement about what happened in one room on one
afternoon, and the person who was in the room is the only one who can make it.
No `override` permission is invented for the office case: `recorded_by` and
`updated_by` already name whoever actually typed it, so the row says "an
administrator entered this" without a second mechanism to say so.

**Released marks only reach a student or a guardian.** A tutor's working note on
how somebody participated is not a result. The lifecycle is the same
DRAFT -> FINALIZED -> PUBLISHED that §14 gives every other mark, and
`PerformanceService` already filters on it -- this service adds the act that
moves it, not a second rule about who may see what.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.core.permissions import Action, Module, perm
from backend.models.batch import Batch, BatchSession
from backend.models.class_performance import ClassPerformanceMark
from backend.models.enrollment import Enrollments
from backend.models.identity.user import User
from backend.repositories.enrollment import ACTIVE_STATUSES
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.scope import ScopeResolver
from backend.utils.enums import ResultState

#: The eight named criteria, in the order §11 lists them and the order the grid
#: renders them. Defined once: the request schema, the validator, the response
#: and the frontend all walk this tuple, so a ninth criterion cannot be added to
#: some of them and not the others.
CRITERIA: tuple[str, ...] = (
    "participation",
    "interaction",
    "preparation",
    "practical",
    "presentation",
    "teamwork",
    "communication",
    "professionalism",
)

#: What counts as released. `FINALIZED` is included because
#: `PerformanceService` already counts it -- one definition of "released", not
#: two that can quietly disagree about whether a guardian may see a mark.
RELEASED_STATES: frozenset[ResultState] = frozenset(
    {ResultState.FINALIZED, ResultState.PUBLISHED}
)

_VIEW_ALL = perm(Module.INSTITUTION, Action.VIEW_ALL)
_WRITE_GRANTS = frozenset(
    {
        perm(Module.CLASS_PERFORMANCE, Action.CREATE),
        perm(Module.CLASS_PERFORMANCE, Action.UPDATE),
        perm(Module.CLASS_PERFORMANCE, Action.PUBLISH),
    }
)


class ClassPerformanceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.scopes = ScopeResolver(session)

    # -- authority -----------------------------------------------------------

    @staticmethod
    def may_record(actor: User, batch_session: BatchSession) -> bool:
        """The assigned tutor, or the academic office.

        Not "any tutor who teaches the batch": a colleague covering one class
        is not the person who observed the students in it, and a mark that says
        otherwise is one nobody can defend at an appeal.
        """
        if batch_session.tutor_id == actor.id:
            return True
        return _VIEW_ALL in ScopeResolver.held_permissions(actor)

    def sees_unreleased(self, actor: User) -> bool:
        """Teaching staff and the office see drafts; nobody else does.

        Keyed on holding a *write* grant rather than on a role name (§21):
        whoever may record these marks is by definition somebody whose working
        notes they are.
        """
        return bool(_WRITE_GRANTS & ScopeResolver.held_permissions(actor))

    # -- reads ---------------------------------------------------------------

    async def _session(self, public_id: uuid.UUID, *, actor: User) -> BatchSession:
        row = (
            await self.session.execute(
                select(BatchSession)
                .options(selectinload(BatchSession.batch))
                .where(BatchSession.public_id == public_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Session not found.")

        scope = await self.scopes.visible_session_ids(actor)
        if not scope.allows(row.id):
            # Reported as absent, not forbidden: a session somebody cannot see
            # must not be provable to exist.
            raise NotFoundError("Session not found.")
        return row

    async def sheet(
        self, session_public_id: uuid.UUID, *, actor: User
    ) -> tuple[BatchSession, list[User], dict[int, ClassPerformanceMark], bool]:
        """The grid a tutor fills in: the roster, plus whatever is already there.

        The roster comes from *enrollments*, not from attendance. A student who
        missed the class still gets a row -- left blank, which the engine
        excludes -- because deciding that an absence means a class-performance
        mark of zero is a policy the institution expresses through attendance
        weighting, not something this screen should assert on its own.
        """
        batch_session = await self._session(session_public_id, actor=actor)
        roster = await self._roster(batch_session.batch_id)
        rows = await self._marks_for_session(batch_session.id)

        if not self.sees_unreleased(actor):
            visible = await self.scopes.visible_student_ids(actor)
            rows = {
                sid: r
                for sid, r in rows.items()
                if r.state in RELEASED_STATES and visible.allows(sid)
            }
            roster = [u for u in roster if visible.allows(u.id)]

        return batch_session, roster, rows, self.may_record(actor, batch_session)

    async def for_student(
        self,
        *,
        student_public_id: uuid.UUID,
        batch_public_id: uuid.UUID | None,
        actor: User,
    ) -> list[ClassPerformanceMark]:
        """§37's drill-down: the marks behind one student's `PRACTICAL` line, so
        the figure can be explained rather than asserted."""
        student = await self._load_user(student_public_id)
        visible = await self.scopes.visible_student_ids(actor)
        if not visible.allows(student.id):
            raise NotFoundError("Student not found.")

        stmt = (
            select(ClassPerformanceMark)
            .options(selectinload(ClassPerformanceMark.session))
            .join(BatchSession, BatchSession.id == ClassPerformanceMark.session_id)
            .where(ClassPerformanceMark.student_id == student.id)
        )
        if batch_public_id is not None:
            stmt = stmt.join(Batch, Batch.id == BatchSession.batch_id).where(
                Batch.public_id == batch_public_id
            )

        rows = list((await self.session.execute(stmt)).scalars().unique().all())
        if not self.sees_unreleased(actor):
            rows = [r for r in rows if r.state in RELEASED_STATES]
        rows.sort(key=lambda r: r.session.session_start_time, reverse=True)
        return rows

    # -- writes --------------------------------------------------------------

    async def save(
        self,
        session_public_id: uuid.UUID,
        entries: Sequence[dict[str, Any]],
        *,
        actor: User,
        max_score: Decimal | None = None,
    ) -> list[ClassPerformanceMark]:
        """Record or correct a whole class in one call.

        Upserts on `(session_id, student_id)`: re-entering a mark corrects the
        row. A second row would double the student's class-performance
        contribution, and `uq_class_perf_session_student` would refuse it
        anyway -- this is the behaviour a tutor expects when fixing a typo.

        A **published** row is not silently amended. Somebody has already seen
        that figure, so changing it is a deliberate act: withdraw it first.
        """
        batch_session = await self._session(session_public_id, actor=actor)
        if not self.may_record(actor, batch_session):
            raise AuthorizationError(
                "Only the session's assigned tutor can record its class performance marks."
            )

        enrolled = await self._enrolled_student_ids(batch_session.batch_id)
        students = await self._resolve_students([e.get("student_id") for e in entries])
        existing = await self._marks_for_session(batch_session.id)

        # Refused names are collected and reported together: a tutor saving a
        # class of twenty wants to know which rows were rejected, not to
        # discover them one failed save at a time. Checked *before* anything is
        # written, so a refusal leaves the sheet exactly as it was.
        locked = sorted(
            str(students[e["student_id"]].public_id)
            for e in entries
            if (row := existing.get(students[e["student_id"]].id)) is not None
            and row.state == ResultState.PUBLISHED
        )
        if locked:
            raise ValidationError(
                "Some of these marks have already been released. Withdraw them before "
                "amending them.",
                details={"published_students": locked},
            )

        now = datetime.now(UTC)
        saved: list[ClassPerformanceMark] = []

        for entry in entries:
            student = students[entry["student_id"]]
            if student.id not in enrolled:
                raise ValidationError(
                    "That student is not enrolled in this batch.",
                    details={"student_id": str(student.public_id)},
                )

            row = existing.get(student.id)
            ceiling = (
                max_score
                if max_score is not None
                else (Decimal(row.max_score) if row is not None else Decimal("10"))
            )
            scores = {c: entry.get(c) for c in CRITERIA}
            self._validate(scores, entry.get("overall_score"), ceiling)

            if row is None:
                row = ClassPerformanceMark(
                    session_id=batch_session.id,
                    student_id=student.id,
                    recorded_by=actor.id,
                    recorded_at=now,
                    state=ResultState.DRAFT,
                )
                self.session.add(row)
            else:
                row.updated_by = actor.id

            for criterion, value in scores.items():
                setattr(row, criterion, value)
            row.overall_score = entry.get("overall_score")
            row.comment = entry.get("comment")
            row.custom_scores = entry.get("custom_scores")
            row.max_score = ceiling
            saved.append(row)

        await self.session.flush()

        # The response names each student. A row created a moment ago has never
        # had its `student` relationship loaded, so touching it in the response
        # mapper lazy-loads from inside the async request and raises
        # MissingGreenlet -- a 500 on every save, which is exactly what it did.
        # Re-reading with the relationship attached is the cheapest fix that
        # keeps the mapper simple; the order the caller sent is preserved.
        if saved:
            order = {row.id: i for i, row in enumerate(saved)}
            reloaded = (
                (
                    await self.session.execute(
                        select(ClassPerformanceMark)
                        .where(ClassPerformanceMark.id.in_(list(order)))
                        .options(selectinload(ClassPerformanceMark.student))
                    )
                )
                .scalars()
                .all()
            )
            saved = sorted(reloaded, key=lambda row: order[row.id])

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="class_performance",
            entity_id=batch_session.id,
            details={
                "session": str(batch_session.public_id),
                "students": len(saved),
                # An administrator entering a tutor's observations is recorded
                # as such, which is why no separate override permission exists.
                "on_behalf": batch_session.tutor_id != actor.id,
            },
        )
        return saved

    @staticmethod
    def _validate(
        scores: dict[str, Any], overall: Any, ceiling: Decimal
    ) -> None:
        """Refuse a score above the stated maximum, or below zero.

        A criterion marked 15 out of 10 is not a generous tutor, it is a typo,
        and it would inflate a weighted result somebody later has to defend.
        Checked here rather than left to the database because the ceiling is
        per-row (`max_score`), which a CHECK constraint cannot see.
        """
        for name, value in list(scores.items()) + [("overall score", overall)]:
            if value is None:
                continue
            number = Decimal(str(value))
            if number < 0 or number > ceiling:
                raise ValidationError(
                    f"{name.replace('_', ' ').capitalize()} must be between 0 and {ceiling}.",
                    details={"criterion": name, "max_score": str(ceiling)},
                )

    async def set_state(
        self,
        session_public_id: uuid.UUID,
        state: ResultState,
        *,
        actor: User,
        student_public_id: uuid.UUID | None = None,
    ) -> list[ClassPerformanceMark]:
        """Move a session's marks through the lifecycle (§14).

        Withdrawing back to `DRAFT` is the same endpoint, deliberately: a
        released mark found to be wrong has to be retractable, or the only
        remedy is a correction nobody is told about.
        """
        batch_session = await self._session(session_public_id, actor=actor)
        if not self.may_record(actor, batch_session):
            raise AuthorizationError(
                "Only the session's assigned tutor can release its class performance marks."
            )

        # `student` is eager-loaded for the same reason as in `save`: the
        # response names the student, and a lazy load here is a 500.
        stmt = select(ClassPerformanceMark).options(
            selectinload(ClassPerformanceMark.student)
        ).where(
            ClassPerformanceMark.session_id == batch_session.id
        )
        if student_public_id is not None:
            student = await self._load_user(student_public_id)
            stmt = stmt.where(ClassPerformanceMark.student_id == student.id)

        rows = list((await self.session.execute(stmt)).scalars().unique().all())
        if not rows:
            raise NotFoundError("There are no class performance marks for this session yet.")

        now = datetime.now(UTC)
        for row in rows:
            row.state = state
            row.updated_by = actor.id
            row.updated_at = now
        await self.session.flush()

        audit_service.record(
            self.session,
            # `UPDATE` with the state in `details`, matching how assignment and
            # examination publication is already recorded. A `PUBLISH` action
            # used by one service alone would mean an auditor asking "what marks
            # were released last week" has to know which module to ask about.
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="class_performance",
            entity_id=batch_session.id,
            details={
                "session": str(batch_session.public_id),
                "state": state.value,
                "marks": len(rows),
            },
        )
        return rows

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        """Remove a mark entered against the wrong student.

        Deleted rather than zeroed, because zero is itself a mark: it would be
        averaged into the student's class-performance figure and pull it down.
        The audit row is what preserves the history.
        """
        row = (
            await self.session.execute(
                select(ClassPerformanceMark)
                .options(selectinload(ClassPerformanceMark.session))
                .where(ClassPerformanceMark.public_id == public_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Class performance mark not found.")

        batch_session = await self._session(row.session.public_id, actor=actor)
        if not self.may_record(actor, batch_session):
            raise AuthorizationError(
                "Only the session's assigned tutor can remove its class performance marks."
            )

        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="class_performance",
            entity_id=row.id,
            details={
                "session": str(batch_session.public_id),
                "student_id": row.student_id,
                "state": row.state.value,
            },
        )
        await self.session.delete(row)
        await self.session.flush()

    # -- helpers -------------------------------------------------------------

    async def _marks_for_session(self, session_id: int) -> dict[int, ClassPerformanceMark]:
        return {
            r.student_id: r
            for r in (
                await self.session.execute(
                    select(ClassPerformanceMark).where(
                        ClassPerformanceMark.session_id == session_id
                    )
                )
            )
            .scalars()
            .unique()
        }

    async def _roster(self, batch_id: int) -> list[User]:
        stmt = (
            select(User)
            .join(Enrollments, Enrollments.student_id == User.id)
            .where(
                Enrollments.batch_id == batch_id,
                Enrollments.status.in_(ACTIVE_STATUSES),
            )
            .order_by(User.username)
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def _enrolled_student_ids(self, batch_id: int) -> set[int]:
        stmt = select(Enrollments.student_id).where(
            Enrollments.batch_id == batch_id,
            Enrollments.status.in_(ACTIVE_STATUSES),
        )
        return set((await self.session.execute(stmt)).scalars().all())

    async def _resolve_students(
        self, public_ids: Sequence[Any]
    ) -> dict[uuid.UUID, User]:
        ids = [p for p in public_ids if isinstance(p, uuid.UUID)]
        found = {
            u.public_id: u
            for u in (
                await self.session.execute(select(User).where(User.public_id.in_(ids)))
            )
            .scalars()
            .unique()
        }
        missing = set(ids) - set(found)
        if missing:
            raise ValidationError(
                "Unknown student(s).",
                details={"unknown_students": sorted(str(m) for m in missing)},
            )
        return found

    async def _load_user(self, public_id: uuid.UUID) -> User:
        user = (
            await self.session.execute(select(User).where(User.public_id == public_id))
        ).scalar_one_or_none()
        if user is None:
            raise NotFoundError("User not found.")
        return user

    @staticmethod
    def average(row: ClassPerformanceMark) -> Decimal | None:
        """The tutor's own figure, or the mean of the criteria they filled in.

        Delegates to the calculation engine's own function rather than
        repeating it: two answers to "what is this student's class-performance
        score" disagreeing is exactly what a single engine exists to prevent
        (§7, §23). The grid shows the same number the transcript will use.
        """
        from backend.services.performance_service import PerformanceService

        return PerformanceService._class_overall(row)
