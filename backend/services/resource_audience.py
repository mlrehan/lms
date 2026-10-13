"""Who a person may share a file with, and what they are told about them.

Two questions, deliberately answered in one place:

* **May this share happen at all?** `allowed_ids` is the rule, and `resolve`
  is the gate every write goes through. A picker that offers the right people
  is a convenience; the server refusing the wrong ones is the control.
* **Which person is this?** A tutor choosing who to send a lecture sheet to is
  looking at a list of names, several of which repeat across cohorts. Without
  the batch and the course beside the name, picking the right Sarah is
  guesswork -- and the failure mode of guessing is handing a file to a class
  that should not have it.

The rule:

* **Administrators and the Super Admin** may share with anybody.
* A **tutor** may share with the administrators, with the students in the
  batches they teach, and with those students' guardians. Nobody else: not
  another tutor, not a colleague's class, and not a corporate manager who
  happens to employ somebody they teach.
* Everyone else may not share at all, which is already true of the permission
  (`resource.update`) and is restated here so this file answers the question
  on its own.

**Colleagues are deliberately not in that list.** A tutor may still *hold*
staff-only material (`resource.view_restricted`) and may pass it to an
administrator, but not sideways to another tutor: who sees a class's material
is a decision for the people who run the institution, not a courtesy between
peers.

**No email address, and no login name, ever leaves this module** -- in this
deployment the login name usually *is* the email, so returning it would be the
same disclosure by another name. Candidates are matched on first and last name
for the same reason: searching by address would let a tutor confirm one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import AuthorizationError
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.guardian import StudentGuardian
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.services.scope import ScopeResolver
from backend.utils.enums import UserStatus

ADMIN_ROLES = ("SUPER_ADMIN", "ADMIN")
#: Who a tutor may send a file to besides their own students and those
#: students' guardians. Administrators only: a tutor passing material to a
#: colleague is not a workflow this institution wants, and staff-only material
#: travels upwards rather than sideways.
STAFF_ROLES = ("SUPER_ADMIN", "ADMIN")

#: What a recipient is called in the picker. The role is shown so that
#: "Sarah Wilson" and "Sarah Wilson" are distinguishable when one is a tutor.
_ROLE_LABEL = {
    "SUPER_ADMIN": "Administrator",
    "ADMIN": "Administrator",
    "TUTOR": "Tutor",
    "STUDENT": "Student",
    "GUARDIAN": "Guardian",
    "CORPORATE_MANAGER": "Manager",
}
_ROLE_ORDER = ("SUPER_ADMIN", "ADMIN", "TUTOR", "CORPORATE_MANAGER", "GUARDIAN", "STUDENT")

#: A person in many cohorts would otherwise push the list sideways. Three is
#: enough to identify somebody; the rest are summarised.
MAX_CONTEXT = 3

_REFUSAL = (
    "You can only share with your administrators, the students you teach and "
    "their guardians."
)


@dataclass(frozen=True)
class Placement:
    """One cohort a candidate belongs to, from the sharer's point of view."""

    batch_code: str | None
    course_title: str | None


@dataclass(frozen=True)
class ShareCandidate:
    public_id: uuid.UUID
    name: str
    role: str
    #: The cohorts this person is in -- enrolled, for a student; taught, for a
    #: tutor. Empty for staff, who belong to no cohort.
    placements: tuple[Placement, ...]
    #: How a guardian reaches this audience: "Guardian of Jane Doe". A
    #: guardian's own name says nothing about which class they are connected
    #: to, which is the one thing the sharer needs to know.
    relation: str | None = None
    #: True when more cohorts exist than `placements` shows.
    more_placements: int = 0


def display_name(user: User) -> str:
    """A person's name, never their login name.

    Falling back to `username` -- which every other directory in this codebase
    does -- would print an email address for anyone with no name recorded, in
    the one list that must not contain one. A blank-named account shows as
    "Unnamed account" instead, which is a data problem the administrator can
    see and fix.
    """
    return " ".join(p for p in (user.first_name, user.last_name) if p) or "Unnamed account"


