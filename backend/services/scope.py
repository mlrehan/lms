"""Row-level scoping: *which rows* a caller may reach.

Permissions answer "may this role do X at all". They cannot answer "to whom"
-- `user.read` is one grant whether it means "every student in the
institution" or "the two children I am guardian to". That second question is
answered here.

Three scoped relationships, each a join that already exists in the schema:

* **Tutor** -> students enrolled in batches they teach, via `tutor_courses`
  (course-level assignment) or `batch_sessions.tutor_id` (session-level).
* **Guardian** -> their linked students, via `student_guardians`.
* **Corporate Manager** -> their organization's employees, via
  `organization_managers` -> `organization_memberships`.

A caller holding `institution.view_all` bypasses all of it. Roles are
*additive*: someone who is both a Tutor and a Guardian sees the union of both
sets, so scoping is never a switch on "the" role -- a user has many.

**The dangerous failure mode this module is built to avoid** is an empty
scope silently meaning "no filter". `WHERE id IN ()` is trivially written as
"if we have ids, filter by them", and then a caller connected to nobody sees
everybody. :meth:`Scope.apply` makes empty mean *deny all*, explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, false, or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.permissions import Action, Module, perm
from backend.models.batch import Batch, BatchSession
from backend.models.course import TutorCourse
from backend.models.enrollment import Enrollments
from backend.models.guardian import StudentGuardian
from backend.models.identity.user import User
from backend.models.organization import OrganizationManager, OrganizationMembership
from backend.utils.enums import OrganizationMembershipStatus

_VIEW_ALL = perm(Module.INSTITUTION, Action.VIEW_ALL)

# A membership that has been REMOVED no longer grants a manager visibility of
# that person. The row is kept (historical enrollments reference the
# organization) but the individual has left the company, and their ongoing
# coursework is not the former employer's to read.
_VISIBLE_MEMBERSHIP_STATUSES = (
    OrganizationMembershipStatus.INVITED,
    OrganizationMembershipStatus.ACTIVE,
    OrganizationMembershipStatus.SUSPENDED,
)


@dataclass(frozen=True)
class Scope:
    """A set of primary keys the caller may reach, or unrestricted access."""

    unrestricted: bool
    ids: frozenset[int]

    @classmethod
    def all(cls) -> "Scope":
        return cls(unrestricted=True, ids=frozenset())

    @classmethod
    def of(cls, ids: set[int] | frozenset[int]) -> "Scope":
        return cls(unrestricted=False, ids=frozenset(ids))

    def allows(self, entity_id: int) -> bool:
        return self.unrestricted or entity_id in self.ids

    def apply(self, stmt: Select[Any], column: Any) -> Select[Any]:
        """Constrain ``stmt`` to this scope.

        An empty scope yields a provably-empty result, **not** an unfiltered
        one. Writing this as `if self.ids: stmt = stmt.where(...)` is the
        classic row-scoping bug: a guardian linked to nobody, or a manager of
        an empty organization, would fall through the `if` and be handed the
        entire table.
        """
        if self.unrestricted:
            return stmt
        if not self.ids:
            return stmt.where(false())
        return stmt.where(column.in_(self.ids))


@dataclass(frozen=True)
class EnrollmentVisibility:
    """Two different reasons an enrollment row may be yours to read.

    Enrollment visibility is deliberately *not* `visible_student_ids`. Those
    two questions differ for a Tutor: she may read the profiles of students
    she teaches, but her business is her own batches -- she has no standing
    to see that one of them is also taking Ancient History with someone
    else. A Guardian is the opposite: their ward's *whole* record is theirs
    to see, across every batch.

    So: batch-scoped for teaching, student-scoped for care, OR'd together.
    `cared_for_student_ids` therefore excludes a tutor's students on purpose
    -- they are already covered by `taught_batch_ids`, and including them
    would silently widen a tutor to every course their students take.
    """

    unrestricted: bool
    taught_batch_ids: frozenset[int]
    cared_for_student_ids: frozenset[int]

    def apply(self, stmt: Select[Any], *, batch_column: Any, student_column: Any) -> Select[Any]:
        if self.unrestricted:
            return stmt

        conditions = []
        if self.taught_batch_ids:
            conditions.append(batch_column.in_(self.taught_batch_ids))
        if self.cared_for_student_ids:
            conditions.append(student_column.in_(self.cared_for_student_ids))

        # Same discipline as `Scope.apply`: no conditions means deny all,
        # never "skip the filter".
        if not conditions:
            return stmt.where(false())
        return stmt.where(or_(*conditions))


@dataclass(frozen=True)
class AttendanceVisibility:
    """The same two-reason split as :class:`EnrollmentVisibility`, one level
    down: a tutor reaches attendance through the *sessions* she teaches, a
    guardian or manager through the *people* in their care."""

    unrestricted: bool
    taught_session_ids: frozenset[int]
    cared_for_student_ids: frozenset[int]

    def apply(self, stmt: Select[Any], *, session_column: Any, student_column: Any) -> Select[Any]:
        if self.unrestricted:
            return stmt

        conditions = []
        if self.taught_session_ids:
            conditions.append(session_column.in_(self.taught_session_ids))
        if self.cared_for_student_ids:
            conditions.append(student_column.in_(self.cared_for_student_ids))

        if not conditions:
            return stmt.where(false())
        return stmt.where(or_(*conditions))


@dataclass(frozen=True)
class WorkVisibility:
    """Visibility over a student's *work* -- assignment submissions, quiz
    attempts, exam results.

    The same two-reason split as :class:`EnrollmentVisibility`, but keyed on
    course rather than batch, because assignments and quizzes hang off
    `course_id`. A tutor reaches work through the courses she teaches; a
    guardian or corporate manager reaches it through the people in their
    care. `cared_for_student_ids` again excludes a tutor's students on
    purpose -- they are covered by the course side, and including them would
    widen a tutor to her students' work in courses she has nothing to do
    with.
    """

    unrestricted: bool
    taught_course_ids: frozenset[int]
    cared_for_student_ids: frozenset[int]

    def apply(self, stmt: Select[Any], *, course_column: Any, student_column: Any) -> Select[Any]:
        if self.unrestricted:
            return stmt

        conditions = []
        if self.taught_course_ids:
            conditions.append(course_column.in_(self.taught_course_ids))
        if self.cared_for_student_ids:
            conditions.append(student_column.in_(self.cared_for_student_ids))

        if not conditions:
            return stmt.where(false())
        return stmt.where(or_(*conditions))


class ScopeResolver:
    """Computes what a given user may see.

    Queries only run for the relationships the caller actually participates
    in: a plain Administrator short-circuits on `institution.view_all` and
    issues none at all.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _held_permissions(user: User) -> set[str]:
        return {
            p.name
            for role in (user.roles or [])
            for p in (role.permissions or [])
        }

    @classmethod
    def held_permissions(cls, user: User) -> set[str]:
        """The caller's flattened permission names.

        Public because the dashboard decides *per panel* whether the caller
        may see a tile, and importing the API layer's `resolve_permissions`
        into a service would point the dependency the wrong way. Same walk
        over already-loaded objects, no extra queries.
        """
        return cls._held_permissions(user)

    @classmethod
    def is_unrestricted(cls, user: User) -> bool:
        return _VIEW_ALL in cls._held_permissions(user)

    # -- students ------------------------------------------------------------

    async def visible_student_ids(self, user: User) -> Scope:
        """Which people's records this user may read.

        Always includes the caller themselves: every role can see its own
        profile, and excluding it would make `/users/{my own id}` a 404.
        """
        if self.is_unrestricted(user):
            return Scope.all()

        visible: set[int] = {user.id}
        visible |= await self._guardian_student_ids(user.id)
        visible |= await self._managed_employee_ids(user.id)
        visible |= await self._taught_student_ids(user.id)
        return Scope.of(visible)

    async def _guardian_student_ids(self, guardian_id: int) -> set[int]:
        stmt = select(StudentGuardian.student_id).where(
            StudentGuardian.guardian_id == guardian_id
        )
        return set((await self.session.execute(stmt)).scalars().all())

    async def _managed_employee_ids(self, manager_user_id: int) -> set[int]:
        managed_orgs = select(OrganizationManager.organization_id).where(
            OrganizationManager.user_id == manager_user_id,
            OrganizationManager.is_active.is_(True),
        )
        stmt = select(OrganizationMembership.user_id).where(
            OrganizationMembership.organization_id.in_(managed_orgs),
            OrganizationMembership.status.in_(_VISIBLE_MEMBERSHIP_STATUSES),
        )
        return set((await self.session.execute(stmt)).scalars().all())

    async def _taught_student_ids(self, tutor_id: int) -> set[int]:
        """Students enrolled in any batch this tutor teaches.

        Enrollment status is not filtered: a tutor must still be able to see
        a student who has dropped or completed, in order to read back the
        attendance and grades recorded while they were active.
        """
        batch_ids = await self._taught_batch_ids(tutor_id)
        if not batch_ids:
            return set()

        stmt = select(Enrollments.student_id).where(Enrollments.batch_id.in_(batch_ids))
        return set((await self.session.execute(stmt)).scalars().all())

    # -- teaching assignments ------------------------------------------------

    async def _taught_batch_ids(self, tutor_id: int) -> set[int]:
        """Batches a tutor reaches, by either route.

        Two independent routes exist in the schema and both count:
        `tutor_courses` assigns a tutor to a *course* (and therefore to all
        of its batches), while `batch_sessions.tutor_id` assigns them to
        individual sessions -- which is how a stand-in covering one class
        gets access without being made a course tutor.
        """
        via_course = select(Batch.id).where(
            Batch.course_id.in_(
                select(TutorCourse.course_id).where(TutorCourse.tutor_id == tutor_id)
            )
        )
        via_session = select(BatchSession.batch_id).where(BatchSession.tutor_id == tutor_id)

        rows = await self.session.execute(union(via_course, via_session))
        return {row[0] for row in rows.all()}

    async def visible_batch_ids(self, user: User) -> Scope:
        """Batches this user may reach.

        Built from :meth:`enrollment_visibility`, not from
        :meth:`visible_student_ids`, and the difference is a real leak that
        the naive version caused: a tutor may read the *profiles* of the
        students she teaches, so widening from that set pulled in every batch
        any of them happened to be enrolled in -- handing her a batch of a
        course she has nothing to do with, because one of her students also
        studies history.

        The correct union is: batches I teach, plus batches the people *in my
        care* (myself, my wards, my employees) are enrolled in.
        """
        if self.is_unrestricted(user):
            return Scope.all()

        visibility = await self.enrollment_visibility(user)
        batches = set(visibility.taught_batch_ids)

        if visibility.cared_for_student_ids:
            stmt = select(Enrollments.batch_id).where(
                Enrollments.student_id.in_(visibility.cared_for_student_ids)
            )
            batches |= set((await self.session.execute(stmt)).scalars().all())

        return Scope.of(batches)

    async def visible_course_ids(self, user: User) -> Scope:
        """Courses whose *management* surface this user may reach.

        Note this is not the course *catalogue*: browsing what is on offer is
        an ordinary `course.read` matter and is not scoped, or a Corporate
        Manager could never find a course to enrol employees into. This
        answers the narrower question of which courses' internals -- rosters,
        submissions, attendance -- are the caller's business.
        """
        if self.is_unrestricted(user):
            return Scope.all()

        courses = set(
            (
                await self.session.execute(
                    select(TutorCourse.course_id).where(TutorCourse.tutor_id == user.id)
                )
            )
            .scalars()
            .all()
        )

        batch_scope = await self.visible_batch_ids(user)
        if not batch_scope.unrestricted and batch_scope.ids:
            stmt = select(Batch.course_id).where(Batch.id.in_(batch_scope.ids))
            courses |= set((await self.session.execute(stmt)).scalars().all())

        return Scope.of(courses)

    # -- enrollments ---------------------------------------------------------

    async def enrollment_visibility(self, user: User) -> EnrollmentVisibility:
        if self.is_unrestricted(user):
            return EnrollmentVisibility(True, frozenset(), frozenset())

        taught = await self._taught_batch_ids(user.id)
        cared_for = (
            {user.id}
            | await self._guardian_student_ids(user.id)
            | await self._managed_employee_ids(user.id)
        )
        return EnrollmentVisibility(False, frozenset(taught), frozenset(cared_for))

    async def attendance_visibility(self, user: User) -> AttendanceVisibility:
        if self.is_unrestricted(user):
            return AttendanceVisibility(True, frozenset(), frozenset())

        enrollment = await self.enrollment_visibility(user)

        taught_sessions: set[int] = set()
        if enrollment.taught_batch_ids:
            stmt = select(BatchSession.id).where(
                BatchSession.batch_id.in_(enrollment.taught_batch_ids)
            )
            taught_sessions = set((await self.session.execute(stmt)).scalars().all())

        return AttendanceVisibility(
            False, frozenset(taught_sessions), enrollment.cared_for_student_ids
        )

    async def work_visibility(self, user: User) -> WorkVisibility:
        """Which assignment submissions / quiz attempts / exam results this
        user may read."""
        if self.is_unrestricted(user):
            return WorkVisibility(True, frozenset(), frozenset())

        enrollment = await self.enrollment_visibility(user)
        taught_courses = await self.teaching_course_ids(user, enrollment=enrollment)

        return WorkVisibility(
            False, frozenset(taught_courses), enrollment.cared_for_student_ids
        )

    async def teaching_course_ids(
        self, user: User, *, enrollment: "EnrollmentVisibility | None" = None
    ) -> set[int]:
        """Every course this person teaches, by either route.

        Two ways to teach a course and both count:

        * a direct `tutor_courses` assignment -- tutor of record;
        * taking sessions for one of its batches, which is how a stand-in or a
          second tutor is attached without being put on the course itself.

        Keeping these apart is what made the catalogue scope wrong on its
        first pass: restricted to `tutor_courses` alone, a tutor taking three
        batches of Data Analysis could see the batches, the students and the
        timetable, and not the course they belong to -- so they could not set
        an assignment for a class they teach every week.

        `enrollment` is accepted so a caller that already resolved it does not
        pay for it twice.
        """
        courses = await self.tutor_course_ids(user)
        enrollment = enrollment or await self.enrollment_visibility(user)
        if enrollment.taught_batch_ids:
            stmt = select(Batch.course_id).where(Batch.id.in_(enrollment.taught_batch_ids))
            courses |= set((await self.session.execute(stmt)).scalars().all())
        return courses

    async def visible_session_ids(self, user: User) -> Scope:
        """Sessions this user may reach -- those belonging to a batch they
        can already see."""
        if self.is_unrestricted(user):
            return Scope.all()

        batch_scope = await self.visible_batch_ids(user)
        if not batch_scope.ids:
            return Scope.of(set())

        stmt = select(BatchSession.id).where(BatchSession.batch_id.in_(batch_scope.ids))
        return Scope.of(set((await self.session.execute(stmt)).scalars().all()))

    async def tutor_course_ids(self, user: User) -> set[int]:
        """Courses this user is assigned to teach, by direct assignment only.

        Used for course *visibility* rather than scoping: an assigned tutor
        can see their own course while it is still a DRAFT, which nobody
        else outside the administration can.
        """
        stmt = select(TutorCourse.course_id).where(TutorCourse.tutor_id == user.id)
        return set((await self.session.execute(stmt)).scalars().all())

    # -- organizations -------------------------------------------------------

    async def visible_organization_ids(self, user: User) -> Scope:
        if self.is_unrestricted(user):
            return Scope.all()

        stmt = select(OrganizationManager.organization_id).where(
            OrganizationManager.user_id == user.id,
            OrganizationManager.is_active.is_(True),
        )
        return Scope.of(set((await self.session.execute(stmt)).scalars().all()))
