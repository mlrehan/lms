"""Returning the installation to a freshly-installed state.

This is the only operation in the product with no recovery path through the
product. Everything below exists to make that fact hard to stumble into.

**Four gates, and each one is a refusal by default rather than a permission by
default:**

1. **`APP_SYSTEM_RESET_ENABLED` is off unless somebody turns it on.** It lives
   in deployment configuration, not in the interface, because the person who
   may *run* a reset and the person who may *enable* one hold different kinds
   of access. A Super Admin session is not enough on its own.
2. **Production is refused outright, whatever the flag says.** A production
   reset is a maintenance operation performed with shell access, a maintenance
   window and somebody watching -- not an HTTP request. There is no
   configuration value that turns this one off.
3. **A verified, recent backup must exist**, or the reset stops and says which
   check failed. An unset backup path is itself a refusal: "there is no backup
   configured" and "the backup is fine" must never look the same to the person
   about to erase everything.
4. **The typed confirmation names this database.** A screen left open against
   staging cannot be used to reset something else, because the phrase it is
   showing will not match.

**What it keeps, deliberately.** The schema and its migration history, the
permission catalogue, the geographic reference data, and the audit trail,
which the database keeps append-only whatever this code wants. A fresh
install has no *institutional*
history; it does have a permission model and a list of countries, and
regenerating those from scratch buys nothing but risk.

**What it cannot promise, stated rather than implied.** Object storage is
cleared only where the deployment holds the bytes itself. With R2 configured,
the database rows go and the objects do not: a reset here cannot authorise a
bulk delete against somebody's cloud bucket, and pretending otherwise would be
worse than saying so. The response carries that as a warning.

**It does not stop a running sync, it refuses to run during one.** Terminating
a pipeline mid-flight would leave the external system believing it had handed
over records that no longer exist here. Waiting is free; a half-applied sync
against an empty database is not.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.bootstrap.runner import (
    bootstrap_geo,
    bootstrap_grading,
    bootstrap_identity,
    ensure_super_admin,
)
from backend.core.backups import backup_blockers
from backend.core.config import Settings
from backend.core.errors import ConflictError, ValidationError
from backend.core.logging import get_logger
from backend.models.identity.user import User
from backend.services import audit_service
from backend.services.audit_service import AuditAction

logger = get_logger(__name__)

#: Kept through a reset.
#:
#: `alembic_version` -- the schema's identity; losing it makes the database
#: unrecognisable to migrations.
#: `permissions` / `roles` / `role_permissions` -- the catalogue every gate is
#: resolved against. Re-seeded anyway, so truncating it would only create a
#: window in which nobody can do anything.
#: `countries` / `cities` / `time_zones` -- reference data about the world,
#: not about this institution.
PRESERVED_TABLES = frozenset(
    {
        "alembic_version",
        "permissions",
        "roles",
        "role_permissions",
        "countries",
        "cities",
        "time_zones",
    }
)

#: The audit trail. Always kept, and not by this module's choice.
#:
#: `trg_audit_logs_append_only` is a BEFORE DELETE OR UPDATE OR TRUNCATE
#: trigger that raises, so the table cannot be emptied by any statement this
#: service could issue. An earlier draft offered a "clear the audit trail too"
#: option; it would have failed at run time, which is the right outcome and a
#: bad feature. Defeating the trigger from an HTTP route was never on the
#: table: an append-only guarantee that an endpoint can switch off is not one.
#:
#: Nothing references `audit_logs` and it references nothing, so the
#: `TRUNCATE ... CASCADE` below cannot reach it either.
AUDIT_TABLE = "audit_logs"

#: Friendlier names for the impact summary, for the tables somebody running a
#: college would actually recognise. Anything unlisted shows its table name:
#: better a technical word than a wrong one.
_LABELS: dict[str, str] = {
    "users": "People",
    "user_roles": "Role assignments",
    "courses": "Courses",
    "batches": "Batches",
    "batch_sessions": "Class sessions",
    "enrollments": "Enrolments",
    "attendances": "Attendance records",
    "attendance_sheets": "Attendance registers",
    "assignments": "Assignments",
    "assignment_submissions": "Submissions",
    "quizzes": "Quizzes",
    "quiz_attempts": "Quiz attempts",
    "exams": "Examinations",
    "exam_results": "Exam results",
    "gradebook_entries": "Grade book entries",
    "class_performance_marks": "Participation marks",
    "transcripts": "Transcripts",
    "grading_schemes": "Grading schemes",
    "resources": "Files and resources",
    "announcements": "Announcements",
    "course_discussions": "Discussions",
    "mail_messages": "Messages",
    "notifications": "Notifications",
    "organizations": "Organisations",
    "student_guardians": "Guardian links",
    "tokens": "Sign-in sessions",
    "audit_logs": "Audit trail",
    "sync_pipeline_runs": "Sync history",
}


@dataclass
class ResetImpact:
    table: str
    label: str
    rows: int


@dataclass
class ResetPreview:
    database: str
    environment: str
    enabled: bool
    blockers: list[str]
    impact: list[ResetImpact]
    total_rows: int
    preserved: list[str]
    confirmation_phrase: str


@dataclass
class ResetOutcome:
    database: str
    rows_deleted: int
    cleared: list[ResetImpact]
    seeded: dict[str, Any]
    bootstrap_username: str
    bootstrap_password: str
    sessions_invalidated: int
    warnings: list[str]


class SystemResetService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    # -------------------------------------------------------------- preview

    async def preview(self) -> ResetPreview:
        database = await self._database_name()
        impact = await self._impact()
        return ResetPreview(
            database=database,
            environment=self.settings.app.environment.value,
            enabled=self.settings.app.system_reset_enabled,
            blockers=await self._blockers(),
            impact=impact,
            total_rows=sum(i.rows for i in impact),
            preserved=[
                "The database schema and its migration history",
                "The permission catalogue and the six roles",
                "Countries, cities and time zones",
                "The audit trail, which the database itself keeps append-only",
            ],
            confirmation_phrase=_phrase(database),
        )

    async def _blockers(self) -> list[str]:
        """Every reason this reset will not run. Empty means it would.

        All of them are collected rather than the first one raised, so somebody
        preparing a reset learns everything they must arrange in one look.
        """
        blockers: list[str] = []
        app = self.settings.app

        if app.is_production:
            blockers.append(
                "This is a production installation. A reset here is a maintenance "
                "operation performed with direct server access, not from this screen. "
                "No configuration setting enables it."
            )
        if not app.system_reset_enabled:
            blockers.append(
                "Resetting is switched off for this installation. It is enabled in "
                "deployment configuration (APP_SYSTEM_RESET_ENABLED), deliberately not "
                "from this screen."
            )

        blockers.extend(self._backup_blockers())

        running = await self._running_sync_count()
        if running:
            blockers.append(
                f"{running} synchronisation run(s) are in progress. Resetting now would "
                "leave the external system believing it handed over records that no "
                "longer exist. Wait for them to finish."
            )
        return blockers

    def _backup_blockers(self) -> list[str]:
        """Check there is a recent, readable backup. Refuse if unsure.

        The rule is `core/backups.backup_blockers`, shared with the AI
        assistant's confirmed SQL changes so the two can never disagree about
        what counts as a backup.
        """
        app = self.settings.app
        return backup_blockers(
            app.system_reset_backup_path,
            max_age_hours=app.system_reset_backup_max_age_hours,
            action="A reset",
        )

    # -------------------------------------------------------------- execute

    async def execute(
        self,
        *,
        actor: User,
        confirmation: str,
        user_agent: str | None = None,
    ) -> ResetOutcome:
        database = await self._database_name()

        blockers = await self._blockers()
        if blockers:
            raise ConflictError(" ".join(blockers))

        expected = _phrase(database)
        if (confirmation or "").strip() != expected:
            # Case-sensitive, and quoting the database name: the whole purpose
            # of this phrase is that it cannot be typed by muscle memory from a
            # different environment.
            raise ValidationError(f"To confirm, type exactly: {expected}")

        impact = await self._impact()
        total = sum(i.rows for i in impact)
        sessions = next((i.rows for i in impact if i.table == "tokens"), 0)

        # Recorded before the tables go, and committed with them. If the reset
        # fails this rolls back with it, so no entry ever claims a reset that
        # did not happen -- and `audit_logs` is append-only at the database, so
        # the entry cannot be taken out by what follows.
        self._record(actor, database, impact, total, user_agent)

        cleared = await self._truncate(impact)

        seeded = await self._reseed()
        username, password = await self._new_bootstrap_admin(actor)
        warnings = self._storage_warnings()

        logger.warning(
            "System reset performed",
            extra={"database": database, "rows": total, "actor_user_id": actor.id},
        )
        return ResetOutcome(
            database=database,
            rows_deleted=total,
            cleared=cleared,
            seeded=seeded,
            bootstrap_username=username,
            bootstrap_password=password,
            sessions_invalidated=sessions,
            warnings=warnings,
        )

    def _record(
        self,
        actor: User,
        database: str,
        impact: list[ResetImpact],
        total: int,
        user_agent: str | None,
    ) -> None:
        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="system:reset",
            success=True,
            user_agent=user_agent,
            details={
                "permanent": True,
                "database": database,
                "environment": self.settings.app.environment.value,
                "rows_deleted_total": total,
                "tables": [{"table": i.table, "rows": i.rows} for i in impact if i.rows],
            },
        )

    async def _truncate(self, impact: list[ResetImpact]) -> list[ResetImpact]:
        """Empty the tables in one statement.

        `TRUNCATE` over `DELETE` because this is a reset: it restarts the
        identity sequences, so a fresh installation's first course is course 1
        rather than course 4,312 -- which is what somebody means by "like a new
        install". One statement with every table named avoids ordering
        entirely; `CASCADE` covers anything reachable that was not listed,
        which on this schema is nothing, since the list is every table bar the
        preserved ones.
        """
        if not impact:
            return []
        quoted = ", ".join(f'"{i.table}"' for i in impact)
        await self.session.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
        # The counts the caller was shown and confirmed, not a second
        # measurement: re-counting here could disagree with what was agreed to
        # and with what the audit entry already records.
        return [i for i in impact if i.rows]

    async def _reseed(self) -> dict[str, Any]:
        """Put back what a fresh installation has.

        These are the same bootstrap functions a new deployment runs, not a
        parallel copy of them -- so "reset" and "freshly installed" cannot come
        to mean different things.
        """
        identity = await bootstrap_identity(self.session)
        geo = await bootstrap_geo(self.session)
        grading = await bootstrap_grading(self.session)
        return {"identity": identity, "geo": geo, "grading": grading}

    async def _new_bootstrap_admin(self, actor: User) -> tuple[str, str]:
        """One Super Admin, with a freshly generated password.

        **It carries the operator's own username and email**, so whoever ran
        the reset can still sign in afterwards. Inventing a `superadmin` with a
        placeholder address would leave a real installation with an account
        nobody can receive a password reset for.

        **The password is new, and that is the point.** It is returned once, in
        this response, and never logged or stored in readable form. Leaving the
        old password working would mean the credentials of a system somebody
        has just erased are still the credentials of the new one -- and the
        account row itself was truncated moments ago, so there is no password
        left to keep.
        """
        password = _generate_password()
        user, created = await ensure_super_admin(
            self.session,
            username=actor.username,
            email=actor.email or f"{actor.username}@invalid.local",
            raw_password=password,
        )
        if not created:
            # Unreachable after a truncate of `users`, and handled rather than
            # assumed away: `ensure_super_admin` never overwrites an existing
            # password, so returning the generated one would be a lie.
            raise ConflictError(
                "A Super Admin account already existed after the reset, so no new "
                "password was set. Use the existing credentials, or the bootstrap "
                "command with server access."
            )
        return user.username, password

    def _storage_warnings(self) -> list[str]:
        warnings: list[str] = []
        storage = self.settings.storage
        if storage.mode.value == "r2":
            warnings.append(
                "Uploaded files are stored in Cloudflare R2. The database records of "
                "them have been cleared, but the objects themselves have not: a reset "
                "from this screen does not issue bulk deletes against your cloud "
                "bucket. Empty it separately if that is what you want."
            )
        else:
            warnings.append(
                f"Uploaded files on disk at {storage.local_path} were left in place. "
                "The records pointing at them are gone, so they are now unreferenced "
                "and safe to remove."
            )
        return warnings

    # -------------------------------------------------------------- queries

    async def _database_name(self) -> str:
        return str((await self.session.execute(text("SELECT current_database()"))).scalar_one())

    async def _running_sync_count(self) -> int:
        result = await self.session.execute(
            text("SELECT count(*) FROM sync_pipeline_runs WHERE status = 'RUNNING'")
        )
        return int(result.scalar_one() or 0)

    async def _impact(self) -> list[ResetImpact]:
        """Row counts for every table a reset would empty.

        Counted exactly rather than estimated from `pg_class.reltuples`: the
        figure is what somebody types a confirmation against, and an estimate
        that reads "about 1,200 people" is not something to agree to.
        """
        tables = await self._resettable_tables()
        if not tables:
            return []
        # One statement rather than one per table: a reset preview on a wide
        # schema is otherwise 70 round trips.
        # Column names avoid `t` and `n`: `Row.t` and `Row.n` collide with
        # Row's own underscored attributes and resolve to the wrong object.
        union = " UNION ALL ".join(
            f"SELECT '{t}' AS tbl, count(*) AS cnt FROM \"{t}\"" for t in tables
        )
        rows = await self.session.execute(
            text(f"SELECT tbl, cnt FROM ({union}) s ORDER BY cnt DESC, tbl")
        )
        return [
            ResetImpact(
                table=r.tbl,
                label=_LABELS.get(r.tbl, r.tbl.replace("_", " ").capitalize()),
                rows=int(r.cnt),
            )
            for r in rows
        ]

    async def _resettable_tables(self) -> list[str]:
        """Every public table except the preserved ones.

        Read from the catalogue, so a table added by a later migration is
        cleared by a reset without anybody remembering to add it here. The
        failure mode of a hand-kept list is a "fresh" installation that still
        holds the last institution's data in whatever table was forgotten.
        """
        rows = await self.session.execute(
            text(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
                ORDER BY tablename
                """
            )
        )
        preserved = set(PRESERVED_TABLES) | {AUDIT_TABLE}
        return [t for (t,) in rows if t not in preserved]


def _phrase(database: str) -> str:
    """The sentence that must be typed back.

    It names the database on purpose. A confirmation of "RESET" is muscle
    memory; one that spells out which installation is about to be erased is the
    only thing standing between a screen left open on staging and the wrong
    database.
    """
    return f"RESET {database} PERMANENTLY"


def _generate_password() -> str:
    """A password for the one account a reset leaves behind.

    `secrets`, not `random`. Grouped for reading aloud over a phone, because it
    is shown exactly once and somebody has to get it from the screen into a
    password manager without a typo.
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    groups = ["".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(4)]
    return "-".join(groups)
