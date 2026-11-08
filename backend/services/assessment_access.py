"""Whose assessment is it: tutor isolation, ownership and withdrawal.

`ScopeResolver.visible_course_ids` answers "which courses' internals may this
person reach", and before this module that was the whole of assessment
visibility. Two tutors teaching the same course therefore saw -- and could
edit, mark and delete -- each other's assignments, quizzes and exams. This
module adds the second question every assessment read and write now asks:
*whose is it?*

The rule, in the order it is applied:

1. **Withdrawn assessments do not exist.** `deleted_at` is set by deletion;
   every listing and every lookup excludes the row, so an old link is a 404.
   The students' submissions, marks and grade-book entries stay in the
   database untouched -- nothing cascades.
2. **Unrestricted callers** (`institution.view_all`: Super Admin and
   Administrator) see everything.
3. **Everybody else** sees what `visible_course_ids` admits, minus one thing:
   in a course they reach *as a teacher*, an assessment written by **another
   tutor** is hidden. Assessments written by the administration, and old rows
   whose author is unknown (`created_by IS NULL`), stay visible to the tutors
   of that course, who need to mark them.

The exclusion is applied only in the caller's teaching capacity. A tutor who
is also enrolled on a course -- or whose ward is -- reaches it as a learner
too, and a student must see every assessment set for them whoever wrote it.
That is why `isolated_course_ids` is "courses I teach" *minus* "courses I or
the people in my care study on".

Writing is narrower than reading: only the author (or an unrestricted caller)
may edit, delete, or ask for review. Marking stays with whoever can see it --
an Administrator's exam set for a tutor's batch is the tutor's to mark.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, false, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from backend.models.batch import Batch, BatchSession
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.identity.user_role import UserRole
from backend.services.scope import ScopeResolver
from backend.utils.enums import Roles


def _tutor_ids() -> Select[Any]:
    return (
        select(UserRole.user_id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.name == Roles.TUTOR.value)
    )


def _admin_ids() -> Select[Any]:
    return (
        select(UserRole.user_id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.name.in_((Roles.SUPER_ADMIN.value, Roles.ADMIN.value)))
    )


def reaches_learner(model: Any, learner_ids: frozenset[int]) -> Any:
    """SQL: the assessment reaches an enrolment of one of these people.

    Any enrolment status and any batch, active or not: this decides what a
    learner may *read*, and a finished course's work stays in their history.
    """
    from backend.services.assessment_scope import reaches_student

    batch = aliased(Batch)
    return (
        select(Enrollments.enrollment_id)
        .join(batch, batch.id == Enrollments.batch_id)
        .where(
            Enrollments.student_id.in_(learner_ids),
            reaches_student(model, batch, Enrollments.student_id, active_batches_only=False),
        )
        .exists()
    )


def written_by_another_tutor(creator_column: Any, actor_id: int) -> Any:
    """SQL: the row's author is a tutor who is not `actor_id` and not an administrator."""
    return and_(
        creator_column.is_not(None),
        creator_column != actor_id,
        creator_column.in_(_tutor_ids()),
        creator_column.not_in(_admin_ids()),
    )


@dataclass(frozen=True)
class AssessmentVisibility:
    """Which assessment rows a caller may read. Build with `AssessmentAccess.visibility`."""

    unrestricted: bool
    actor_id: int
    #: Courses reachable at all (None = every course).
    course_ids: frozenset[int] | None
    #: Courses reached only as a teacher, where colleagues' work is hidden.
    isolated_course_ids: frozenset[int]
    #: Courses the caller teaches. On these they see the course's assessments
    #: (bar a colleague's, above); everywhere else they are a learner.
    taught_course_ids: frozenset[int] = frozenset()
    #: The caller, their wards and their employees -- whose enrolments decide
    #: what a *learner* may read.
    learner_ids: frozenset[int] = frozenset()

    def apply(
        self,
        stmt: Select[Any],
        *,
        course_column: Any,
        creator_column: Any,
        deleted_column: Any,
        model: Any = None,
    ) -> Select[Any]:
        """Narrow a query over one assessment kind to what the caller may read.

        **A learner reads what reaches them, not what their course holds.**
        With ``model`` given, an assessment on a course the caller does not
        teach is visible only when it reaches an enrolment of theirs (or of
        their ward or employee): its scope covers that enrolment's batch, and
        for named students they are one of the names. This used to be the
        course alone, so a student in one batch listed and opened work set
        for another batch of the same course -- 40 such pairs in the
        development data when it was found.

        Callers that already restrict rows another way omit ``model`` and keep
        the course rule; the three assessment listings pass it.
        """
        stmt = stmt.where(deleted_column.is_(None))
        if self.unrestricted:
            return stmt
        if model is None:
            stmt = stmt.where(course_column.in_(self.course_ids)) if self.course_ids else stmt.where(false())
            return self.exclude_colleagues(stmt, course_column=course_column, creator_column=creator_column)

        taught = and_(
            course_column.in_(self.taught_course_ids or {-1}),
            not_(
                and_(
                    course_column.in_(self.isolated_course_ids or {-1}),
                    written_by_another_tutor(creator_column, self.actor_id),
                )
            ),
        )
        if not self.learner_ids:
            return stmt.where(taught)
        return stmt.where(or_(taught, reaches_learner(model, self.learner_ids)))

    def exclude_colleagues(
        self, stmt: Select[Any], *, course_column: Any, creator_column: Any
    ) -> Select[Any]:
        """Only the isolation half -- for queries that already scope by course another way."""
        if self.unrestricted or not self.isolated_course_ids:
            return stmt
        return stmt.where(
            not_(
                and_(
                    course_column.in_(self.isolated_course_ids),
                    written_by_another_tutor(creator_column, self.actor_id),
                )
            )
        )


