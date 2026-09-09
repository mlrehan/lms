"""Audit trail queries and entity resolution (spec §19).

Two jobs. The first is ordinary: filter and page a large, append-only table.

The second is the interesting one. `audit_logs.entity_id` holds an
**internal** primary key, and it has to — the audit row outlives the row it
describes, so a public identifier copied at write time would be the only
copy of a value that no longer resolves to anything. But the internal key
must never leave the process (this project's whole ID strategy), and
"UPDATE course 47" is unreadable even where it would be safe.

So the registry below maps each audited `entity_type` to its model plus the
column that names it, and :meth:`AuditRepository.resolve_entities` turns a
page of rows into `{public_id, label}` pairs with **one query per distinct
entity type**, not one per row. A resolution that comes back empty is
expected, not an error: the course really has been deleted, and the audit
row saying so is the point.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import Select, func, or_, select

from backend.models.administration import (
    AcademicYear,
    Category,
    Department,
    Semester,
    Tag,
)
from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.audit import AuditLog
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.exam import Exam
from backend.models.gradebook import GradeBookEntry, Transcript
from backend.models.guardian import StudentGuardian
from backend.models.identity.role import Role
from backend.models.identity.token import Token
from backend.models.identity.user import User
from backend.models.messaging import CourseDiscussion, DiscussionReply, UserMessage
from backend.models.notification import Announcement
from backend.models.organization import Organization, OrganizationMembership
from backend.models.quiz import Question, Quiz, QuizAttempt
from backend.models.resource import Resource, ResourceFolder
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams


@dataclass(frozen=True)
class EntityKind:
    """How one audited `entity_type` is looked up and named."""

    model: Any
    label: Any | None = None

    @property
    def addressable(self) -> bool:
        """Whether a caller can name a row of this type by public id.

        `role` is the one registered type that cannot: roles are addressed
        by name everywhere else in this API, so their integer id is purely
        internal. It still resolves to a label; it is just not filterable,
        and the API says so rather than exposing the integer.
        """
        return hasattr(self.model, "public_id")


ENTITY_KINDS: dict[str, EntityKind] = {
    "academic_year": EntityKind(AcademicYear, AcademicYear.label),
    "announcement": EntityKind(Announcement, Announcement.title),
    "assignment": EntityKind(Assignment, Assignment.title),
    "assignment_submission": EntityKind(AssignmentSubmission),
    "batch": EntityKind(Batch, Batch.batch_code),
    "batch_session": EntityKind(BatchSession),
    "category": EntityKind(Category, Category.name),
    "course": EntityKind(Course, Course.title),
    "course_discussion": EntityKind(CourseDiscussion, CourseDiscussion.title),
    "department": EntityKind(Department, Department.name),
    "discussion_reply": EntityKind(DiscussionReply),
    "enrollment": EntityKind(Enrollments),
    "exam": EntityKind(Exam, Exam.title),
    "gradebook_entry": EntityKind(GradeBookEntry),
    "organization": EntityKind(Organization, Organization.name),
    "organization_membership": EntityKind(OrganizationMembership),
    "question": EntityKind(Question),
    "quiz": EntityKind(Quiz, Quiz.title),
    "quiz_attempt": EntityKind(QuizAttempt),
    "resource": EntityKind(Resource, Resource.name),
    "resource_folder": EntityKind(ResourceFolder, ResourceFolder.name),
    "role": EntityKind(Role, Role.name),
    "semester": EntityKind(Semester, Semester.name),
    "student_guardian": EntityKind(StudentGuardian),
    "tag": EntityKind(Tag, Tag.name),
    "token": EntityKind(Token),
    "transcript": EntityKind(Transcript),
    "user": EntityKind(User, User.username),
    "user_message": EntityKind(UserMessage, UserMessage.subject),
}

# `system_setting`, `grade_band` and `resource_permission` are audited but
# deliberately absent: the first records `entity_id=None` (its key is text and
# travels in `details`), and the other two have neither a public id nor a name
# worth resolving. An unknown type resolves to nothing rather than raising --
# an audit row for a table that has since been dropped must still be readable.

ENTITY_TYPES: list[str] = sorted(ENTITY_KINDS)
FILTERABLE_ENTITY_TYPES: list[str] = sorted(
    name for name, kind in ENTITY_KINDS.items() if kind.addressable
)


@dataclass(frozen=True)
class ResolvedEntity:
    public_id: uuid.UUID | None
    label: str | None


class AuditRepository(BaseRepository[AuditLog]):
    model = AuditLog

    def _base(self) -> Select[tuple[AuditLog]]:
        # No `selectinload(AuditLog.actor)`: that relationship is
        # `lazy="raise"` for a reason (see the model). Actor identity comes
        # from the denormalized email plus one batch id lookup.
        return select(AuditLog)

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> AuditLog | None:
        stmt = self._base().where(AuditLog.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        actions: Sequence[str] | None = None,
        actor_id: int | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        success: bool | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        query: str | None = None,
        limit_override: int | None = None,
    ) -> tuple[Sequence[AuditLog], int]:
        stmt = self._base()

        if actions:
            stmt = stmt.where(AuditLog.action.in_(actions))
        if actor_id is not None:
            stmt = stmt.where(AuditLog.actor_user_id == actor_id)
        if entity_type is not None:
            stmt = stmt.where(AuditLog.entity_type == entity_type)
        if entity_id is not None:
            stmt = stmt.where(AuditLog.entity_id == entity_id)
        if success is not None:
            stmt = stmt.where(AuditLog.success.is_(success))
        if date_from is not None:
            stmt = stmt.where(AuditLog.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(AuditLog.created_at < date_to)
        if query:
            needle = f"%{query.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(func.coalesce(AuditLog.actor_email, "")).like(needle),
                    func.lower(func.coalesce(AuditLog.ip_address, "")).like(needle),
                    func.lower(func.coalesce(AuditLog.request_id, "")).like(needle),
                )
            )

        stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())

        if limit_override is not None:
            # The export path: one bounded slab rather than a page, and the
            # total still comes from the same statement so the caller can be
            # told the file is short of the truth.
            count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
            total = int((await self.session.execute(count_stmt)).scalar_one())
            rows = (
                (await self.session.execute(stmt.limit(limit_override)))
                .scalars()
                .unique()
                .all()
            )
            return rows, total

        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def count_since(
        self, *, actions: Sequence[str], since: datetime, success: bool | None = None
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action.in_(actions), AuditLog.created_at >= since)
        )
        if success is not None:
            stmt = stmt.where(AuditLog.success.is_(success))
        return int((await self.session.execute(stmt)).scalar_one())

    # -- identity resolution -------------------------------------------------

    async def resolve_actors(self, actor_ids: set[int]) -> dict[int, tuple[uuid.UUID, str]]:
        """`{internal id: (public_id, username)}` for a whole page at once."""
        if not actor_ids:
            return {}
        stmt = select(User.id, User.public_id, User.username).where(User.id.in_(actor_ids))
        return {
            int(row[0]): (row[1], row[2]) for row in (await self.session.execute(stmt)).all()
        }

    async def resolve_entities(
        self, pairs: Sequence[tuple[str, int]]
    ) -> dict[tuple[str, int], ResolvedEntity]:
        """Resolve `(entity_type, internal id)` pairs to public id + label.

        One query per distinct *type*, not per row. Types absent from the
        registry, and ids whose row has since been deleted, simply do not
        appear in the result — the caller renders them as "no longer exists",
        which is a true statement about an audit trail rather than an error.
        """
        by_type: dict[str, set[int]] = {}
        for entity_type, entity_id in pairs:
            if entity_type in ENTITY_KINDS:
                by_type.setdefault(entity_type, set()).add(entity_id)

        resolved: dict[tuple[str, int], ResolvedEntity] = {}
        for entity_type, ids in by_type.items():
            kind = ENTITY_KINDS[entity_type]
            # The four shapes are spelled out rather than assembled, so the
            # selected columns and the unpacking below cannot drift apart.
            if kind.addressable and kind.label is not None:
                stmt = select(kind.model.id, kind.model.public_id, kind.label)
            elif kind.addressable:
                stmt = select(kind.model.id, kind.model.public_id)
            elif kind.label is not None:
                stmt = select(kind.model.id, kind.label)
            else:
                stmt = select(kind.model.id)

            stmt = stmt.where(kind.model.id.in_(ids))
            for row in (await self.session.execute(stmt)).all():
                row_id = int(row[0])
                if kind.addressable and kind.label is not None:
                    entry = ResolvedEntity(row[1], _as_label(row[2]))
                elif kind.addressable:
                    entry = ResolvedEntity(row[1], None)
                elif kind.label is not None:
                    entry = ResolvedEntity(None, _as_label(row[1]))
                else:
                    entry = ResolvedEntity(None, None)
                resolved[(entity_type, row_id)] = entry

        return resolved

    async def entity_pk(self, entity_type: str, public_id: uuid.UUID) -> int | None:
        """Public id -> internal id, for the `entity_id` filter."""
        kind = ENTITY_KINDS.get(entity_type)
        if kind is None or not kind.addressable:
            return None
        stmt = select(kind.model.id).where(kind.model.public_id == public_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return int(row) if row is not None else None


def _as_label(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:200] or None
