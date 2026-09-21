"""Mirror batches, sessions and enrolments into Google Calendar.

Shape: **one Google calendar per batch, one event per session, guests = the people enrolled**
(plus the session's tutor, each student's guardians, and the managers of the organisations
that enrolled them). Administrators are given write access to every batch calendar, so they
can manage the schedule from Google's own interface; everyone else sees their sessions on
their own calendar because they are guests on the events.

The LMS is the source of truth, with one deliberate exception and one deliberate refusal:

* **Time changes made in Google are applied back** to the session (an admin dragging a class
  to another slot is the most natural thing to do in a calendar). Sanity-checked, audited.
* **Guest-list edits made in Google are *not* applied to enrolments.** An enrolment carries a
  fee, a certificate and a grade book; it must not be created or ended by someone typing an
  address into a calendar. A drifted guest list is detected, reported and put back.
* **An event deleted in Google is recreated**, not treated as cancelling the class. To cancel a
  session, delete it in the LMS. (Deleting a session in the LMS deletes its event.)

Everything else about how this runs:

* **Pull first, then push.** Changes made in Google are read before the LMS overwrites them.
* **A digest of what was last pushed** is kept per batch and session, so a re-run with nothing
  changed makes no writes (Google's quotas are per-write, and each write can notify people).
* **One transaction per batch**; a failure in one batch skips it and the run carries on.
* **A dry run reads only the LMS**: it reports what would be created, changed and removed and
  makes no Google or database writes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.config import Settings
from backend.core.errors import AuthorizationError, ServiceUnavailableError, ValidationError
from backend.core.logging import get_logger
from backend.integrations import google_events as ge
from backend.integrations.google_calendar import (
    GoogleApiError, GoogleAuthRevoked, GoogleCalendarClient, GoogleNotFound, GoogleOAuth, build_auth_url,
)
from backend.models.attendance import Attendance
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.google_connection import GoogleChangeRequest, GoogleConnection
from backend.models.guardian import StudentGuardian
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.organization import OrganizationManager
from backend.models.user_sync import UserSyncRun
from backend.security import token_cipher
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.lait_sync_service import LaitSyncService, RunReport, SourceStats
from backend.utils.enums import EnrollmentStatus, Platforms, UserStatus

logger = get_logger("google.calendar")

TOKEN_PURPOSE = "google-calendar-refresh-token:v1"
STATE_TTL_SECONDS = 600
_ACTIVE = (EnrollmentStatus.PENDING, EnrollmentStatus.CONFIRMED, EnrollmentStatus.COMPLETED)
MAX_TIME_SHIFT = timedelta(days=366)
MAX_SESSION_LENGTH = timedelta(hours=24)
ADOPT_WINDOW = timedelta(days=60)


# =============================================================================
# CONNECTION
# =============================================================================


class GoogleConnectionService:
    def __init__(self, session: AsyncSession, settings: Settings, *, oauth_transport=None) -> None:  # noqa: ANN001
        self.session = session
        self.settings = settings
        self._oauth = GoogleOAuth(settings.google, transport=oauth_transport)

    # -- signed state: ties the consent round-trip to the person who started it (CSRF) -------

    def _sign(self, payload: str) -> str:
        key = self.settings.security.jwt_secret.get_secret_value().encode()
        return base64.urlsafe_b64encode(hmac.new(key, payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")

    def make_state(self, user_id: int, *, now: float | None = None) -> str:
        body = base64.urlsafe_b64encode(json.dumps({"u": user_id, "e": int((now or time.time()) + STATE_TTL_SECONDS), "n": secrets.token_hex(8)}).encode()).decode().rstrip("=")
        return f"{body}.{self._sign(body)}"

    def check_state(self, state: str, user_id: int, *, now: float | None = None) -> None:
        try:
            body, sig = state.split(".")
            if not hmac.compare_digest(sig, self._sign(body)):
                raise ValueError
            claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except (ValueError, TypeError):
            raise ValidationError("The sign-in link is not valid. Start again.") from None
        if claims.get("u") != user_id:
            raise AuthorizationError("This sign-in was started by someone else.")
        if (now or time.time()) > claims.get("e", 0):
            raise ValidationError("The sign-in took too long. Start again.")

    # -- operations ------------------------------------------------------------------------

    def authorize_url(self, user: User) -> str:
        problem = self.settings.google.configuration_problem
        if problem:
            raise ServiceUnavailableError(problem)
        return build_auth_url(self.settings.google, self.make_state(user.id))

    async def active(self) -> GoogleConnection | None:
        return (await self.session.execute(select(GoogleConnection).where(GoogleConnection.status == "ACTIVE"))).scalar_one_or_none()

    async def complete(self, code: str, state: str, actor: User) -> GoogleConnection:
        self.check_state(state, actor.id)
        result = await self._oauth.exchange_code(code)
        expected = self.settings.google.email.strip().lower()
        if expected and result["email"] and result["email"] != expected:
            # Connecting the wrong Google account would put the whole schedule in someone's
            # personal calendar. Refuse, and say which account was expected.
            raise ValidationError(f"Signed in as a different Google account. Sign in as {self.settings.google.email}.")
        now = datetime.now(timezone.utc)
        for old in (await self.session.execute(select(GoogleConnection).where(GoogleConnection.status == "ACTIVE"))).scalars():
            old.status, old.disconnected_at = "REVOKED", now
        await self.session.flush()  # the partial unique index allows only one ACTIVE row
        connection = GoogleConnection(
            account_email=result["email"] or expected, refresh_token_enc=token_cipher.encrypt(result["refresh_token"], purpose=TOKEN_PURPOSE),
            scopes=result["scope"], status="ACTIVE", connected_by_user_id=actor.id, connected_at=now,
        )
        self.session.add(connection)
        await self.session.flush()
        audit_service.record(self.session, action=AuditAction.GOOGLE_CONNECT, actor_user_id=actor.id, actor_email=actor.email,
                             entity_type="google_connection", entity_id=connection.id, details={"account": connection.account_email})
        return connection

    async def disconnect(self, actor: User) -> bool:
        connection = await self.active()
        if connection is None:
            return False
        try:
            await self._oauth.revoke(token_cipher.decrypt(connection.refresh_token_enc, purpose=TOKEN_PURPOSE))
        except token_cipher.TokenCipherError:
            pass  # cannot decrypt (key rotated): still disconnect locally
        connection.status, connection.disconnected_at = "REVOKED", datetime.now(timezone.utc)
        audit_service.record(self.session, action=AuditAction.GOOGLE_DISCONNECT, actor_user_id=actor.id, actor_email=actor.email,
                             entity_type="google_connection", entity_id=connection.id, details={"account": connection.account_email})
        return True

    async def status(self) -> dict[str, Any]:
        connection = await self.active()
        g = self.settings.google
        mirrored = (await self.session.execute(select(func.count()).select_from(Batch).where(Batch.google_calendar_id.is_not(None)))).scalar_one()
        return {
            "configured": g.is_configured,
            "problem": g.configuration_problem,
            "connected": connection is not None,
            "account_email": connection.account_email if connection else None,
            "connected_at": connection.connected_at if connection else None,
            "expected_email": g.email or None,
            "redirect_uri": g.redirect_uri,
            "invite_attendees": g.invite_attendees,
            "send_updates": g.send_updates,
            "share_with_admins": g.share_with_admins,
            "pull_session_times": g.pull_session_times,
            "calendars": mirrored,
            "pending_changes": int((await self.session.execute(select(func.count()).select_from(GoogleChangeRequest).where(GoogleChangeRequest.status == "PENDING"))).scalar_one()),
            "admins_can_edit": g.admins_can_edit,
        }


# =============================================================================
# SYNC
# =============================================================================


@dataclass
class GoogleStats:
    batches: SourceStats = field(default_factory=SourceStats)
    calendars: dict[str, int] = field(default_factory=lambda: {"created": 0, "updated": 0, "unchanged": 0, "recreated": 0, "shared": 0})
    events: dict[str, int] = field(default_factory=lambda: {"created": 0, "updated": 0, "unchanged": 0, "deleted": 0, "recreated": 0})
    pulled: dict[str, int] = field(default_factory=lambda: {
        "time_changes": 0, "adopted": 0, "rejected_events": 0, "deleted": 0, "cancelled": 0,
        "guest_drift": 0, "change_requests": 0, "rejected": 0,
    })
    guests_dropped: int = 0
    report: RunReport = field(default_factory=RunReport)

    def as_stats(self) -> dict[str, Any]:
        return {"batches": self.batches.as_dict(), "calendars": self.calendars, "events": self.events,
                "pulled": self.pulled, "guests_dropped": self.guests_dropped, "errors_dropped": self.report.errors_dropped}


@dataclass
class _Loaded:
    batch: Batch
    course_title: str
    sessions: list[Any]
    tutors: dict[int, ge.Guest]
    students: list[ge.Guest]
    guardians: list[ge.Guest]
    managers: list[ge.Guest]


def _name(first: str | None, last: str | None, fallback: str | None) -> str | None:
    return " ".join(p for p in (first, last) if p) or fallback


class GoogleCalendarSyncService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        *,
        client_factory: Callable[[str], GoogleCalendarClient] | None = None,
        token_override: str | None = None,
    ) -> None:
        self._factory = session_factory
        self._settings = settings
        self._client_factory = client_factory
        # Tests only: bypass the stored connection so they never touch the real one.
        self._token_override = token_override
        self._users = LaitSyncService(session_factory, settings)

    # ---------------------------------------------------------------- lifecycle

    async def start(self, *, trigger_type: str, triggered_by_user_id: int | None, dry_run: bool) -> UserSyncRun:
        problem = self._settings.google.configuration_problem
        if problem:
            raise ServiceUnavailableError(problem)
        async with self._factory() as session:
            if self._token_override is None and (await GoogleConnectionService(session, self._settings).active()) is None:
                raise ServiceUnavailableError("Google Calendar is not connected. A Super Admin must connect it first.")
        return await self._users.start(trigger_type=trigger_type, triggered_by_user_id=triggered_by_user_id, dry_run=dry_run, kind="GOOGLE")

    async def run(self, *, trigger_type: str, triggered_by_user_id: int | None, dry_run: bool, batch_ids: list[int] | None = None) -> UserSyncRun:
        run = await self.start(trigger_type=trigger_type, triggered_by_user_id=triggered_by_user_id, dry_run=dry_run)
        return await self.execute(run.id, batch_ids=batch_ids)

    async def execute(self, run_id: int, *, batch_ids: list[int] | None = None) -> UserSyncRun:
        stats = GoogleStats()
        failure: str | None = None
        async with self._factory() as session:
            run = (await session.execute(select(UserSyncRun).where(UserSyncRun.id == run_id))).scalar_one()
            dry_run, triggered_by = run.dry_run, run.triggered_by_user_id
            connection = await GoogleConnectionService(session, self._settings).active() if self._token_override is None else None
            token = self._token_override
            if token is not None:
                pass
            elif connection is not None:
                try:
                    token = token_cipher.decrypt(connection.refresh_token_enc, purpose=TOKEN_PURPOSE)
                except token_cipher.TokenCipherError:
                    failure = "The stored Google connection cannot be read; connect Google again."
            else:
                failure = "Google Calendar is not connected."

        if token is not None:
            try:
                make = self._client_factory or (lambda t: GoogleCalendarClient(self._settings.google, t))
                async with make(token) as client:
                    await self._sync(client, stats, dry_run, triggered_by, batch_ids)
            except GoogleAuthRevoked:
                failure = "Google no longer accepts the connection. A Super Admin must connect it again."
                await self._mark_connection_error(failure)
            except GoogleApiError as exc:
                failure = f"Google: {exc}"[:300]
            except Exception as exc:  # noqa: BLE001 - a run must always be finalised
                failure = f"Unexpected {type(exc).__name__}"
                logger.exception("Google sync crashed")

        status = "FAILED" if failure else ("PARTIAL" if stats.report.errors else "SUCCEEDED")
        async with self._factory.begin() as session:
            run = (await session.execute(select(UserSyncRun).where(UserSyncRun.id == run_id))).scalar_one()
            run.status, run.finished_at, run.stats, run.errors, run.failure_reason = status, datetime.now(timezone.utc), stats.as_stats(), stats.report.errors, failure
            audit_service.record(session, action=AuditAction.GOOGLE_SYNC, actor_user_id=triggered_by, entity_type="user_sync_run", entity_id=run.id,
                                 success=failure is None, details={"dry_run": dry_run, "status": status, "events": stats.events, "calendars": stats.calendars, "pulled": stats.pulled})
            await session.flush()
            session.expunge(run)
        return run

    async def _mark_connection_error(self, message: str) -> None:
        if self._token_override is not None:
            return  # a run using an injected token is not about the stored connection; never touch it
        async with self._factory.begin() as session:
            connection = await GoogleConnectionService(session, self._settings).active()
            if connection is not None:
                connection.status, connection.last_error, connection.disconnected_at = "ERROR", message[:300], datetime.now(timezone.utc)

    # ------------------------------------------------------------------- engine

    async def _sync(self, client: GoogleCalendarClient, stats: GoogleStats, dry_run: bool, actor_id: int | None, batch_ids: list[int] | None) -> None:
        async with self._factory() as session:
            ids = await self._in_scope(session, batch_ids)
            admins = await self._admin_emails(session)
        for batch_pk in ids:
            try:
                await self._batch(client, batch_pk, admins, stats, dry_run, actor_id)
            except GoogleAuthRevoked:
                raise
            except GoogleApiError as exc:
                stats.batches.skipped += 1
                stats.report.error("batch", str(batch_pk), f"Google: {exc}")
            except Exception as exc:  # noqa: BLE001
                logger.exception("Google batch failed")
                stats.batches.skipped += 1
                stats.report.error("batch", str(batch_pk), f"unexpected {type(exc).__name__}")

    async def _in_scope(self, session: AsyncSession, batch_ids: list[int] | None) -> list[int]:
        """Active batches, recent ones, and anything already mirrored (so a closed batch is updated, not orphaned)."""
        if batch_ids:
            return list((await session.execute(select(Batch.id).where(Batch.id.in_(batch_ids)))).scalars())
        horizon = date.today() - timedelta(days=self._settings.google.sync_past_days)
        rows = await session.execute(
            select(Batch.id).where(
                (Batch.google_calendar_id.is_not(None)) | ((Batch.is_active.is_(True)) & ((Batch.end_date.is_(None)) | (Batch.end_date >= horizon)))
            ).order_by(Batch.start_date, Batch.id)
        )
        return list(rows.scalars())

    async def _admin_emails(self, session: AsyncSession) -> tuple[list[str], list[str]]:
        """`(writers, readers)`: who may edit a batch calendar, and who may only look at it.

        Google cannot tell us which person made an edit, so write access to the calendar is the
        only authorisation there is for creating, moving or deleting sessions from Google. Super
        Admins get it; Administrators can see everything but not change it (unless
        `GOOGLE_ADMINS_CAN_EDIT` is set).
        """
        g = self._settings.google
        if not g.share_with_admins:
            return [], []
        owner = g.email.strip().lower()
        rows = await session.execute(
            select(func.lower(User.email), Role.name).join(User.roles).where(
                Role.name.in_(("ADMIN", "SUPER_ADMIN")), User.status == UserStatus.ACTIVE, User.deleted_at.is_(None), User.email.is_not(None)
            )
        )
        writers: set[str] = set()
        readers: set[str] = set()
        for email, role in rows.all():
            if not ge.valid_email(email) or email == owner:
                continue
            (writers if role == "SUPER_ADMIN" or g.admins_can_edit else readers).add(email)
        return sorted(writers), sorted(readers - writers)

    async def _load(self, session: AsyncSession, batch_pk: int) -> _Loaded | None:
        row = (await session.execute(
            select(Batch.id, Batch.batch_code, Batch.is_active, Batch.start_date, Batch.end_date, Batch.google_calendar_id, Batch.google_synced_hash,
                   Batch.google_admins_hash, Batch.google_pulled_at, Course.title).join(Course, Course.id == Batch.course_id).where(Batch.id == batch_pk)
        )).first()
        if row is None:
            return None
        sessions = [SimpleNamespace(**r._mapping) for r in (await session.execute(
            select(BatchSession.id, BatchSession.public_id, BatchSession.session_start_time,
                   # A session saved with only a duration has no stored end; Google needs one, so it is start + duration (an hour if neither).
                   func.coalesce(BatchSession.session_end_time, BatchSession.session_start_time + func.make_interval(0, 0, 0, 0, 0, func.coalesce(BatchSession.duration_minutes, 60))).label("session_end_time"),
                   BatchSession.tutor_id,
                   BatchSession.platform, BatchSession.meeting_link, BatchSession.classroom, BatchSession.student_notes,
                   BatchSession.google_event_id, BatchSession.google_synced_hash, BatchSession.google_synced_at)
            .where(BatchSession.batch_id == batch_pk, BatchSession.cancelled_at.is_(None)).order_by(BatchSession.session_start_time, BatchSession.id)
        )).all()]

        def guest(email: str | None, first: str | None, last: str | None, username: str | None, role: str) -> ge.Guest | None:
            return ge.Guest(email=email, name=_name(first, last, username), role=role) if email else None

        tutor_ids = {s.tutor_id for s in sessions}
        tutors = {
            u.id: guest(u.email, u.first_name, u.last_name, u.username, "tutor")
            for u in (await session.execute(select(User.id, User.email, User.first_name, User.last_name, User.username).where(User.id.in_(tutor_ids)))).all()
        } if tutor_ids else {}

        enrolled = (await session.execute(
            select(User.id, User.email, User.first_name, User.last_name, User.username, Enrollments.organization_id)
            .join(Enrollments, Enrollments.student_id == User.id)
            .where(Enrollments.batch_id == batch_pk, Enrollments.status.in_(_ACTIVE), User.status != UserStatus.DELETED, User.deleted_at.is_(None))
        )).all()
        student_ids = {e.id for e in enrolled}
        org_ids = {e.organization_id for e in enrolled if e.organization_id}
        students = [g for g in (guest(e.email, e.first_name, e.last_name, e.username, "student") for e in enrolled) if g]
        guardians = [
            g for g in (guest(u.email, u.first_name, u.last_name, u.username, "guardian") for u in (await session.execute(
                select(User.email, User.first_name, User.last_name, User.username).join(StudentGuardian, StudentGuardian.guardian_id == User.id)
                .where(StudentGuardian.student_id.in_(student_ids), User.status != UserStatus.DELETED, User.deleted_at.is_(None))
            )).all()) if g
        ] if student_ids else []
        managers = [
            g for g in (guest(u.email, u.first_name, u.last_name, u.username, "manager") for u in (await session.execute(
                select(User.email, User.first_name, User.last_name, User.username).join(OrganizationManager, OrganizationManager.user_id == User.id)
                .where(OrganizationManager.organization_id.in_(org_ids), OrganizationManager.is_active.is_(True), User.status != UserStatus.DELETED, User.deleted_at.is_(None))
            )).all()) if g
        ] if org_ids else []

        batch = SimpleNamespace(**row._mapping)
        return _Loaded(batch=batch, course_title=row.title, sessions=sessions, tutors={k: v for k, v in tutors.items() if v}, students=students, guardians=guardians, managers=managers)

    async def _batch(self, client: GoogleCalendarClient, batch_pk: int, admins: tuple[list[str], list[str]], stats: GoogleStats, dry_run: bool, actor_id: int | None) -> None:
        g = self._settings.google
        async with self._factory() as session:
            loaded = await self._load(session, batch_pk)
        if loaded is None:
            return
        batch = loaded.batch
        if not loaded.sessions and not batch.google_calendar_id:
            stats.batches.skipped += 1
            return
        if not dry_run:
            await self._reconcile_requests(batch_pk)

        view = ge.BatchView(code=batch.batch_code, course_title=loaded.course_title, is_active=batch.is_active,
                            start_date=batch.start_date, end_date=batch.end_date)
        cal_body = ge.build_calendar_body(view, g.calendar_timezone)
        cal_hash = ge.body_hash(cal_body)
        pull_started = datetime.now(timezone.utc)
        calendar_id = batch.google_calendar_id

        # ---- 1. calendar --------------------------------------------------------------
        recreated_calendar = False
        if calendar_id is None:
            stats.calendars["created"] += 1
            if not dry_run:
                calendar_id = (await client.create_calendar(cal_body))["id"]
                await self._save_batch(batch_pk, google_calendar_id=calendar_id, google_synced_hash=cal_hash, google_admins_hash=None, google_pulled_at=pull_started)
                batch.google_admins_hash = None
        elif batch.google_synced_hash != cal_hash:
            stats.calendars["updated"] += 1
            if not dry_run:
                try:
                    await client.patch_calendar(calendar_id, cal_body)
                except GoogleNotFound:  # deleted in Google: make a fresh one, every event died with it
                    calendar_id = (await client.create_calendar(cal_body))["id"]
                    recreated_calendar = True
                    stats.calendars["recreated"] += 1
                    await self._reset_events(batch_pk)
                    for stale in loaded.sessions:
                        stale.google_event_id = stale.google_synced_hash = stale.google_synced_at = None
                await self._save_batch(batch_pk, google_calendar_id=calendar_id, google_synced_hash=cal_hash)
        else:
            stats.calendars["unchanged"] += 1

        # ---- 2. share with administrators: Super Admins write, Administrators view --------
        writers, readers = admins
        admins_hash = hashlib.sha256(("w:" + ",".join(writers) + "|r:" + ",".join(readers)).encode()).hexdigest() if (writers or readers) else None
        if (writers or readers) and (batch.google_admins_hash != admins_hash or recreated_calendar):
            if not dry_run and calendar_id:
                for email, role in [(e, "writer") for e in writers] + [(e, "reader") for e in readers]:
                    await client.share_calendar(calendar_id, email, role)
                    stats.calendars["shared"] += 1
                await self._save_batch(batch_pk, google_admins_hash=admins_hash)

        if calendar_id is None:  # dry run of a batch with no calendar yet: every event would be created
            stats.events["created"] += len(loaded.sessions)
            stats.batches.created += 1
            return

        # ---- 3. pull: read Google-side edits BEFORE the LMS overwrites them ---------------
        forced: set[int] = set()
        if not dry_run and not recreated_calendar and batch.google_pulled_at is not None:
            forced, dirty = await self._pull(client, calendar_id, loaded, batch.google_pulled_at, stats, actor_id)
            if forced or dirty:
                loaded = await self._reload_sessions(loaded, batch_pk)

        # ---- 4. push events ------------------------------------------------------------------
        guests_common = loaded.students + loaded.guardians + loaded.managers
        current_ids: set[str] = set()
        changed = False
        for number, s in enumerate(loaded.sessions, start=1):
            current_ids.add(str(s.public_id))
            guests, dropped = ge.dedupe_guests(guests_common + ([loaded.tutors[s.tutor_id]] if s.tutor_id in loaded.tutors else []), g.max_attendees_per_event)
            if dropped:
                stats.guests_dropped += dropped
                stats.report.error("batch", batch.batch_code, f"session {number}: {dropped} guest(s) over Google's limit were left off")
            body = ge.build_event_body(
                ge.SessionView(public_id=str(s.public_id), number=number, total=len(loaded.sessions), start_utc=s.session_start_time, end_utc=s.session_end_time,
                               tutor_name=loaded.tutors[s.tutor_id].name if s.tutor_id in loaded.tutors else None,
                               platform=s.platform.name if s.platform else None, meeting_link=s.meeting_link, classroom=s.classroom, student_notes=s.student_notes),
                view, guests, invite=g.invite_attendees)
            digest = ge.body_hash(body)
            if s.google_event_id and s.google_synced_hash == digest and s.id not in forced:
                stats.events["unchanged"] += 1
                continue
            changed = True
            verb = "created" if not s.google_event_id else "updated"
            stats.events[verb] += 1
            if dry_run:
                continue
            event_id = s.google_event_id
            try:
                if event_id:
                    await client.patch_event(calendar_id, event_id, body, send_updates=g.send_updates)
                else:
                    event_id = (await client.create_event(calendar_id, body, send_updates=g.send_updates))["id"]
            except GoogleNotFound:  # the event was removed in Google: put it back
                stats.events[verb] -= 1
                stats.events["recreated"] += 1
                event_id = (await client.create_event(calendar_id, body, send_updates=g.send_updates))["id"]
            await self._save_session(s.id, google_event_id=event_id, google_synced_hash=digest, google_synced_at=datetime.now(timezone.utc))

        # ---- 5. remove events whose session no longer exists ----------------------------------
        if not dry_run:
            for event in await client.list_events(calendar_id):
                private = (event.get("extendedProperties") or {}).get("private") or {}
                if private.get(ge.MANAGED_KEY) == "1" and private.get(ge.SESSION_KEY) not in current_ids and event.get("status") != "cancelled":
                    try:
                        await client.delete_event(calendar_id, event["id"], send_updates=g.send_updates)
                        stats.events["deleted"] += 1
                        changed = True
                    except GoogleNotFound:
                        pass
            await self._save_batch(batch_pk, google_synced_at=datetime.now(timezone.utc), google_pulled_at=pull_started)

        if changed:
            stats.batches.updated += 1
        else:
            stats.batches.unchanged += 1

    # ---------------------------------------------------------------------- pull

    async def _pull(self, client: GoogleCalendarClient, calendar_id: str, loaded: _Loaded, since: datetime, stats: GoogleStats, actor_id: int | None) -> tuple[set[int], bool]:
        """Bring what changed in Google into the database. Returns `(sessions to re-push, sessions changed)`.

        * an event **added** to the calendar becomes a session (validated; rejected with a reason
          written on the event if it cannot be one);
        * an event **moved** updates the session's time;
        * an event **deleted** deletes the session -- or cancels it, when it has attendance
          history that must not be destroyed;
        * an event **titled `CANCEL...`** cancels the session (the record is kept);
        * a **guest list** edited becomes a review request; nothing is enrolled or dropped here.
        """
        g = self._settings.google
        by_public = {str(s.public_id): s for s in loaded.sessions}
        events = await client.list_events(calendar_id, updated_min=ge.iso_utc(since), show_deleted=True)
        force: set[int] = set()
        dirty = False
        common = loaded.students + loaded.guardians + loaded.managers

        for event in events:
            private = (event.get("extendedProperties") or {}).get("private") or {}
            managed = private.get(ge.MANAGED_KEY) == "1"

            # ---- an event nobody in the LMS knows about: somebody added it in Google -------------------
            if not managed:
                if event.get("status") == "cancelled" or ge.is_cancel_title(event.get("summary")):
                    continue
                if private.get(ge.REJECTED_KEY) == ge.event_signature(event):
                    continue  # already refused, unchanged since
                dirty = await self._adopt(client, calendar_id, loaded, event, stats, actor_id) or dirty
                continue

            s = by_public.get(private.get(ge.SESSION_KEY, ""))
            if s is None:
                continue

            # ---- deleted in Google -> deleted here (cancelled if it has history) -----------------------
            if event.get("status") == "cancelled":
                await self._drop_session(s, "Deleted in Google Calendar", soft=False, actor_id=actor_id, stats=stats)
                dirty = True
                continue

            # ---- an explicit cancellation --------------------------------------------------------------
            if ge.is_cancel_title(event.get("summary")):
                await self._drop_session(s, "Cancelled in Google Calendar", soft=True, actor_id=actor_id, stats=stats)
                dirty = True
                continue

            # ---- a guest list edited in Google is a proposal, not an enrolment -------------------------
            # Only an edit made AFTER our last write counts. The event Google returns is otherwise our
            # own previous push: if an enrolment has since changed in the LMS, that older guest list
            # differs from what is expected now, and must not be mistaken for someone removing them.
            updated = _parse_updated(event.get("updated"))
            edited_in_google = s.google_synced_at is None or updated is None or updated > _utc(s.google_synced_at)
            kept, _ = ge.dedupe_guests(common + ([loaded.tutors[s.tutor_id]] if s.tutor_id in loaded.tutors else []), g.max_attendees_per_event)
            expected = {x.email for x in kept}
            if g.invite_attendees and edited_in_google and ge.guest_emails(event) != expected:
                stats.pulled["guest_drift"] += 1
                force.add(s.id)  # the calendar is put back to what the LMS says; the proposal waits for a decision
                await self._propose_enrolment_changes(loaded, event, expected, stats)

            if not g.pull_session_times:
                continue
            start, end = ge.parse_google_datetime(event.get("start")), ge.parse_google_datetime(event.get("end"))
            if start is None or end is None:
                continue
            db_start, db_end = _utc(s.session_start_time), _utc(s.session_end_time)
            if (start, end) == (db_start, db_end):
                continue
            if not edited_in_google:
                continue  # the difference predates our last push: it is ours, not an edit
            if end <= start or (end - start) > MAX_SESSION_LENGTH or abs(start - db_start) > MAX_TIME_SHIFT:
                stats.pulled["rejected"] += 1
                stats.report.error("session", str(s.public_id), "a time change made in Google was refused (implausible) and will be put back")
                force.add(s.id)
                continue
            if await self._tutor_clash(s.tutor_id, start, end, exclude=s.id):
                stats.pulled["rejected"] += 1
                stats.report.error("session", str(s.public_id), "a time change made in Google was refused (the tutor is teaching another class then) and will be put back")
                force.add(s.id)
                continue
            await self._apply_time(s, start, end, actor_id)
            stats.pulled["time_changes"] += 1
            force.add(s.id)
        return force, dirty

    # ------------------------------------------------- a session added in Google

    async def _tutor_clash(self, tutor_id: int, start: datetime, end: datetime, *, exclude: int | None = None) -> Any:
        async with self._factory() as session:
            q = select(BatchSession.id).where(
                BatchSession.tutor_id == tutor_id, BatchSession.cancelled_at.is_(None),
                BatchSession.session_start_time < end, BatchSession.session_end_time > start,
            )
            if exclude is not None:
                q = q.where(BatchSession.id != exclude)
            return (await session.execute(q.limit(1))).scalar_one_or_none()

    async def _adopt(self, client: GoogleCalendarClient, calendar_id: str, loaded: _Loaded, event: dict[str, Any], stats: GoogleStats, actor_id: int | None) -> bool:
        """Turn an event added in Google into a session, or say on the event why it cannot be one."""
        start, end = ge.parse_google_datetime(event.get("start")), ge.parse_google_datetime(event.get("end"))
        if start is None or end is None:
            return False  # an all-day note is not a class; leave it alone, unreported
        batch = loaded.batch

        reason: str | None = None
        if end <= start:
            reason = "the end is not after the start"
        elif (end - start) > MAX_SESSION_LENGTH:
            reason = "a session cannot be longer than 24 hours"
        elif (end - start) < timedelta(minutes=5):
            reason = "a session must be at least 5 minutes long"
        elif batch.start_date and start.date() < batch.start_date - ADOPT_WINDOW:
            reason = f"it is more than {ADOPT_WINDOW.days} days before the batch starts"
        elif batch.end_date and start.date() > batch.end_date + ADOPT_WINDOW:
            reason = f"it is more than {ADOPT_WINDOW.days} days after the batch ends"

        tutor_id = None
        if reason is None:
            tutor_id = await self._tutor_for_event(loaded, event)
            if tutor_id is None:
                reason = "no tutor could be worked out (add the tutor as a guest, or the batch needs an existing session to copy)"
        if reason is None and await self._tutor_clash(tutor_id, start, end):  # type: ignore[arg-type]
            reason = "the tutor is already teaching another class at that time"

        if reason is not None:
            stats.pulled["rejected_events"] += 1
            stats.report.error("event", event.get("id", "?"), f"not added as a session: {reason}")
            previous = str(event.get("description") or "")
            note = f"NOT ADDED TO THE LMS: {reason}.\nFix the event and it will be reconsidered.\n\n"
            body = {
                "description": note + (previous.split("\n\n", 1)[1] if previous.startswith("NOT ADDED TO THE LMS") and "\n\n" in previous else previous),
                "colorId": "11",
                "extendedProperties": {"private": {**((event.get("extendedProperties") or {}).get("private") or {}), ge.REJECTED_KEY: ge.event_signature(event)}},
            }
            try:
                await client.patch_event(calendar_id, event["id"], body, send_updates="none")
            except GoogleNotFound:
                pass
            return False

        platform, classroom = ge.parse_location(event.get("location"))
        if platform is None:  # nothing typed: the batch's own delivery is the sensible default
            recent = loaded.sessions[-1] if loaded.sessions else None
            platform = recent.platform.name if recent and recent.platform else "Classroom"
            classroom = recent.classroom if recent else None

        async with self._factory.begin() as session:
            row = BatchSession(
                batch_id=batch.id, tutor_id=tutor_id, session_start_time=start, session_end_time=end,
                duration_minutes=int((end - start).total_seconds() // 60), platform=Platforms(platform), classroom=classroom,
                origin="GOOGLE", google_event_id=event["id"],
            )
            row.attendances = []
            session.add(row)
            await session.flush()
            audit_service.record(session, action=AuditAction.CREATE, actor_user_id=actor_id, entity_type="batch_session", entity_id=row.id,
                                 details={"source": "google_calendar", "batch": batch.batch_code, "starts": ge.iso_utc(start)})
        await self._recount_planned(batch.id)
        stats.pulled["adopted"] += 1
        return True

    async def _tutor_for_event(self, loaded: _Loaded, event: dict[str, Any]) -> int | None:
        emails = [str(a.get("email", "")).lower() for a in event.get("attendees", []) or [] if a.get("email") and not a.get("organizer")]
        if emails:
            async with self._factory() as session:
                found = (await session.execute(
                    select(User.id, func.lower(User.email)).join(User.roles).where(func.lower(User.email).in_(emails), Role.name == "TUTOR", User.deleted_at.is_(None))
                )).all()
            by_email = {e: i for i, e in found}
            for e in emails:
                if e in by_email:
                    return by_email[e]
        counts: dict[int, int] = {}
        for s in loaded.sessions:
            counts[s.tutor_id] = counts.get(s.tutor_id, 0) + 1
        return max(counts, key=counts.get) if counts else None  # type: ignore[arg-type]

    # ------------------------------------------------- a session deleted or cancelled in Google

    async def _drop_session(self, s: Any, reason: str, *, soft: bool, actor_id: int | None, stats: GoogleStats) -> None:
        """Delete the session from the database; keep it (cancelled) when its history must survive.

        History = an attendance register, a recording, or the tutor's notes. Deleting a session
        with those would destroy records of a class that did happen, so it is cancelled instead
        and the reason says so. An explicit `CANCEL` always keeps the record.
        """
        deleted = False
        if not soft:
            try:
                async with self._factory.begin() as session:
                    marked = (await session.execute(select(func.count()).select_from(Attendance).where(Attendance.session_id == s.id))).scalar_one()
                    notes = (await session.execute(select(BatchSession.recording_link, BatchSession.tutor_notes).where(BatchSession.id == s.id))).first()
                    if not marked and not (notes and any(notes)):
                        await session.execute(delete(BatchSession).where(BatchSession.id == s.id))
                        audit_service.record(session, action=AuditAction.DELETE, actor_user_id=actor_id, entity_type="batch_session", entity_id=s.id,
                                             details={"source": "google_calendar", "starts": ge.iso_utc(s.session_start_time)})
                        deleted = True
            except IntegrityError:
                deleted = False  # something else refers to it: fall back to keeping the record
        if deleted:
            stats.pulled["deleted"] += 1
        else:
            note = reason if soft else f"{reason} (kept because it has attendance or notes)"
            async with self._factory.begin() as session:
                await session.execute(update(BatchSession).where(BatchSession.id == s.id).values(
                    cancelled_at=datetime.now(timezone.utc), cancelled_reason=note[:200], google_event_id=None, google_synced_hash=None))
                audit_service.record(session, action=AuditAction.UPDATE, actor_user_id=actor_id, entity_type="batch_session", entity_id=s.id,
                                     details={"source": "google_calendar", "cancelled": note})
            stats.pulled["cancelled"] += 1
        await self._recount_planned(s.batch_id if hasattr(s, "batch_id") else None)

    async def _recount_planned(self, batch_pk: int | None) -> None:
        if batch_pk is None:
            return
        async with self._factory.begin() as session:
            n = (await session.execute(select(func.count()).select_from(BatchSession).where(BatchSession.batch_id == batch_pk, BatchSession.cancelled_at.is_(None)))).scalar_one()
            await session.execute(update(Batch).where(Batch.id == batch_pk).values(number_of_sessions=n))

    # ------------------------------------------------- enrolment proposals

    async def _person_id(self, session: AsyncSession, email: str, *, must_be_student: bool) -> int | None:
        q = select(User.id).where(func.lower(User.email) == email, User.status != UserStatus.DELETED, User.deleted_at.is_(None))
        if must_be_student:
            q = q.join(User.roles).where(Role.name == "STUDENT")
        return (await session.execute(q.limit(1))).scalar_one_or_none()

    async def _propose_enrolment_changes(self, loaded: _Loaded, event: dict[str, Any], expected: set[str], stats: GoogleStats) -> None:
        batch = loaded.batch
        actual = ge.guest_emails(event)
        student_emails = {x.email.lower() for x in loaded.students if ge.valid_email(x.email)}
        where = f"edited on the event at {event.get('start', {}).get('dateTime', '?')}"
        async with self._factory.begin() as session:
            for email in sorted(actual - expected):
                uid = await self._person_id(session, email, must_be_student=True)
                if uid is None:
                    stats.report.error("event", event.get("id", "?"), f"{email} was added in Google but no student account has that email")
                    continue
                await self._open_request(session, batch.id, "ENROL_ADD", uid, email, f"Added as a guest ({where})", stats)
            for email in sorted((student_emails & expected) - actual):
                uid = await self._person_id(session, email, must_be_student=False)
                if uid is not None:
                    await self._open_request(session, batch.id, "ENROL_REMOVE", uid, email, f"Removed as a guest ({where})", stats)

    async def _open_request(self, session: AsyncSession, batch_id: int, kind: str, user_id: int, email: str, note: str, stats: GoogleStats) -> None:
        exists = (await session.execute(select(GoogleChangeRequest.id).where(
            GoogleChangeRequest.batch_id == batch_id, GoogleChangeRequest.email == email, GoogleChangeRequest.kind == kind, GoogleChangeRequest.status == "PENDING"))).first()
        if exists:
            return
        try:
            async with session.begin_nested():
                session.add(GoogleChangeRequest(batch_id=batch_id, kind=kind, user_id=user_id, email=email, status="PENDING", note=note[:300], detected_at=datetime.now(timezone.utc)))
                await session.flush()
            stats.pulled["change_requests"] += 1
        except IntegrityError:
            pass  # a concurrent run opened it first

    async def _reconcile_requests(self, batch_pk: int) -> None:
        """A proposal that no longer describes a difference (someone made the change in the LMS) is closed."""
        async with self._factory.begin() as session:
            pending = (await session.execute(select(GoogleChangeRequest).where(GoogleChangeRequest.batch_id == batch_pk, GoogleChangeRequest.status == "PENDING"))).scalars().all()
            for req in pending:
                enrolled = (await session.execute(select(Enrollments.enrollment_id).where(
                    Enrollments.batch_id == batch_pk, Enrollments.student_id == req.user_id, Enrollments.status.in_(_ACTIVE)).limit(1))).first() is not None
                if (req.kind == "ENROL_ADD" and enrolled) or (req.kind == "ENROL_REMOVE" and not enrolled):
                    req.status, req.decided_at, req.note = "SUPERSEDED", datetime.now(timezone.utc), "Already done in the LMS."

    async def _apply_time(self, s: Any, start: datetime, end: datetime, actor_id: int | None) -> None:
        async with self._factory.begin() as session:
            await session.execute(update(BatchSession).where(BatchSession.id == s.id).values(
                session_start_time=start, session_end_time=end, duration_minutes=int((end - start).total_seconds() // 60)))
            audit_service.record(session, action=AuditAction.UPDATE, actor_user_id=actor_id, entity_type="batch_session", entity_id=s.id,
                                 details={"source": "google_calendar", "from": ge.iso_utc(s.session_start_time), "to": ge.iso_utc(start)})

    async def _reload_sessions(self, loaded: _Loaded, batch_pk: int) -> _Loaded:
        async with self._factory() as session:
            fresh = await self._load(session, batch_pk)
        return fresh or loaded

    # ------------------------------------------------------------------- writes

    async def _save_batch(self, batch_pk: int, **values: Any) -> None:
        async with self._factory.begin() as session:
            await session.execute(update(Batch).where(Batch.id == batch_pk).values(**values))

    async def _save_session(self, session_pk: int, **values: Any) -> None:
        async with self._factory.begin() as session:
            await session.execute(update(BatchSession).where(BatchSession.id == session_pk).values(**values))

    async def _reset_events(self, batch_pk: int) -> None:
        async with self._factory.begin() as session:
            await session.execute(update(BatchSession).where(BatchSession.batch_id == batch_pk).values(google_event_id=None, google_synced_hash=None, google_synced_at=None))


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _parse_updated(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
