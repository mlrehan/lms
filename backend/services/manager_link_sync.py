"""Corporate managers, and which delegates belong to them.

This is the one genuinely new synchronisation. It reads the two endpoints the
console already exposes read-only --

    GET /api/GetDelegateManagers
    GET /api/GetDelegateManagers/{customer_id}/Delegates

-- and turns them into `manager_students` rows, which is what `ScopeResolver`
uses to decide that a corporate manager may see a delegate's results.

**Three matching rules, each chosen rather than defaulted:**

1. **A manager is matched by email first.** The brief for this step says to
   link by matching email addresses, and it is also forced: `users.email` is
   unique and `LaitSyncService._assert_free` refuses to create an account whose
   email belongs to somebody else. So an upstream manager who is already in the
   LMS -- typically because they are also a student -- is *used*, never
   duplicated, and never altered.
2. **A manager with no match is skipped, and no account is created.** This
   step links people who are already in the LMS; it is not a way for an
   external system to add accounts here. A manager whose email matches nobody
   is recorded with a reason and the step moves on.

   The cost is stated rather than hidden: against live data only a minority of
   upstream managers have an LMS account, so most are skipped every run. That
   is the intended outcome -- the alternative was creating an account for
   every corporate contact LAIT holds, whether or not they have anything to do
   with this institution.
3. **A delegate is matched by `external_student_id`,** not by name. Name
   matching would silently attach a person's coursework to the wrong manager
   the first time two delegates share a name, and the feed gives us a stable
   id. A delegate we have never imported is *counted and reported*, not
   invented -- the same rule as for managers.

**Nothing here is a failure.** A manager with no LMS account, a manager with
no email address, and a delegate who is not a student here are all ordinary
facts about two systems that do not hold the same people. They are counted as
*skipped* and never as failed, so they cannot turn a healthy run into one that
reports problems. Only something that stops the step doing its job -- the LAIT
API refusing to answer -- is an error.

**A manager is never linked to themselves.** Real data has managers appearing
in their own delegate list (they booked themselves onto a course). The link
table would accept it, and it would mean "may see their own results", which is
already true for a different reason. It is skipped and counted.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.config import Settings
from backend.core.logging import get_logger
from backend.integrations import lait_mapping as m
from backend.integrations.lait_client import LaitApiError, LaitClient
from backend.models.identity.user import User
from backend.models.organization import ManagedStudent
from backend.utils.enums import UserStatus

logger = get_logger("lait.managers")

# How many delegate lists to ask for at once. One request per manager and 103
# managers upstream, so this is the difference between a polite trickle and a
# burst that invites a 429. The client retries a refused request on its own.
_CONCURRENCY = 4


@dataclass
class ManagerLinkReport:
    """What the step did, in the shape the pipeline stores."""

    managers_fetched: int = 0
    managers_matched: int = 0
    managers_no_account: int = 0
    managers_no_email: int = 0
    delegates_fetched: int = 0
    links_created: int = 0
    links_existing: int = 0
    delegates_unmatched: int = 0
    self_links_skipped: int = 0
    api_failures: int = 0
    skipped: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    def skip(self, external_id: str, reason: str) -> None:
        """Record why a manager was passed over.

        `external_id` is LAIT's `customer_id`, which is an opaque number in
        their system. **No name, no email address and no company goes in
        here**: this list is stored on the run, rendered in the console and
        read by whoever is looking at a sync, and "which record" is answerable
        without saying who the person is.
        """
        if len(self.skipped) < 200:  # bounded: a systemic skip is not a megabyte of JSON
            self.skipped.append({"customer_id": external_id, "reason": reason})

    def error(self, external_id: str, reason: str) -> None:
        """Something that stopped the step working, as opposed to a record it
        had nothing to do with."""
        if len(self.errors) < 200:
            self.errors.append({"source": "manager", "external_id": external_id, "reason": reason})

    @property
    def processed(self) -> int:
        """Records this step looked at: every manager and every delegate."""
        return self.managers_fetched + self.delegates_fetched

    @property
    def succeeded(self) -> int:
        return self.managers_matched + self.links_created + self.links_existing

    @property
    def failed(self) -> int:
        """Only what actually went wrong.

        A manager with no LMS account, a manager with no email address and a
        delegate who is not a student here are facts about two systems holding
        different people -- not failures, and no amount of retrying changes
        them. Counting them made a healthy run report PARTIAL for ever, which
        trains an operator to ignore the status. The only failure here is the
        LAIT API refusing to answer, which *is* worth retrying.
        """
        return self.api_failures

    @property
    def passed_over(self) -> int:
        """Looked at, deliberately not acted on."""
        return (
            self.managers_no_account
            + self.managers_no_email
            + self.delegates_unmatched
            + self.self_links_skipped
        )

    def as_detail(self) -> dict[str, Any]:
        return {
            "managers": {
                "fetched": self.managers_fetched,
                "matched": self.managers_matched,
                "no_lms_account": self.managers_no_account,
                "no_email": self.managers_no_email,
            },
            "delegates": {
                "fetched": self.delegates_fetched,
                "linked": self.links_created,
                "already_linked": self.links_existing,
                "unmatched": self.delegates_unmatched,
                "self_links_skipped": self.self_links_skipped,
            },
            "skipped": self.skipped,
            "errors": self.errors,
        }


class ManagerLinkSyncService:
    """Reads the delegate-manager feed and maintains `manager_students`."""

    def __init__(self, factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._factory = factory
        self._settings = settings

    async def run(
        self,
        *,
        dry_run: bool = False,
        actor_id: int | None = None,
        run_id: int | None = None,
        on_progress: Any = None,
    ) -> ManagerLinkReport:
        report = ManagerLinkReport()
        if not self._settings.lait.is_configured:
            raise LaitApiError("The LAIT integration is not configured.")

        async with LaitClient(self._settings.lait) as client:
            managers = await client.delegate_managers()
            report.managers_fetched = len(managers)
            if on_progress:
                on_progress(report)

            # Resolve every manager to a user id first, then fetch delegate
            # lists concurrently. Account creation is serialised on purpose:
            # two managers sharing an email would otherwise race the uniqueness
            # check and one of them would hit a constraint instead of a skip.
            resolved: list[tuple[dict[str, Any], int]] = []
            for payload in managers:
                try:
                    user_id = await self._manager_user_id(payload, report, dry_run, actor_id, run_id)
                except Exception as exc:  # noqa: BLE001 - one bad manager must not end the step
                    report.api_failures += 1
                    report.error(str(payload.get("customer_id") or "?"), _readable(exc))
                    continue
                if user_id is not None:
                    resolved.append((payload, user_id))
                if on_progress:
                    on_progress(report)

            semaphore = asyncio.Semaphore(_CONCURRENCY)

            async def one(payload: dict[str, Any], manager_user_id: int) -> None:
                customer_id = payload.get("customer_id")
                async with semaphore:
                    try:
                        delegates = await client.delegate_manager_students(int(customer_id))
                    except (LaitApiError, TypeError, ValueError) as exc:
                        # This one *is* a failure: the delegate list exists and
                        # we could not read it, so links may be missing.
                        report.api_failures += 1
                        report.error(str(customer_id), _readable(exc))
                        return
                if delegates is None:  # upstream 404: the manager has gone
                    return
                await self._link_all(manager_user_id, delegates, report, dry_run)
                if on_progress:
                    on_progress(report)

            await asyncio.gather(*(one(p, uid) for p, uid in resolved))

        return report

    # -- managers ------------------------------------------------------------

    async def _manager_user_id(
        self,
        payload: dict[str, Any],
        report: ManagerLinkReport,
        dry_run: bool,
        actor_id: int | None,
        run_id: int | None,
    ) -> int | None:
        """The LMS user id for one upstream manager, or None to pass them over.

        **Matching only. No account is ever created here.** An external
        directory saying somebody is a corporate contact is not a reason for
        them to have a login on this platform; a manager who is not already a
        user is somebody this institution has no relationship with yet.
        """
        customer_id = str(payload.get("customer_id") or "?")
        mapped = m.map_delegate_manager(payload, source_timezone=self._settings.lait.source_timezone)

        if not mapped.username:
            report.managers_no_email += 1
            report.skip(customer_id, "LAIT holds no email address for this manager")
            return None

        async with self._factory() as session:
            existing = await self._by_email(session, mapped.username, mapped.email)

        if existing is None:
            # The ordinary case, not an error: most corporate contacts LAIT
            # holds have never had an account here.
            report.managers_no_account += 1
            report.skip(customer_id, "no LMS user has this email address")
            return None

        # Already here -- as a student, a tutor, or because somebody created
        # them. Used as-is: this step's job is the links, not rewriting
        # accounts or granting roles.
        report.managers_matched += 1
        return existing

    @staticmethod
    async def _by_email(session: AsyncSession, username: str, email: str | None) -> int | None:
        """Match on either identifier, because login accepts either.

        **Deleted accounts are not matches.** Users here are soft-deleted --
        `audit_logs` references the row, so it stays -- which means a deleted
        person keeps their email in the table. Without this filter a manager
        removed yesterday is matched again today and linked to delegates,
        quietly resurrecting the relationship the deletion was meant to end.
        Found exactly that way: 95 removed accounts were re-matched on the
        very next run.
        """
        keys = {k.lower() for k in (username, email) if k}
        row = (
            await session.execute(
                select(User.id)
                .where(
                    or_(func.lower(User.username).in_(keys), func.lower(User.email).in_(keys)),
                    User.deleted_at.is_(None),
                    User.status != UserStatus.DELETED,
                )
                .limit(1)
            )
        ).first()
        return int(row[0]) if row else None

    # -- links ---------------------------------------------------------------

    async def _link_all(
        self,
        manager_user_id: int,
        delegates: list[dict[str, Any]],
        report: ManagerLinkReport,
        dry_run: bool,
    ) -> None:
        report.delegates_fetched += len(delegates)
        student_ids = [
            int(d["student_id"])
            for d in delegates
            if isinstance(d.get("student_id"), int) or str(d.get("student_id") or "").isdigit()
        ]
        if not student_ids:
            report.delegates_unmatched += len(delegates)
            return

        async with self._factory() as session:
            rows = (
                await session.execute(
                    select(User.id, User.external_student_id).where(
                        User.external_student_id.in_(student_ids),
                        # Same reason as `_by_email`: a deleted student must
                        # not be linked to a manager by the next sync.
                        User.deleted_at.is_(None),
                        User.status != UserStatus.DELETED,
                    )
                )
            ).all()
            by_external = {int(ext): int(uid) for uid, ext in rows}

            for delegate in delegates:
                raw = delegate.get("student_id")
                external = int(raw) if str(raw or "").isdigit() else None
                user_id = by_external.get(external) if external is not None else None

                if user_id is None:
                    # Known about upstream, never imported here. Reported, not invented.
                    report.delegates_unmatched += 1
                    continue
                if user_id == manager_user_id:
                    report.self_links_skipped += 1
                    continue

                if dry_run:
                    report.links_created += 1
                    continue

                # ON CONFLICT DO NOTHING against uq_manager_students_manager_student:
                # the check and the write are one statement, so two pipelines (or a
                # retry) cannot both insert the same pair.
                #
                # **RETURNING, not `rowcount`.** This driver reports `-1` for an
                # insert with nothing to fetch -- and `-1` is truthy, so reading
                # it counted every link as newly created and left
                # `already_linked` permanently at 0, on runs that in fact wrote
                # nothing. With RETURNING, a conflict yields no row and the two
                # cases are actually distinguishable.
                inserted = (
                    await session.execute(
                        pg_insert(ManagedStudent)
                        .values(
                            manager_id=manager_user_id,
                            student_id=user_id,
                            relationship_type="EMPLOYER",
                            is_primary=False,
                        )
                        .on_conflict_do_nothing(constraint="uq_manager_students_manager_student")
                        .returning(ManagedStudent.id)
                    )
                ).scalar_one_or_none()
                if inserted is not None:
                    report.links_created += 1
                else:
                    report.links_existing += 1

            if not dry_run:
                await session.commit()


def _readable(exc: Exception) -> str:
    """A short reason for the report. The exception text, never a traceback --
    these responses carry people's names and must not reach a log line."""
    if isinstance(exc, LaitApiError):
        return f"LAIT did not answer ({exc.status or 'no response'})"
    return f"{type(exc).__name__}: {exc}"[:200]
