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
from typing import Any, Sequence

from sqlalchemy import ColumnElement, Select, and_, or_, select
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
    #: For ``STUDENTS``: the assessment whose recipient rows name them
    #: (``(kind, id)``, set by `of`), or the ids themselves before any row
    #: exists (a create request).
    assessment: tuple[str, int] | None = None
    student_ids: frozenset[int] | None = None

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
            assessment=(kind_of(row), getattr(row, "id")) if getattr(row, "id", None) else None,
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
    if target.scope is AssessmentScope.STUDENTS:
        if target.batch_id or target.session_id:
            raise ValidationError(
                "An assessment for named students cannot also name a batch or session."
            )
        return
    if target.scope is AssessmentScope.COURSE and (target.batch_id or target.session_id):
        # Not pedantry: leaving a stale batch id on a course-scoped assessment
        # is how somebody later "fixes" the scope by reading the wrong column.
        raise ValidationError(
            "A course-wide assessment cannot also name a batch or session."
        )


def covers_batch(model: Any, batch: Any = Batch) -> ColumnElement[bool]:
    """True when `batch` falls inside the population `model`'s scope selects.

    **The same rule as `AssessmentScopeResolver.eligible_student_ids_stmt`,
    written once more only because the two are needed in opposite
    directions** -- that one starts from a single assessment and finds its
    students, this one starts from an assessment *row in a query* and asks
    which batches it reaches. An aggregate over hundreds of assignments cannot
    use the first without resolving each one separately, which is the N+1 §33
    forbids.

    They are kept in the same module, adjacent, because this codebase has
    already paid for the alternative: the exam service once carried its own
    copy of the eligibility join and quietly omitted `Batch.is_active`, so a
    course-wide exam put last year's closed cohort on this year's mark sheet.
    `tests/integration/test_assessment_scope.py` asserts the two agree for
    every scope, so a change to one that is not made to the other fails.

    Matching is on `scope`, never on "whichever id is non-null": a
    batch-scoped assessment also carries its course id, so the lazy version
    hands a course-wide population something set for one batch.
    """
    return or_(
        and_(
            model.scope == AssessmentScope.COURSE,
            batch.course_id == model.course_id,
            # §3: "all *active* Batches of that Course".
            batch.is_active.is_(True),
        ),
        and_(model.scope == AssessmentScope.BATCH, batch.id == model.batch_id),
        and_(
            model.scope == AssessmentScope.SESSION,
            batch.id
            == select(BatchSession.batch_id)
            .where(BatchSession.id == model.session_id)
            .scalar_subquery(),
        ),
        # Named students: any batch of the course *may* hold one of them. A
        # batch-level question ("which batches does this reach") cannot say
        # more than that; anything about a particular student must go through
        # `reaches_student`, which also checks the recipient rows.
        and_(model.scope == AssessmentScope.STUDENTS, batch.course_id == model.course_id),
    )


def kind_of(model: Any) -> str:
    """``"assignment"``, ``"quiz"`` or ``"exam"`` for a model class, alias or row."""
    from sqlalchemy import inspect as sa_inspect

    insp = sa_inspect(model, raiseerr=False)
    mapper = getattr(insp, "mapper", None) if insp is not None else None
    table = mapper.class_.__tablename__ if mapper is not None else getattr(model, "__tablename__")
    return {"assignments": "assignment", "quizzes": "quiz", "exams": "exam"}[table]


def is_recipient(model: Any, student_id: Any) -> ColumnElement[bool]:
    """SQL: `student_id` is named in this assessment's recipient rows."""
    from backend.models.assessment_links import KIND_COLUMN, AssessmentRecipient

    column = getattr(AssessmentRecipient, KIND_COLUMN[kind_of(model)])
    return (
        select(AssessmentRecipient.id)
        .where(column == model.id, AssessmentRecipient.student_id == student_id)
        .exists()
    )


