"""Synchronise LMS users from the LAIT API.

Two entry points drive the same code: the scheduled worker
(`backend/cli/sync_lait_users.py`) and the admin "Sync Now" button.

Rules that shape everything below, and why:

* **The feed is additive.** `/api/Students/latest` is a recent-registrations
  feed, so an account's absence means nothing. The sync creates and updates;
  it never suspends, deletes or demotes.
* **It never touches access.** `status`, `can_login`, the password, the slug
  and the username of an existing account are not written by an update, and the
  only roles it can grant come from `SYNC_GRANTABLE_ROLES` -- so nothing a
  remote payload says can make someone an administrator or switch a login on.
* **One transaction per record.** A bad record skips itself; the other 499
  are unaffected. A run's dry-run mode does the full work and rolls back.
* **A collision skips, it does not merge or rename.** Two people sharing a
  username or email is a data problem for a human; silently picking a winner
  is how one person ends up reading another's account.
* **The `RUNNING` row is the lock**, enforced by a partial unique index.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.config import Settings
from backend.core.errors import ConflictError, ServiceUnavailableError
from backend.core.logging import get_logger
from backend.integrations import lait_mapping as m
from backend.integrations.lait_client import LaitApiError, LaitClient
from backend.integrations.lait_geo import GeoResolver
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.user_sync import UserSyncRun
from backend.security import password as pwd
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.utils.enums import UserStatus

logger = get_logger("lait.sync")

MAX_RECORDED_ERRORS = 200

# Fields a LAIT student payload owns on an existing account. Deliberately
# excludes username, slug, status, can_login and the password.
_STUDENT_FIELDS = (
    "title", "first_name", "last_name", "phone_number", "company",
    "address", "postcode", "web", "ip_address",
)
_TUTOR_BLANK_FILL = ("title", "first_name", "last_name")


@dataclass
class SourceStats:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    warnings: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


@dataclass
class RunReport:
    students: SourceStats = field(default_factory=SourceStats)
    tutors: SourceStats = field(default_factory=SourceStats)
    errors: list[dict[str, Any]] = field(default_factory=list)
    roles_unknown: int = 0
    errors_dropped: int = 0

    def error(self, source: str, external_id: str, reason: str) -> None:
        if len(self.errors) >= MAX_RECORDED_ERRORS:
            self.errors_dropped += 1
            return
        self.errors.append({"source": source, "external_id": external_id[:60], "reason": reason[:200]})


class _Skip(Exception):
    """A record that cannot be synced. The message is safe to store."""


class LaitSyncService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        *,
        client: LaitClient | None = None,
    ) -> None:
        self._factory = session_factory
        self._settings = settings
        self._client = client

    # ------------------------------------------------------------------ lifecycle

    async def start(
        self, *, trigger_type: str, triggered_by_user_id: int | None, dry_run: bool
    ) -> UserSyncRun:
        """Record a RUNNING row. Raises ConflictError if a run is already live."""
        if not self._settings.lait.is_configured:
            raise ServiceUnavailableError("LAIT synchronisation is not configured.")

        await self._reap_stale()
        try:
            async with self._factory.begin() as session:
                run = UserSyncRun(
                    trigger_type=trigger_type,
                    triggered_by_user_id=triggered_by_user_id,
                    dry_run=dry_run,
                    status="RUNNING",
                    started_at=datetime.now(timezone.utc),
                )
                session.add(run)
                await session.flush()
                session.expunge(run)
        except IntegrityError:
            raise ConflictError("A synchronisation is already running.") from None
        return run

    async def _reap_stale(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self._settings.lait.stale_run_minutes)
        async with self._factory.begin() as session:
            await session.execute(
                update(UserSyncRun)
                .where(UserSyncRun.status == "RUNNING", UserSyncRun.started_at < cutoff)
                .values(
                    status="FAILED",
                    finished_at=datetime.now(timezone.utc),
                    failure_reason="Abandoned: the process running it stopped without finishing.",
                )
            )

    async def run(
        self, *, trigger_type: str, triggered_by_user_id: int | None, dry_run: bool
    ) -> UserSyncRun:
        run = await self.start(
            trigger_type=trigger_type, triggered_by_user_id=triggered_by_user_id, dry_run=dry_run
        )
        return await self.execute(run.id)

    # ------------------------------------------------------------------ execution

    async def execute(self, run_id: int) -> UserSyncRun:
        report = RunReport()
        failure: str | None = None
        geo_stats: dict[str, Any] = {}

        async with self._factory() as session:
            run = (await session.execute(select(UserSyncRun).where(UserSyncRun.id == run_id))).scalar_one()
            dry_run, triggered_by = run.dry_run, run.triggered_by_user_id
            actor_id = triggered_by or await self._scheduled_actor(session)

        geo = GeoResolver(self._factory, dry_run=dry_run)
        try:
            if self._client is not None:
                await self._sync_all(self._client, report, geo, dry_run, actor_id, run_id)
            else:
                async with LaitClient(self._settings.lait) as client:
                    await self._sync_all(client, report, geo, dry_run, actor_id, run_id)
        except LaitApiError as exc:
            failure = f"LAIT API: {exc}"[:300]
            logger.warning("LAIT sync aborted", extra={"reason": failure})
        except Exception as exc:  # noqa: BLE001 - a run must always be finalised
            failure = f"Unexpected {type(exc).__name__}"
            logger.exception("LAIT sync crashed")
        geo_stats = {k: (sorted(v) if isinstance(v, set) else v) for k, v in vars(geo.stats).items()}

        status = "FAILED" if failure else ("PARTIAL" if report.errors else "SUCCEEDED")
        stats = {
            "students": report.students.as_dict(),
            "tutors": report.tutors.as_dict(),
            "geo": geo_stats,
            "unknown_roles": report.roles_unknown,
            "errors_dropped": report.errors_dropped,
        }
        async with self._factory.begin() as session:
            run = (await session.execute(select(UserSyncRun).where(UserSyncRun.id == run_id))).scalar_one()
            run.status = status
            run.finished_at = datetime.now(timezone.utc)
            run.stats = stats
            run.errors = report.errors
            run.failure_reason = failure
            audit_service.record(
                session,
                action=AuditAction.USER_SYNC,
                actor_user_id=triggered_by,
                entity_type="user_sync_run",
                entity_id=run.id,
                success=failure is None,
                details={
                    "trigger": run.trigger_type,
                    "dry_run": dry_run,
                    "status": status,
                    "students": report.students.as_dict(),
                    "tutors": report.tutors.as_dict(),
                },
            )
            await session.flush()
            session.expunge(run)
        return run

    async def _scheduled_actor(self, session: AsyncSession) -> int | None:
        username = self._settings.lait.sync_actor_username
        return (await session.execute(select(User.id).where(User.username == username))).scalar_one_or_none()

    async def _sync_all(
        self, client: LaitClient, report: RunReport, geo: GeoResolver,
        dry_run: bool, actor_id: int | None, run_id: int,
    ) -> None:
        students = await client.students_latest()
        tutors = await client.tutors()
        source_tz = self._settings.lait.source_timezone

        report.students.fetched = len(students)
        for payload in students:
            await self._one(
                "student", report, report.students, payload, "UserID",
                lambda p=payload: m.map_student(p, source_timezone=source_tz),
                None, geo, dry_run, actor_id, run_id,
            )

        report.tutors.fetched = len(tutors)
        for payload in tutors:
            await self._one(
                "tutor", report, report.tutors, payload, "user_id",
                lambda p=payload: m.map_tutor(p),
                client, geo, dry_run, actor_id, run_id,
            )

    async def _one(
        self, source: str, report: RunReport, stats: SourceStats, payload: Any, id_key: str,
        mapper: Any, client: LaitClient | None, geo: GeoResolver, dry_run: bool,
        actor_id: int | None, run_id: int,
    ) -> None:
        external = str(payload.get(id_key) if isinstance(payload, dict) else "?")
        try:
            if not isinstance(payload, dict):
                raise _Skip("record is not an object")
            try:
                mapped = mapper()
            except m.MappingError as exc:
                raise _Skip(str(exc)) from None

            report.roles_unknown += len(mapped.unknown_roles)
            stats.warnings += len(mapped.warnings)

            outcome = await self._upsert(mapped, client, geo, dry_run, actor_id, run_id)
            setattr(stats, outcome, getattr(stats, outcome) + 1)
        except _Skip as exc:
            stats.skipped += 1
            report.error(source, external, str(exc))
        except LaitApiError:
            raise  # whole-run problem (key revoked, API down) -- abort, do not skip 500 rows
        except IntegrityError:
            stats.skipped += 1
            report.error(source, external, "database constraint refused this record")
        except Exception as exc:  # noqa: BLE001 - one record must not sink the run
            logger.exception("LAIT record failed")
            stats.skipped += 1
            report.error(source, external, f"unexpected {type(exc).__name__}")

    # ---------------------------------------------------------------- one record

    async def _upsert(
        self, mapped: m.MappedUser, client: LaitClient | None, geo: GeoResolver,
        dry_run: bool, actor_id: int | None, run_id: int,
    ) -> str:
        async with self._factory() as session:
            existing = await self._find_existing(session, mapped)
            hashed: str | None = None

            if existing is None:
                if mapped.source == "tutor" and client is not None:
                    m.apply_tutor_detail(mapped, await client.tutor_by_guid(mapped.guid))
                    if not mapped.username:
                        mapped.username = m.fallback_username(mapped.first_name, mapped.last_name)
                problem = m.username_problem(mapped.username)
                if problem:
                    raise _Skip(problem)
                await self._assert_free(session, mapped)
                hashed = await asyncio.to_thread(
                    pwd.hash_password, self._settings.lait.default_password.get_secret_value()
                )

            country_id = await geo.country(mapped.country_name)
            city_id = await geo.city(country_id, mapped.city_name)

            if existing is None:
                assert hashed is not None and mapped.username is not None
                roles = await self._roles(session, mapped.roles)
                slug = await self._slug(session, mapped)
                now = mapped.registered_at or datetime.now(timezone.utc)
                user = User(
                    public_id=mapped.guid,
                    username=mapped.username,
                    slug=slug,
                    email=mapped.email,
                    hashed_password=hashed,
                    status=UserStatus.ACTIVE,
                    can_login=False,
                    is_locked=False,
                    country_id=country_id,
                    city_id=city_id,
                    external_student_id=mapped.external_student_id,
                    external_tutor_id=mapped.external_tutor_id,
                    created_by=actor_id,
                    updated_by=actor_id,
                    created_at=now,
                    updated_at=now,
                    roles=roles,  # set before add: assigning after risks MissingGreenlet
                    **{f: getattr(mapped, f) for f in _STUDENT_FIELDS},
                )
                if mapped.is_public is not None:
                    user.is_public = mapped.is_public
                session.add(user)
                await session.flush()
                self._audit(session, actor_id, user.id, run_id, mapped.source, "created", [])
                outcome = "created"
            else:
                changed = await self._apply_update(session, existing, mapped, country_id, city_id, actor_id)
                if not changed:
                    return "unchanged"
                self._audit(session, actor_id, existing.id, run_id, mapped.source, "updated", changed)
                outcome = "updated"

            if dry_run:
                await session.rollback()
            else:
                await session.commit()
            return outcome

    async def _find_existing(self, session: AsyncSession, mapped: m.MappedUser) -> User | None:
        conds = [User.public_id == mapped.guid]
        if mapped.external_student_id is not None:
            conds.append(User.external_student_id == mapped.external_student_id)
        if mapped.external_tutor_id is not None:
            conds.append(User.external_tutor_id == mapped.external_tutor_id)
        rows = (await session.execute(select(User).where(or_(*conds)))).scalars().all()
        if len(rows) > 1:
            raise _Skip("GUID and LAIT ids point at different accounts")
        return rows[0] if rows else None

    async def _assert_free(self, session: AsyncSession, mapped: m.MappedUser) -> None:
        """Refuse when the username or email belongs to anyone already.

        Crosswise on purpose: login resolves an identifier against username *or*
        email, so one account's username equalling another's email would make
        that identifier ambiguous.
        """
        keys = {k for k in (mapped.username, mapped.email) if k}
        hit = (
            await session.execute(
                select(User.id).where(
                    or_(func.lower(User.username).in_(keys), func.lower(User.email).in_(keys))
                ).limit(1)
            )
        ).first()
        if hit:
            raise _Skip("username or email already belongs to another account")

    async def _slug(self, session: AsyncSession, mapped: m.MappedUser) -> str:
        base = m.slug_base(mapped.first_name, mapped.last_name, mapped.username)
        taken = (await session.execute(select(User.id).where(User.slug == base))).first()
        return m.slug_with_suffix(base, mapped.guid) if taken else base

    async def _roles(self, session: AsyncSession, names: list[str]) -> list[Role]:
        assert set(names) <= m.SYNC_GRANTABLE_ROLES, "sync attempted to grant a non-grantable role"
        if not names:
            return []
        return list((await session.execute(select(Role).where(Role.name.in_(names)))).scalars().all())

    async def _apply_update(
        self, session: AsyncSession, user: User, mapped: m.MappedUser,
        country_id: int | None, city_id: int | None, actor_id: int | None,
    ) -> list[str]:
        changed: list[str] = []

        def set_if(name: str, value: Any) -> None:
            if value is not None and getattr(user, name) != value:
                setattr(user, name, value)
                changed.append(name)

        if mapped.source == "student":
            for f in _STUDENT_FIELDS:
                set_if(f, getattr(mapped, f))
            set_if("country_id", country_id)
            set_if("city_id", city_id)
            set_if("external_student_id", mapped.external_student_id)
            if mapped.email and user.email != mapped.email:
                taken = (
                    await session.execute(
                        select(User.id).where(func.lower(User.email) == mapped.email, User.id != user.id).limit(1)
                    )
                ).first()
                if not taken:
                    set_if("email", mapped.email)
        else:
            # The tutor feed is thinner and must not overwrite what a student
            # record (or an administrator) already holds; it only fills blanks.
            for f in _TUTOR_BLANK_FILL:
                if getattr(user, f) in (None, ""):
                    set_if(f, getattr(mapped, f))
            set_if("external_tutor_id", mapped.external_tutor_id)
            if mapped.is_public is not None:
                set_if("is_public", mapped.is_public)

        if mapped.roles:
            have = {r.name for r in user.roles}
            missing = [r for r in mapped.roles if r not in have]
            if missing:
                user.roles = [*user.roles, *await self._roles(session, missing)]
                changed.append("roles")

        if changed:
            user.updated_by = actor_id
        return changed

    @staticmethod
    def _audit(
        session: AsyncSession, actor_id: int | None, user_id: int, run_id: int,
        source: str, what: str, fields: list[str],
    ) -> None:
        audit_service.record(
            session,
            action=AuditAction.USER_SYNC,
            actor_user_id=actor_id,
            entity_type="user",
            entity_id=user_id,
            details={"run": run_id, "source": source, "result": what, "fields": fields},
        )
