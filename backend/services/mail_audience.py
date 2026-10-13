"""Who may write to whom.

The rule, and the only rule:

* **Administrators and the Super Admin** may write to anybody, and anybody may write to them.
* A **tutor** may write to the students in the batches they teach.
* A **student** may write to the tutors who teach the batches they are enrolled in.
* A **guardian** or **corporate manager** may write to the tutors teaching the people in their care, **and to
  those people themselves** -- and they may write back. A manager who may read an employee's grades but cannot
  send them a message is a stranger to the one person they are actually responsible for; and without the
  return direction Reply would be refused on a message the platform had just delivered.

Everything else is refused. The relationship is read from live enrolment and session data every time, never from
anything the client sends, so a student who is dropped from a batch stops being able to write to that tutor at
once. The sender is never in their own audience.

The directory (`search`) returns *names and a role label only* -- no email address, no login name (which is
usually the email) -- so choosing a recipient discloses nothing that `core/privacy.py` withholds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import AuthorizationError
from backend.models.batch import Batch, BatchSession
from backend.models.enrollment import Enrollments
from backend.models.guardian import StudentGuardian
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.organization import ManagedStudent
from backend.services.scope import ScopeResolver
from backend.utils.enums import EnrollmentStatus, UserStatus

ADMIN_ROLES = ("SUPER_ADMIN", "ADMIN")
_LIVE = (EnrollmentStatus.PENDING, EnrollmentStatus.CONFIRMED, EnrollmentStatus.COMPLETED)
_ROLE_LABEL = {"SUPER_ADMIN": "Administrator", "ADMIN": "Administrator", "TUTOR": "Tutor", "STUDENT": "Student", "GUARDIAN": "Guardian", "CORPORATE_MANAGER": "Manager"}
_ROLE_ORDER = ("SUPER_ADMIN", "ADMIN", "TUTOR", "CORPORATE_MANAGER", "GUARDIAN", "STUDENT")

MAX_RECIPIENTS = 100


@dataclass(frozen=True)
class Person:
    public_id: object
    name: str
    role: str


def role_label(user: User) -> str:
    names = {r.name for r in (user.roles or [])}
    for name in _ROLE_ORDER:
        if name in names:
            return _ROLE_LABEL[name]
    return "Member"


def display_name(user: User) -> str:
    return " ".join(p for p in (user.first_name, user.last_name) if p) or user.username


class MailAudience:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.scopes = ScopeResolver(session)

    async def _admin_ids(self) -> set[int]:
        rows = await self.session.execute(
            select(User.id).join(User.roles).where(Role.name.in_(ADMIN_ROLES), User.status == UserStatus.ACTIVE)
        )
        return {r for (r,) in rows.all()}

    async def _care_circle(self, actor: User) -> set[int]:
        """People `actor` is personally responsible for, and people personally responsible for `actor`.

        Deliberately computed here rather than taken from `ScopeResolver`: that answers whose **data** you may
        read, and an employee being allowed to reply to their manager must not turn into the employee reading
        that manager's enrolments. Writing to somebody is a smaller permission than reading about them, so it
        gets its own, smaller query.
        """
        # The four are two pairs, and they are now the same pair twice: a
        # direct link read in both directions, so the return journey exists
        # and Reply works. The corporate half used to go out through the
        # company and back -- every employee of a company I manage, every
        # manager of a company that employs me -- which let two strangers at
        # the same large employer write to each other because a manager sat
        # between them.
        students = select(ManagedStudent.student_id).where(ManagedStudent.manager_id == actor.id)
        managers = select(ManagedStudent.manager_id).where(ManagedStudent.student_id == actor.id)
        wards = select(StudentGuardian.student_id).where(StudentGuardian.guardian_id == actor.id)
        guardians = select(StudentGuardian.guardian_id).where(StudentGuardian.student_id == actor.id)

        found: set[int] = set()
        for stmt in (students, managers, wards, guardians):
            found |= {r for (r,) in (await self.session.execute(stmt)).all()}
        return found

    async def allowed_ids(self, actor: User) -> set[int] | None:
        """The ids `actor` may write to; `None` means everybody (an administrator)."""
        if ScopeResolver.is_unrestricted(actor):
            return None

        ids = await self._admin_ids()
        vis = await self.scopes.enrollment_visibility(actor)

        if vis.taught_batch_ids:  # a tutor: the students in the batches they teach
            rows = await self.session.execute(
                select(distinct(Enrollments.student_id)).where(Enrollments.batch_id.in_(vis.taught_batch_ids), Enrollments.status.in_(_LIVE))
            )
            ids |= {r for (r,) in rows.all()}

        if vis.cared_for_student_ids:  # a student, guardian or manager: the tutors teaching them (or the people in their care)
            rows = await self.session.execute(
                select(distinct(BatchSession.tutor_id))
                .join(Batch, Batch.id == BatchSession.batch_id)
                .join(Enrollments, Enrollments.batch_id == Batch.id)
                .where(Enrollments.student_id.in_(vis.cared_for_student_ids), Enrollments.status.in_(_LIVE), BatchSession.cancelled_at.is_(None))
            )
            ids |= {r for (r,) in rows.all()}

        ids |= await self._care_circle(actor)

        ids.discard(actor.id)
        return ids

    async def search(self, actor: User, *, query: str | None, limit: int = 20) -> list[Person]:
        allowed = await self.allowed_ids(actor)
        stmt = select(User).where(User.status == UserStatus.ACTIVE, User.id != actor.id)
        if allowed is not None:
            if not allowed:
                return []
            stmt = stmt.where(User.id.in_(allowed))
        term = (query or "").strip().lower()
        if term:
            like = f"%{term}%"
            # Names only. Matching on the login name or email would let a person confirm an address by typing it.
            full = func.lower(func.concat_ws(" ", User.first_name, User.last_name))
            stmt = stmt.where(or_(full.like(like), func.lower(User.first_name).like(like), func.lower(User.last_name).like(like)))
        stmt = stmt.order_by(User.first_name, User.last_name, User.id).limit(limit)
        return [Person(public_id=u.public_id, name=display_name(u), role=role_label(u)) for u in (await self.session.execute(stmt)).scalars().unique()]

    async def resolve(self, actor: User, public_ids: Sequence[object]) -> dict[object, User]:
        """The users behind these ids, if -- and only if -- every one of them is somebody `actor` may write to."""
        if not public_ids:
            return {}
        users = list((await self.session.execute(select(User).where(User.public_id.in_(set(public_ids))))).scalars().unique())
        allowed = await self.allowed_ids(actor)
        by_id = {u.public_id: u for u in users}
        for pid in public_ids:
            u = by_id.get(pid)
            ok = u is not None and u.status == UserStatus.ACTIVE and u.id != actor.id and (allowed is None or u.id in allowed)
            if not ok:
                # One message for a missing person and a forbidden one alike: which of the two it is must not leak.
                raise AuthorizationError(
                    "You can only write to your administrators, the people you teach or are taught by, "
                    "and the people in your care."
                )
        return by_id