def reaches_student(
    model: Any, batch: Any, student_id: Any, *, active_batches_only: bool = True
) -> ColumnElement[bool]:
    """True when the assessment reaches *this student* through *this batch*.

    The per-student form of `covers_batch`, and the one every question about a
    particular person must use: a STUDENTS-scoped assessment covers every batch
    of its course at the batch level, and only the recipient rows say which of
    those students it is actually for.

    ``active_batches_only=False`` is for **reading history**: a course-wide
    assignment does not vanish from a student's list because their batch
    finished. Setting *new* work, counting who is missing it and notifying
    keep the default, which is §3's "all active batches".
    """
    batch_rule = covers_batch(model, batch)
    if not active_batches_only:
        batch_rule = or_(
            batch_rule,
            and_(model.scope == AssessmentScope.COURSE, batch.course_id == model.course_id),
        )
    return and_(
        batch_rule,
        or_(model.scope != AssessmentScope.STUDENTS, is_recipient(model, student_id)),
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

        if target.scope is AssessmentScope.STUDENTS:
            # The named students, and only while they hold an active seat on
            # the course: a recipient who has since left is not set new work.
            stmt = stmt.where(Batch.course_id == target.course_id)
            if target.student_ids is not None:
                return stmt.where(Enrollments.student_id.in_(target.student_ids or {-1}))
            if target.assessment is None:
                raise ValidationError("An assessment for named students needs its students.")
            from backend.models.assessment_links import KIND_COLUMN, AssessmentRecipient

            kind, assessment_id = target.assessment
            named = select(AssessmentRecipient.student_id).where(
                getattr(AssessmentRecipient, KIND_COLUMN[kind]) == assessment_id
            )
            return stmt.where(Enrollments.student_id.in_(named))

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

    # -- named students (scope STUDENTS) ---------------------------------------

    #: A hand-picked group, not a cohort: anything larger is a batch or the course.
    MAX_RECIPIENTS = 500

    async def recipient_ids(
        self, course_id: int, public_ids: "Sequence[uuid.UUID] | None", *, actor: Any
    ) -> frozenset[int]:
        """Resolve the students named for a STUDENTS-scoped assessment.

        Each must hold an active seat on the course **in a class the caller may
        see the roster of** (every class for an unrestricted caller, the classes
        they teach for a tutor). One failure refuses the whole list, and the
        refusal never says which name failed or why: "not on this course" and
        "on it, in a colleague's class" must read the same, or the picker would
        become a way to find out where a student is enrolled.
        """
        from backend.models.identity.user import User
        from backend.services.scope import ScopeResolver

        wanted = list(dict.fromkeys(public_ids or ()))
        if not wanted:
            raise ValidationError("Choose at least one student.")
        if len(wanted) > self.MAX_RECIPIENTS:
            raise ValidationError(
                f"At most {self.MAX_RECIPIENTS} students can be named; set it for a batch instead."
            )
        stmt = (
            select(User.id)
            .join(Enrollments, Enrollments.student_id == User.id)
            .join(Batch, Batch.id == Enrollments.batch_id)
            .where(
                User.public_id.in_(wanted),
                Batch.course_id == course_id,
                Enrollments.status.in_(ACTIVE_STATUSES),
            )
        )
        if not ScopeResolver.is_unrestricted(actor):
            taught = (await ScopeResolver(self.session).enrollment_visibility(actor)).taught_batch_ids
            stmt = stmt.where(Batch.id.in_(taught or {-1}))
        found = frozenset((await self.session.execute(stmt.distinct())).scalars().all())
        if len(found) != len(wanted):
            raise ValidationError(
                "Every student must be enrolled on this course in a class you teach.",
                details={"named": len(wanted), "accepted": len(found)},
            )
        return found

    async def recipients_for(
        self, target: AssessmentTarget, public_ids: "Sequence[uuid.UUID] | None", *, actor: Any
    ) -> frozenset[int] | None:
        """The named students for a create request, or None for any other scope."""
        if target.scope is AssessmentScope.STUDENTS:
            if not target.course_id:
                raise ValidationError("An assessment for named students needs its course.")
            return await self.recipient_ids(target.course_id, public_ids, actor=actor)
        if public_ids:
            raise ValidationError("Students are named only when the scope is STUDENTS.")
        return None

    async def set_recipients(self, row: Any, student_ids: "frozenset[int]", *, actor_id: int) -> None:
        """Make `student_ids` exactly the recipients of `row` (insert/delete the difference)."""
        from sqlalchemy import delete

        from backend.models.assessment_links import KIND_COLUMN, AssessmentRecipient

        column_name = KIND_COLUMN[kind_of(row)]
        column = getattr(AssessmentRecipient, column_name)
        current = set(
            (
                await self.session.execute(
                    select(AssessmentRecipient.student_id).where(column == row.id)
                )
            ).scalars()
        )
        gone = current - set(student_ids)
        if gone:
            await self.session.execute(
                delete(AssessmentRecipient).where(
                    column == row.id, AssessmentRecipient.student_id.in_(gone)
                )
            )
        for student_id in sorted(set(student_ids) - current):
            self.session.add(
                AssessmentRecipient(
                    **{column_name: row.id}, student_id=student_id, added_by=actor_id
                )
            )
        await self.session.flush()

    async def recipients_of(self, row: Any) -> list[int]:
        from backend.models.assessment_links import KIND_COLUMN, AssessmentRecipient

        column = getattr(AssessmentRecipient, KIND_COLUMN[kind_of(row)])
        return list(
            (
                await self.session.execute(
                    select(AssessmentRecipient.student_id)
                    .where(column == row.id)
                    .order_by(AssessmentRecipient.student_id)
                )
            ).scalars()
        )

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
    if target.scope is AssessmentScope.STUDENTS:
        return "Chosen students"
    return "One class session"
