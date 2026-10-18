"""The Super Admin's permanent-delete surface.

`PurgeService` knows how to take a row and everything beneath it out of the
database. This module decides *what may be asked of it* and *what must never
be*, and records what was done.

**Why a registry rather than any table name the caller sends.** The purge
walker is generic by design -- that is what stops it going stale. But "generic"
must not mean "any table": `countries`, `time_zones` and `system_settings` are
shared reference data that no single institution's housekeeping should be able
to delete, and a free-form table name turns one screen into unrestricted
`DELETE` across the schema. So callers name an *entity*, and the entity names
the table.

**Four protections, and each one exists because the alternative is
unrecoverable:**

* **The last active Super Admin cannot be deleted.** There is no screen that
  creates the first one -- that is bootstrap, with shell access. Deleting the
  only one locks everybody out of the permission system permanently.
* **Nobody may delete their own account.** The same reasoning in miniature, and
  it removes the one mistake somebody makes while learning what this screen
  does.
* **The permission catalogue is untouchable** (enforced in `PurgeService`):
  deleting a permission row removes the *check*, not the ability.
* **The audit trail is untouchable, and is written in the same transaction as
  the deletion.** `audit_logs` has no foreign keys, so the record survives the
  records it describes. The deletion and its evidence commit together or
  neither does.

**What this deliberately does not have, stated plainly because the absence is a
decision and not an oversight:** no second factor and no CAPTCHA. The gate is a
Super Admin session, an explicit permission, a dependency preview, and a typed
confirmation of the record count. That was the instruction; it is written here
so that whoever reads this later knows the depth of the gate rather than
assuming it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.core.logging import get_logger
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.identity.user_role import UserRole
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.purge_service import PurgePlan, PurgeService
from backend.utils.enums import Roles, UserStatus

logger = get_logger(__name__)


@dataclass(frozen=True)
class Entity:
    """One thing a Super Admin may permanently delete."""

    key: str
    table: str
    label: str
    #: The singular, because every count on this screen can be one. "1 people"
    #: and "1 records" read as a bug and make an administrator trust the figure
    #: less at exactly the moment they most need to read it carefully.
    singular: str
    #: Shown above the warning. Says what else goes, in the words of somebody
    #: who runs a college rather than somebody who reads schemas.
    consequence: str
    #: Column used for the human-readable name in the preview, if any.
    name_column: str | None = None


#: The entity list, in the order the brief gives them.
#:
#: `roles`, `permissions` and `audit_logs` are deliberately **absent and
#: explained** rather than quietly missing -- see `BLOCKED_ENTITIES`. A screen
#: that silently omits what somebody asked for teaches them the feature is
#: broken; one that says why teaches them the rule.
ENTITIES: tuple[Entity, ...] = (
    Entity("user", "users", "People", "Person", "their enrolments, submissions, marks, attendance and messages", "username"),
    Entity("batch", "batches", "Batches", "Batch", "their sessions, attendance registers and enrolments", "batch_code"),
    Entity("course", "courses", "Courses", "Course", "their batches, sessions, assignments, quizzes and exams", "title"),
    Entity("session", "batch_sessions", "Class sessions", "Class session", "their attendance registers, recordings and participation marks", "session_start_time"),
    Entity("enrollment", "enrollments", "Enrolments", "Enrolment", "the student's submissions, marks and attendance for that batch"),
    Entity("attendance", "attendances", "Attendance records", "Attendance record", "nothing else"),
    Entity("assignment", "assignments", "Assignments", "Assignment", "every submission and mark against them", "title"),
    Entity("quiz", "quizzes", "Quizzes", "Quiz", "their questions, attempts and answers", "title"),
    Entity("exam", "exams", "Examinations", "Examination", "their results and invigilator assignments", "title"),
    Entity("gradebook_entry", "gradebook_entries", "Grade book entries", "Grade book entry", "nothing else"),
    Entity("performance_mark", "class_performance_marks", "Participation marks", "Participation mark", "nothing else"),
    Entity("transcript", "transcripts", "Transcripts", "Transcript", "nothing else"),
    Entity("grading_scheme", "grading_schemes", "Grading schemes", "Grading scheme", "their components and grade bands", "name"),
    Entity("resource", "resources", "Resources", "Resource", "their versions, shares and permissions", "name"),
    Entity("announcement", "announcements", "Announcements", "Announcement", "who has read them", "title"),
    Entity("discussion", "course_discussions", "Discussions", "Discussion", "every reply", "title"),
    Entity("message", "mail_messages", "Messages", "Message", "their attachments and recipients", "subject"),
    Entity("notification", "notifications", "Notifications", "Notification", "nothing else"),
    Entity("organization", "organizations", "Organisations", "Organisation", "their memberships and manager appointments", "name"),
    Entity("guardian_link", "student_guardians", "Guardian links", "Guardian link", "nothing else"),
    Entity("manager_link", "organization_managers", "Manager appointments", "Manager appointment", "the students assigned to that manager"),
)

#: Asked for by the brief, and refused with the reason. Returned by the API
#: alongside `ENTITIES` so the screen can show them greyed out and explained.
BLOCKED_ENTITIES: tuple[tuple[str, str, str], ...] = (
    (
        "role",
        "Roles",
        "Deleting a role would strip everybody holding it of their access with no record of "
        "what they had. Change a role's permissions, or move people off it, instead.",
    ),
    (
        "permission",
        "Permissions",
        "Removing a permission does not withdraw an ability — it removes the check for one. "
        "It is the only deletion here that would grant access rather than withdraw it.",
    ),
    (
        "audit_log",
        "Audit log",
        "The audit trail is the evidence of every other deletion, this one included. It is "
        "kept deliberately independent of the records it describes.",
    ),
)

BY_KEY: dict[str, Entity] = {e.key: e for e in ENTITIES}
_BLOCKED_BY_KEY: dict[str, tuple[str, str, str]] = {b[0]: b for b in BLOCKED_ENTITIES}


@dataclass
class PurgePreview:
    entity: str
    label: str
    singular: str
    consequence: str
    requested: int
    found: int
    #: What each target actually is, so somebody can see they picked the right
    #: rows before agreeing to lose them.
    targets: list[dict[str, Any]]
    deleted_rows: int
    detached_rows: int
    breakdown: list[dict[str, Any]]
    detached_breakdown: list[dict[str, Any]]
    truncated: bool
    blockers: list[str]
    #: The exact phrase the caller must type back. Derived from the real count,
    #: so a preview that is out of date cannot be confirmed.
    confirmation_phrase: str


def resolve_entity(key: str) -> Entity:
    if key in _BLOCKED_BY_KEY:
        raise ConflictError(_BLOCKED_BY_KEY[key][2])
    entity = BY_KEY.get(key)
    if entity is None:
        raise ValidationError(f"'{key}' is not something that can be permanently deleted.")
    return entity


class PurgeAdminService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.purger = PurgeService(session)

    # -------------------------------------------------------------- preview

    async def preview(self, entity_key: str, ids: list[int], *, actor: User) -> PurgePreview:
        entity = resolve_entity(entity_key)
        ids = self._clean_ids(ids)
        plan = await self.purger.plan(entity.table, ids)
        blockers = await self._protection_failures(entity, ids, actor=actor)

        return PurgePreview(
            entity=entity.key,
            label=entity.label,
            singular=entity.singular,
            consequence=entity.consequence,
            requested=len(ids),
            found=plan.found,
            targets=await self._describe(entity, ids),
            deleted_rows=plan.total_deleted,
            detached_rows=plan.total_detached,
            breakdown=_flatten(plan.deleted),
            detached_breakdown=_flatten(plan.detached),
            truncated=plan.truncated,
            blockers=blockers,
            confirmation_phrase=_phrase(entity, plan),
        )

    # -------------------------------------------------------------- execute

    async def execute(
        self,
        entity_key: str,
        ids: list[int],
        *,
        actor: User,
        confirmation: str,
        user_agent: str | None = None,
    ) -> PurgePreview:
        """Delete permanently. One transaction, with its own audit record.

        The plan is recomputed here rather than trusted from the preview: the
        preview was a separate request, and between the two somebody may have
        enrolled a student or marked a submission. Confirming a count that is
        no longer true must fail, not delete more than was agreed.
        """
        entity = resolve_entity(entity_key)
        ids = self._clean_ids(ids)

        plan = await self.purger.plan(entity.table, ids)
        if plan.found == 0:
            raise NotFoundError("Those records no longer exist. Nothing was deleted.")

        blockers = await self._protection_failures(entity, ids, actor=actor)
        if blockers:
            raise ConflictError(" ".join(blockers))

        expected = _phrase(entity, plan)
        if (confirmation or "").strip().upper() != expected.upper():
            # Deliberately quotes the expected phrase: the count may have moved
            # since the preview, and "type DELETE 7 PEOPLE" is actionable where
            # "confirmation did not match" is not.
            raise ValidationError(
                f"To confirm, type exactly: {expected}. "
                "The number of affected records may have changed since the preview."
            )

        targets = await self._describe(entity, ids)
        breakdown = _flatten(plan.deleted)
        detached = _flatten(plan.detached)

        if entity.table == "users":
            # Nothing may be signed in as an account that no longer exists.
            # Done before the delete because `tokens.user_id` is one of the
            # cascades -- afterwards there would be no rows left to revoke and
            # no way to tell a revoked session from a deleted one.
            await self._revoke_sessions(ids)

        deleted_targets = await self.purger.purge(entity.table, ids)

        # In the same transaction as the deletion, on purpose. `audit_logs` has
        # no foreign keys, so this row outlives everything it names.
        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type=f"purge:{entity.key}",
            entity_id=ids[0] if len(ids) == 1 else None,
            success=True,
            user_agent=user_agent,
            details={
                "permanent": True,
                "entity": entity.key,
                "table": entity.table,
                "ids": ids,
                "targets": targets,
                "rows_deleted_total": plan.total_deleted,
                "rows_detached_total": plan.total_detached,
                "target_rows_deleted": deleted_targets,
                "breakdown": breakdown,
                "detached": detached,
                "truncated_preview": plan.truncated,
                "confirmed_phrase": expected,
            },
        )
        logger.warning(
            "Permanent deletion performed",
            extra={
                "entity": entity.key,
                "ids": ids,
                "rows": plan.total_deleted,
                "actor_user_id": actor.id,
            },
        )

        return PurgePreview(
            entity=entity.key,
            label=entity.label,
            singular=entity.singular,
            consequence=entity.consequence,
            requested=len(ids),
            found=plan.found,
            targets=targets,
            deleted_rows=plan.total_deleted,
            detached_rows=plan.total_detached,
            breakdown=breakdown,
            detached_breakdown=detached,
            truncated=plan.truncated,
            blockers=[],
            confirmation_phrase=expected,
        )

    # ------------------------------------------------------- empty batches

    async def empty_batches(self) -> list[dict[str, Any]]:
        """Batches with nobody enrolled and no sessions held.

        Offered because it is the one bulk deletion that is genuinely safe to
        suggest: an empty batch is a mistake somebody made in the scheduler, and
        hunting for them by hand is how real ones get deleted by accident.
        """
        rows = await self.session.execute(
            text(
                """
                SELECT b.id, b.batch_code, b.start_date,
                       (SELECT count(*) FROM batch_sessions s WHERE s.batch_id = b.id) AS sessions
                FROM batches b
                WHERE NOT EXISTS (SELECT 1 FROM enrollments e WHERE e.batch_id = b.id)
                  AND NOT EXISTS (
                      SELECT 1 FROM batch_sessions s
                      JOIN attendance_sheets a ON a.session_id = s.id
                      WHERE s.batch_id = b.id
                  )
                ORDER BY b.start_date DESC NULLS LAST, b.id
                LIMIT 200
                """
            )
        )
        return [
            {
                "id": r.id,
                "batch_code": r.batch_code,
                "start_date": r.start_date.isoformat() if r.start_date else None,
                "sessions": r.sessions,
            }
            for r in rows
        ]

    # ---------------------------------------------------------- protections

    async def _protection_failures(
        self, entity: Entity, ids: list[int], *, actor: User
    ) -> list[str]:
        """Reasons this deletion must be refused. Empty means it may proceed.

        Returned as a list rather than raised, so the preview can show every
        reason at once instead of one per attempt.
        """
        if entity.table != "users":
            return []

        reasons: list[str] = []

        if actor.id in ids:
            reasons.append(
                "You cannot delete your own account. Ask another Super Admin to do it."
            )

        targeted_supers = await self._super_admin_ids(ids)
        if targeted_supers:
            remaining = await self._active_super_admin_count(excluding=ids)
            if remaining == 0:
                reasons.append(
                    "This would delete the last active Super Admin, leaving nobody able to "
                    "manage roles, permissions or accounts. Appoint another Super Admin first."
                )
        return reasons

    async def _super_admin_ids(self, ids: list[int]) -> list[int]:
        result = await self.session.execute(
            select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.name == Roles.SUPER_ADMIN.value, UserRole.user_id.in_(ids))
        )
        return [r for (r,) in result]

    async def _active_super_admin_count(self, *, excluding: list[int]) -> int:
        result = await self.session.execute(
            select(func.count(func.distinct(User.id)))
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                Role.name == Roles.SUPER_ADMIN.value,
                User.status == UserStatus.ACTIVE,
                User.deleted_at.is_(None),
                User.id.notin_(excluding),
            )
        )
        return int(result.scalar_one() or 0)

    async def _revoke_sessions(self, user_ids: list[int]) -> None:
        await self.session.execute(
            text("DELETE FROM tokens WHERE user_id = ANY(:ids)"), {"ids": user_ids}
        )

    # ------------------------------------------------------------- helpers

    async def _describe(self, entity: Entity, ids: list[int]) -> list[dict[str, Any]]:
        """Identify each target, so the warning names what is going.

        For people this is the username -- not the email address, which is
        contact data and has no business being echoed into a confirmation
        dialog or an audit payload that administrators read routinely.
        """
        column = entity.name_column
        pk = await self.purger.primary_key(entity.table)
        if pk is None:
            return []
        # Cast so a non-text identifier (a session's start time) is still JSON.
        label = f'"{column}"::text' if column else "NULL::text"
        rows = await self.session.execute(
            text(f'SELECT "{pk}" AS id, {label} AS label FROM "{entity.table}" WHERE "{pk}" = ANY(:ids)'),
            {"ids": ids},
        )
        return [{"id": r.id, "label": r.label} for r in rows]

    @staticmethod
    def _clean_ids(ids: list[int]) -> list[int]:
        unique = sorted({int(i) for i in ids})
        if not unique:
            raise ValidationError("Nothing was selected.")
        if len(unique) > 500:
            # A bulk delete is supported; an unbounded one is not. 500 rows is
            # past any plausible housekeeping action and short of the point
            # where one transaction holds locks long enough to matter.
            raise ValidationError(
                "Select 500 records or fewer at a time. "
                f"{len(unique)} were submitted."
            )
        return unique


def _phrase(entity: Entity, plan: PurgePlan) -> str:
    """The sentence the administrator must type back.

    It carries the real row count on purpose: typing "DELETE" teaches nothing,
    whereas typing a number means having read the one figure that says how much
    is about to be lost. The count comes from the plan, so a stale preview
    produces a phrase that no longer matches and the delete is refused.
    """
    noun = (entity.singular if plan.found == 1 else entity.label).upper()
    related = plan.total_deleted - plan.found
    return f"DELETE {plan.found} {noun} AND {related} RELATED RECORD{'' if related == 1 else 'S'}"


def _flatten(items: list[Any], *, depth: int = 0) -> list[dict[str, Any]]:
    """The dependency tree as a flat, ordered list for display."""
    out: list[dict[str, Any]] = []
    for node in items:
        out.append(
            {
                "table": node.table,
                "column": node.column,
                "effect": node.effect,
                "rows": node.rows,
                "depth": depth,
            }
        )
        out.extend(_flatten(node.children, depth=depth + 1))
    return out
