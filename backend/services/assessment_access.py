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

from sqlalchemy import Select, and_, false, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.batch import Batch
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

    def apply(
        self, stmt: Select[Any], *, course_column: Any, creator_column: Any, deleted_column: Any
    ) -> Select[Any]:
        stmt = stmt.where(deleted_column.is_(None))
        if self.unrestricted:
            return stmt
        stmt = stmt.where(course_column.in_(self.course_ids)) if self.course_ids else stmt.where(false())
        return self.exclude_colleagues(stmt, course_column=course_column, creator_column=creator_column)

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
        )

    async def may_read(self, row: Any, actor: User) -> bool:
        """Whether one already-loaded assessment row is visible to `actor`."""
        if row.deleted_at is not None:
            return False
        vis = await self.visibility(actor)
        if vis.unrestricted:
            return True
        if row.course_id not in (vis.course_ids or frozenset()):
            return False
        if row.course_id not in vis.isolated_course_ids:
            return True
        return not await self.is_colleagues(row.created_by, actor.id)

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

    @staticmethod
    def may_manage(row: Any, actor: User) -> bool:
        """Edit, delete or send for review: the author, or an unrestricted caller."""
        if ScopeResolver.is_unrestricted(actor):
            return True
        return row.created_by is not None and row.created_by == actor.id
