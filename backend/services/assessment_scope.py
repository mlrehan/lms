"""Who an assessment is actually for (spec §3).

One resolver, used by assignments, quizzes and examinations. §3 says so
explicitly -- "Do not create duplicated implementations for Course, Batch, and
Session assessments" -- and the reason is not tidiness: eligibility decides who
is handed work and whose absence counts as a missing submission. Three copies of
that rule is three chances for one of them to disagree, and the disagreement
shows up as a student who never received an assignment they are later marked
down for.

**It reads three columns and does not care which table they came from.** Every
assessment type now carries `scope` + `course_id` + `batch_id` + `session_id`,
so this module takes those four values rather than a model, and the three
services hand them over identically.

---

**Session scope resolves through the batch, not through attendance.** A session
belongs to exactly one batch, so "the students of this session" means "the
students enrolled in its batch". Resolving it through the attendance register
instead would make eligibility depend on who turned up -- so a student who
missed the class would not be set the work arising from it, which is precisely
backwards.

**Only active enrolments count.** A withdrawn student is not handed new work and
does not appear in a tutor's missing-submissions list. `ACTIVE_STATUSES` is the
enrolment module's own definition, reused rather than restated.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ValidationError
from backend.models.batch import Batch, BatchSession
from backend.models.enrollment import Enrollments
from backend.repositories.enrollment import ACTIVE_STATUSES
from backend.utils.enums import AssessmentScope


@dataclass(frozen=True)
class AssessmentTarget:
    """Where an assessment is aimed, as the four values every type carries.

    A plain value object rather than a model, so one resolver serves three
    tables. Built from a row with `AssessmentTarget.of(assignment)`, or from a
    create request before any row exists.
    """

    scope: AssessmentScope
    course_id: int
    batch_id: int | None = None
    session_id: int | None = None

    @staticmethod
    def of(row: object) -> "AssessmentTarget":
        """Read the four columns off any assessment row.

        Deliberately duck-typed. The alternative -- a shared base class for
        `Assignment`, `Quiz` and `Exam` -- would be a large refactor of three
        working models to express a relationship they already express through
        having the same four columns.
        """
        return AssessmentTarget(
            scope=getattr(row, "scope"),
            course_id=getattr(row, "course_id"),
            batch_id=getattr(row, "batch_id", None),
            session_id=getattr(row, "session_id", None),
        )


def validate(target: AssessmentTarget) -> None:
    """Refuse a scope that does not match the ids it was given.

    The database has the same CHECK, and that is on purpose: this one produces
    a message a tutor can act on, and the constraint catches anything that
    reaches the table by another route -- a migration, a fixture, a script.
    Neither makes the other redundant.
    """
    if target.scope is AssessmentScope.BATCH and target.batch_id is None:
        raise ValidationError("A batch-scoped assessment needs a batch.")
    if target.scope is AssessmentScope.SESSION and target.session_id is None:
        raise ValidationError("A session-scoped assessment needs a session.")
    if target.scope is AssessmentScope.COURSE and (target.batch_id or target.session_id):
        # Not pedantry: leaving a stale batch id on a course-scoped assessment
        # is how somebody later "fixes" the scope by reading the wrong column.
        raise ValidationError(
            "A course-wide assessment cannot also name a batch or session."
        )


class AssessmentScopeResolver:
    """Turns a target into the students it applies to."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- the eligible population ---------------------------------------------

    def eligible_student_ids_stmt(self, target: AssessmentTarget) -> Select:
        """A SELECT of eligible student ids, for composing into larger queries.

        Returned as a statement rather than a list because §33 forbids loading
        every student of a large batch into memory to answer a question the
        database can answer -- a tutor's submission list joins against this
        rather than fetching a thousand ids first.
        """
        stmt = (
            select(Enrollments.student_id)
            .join(Batch, Batch.id == Enrollments.batch_id)
            .where(Enrollments.status.in_(ACTIVE_STATUSES))
        )

        if target.scope is AssessmentScope.COURSE:
            # Every active batch of the course. §3's "Students from all active
            # Batches of that Course".
            return stmt.where(Batch.course_id == target.course_id, Batch.is_active.is_(True))

        if target.scope is AssessmentScope.BATCH:
            return stmt.where(Enrollments.batch_id == target.batch_id)

        # SESSION: through the batch the session belongs to -- never through
        # the attendance register, or missing the class would excuse the work.
        return stmt.where(
            Enrollments.batch_id
            == select(BatchSession.batch_id)
            .where(BatchSession.id == target.session_id)
            .scalar_subquery()
        )

    async def eligible_student_ids(self, target: AssessmentTarget) -> set[int]:
        """The eligible population, materialised.

        For notification fan-out and small batches. Prefer the statement form
        when the ids are only needed to filter another query.
        """
        rows = await self.session.execute(self.eligible_student_ids_stmt(target))
        return set(rows.scalars().all())

    async def is_eligible(self, target: AssessmentTarget, student_id: int) -> bool:
        """One membership test, as one indexed query.

        Never "fetch the whole population and check membership in Python": for
        a course-wide assessment across several batches that is thousands of
        rows to answer a yes/no.
        """
        stmt = self.eligible_student_ids_stmt(target).where(
            Enrollments.student_id == student_id
        ).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def count_eligible(self, target: AssessmentTarget) -> int:
        from sqlalchemy import func

        inner = self.eligible_student_ids_stmt(target).subquery()
        stmt = select(func.count()).select_from(
            select(inner.c.student_id).distinct().subquery()
        )
        return int((await self.session.execute(stmt)).scalar_one())

    # -- public id lookups ---------------------------------------------------
    # Here rather than on each service: three copies of "turn a batch public_id
    # into an internal id, or say it does not exist" is three places for the
    # error message to drift, and §45 is explicit about duplicated logic.

    async def batch_id(self, public_id: "uuid.UUID | None") -> int | None:
        if public_id is None:
            return None
        found = (
            await self.session.execute(select(Batch.id).where(Batch.public_id == public_id))
        ).scalar_one_or_none()
        if found is None:
            raise ValidationError("That batch does not exist.")
        return found

    async def session_id(self, public_id: "uuid.UUID | None") -> int | None:
        if public_id is None:
            return None
        found = (
            await self.session.execute(
                select(BatchSession.id).where(BatchSession.public_id == public_id)
            )
        ).scalar_one_or_none()
        if found is None:
            raise ValidationError("That class session does not exist.")
        return found

    # -- describing it -------------------------------------------------------

    async def resolve_ids(
        self,
        *,
        scope: AssessmentScope,
        course_id: int,
        batch_id: int | None,
        session_id: int | None,
    ) -> AssessmentTarget:
        """Build a target, filling in what the scope implies.

        A session names its batch and a batch names its course, so a tutor who
        picked a session should not have to state the other two -- and if they
        do state them, they must agree. Deriving rather than trusting is what
        stops a session-scoped assessment carrying a course id from a different
        course entirely, which would put it on the wrong students' dashboards.
        """
        if scope is AssessmentScope.SESSION:
            if session_id is None:
                raise ValidationError("A session-scoped assessment needs a session.")
            row = (
                await self.session.execute(
                    select(BatchSession.batch_id, Batch.course_id)
                    .join(Batch, Batch.id == BatchSession.batch_id)
                    .where(BatchSession.id == session_id)
                )
            ).first()
            if row is None:
                raise ValidationError("That class session does not exist.")
            return AssessmentTarget(scope, course_id=row[1], batch_id=row[0], session_id=session_id)

        if scope is AssessmentScope.BATCH:
            if batch_id is None:
                raise ValidationError("A batch-scoped assessment needs a batch.")
            found = (
                await self.session.execute(
                    select(Batch.course_id).where(Batch.id == batch_id)
                )
            ).scalar_one_or_none()
            if found is None:
                raise ValidationError("That batch does not exist.")
            return AssessmentTarget(scope, course_id=found, batch_id=batch_id, session_id=None)

        # COURSE: the other two are cleared rather than carried, so the stored
        # row cannot later be misread as batch-scoped.
        return AssessmentTarget(scope, course_id=course_id, batch_id=None, session_id=None)


def describe(target: AssessmentTarget, *, batch_code: str | None = None) -> str:
    """One line a tutor can read: "Batch LMS-A" rather than "scope=BATCH"."""
    if target.scope is AssessmentScope.COURSE:
        return "Everyone on the course"
    if target.scope is AssessmentScope.BATCH:
        return f"Batch {batch_code}" if batch_code else "One batch"
    return "One class session"