class AssessmentAccess:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.scopes = ScopeResolver(session)

    async def visibility(self, actor: User) -> AssessmentVisibility:
        if ScopeResolver.is_unrestricted(actor):
            return AssessmentVisibility(True, actor.id, None, frozenset())

        courses = await self.scopes.visible_course_ids(actor)
        enrollment = await self.scopes.enrollment_visibility(actor)
        taught = await self.scopes.teaching_course_ids(actor, enrollment=enrollment)
        learning: set[int] = set()
        if enrollment.cared_for_student_ids:
            learning = set(
                (
                    await self.session.execute(
                        select(Batch.course_id)
                        .join(Enrollments, Enrollments.batch_id == Batch.id)
                        .where(Enrollments.student_id.in_(enrollment.cared_for_student_ids))
                    )
                )
                .scalars()
                .all()
            )
        return AssessmentVisibility(
            False,
            actor.id,
            frozenset(courses.ids or ()),
            frozenset(taught - learning),
            taught_course_ids=frozenset(taught),
            learner_ids=frozenset(enrollment.cared_for_student_ids),
        )

    async def may_read(self, row: Any, actor: User) -> bool:
        """Whether one already-loaded assessment row is visible to `actor`.

        The listing's own predicate, asked about one row. Two implementations
        -- one for the list and one for the page it links to -- drift, and the
        drift is a student opening by URL what their list correctly hides.
        """
        if row.deleted_at is not None:
            return False
        vis = await self.visibility(actor)
        if vis.unrestricted:
            return True
        model = type(row)
        stmt = vis.apply(
            select(model.id).where(model.id == row.id),
            course_column=model.course_id,
            creator_column=model.created_by,
            deleted_column=model.deleted_at,
            model=model,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def is_colleagues(self, creator_id: int | None, actor_id: int) -> bool:
        """True when `creator_id` is another tutor's (not an administrator's) work."""
        if creator_id is None or creator_id == actor_id:
            return False
        roles = set(
            (
                await self.session.execute(
                    select(Role.name)
                    .join(UserRole, UserRole.role_id == Role.id)
                    .where(UserRole.user_id == creator_id)
                )
            )
            .scalars()
            .all()
        )
        if roles & {Roles.SUPER_ADMIN.value, Roles.ADMIN.value}:
            return False
        return Roles.TUTOR.value in roles

    async def markers_for(self, row: Any, student_id: int) -> list[int]:
        """Who should hear that `student_id` handed this assessment in.

        Its author, and -- unless the author is a tutor, whose work their
        colleagues cannot see -- the tutors teaching the batch through which
        it reaches this student. Never the student themselves.
        """
        from backend.services.assessment_scope import reaches_student

        out: list[int] = [row.created_by] if row.created_by else []
        if not await self.is_colleagues(row.created_by, -1):
            model = type(row)
            batch = aliased(Batch)
            tutors = await self.session.execute(
                select(BatchSession.tutor_id)
                .join(batch, batch.id == BatchSession.batch_id)
                .join(Enrollments, Enrollments.batch_id == batch.id)
                .where(
                    Enrollments.student_id == student_id,
                    BatchSession.tutor_id.is_not(None),
                    BatchSession.cancelled_at.is_(None),
                    select(model.id)
                    .where(model.id == row.id, reaches_student(model, batch, student_id))
                    .exists(),
                )
                .distinct()
            )
            out.extend(tutors.scalars())
        return [u for u in dict.fromkeys(out) if u != student_id]

    @staticmethod
    def may_manage(row: Any, actor: User) -> bool:
        """Edit, delete or send for review: the author, or an unrestricted caller."""
        if ScopeResolver.is_unrestricted(actor):
            return True
        return row.created_by is not None and row.created_by == actor.id