def role_label(user: User) -> str:
    names = {r.name for r in (user.roles or [])}
    for name in _ROLE_ORDER:
        if name in names:
            return _ROLE_LABEL[name]
    return "Member"


class ResourceShareAudience:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.scopes = ScopeResolver(session)

    # -- the rule ------------------------------------------------------------

    async def _staff_ids(self) -> set[int]:
        rows = await self.session.execute(
            select(User.id)
            .join(User.roles)
            .where(Role.name.in_(STAFF_ROLES), User.status == UserStatus.ACTIVE)
        )
        return {r for (r,) in rows.all()}

    async def _taught_student_ids(self, batch_ids: set[int]) -> set[int]:
        if not batch_ids:
            return set()
        rows = await self.session.execute(
            select(distinct(Enrollments.student_id)).where(Enrollments.batch_id.in_(batch_ids))
        )
        return {r for (r,) in rows.all()}

    async def _guardians_of(self, student_ids: set[int]) -> set[int]:
        if not student_ids:
            return set()
        rows = await self.session.execute(
            select(distinct(StudentGuardian.guardian_id)).where(
                StudentGuardian.student_id.in_(student_ids)
            )
        )
        return {r for (r,) in rows.all()}

    async def allowed_ids(self, actor: User) -> set[int] | None:
        """The ids `actor` may share with; `None` means everybody."""
        if ScopeResolver.is_unrestricted(actor):
            return None

        # Colleagues first, and unconditionally. A tutor of record who has not
        # yet been given a session teaches nobody by this system's definition
        # (`_taught_batch_ids` reads sessions, not course ownership) -- but
        # they are still staff, and refusing them the ability to send a file to
        # an administrator would be a lockout, not a safeguard.
        allowed = await self._staff_ids()

        taught_batches = (await self.scopes.enrollment_visibility(actor)).taught_batch_ids
        if taught_batches:
            students = await self._taught_student_ids(set(taught_batches))
            allowed |= students | await self._guardians_of(students)

        allowed.discard(actor.id)
        return allowed

    # -- the directory -------------------------------------------------------

    async def _placements(
        self, user_ids: set[int], *, batch_scope: set[int] | None
    ) -> dict[int, list[Placement]]:
        """Which cohorts each candidate belongs to.

        `batch_scope` narrows it to the sharer's own batches. For a tutor that
        matters twice over: a student's other cohorts are none of their
        business, and showing them would bury the one line that identifies the
        student *in this tutor's class*.
        """
        if not user_ids:
            return {}

        found: dict[int, list[Placement]] = {}

        def add(person_id: int, code: str | None, title: str | None) -> None:
            seen = found.setdefault(person_id, [])
            place = Placement(batch_code=code, course_title=title)
            if place not in seen:
                seen.append(place)

        enrolled = (
            select(Enrollments.student_id, Batch.batch_code, Course.title)
            .join(Batch, Batch.id == Enrollments.batch_id)
            .join(Course, Course.id == Batch.course_id, isouter=True)
            .where(Enrollments.student_id.in_(user_ids))
        )
        taught = (
            select(distinct(BatchSession.tutor_id), Batch.batch_code, Course.title)
            .join(Batch, Batch.id == BatchSession.batch_id)
            .join(Course, Course.id == Batch.course_id, isouter=True)
            .where(BatchSession.tutor_id.in_(user_ids))
        )
        if batch_scope is not None:
            enrolled = enrolled.where(Enrollments.batch_id.in_(batch_scope))
            taught = taught.where(BatchSession.batch_id.in_(batch_scope))

        for stmt in (enrolled, taught):
            for person_id, code, title in (await self.session.execute(stmt)).all():
                add(person_id, code, title)
        return found

    async def _relations(
        self, guardian_ids: set[int], *, student_ids: set[int] | None
    ) -> dict[int, tuple[str, int]]:
        """`{guardian_id: ("Guardian of Jane Doe", student_id)}`.

        Scoped to the students in the sharer's audience, so a guardian who also
        looks after somebody in a colleague's class is described by the ward
        the sharer actually teaches.
        """
        if not guardian_ids:
            return {}
        stmt = (
            select(StudentGuardian.guardian_id, User.first_name, User.last_name, User.id)
            .join(User, User.id == StudentGuardian.student_id)
            .where(StudentGuardian.guardian_id.in_(guardian_ids))
            .order_by(StudentGuardian.is_primary.desc(), StudentGuardian.id)
        )
        if student_ids is not None:
            stmt = stmt.where(StudentGuardian.student_id.in_(student_ids))

        found: dict[int, tuple[str, int]] = {}
        for guardian_id, first, last, student_id in (await self.session.execute(stmt)).all():
            if guardian_id in found:
                continue  # the primary ward, or the earliest link, is enough
            ward = " ".join(p for p in (first, last) if p) or "a student"
            found[guardian_id] = (f"Guardian of {ward}", student_id)
        return found

    async def search(
        self, actor: User, *, query: str | None = None, limit: int = 20, offset: int = 0
    ) -> list[ShareCandidate]:
        allowed = await self.allowed_ids(actor)
        if allowed is not None and not allowed:
            return []

        stmt = select(User).where(User.status == UserStatus.ACTIVE, User.id != actor.id)
        if allowed is not None:
            stmt = stmt.where(User.id.in_(allowed))

        term = (query or "").strip().lower()
        if term:
            like = f"%{term}%"
            # Names only -- see the module docstring. Matching the login name
            # would turn this box into an address checker.
            full = func.lower(func.concat_ws(" ", User.first_name, User.last_name))
            stmt = stmt.where(
                or_(
                    full.like(like),
                    func.lower(User.first_name).like(like),
                    func.lower(User.last_name).like(like),
                )
            )

        stmt = stmt.order_by(User.first_name, User.last_name, User.id).offset(offset).limit(limit)
        people = list((await self.session.execute(stmt)).scalars().unique().all())
        if not people:
            return []

        # An administrator sees every cohort a person is in; a tutor sees only
        # the ones they teach, which is what makes the line identifying.
        batch_scope: set[int] | None = None
        audience_students: set[int] | None = None
        if allowed is not None:
            taught = set((await self.scopes.enrollment_visibility(actor)).taught_batch_ids)
            batch_scope = taught
            audience_students = await self._taught_student_ids(taught)

        ids = {p.id for p in people}
        placements = await self._placements(ids, batch_scope=batch_scope)
        relations = await self._relations(ids, student_ids=audience_students)

        # A guardian is in no cohort of their own, so their ward's one is
        # shown instead -- that is the cohort the sharer recognises.
        ward_ids = {student_id for _, student_id in relations.values()}
        ward_places = await self._placements(ward_ids, batch_scope=batch_scope)

        candidates: list[ShareCandidate] = []
        for person in people:
            relation = relations.get(person.id)
            places = placements.get(person.id) or []
            if not places and relation is not None:
                places = ward_places.get(relation[1]) or []
            candidates.append(
                ShareCandidate(
                    public_id=person.public_id,
                    name=display_name(person),
                    role=role_label(person),
                    placements=tuple(places[:MAX_CONTEXT]),
                    relation=relation[0] if relation else None,
                    more_placements=max(0, len(places) - MAX_CONTEXT),
                )
            )
        return candidates

    # -- the gate ------------------------------------------------------------

    async def resolve(self, actor: User, public_ids: Sequence[uuid.UUID]) -> list[User]:
        """The users behind these ids, if every one of them is in the audience.

        One message whether an id is unknown, inactive, the actor themselves or
        simply out of bounds: which of those it is would tell a tutor whether a
        given id exists, and this endpoint is reachable by every tutor on the
        platform.
        """
        wanted = list(dict.fromkeys(public_ids))
        if not wanted:
            return []

        users = list(
            (await self.session.execute(select(User).where(User.public_id.in_(wanted))))
            .scalars()
            .unique()
            .all()
        )
        allowed = await self.allowed_ids(actor)
        by_id = {u.public_id: u for u in users}

        for pid in wanted:
            person = by_id.get(pid)
            ok = (
                person is not None
                and person.status == UserStatus.ACTIVE
                and person.id != actor.id
                and (allowed is None or person.id in allowed)
            )
            if not ok:
                raise AuthorizationError(_REFUSAL)
        return [by_id[pid] for pid in wanted]
