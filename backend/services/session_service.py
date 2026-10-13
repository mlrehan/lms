"""Class session scheduling (spec §8)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.core.video_links import VideoLinkError, parse_video_url
from backend.core.live_class import JoinWindow, join_window
from backend.core.permissions import Action, Module, perm
from backend.models.batch import BatchSession
from backend.models.identity.user import User
from backend.models.resource import Resource
from backend.repositories.session import SessionRepository
from backend.schemas.base import PageParams
from backend.schemas.session import SessionCreateRequest, SessionUpdateRequest
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.batch_service import BatchService
from backend.services.scope import ScopeResolver
from backend.utils.enums import ResourcePermissionLevel, Roles

_OVERRIDE = perm(Module.SESSION, Action.OVERRIDE)
#: Holding this is what separates "may set the meeting link" from "may be given
#: it". Tutors and administrators author a session; everyone else is let into
#: the room by the API, during the window, one join at a time.
_MANAGE = perm(Module.SESSION, Action.UPDATE)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(moment: datetime | None) -> datetime | None:
    """Storage hands back naive UTC on some drivers; comparing that to an aware
    `now()` raises, and a join window that raises is a class nobody can enter."""
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class JoinTicket:
    """One admission to one class."""

    session: BatchSession
    meeting_link: str
    window: JoinWindow
    #: True when the door was shut and the caller's `session.override` opened it.
    #: Recorded on the ticket as well as in the audit trail so the UI can say so.
    overridden: bool


@dataclass(frozen=True)
class RecordingView:
    """What a caller may be told about a class recording."""

    session: BatchSession
    resource: Resource | None
    playback_url: str | None
    #: A path on this API that re-checks permission and then hands the browser
    #: on to the provider's player, for framing inside the session page. Given
    #: to everyone who may read the session, which is the audience entitled to
    #: watch the class back.
    embed_url: str | None
    #: The provider's own URL, in the clear. Staff only -- see `recording`.
    external_url: str | None


@dataclass(frozen=True)
class JoinState:
    """What a *listing* may say about joining, with no link attached."""

    opens_at: datetime | None
    closes_at: datetime | None
    can_join_now: bool


class SessionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.sessions = SessionRepository(session)
        self.batches = BatchService(session)
        self.scopes = ScopeResolver(session)
        self._permission_cache: tuple[int, set[str]] | None = None

    # -- reads ---------------------------------------------------------------

    async def list_sessions(
        self,
        params: PageParams,
        *,
        actor: User,
        batch_public_id: uuid.UUID | None = None,
        starts_after: datetime | None = None,
        starts_before: datetime | None = None,
        tutor_public_id: uuid.UUID | None = None,
        student_public_id: uuid.UUID | None = None,
        mine_only: bool = False,
    ) -> tuple[Sequence[BatchSession], int]:
        batch_id = None
        if batch_public_id is not None:
            batch_id = (await self.batches.get(batch_public_id, actor=actor)).id

        async def person(public_id: uuid.UUID | None) -> int | None:
            if public_id is None:
                return None
            found = (
                await self.session.execute(select(User.id).where(User.public_id == public_id))
            ).scalar_one_or_none()
            # An unknown id narrows to nothing. A filter that quietly does not
            # apply shows the whole timetable and reads as "this person takes
            # every class".
            return found if found is not None else -1

        scope = await self.scopes.visible_session_ids(actor)
        return await self.sessions.search(
            params,
            scope=scope,
            batch_id=batch_id,
            # `mine_only` is the tutor's own timetable and wins over a filter:
            # both narrow the same column, and the caller cannot be two people.
            tutor_id=actor.id if mine_only else await person(tutor_public_id),
            student_id=await person(student_public_id),
            starts_after=starts_after,
            starts_before=starts_before,
        )

    async def calendar(
        self, *, actor: User, start: datetime, end: datetime, batch_public_id: uuid.UUID | None, limit: int
    ) -> Sequence[BatchSession]:
        batch_id = None
        if batch_public_id is not None:
            batch_id = (await self.batches.get(batch_public_id, actor=actor)).id
        scope = await self.scopes.visible_session_ids(actor)
        return await self.sessions.window(scope=scope, start=start, end=end, batch_id=batch_id, limit=limit)

    async def get(self, public_id: uuid.UUID, *, actor: User) -> BatchSession:
        row = await self.sessions.get_by_public_id_full(public_id)
        if row is None:
            raise NotFoundError("Session not found.")

        scope = await self.scopes.visible_session_ids(actor)
        if not scope.allows(row.id):
            raise NotFoundError("Session not found.")
        return row

    # -- joining a class -----------------------------------------------------

    def _held(self, actor: User) -> set[str]:
        """The actor's flattened permissions, resolved once per service instance.

        `join_state` is called per row, and the calendar draws up to 3000 of
        them; re-walking every role's permission collection for each one is
        work proportional to the window for an answer that cannot change
        within a request.
        """
        if self._permission_cache is None or self._permission_cache[0] != actor.id:
            self._permission_cache = (actor.id, ScopeResolver.held_permissions(actor))
        return self._permission_cache[1]

    def can_manage(self, actor: User) -> bool:
        """May this caller see the raw meeting and recording links?

        The people who *author* a session already hold them; withholding the
        link from them would only mean they could not check what they had
        entered. Everyone else is admitted through `join`.
        """
        return _MANAGE in self._held(actor)

    def can_override(self, actor: User) -> bool:
        return _OVERRIDE in self._held(actor)

    def window_for(self, row: BatchSession) -> JoinWindow | None:
        return join_window(
            _aware(row.session_start_time),
            _aware(row.session_end_time),
            duration_minutes=row.duration_minutes,
        )

    def join_state(self, row: BatchSession, *, actor: User) -> JoinState:
        """What a listing may say, with no link attached.

        Deliberately separate from `join`: rendering a countdown must not be
        able to obtain a link as a side effect, and `join` must not be
        something a page calls for every row it draws.
        """
        window = self.window_for(row)
        if window is None:
            return JoinState(opens_at=None, closes_at=None, can_join_now=False)

        open_now = window.contains(_now())
        joinable = bool(row.meeting_link) and row.cancelled_at is None and (
            open_now or self.can_override(actor)
        )
        return JoinState(
            opens_at=window.opens_at, closes_at=window.closes_at, can_join_now=joinable
        )

    async def join(self, public_id: uuid.UUID, *, actor: User) -> JoinTicket:
        """Hand out the meeting link, once, to someone entitled to it right now.

        Every refusal below is a refusal the browser could not have enforced,
        which is the reason the link is not in the session payload to begin
        with.
        """
        row = await self.get(public_id, actor=actor)

        if row.cancelled_at is not None:
            raise ConflictError(
                "This class was cancelled.",
                details={"reason": row.cancelled_reason},
            )

        window = self.window_for(row)
        if window is None:
            raise ConflictError("This class has no scheduled start time yet.")

        if not row.meeting_link:
            # Not an authorization failure: the caller is entitled to join, the
            # tutor simply has not recorded a link. Saying so is what stops a
            # student reporting "access denied" for a scheduling omission.
            raise ConflictError("No meeting link has been added to this class yet.")

        overridden = False
        now = _now()
        if not window.contains(now):
            if not self.can_override(actor):
                # Early and late are different facts, and only one of them is
                # worth waiting for. One message for both would have a student
                # sitting in front of a class that finished yesterday.
                raise ConflictError(
                    "This class is not open to join yet."
                    if now < window.opens_at
                    else "This class has already finished.",
                    details={
                        "opens_at": window.opens_at.isoformat(),
                        "closes_at": window.closes_at.isoformat(),
                    },
                )
            overridden = True

        audit_service.record(
            self.session,
            action=AuditAction.CLASS_JOIN,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="batch_session",
            entity_id=row.id,
            details={
                "batch": row.batch.batch_code if row.batch else None,
                "platform": row.platform.name if row.platform else None,
                # The distinguishing fact for anyone reading the trail later:
                # an ordinary join is noise, a join outside the window is not.
                "outside_window": overridden,
            },
        )
        return JoinTicket(
            session=row, meeting_link=row.meeting_link, window=window, overridden=overridden
        )

    # -- recordings ----------------------------------------------------------

    async def recording(
        self, public_id: uuid.UUID, *, actor: User, audit: bool = False
    ) -> RecordingView:
        """Where this caller may play the class back.

        Two shapes of recording, and they are watched differently.

        A recording **stored in the LMS** gets `playback_url`: a path on this
        API, not a URL to the file, so every request for the bytes is
        re-checked and revoking someone's place in the batch revokes the
        recording with it.

        A recording that lives on the **provider** (a Zoom cloud recording,
        say) cannot be served that way -- the signed media URL behind Zoom's
        player is bound to Zoom's own session and refuses our server outright.
        So it gets `embed_url`, which is also a path on this API: it re-checks
        permission on every request and then hands the browser on to the
        provider's player, which the session page frames. The point of the
        indirection is that the provider's URL is not in this payload and not
        in the page's own DOM, and that the only route to it is one that
        checks, each time, that this caller is still entitled to the class.

        `external_url` is that same provider URL in the clear, for staff only.
        They set it, and they need to be able to check what they entered.
        """
        row = await self.get(public_id, actor=actor)

        stored: Resource | None = None
        if row.recording_resource_id is not None:
            stored = (
                await self.session.execute(
                    select(Resource).where(
                        Resource.id == row.recording_resource_id,
                        # A withdrawn file stops being playable immediately;
                        # leaving it would make soft-delete cosmetic for anyone
                        # who still had the session open.
                        Resource.is_deleted.is_(False),
                    )
                )
            ).scalar_one_or_none()

        watchable = stored is not None or bool(row.recording_link)
        if watchable and audit:
            # Recorded here rather than on the byte stream: a player issues a
            # request per seek, and a viewer who scrubs through an hour would
            # otherwise write dozens of rows saying the same thing. The
            # permission check still runs on every one of those requests; only
            # the *record* is once per playback.
            audit_service.record(
                self.session,
                action=AuditAction.RECORDING_VIEW,
                actor_user_id=actor.id,
                actor_email=actor.email,
                entity_type="batch_session",
                entity_id=row.id,
                details=(
                    {"resource_id": stored.id, "name": stored.name}
                    if stored is not None
                    else {"source": "provider_link"}
                ),
            )

        return RecordingView(
            session=row,
            resource=stored,
            playback_url=(
                f"/sessions/{row.public_id}/recording/stream" if stored else None
            ),
            # A stored recording is the better answer and wins: it plays
            # inside our own player, with no download control we do not
            # control. The provider embed is what is offered when that is all
            # there is.
            embed_url=(
                f"/sessions/{row.public_id}/recording/embed"
                if stored is None and row.recording_link
                else None
            ),
            external_url=row.recording_link if self.can_manage(actor) else None,
        )

    async def resolve_recording_embed(self, public_id: uuid.UUID, *, actor: User) -> str:
        """Authorise watching, and hand back the provider URL to redirect to.

        Separate from `recording` so the redirect is its own authorised act:
        the browser asks for this when it frames the player, and a caller who
        has since lost the class is refused here rather than at the end of a
        token's life.
        """
        row = await self.get(public_id, actor=actor)
        if not row.recording_link:
            raise NotFoundError("No recording is published for this class.")

        # The address a tutor copies is the *page*, and for YouTube and Vimeo
        # the page is not the player: framing it shows the provider's whole
        # site, or nothing at all. `parse_video_url` maps each recognised
        # provider to its documented embed endpoint, and leaves anything it
        # does not recognise exactly as it was -- so a link that worked before
        # this still works.
        try:
            return parse_video_url(row.recording_link).embed_url or row.recording_link
        except VideoLinkError:
            # Stored before the field was validated. Refusing to play it would
            # help nobody; it is returned as it always was, and the next save
            # of that session will reject it.
            return row.recording_link

    async def resolve_recording_stream(
        self, public_id: uuid.UUID, *, actor: User
    ) -> tuple[BatchSession, Resource]:
        """Authorise playback and hand back the object to stream.

        Separate from `recording` because a browser re-requests this on every
        seek: the check runs each time, and the audit row is written once per
        playback request rather than once per page view.
        """
        view = await self.recording(public_id, actor=actor)
        if view.resource is None or not view.resource.path:
            raise NotFoundError("No recording is stored for this class.")
        return view.session, view.resource

    async def attach_recording(
        self, public_id: uuid.UUID, *, resource_public_id: uuid.UUID, actor: User
    ) -> BatchSession:
        """Publish an already-uploaded file to the class as its recording.

        Deliberately a link, not an upload endpoint of its own: the file
        manager already handles storing, versioning and validating uploads, and
        a second path would grow its own quietly different rules.

        EDIT on the resource, not merely the ability to see it. Attaching makes
        a file playable by everyone in the batch, so the bar is "this is yours
        to publish" rather than "you happen to have been shown it" -- otherwise
        a tutor could expose any document they had been sent to a whole class.
        """
        row = await self.get(public_id, actor=actor)

        from backend.services.resource_service import ResourceService  # circular at module scope

        resources = ResourceService(self.session)
        resource = await resources.get(resource_public_id, actor=actor)
        await resources.require_level(resource, actor, ResourcePermissionLevel.EDIT)

        row.recording_resource_id = resource.id

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="batch_session",
            entity_id=row.id,
            details={"recording_resource_id": resource.id, "name": resource.name},
        )
        return row

    async def detach_recording(self, public_id: uuid.UUID, *, actor: User) -> BatchSession:
        """Unpublish the recording. The file itself is untouched -- taking a
        class recording down is not a reason to delete someone's upload."""
        row = await self.get(public_id, actor=actor)
        previous = row.recording_resource_id
        row.recording_resource_id = None

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="batch_session",
            entity_id=row.id,
            details={"recording_resource_id": None, "was": previous},
        )
        return row

    # -- writes --------------------------------------------------------------

    async def create(
        self, batch_public_id: uuid.UUID, payload: SessionCreateRequest, *, actor: User
    ) -> BatchSession:
        batch = await self.batches.get(batch_public_id, actor=actor)
        tutor = await self._resolve_tutor(payload.tutor_id)

        await self._assert_tutor_free(
            tutor_id=tutor.id,
            start=payload.session_start_time,
            end=payload.session_end_time,
        )

        # `duration_minutes` is offered as an alternative to an end time; keep the end so nothing downstream sees a session with no end.
        end_time = payload.session_end_time
        if end_time is None and payload.duration_minutes:
            end_time = payload.session_start_time + timedelta(minutes=payload.duration_minutes)

        row = BatchSession(
            batch_id=batch.id,
            tutor_id=tutor.id,
            session_start_time=payload.session_start_time,
            session_end_time=end_time,
            duration_minutes=payload.duration_minutes or self._derive_duration(payload),
            platform=payload.platform,
            classroom=payload.classroom,
            meeting_link=payload.meeting_link,
            tutor_notes=payload.tutor_notes,
            origin="MANUAL",
        )
        await self.sessions.add_and_flush(row)

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="batch_session",
            entity_id=row.id,
            details={
                "batch": batch.batch_code,
                "tutor": tutor.username,
                "starts": payload.session_start_time.isoformat(),
            },
        )
        return await self.sessions.get_by_public_id_full(row.public_id)  # type: ignore[return-value]

    async def update(
        self, public_id: uuid.UUID, payload: SessionUpdateRequest, *, actor: User
    ) -> BatchSession:
        row = await self.get(public_id, actor=actor)
        changes = payload.model_dump(exclude_unset=True)

        if "tutor_id" in changes and changes["tutor_id"] is not None:
            tutor = await self._resolve_tutor(changes.pop("tutor_id"))
            row.tutor_id = tutor.id

        # A PATCH may move only one endpoint, so the pair is re-checked
        # against stored values -- the schema can only validate what it was
        # sent.
        start = changes.get("session_start_time", row.session_start_time)
        end = changes.get("session_end_time", row.session_end_time)
        if start and end and end <= start:
            raise ConflictError("session_end_time must be after session_start_time.")

        if ("session_start_time" in changes or "session_end_time" in changes) and start:
            await self._assert_tutor_free(
                tutor_id=row.tutor_id, start=start, end=end, exclude_session_id=row.id
            )

        for field, value in changes.items():
            setattr(row, field, value)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="batch_session",
            entity_id=row.id,
            details={"fields": sorted(changes)},
        )
        return row

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        row = await self.get(public_id, actor=actor)

        marked = await self.sessions.count_attendance(row.id)
        if marked:
            # Deleting a session cascades its attendance rows away
            # (`ondelete="CASCADE"`), silently rewriting every affected
            # student's attendance record. A session that actually happened
            # is history, not a scheduling mistake.
            raise ConflictError(
                "This session already has attendance recorded and cannot be deleted.",
                details={"attendance_records": marked},
            )

        entity_id = row.id
        await self.session.delete(row)

        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="batch_session",
            entity_id=entity_id,
        )

    # -- guards --------------------------------------------------------------

    @staticmethod
    def _derive_duration(payload: SessionCreateRequest) -> int | None:
        if payload.session_end_time is None:
            return None
        delta = payload.session_end_time - payload.session_start_time
        return int(delta.total_seconds() // 60) or None

    async def _resolve_tutor(self, public_id: uuid.UUID) -> User:
        stmt = select(User).where(User.public_id == public_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise NotFoundError("User not found.")

        # Assigning a session tutor is an authorization write: it grants that
        # person access to this batch's students (see `services/scope.py`,
        # which reads `batch_sessions.tutor_id` as one of the two routes a
        # tutor reaches a batch).
        if not any((r.name or "").upper() == Roles.TUTOR.value for r in (user.roles or [])):
            raise ValidationError(
                "This user does not hold the TUTOR role.",
                details={"username": user.username},
            )
        return user

    async def _assert_tutor_free(
        self,
        *,
        tutor_id: int,
        start: datetime,
        end: datetime | None,
        exclude_session_id: int | None = None,
    ) -> None:
        clash = await self.sessions.overlapping_for_tutor(
            tutor_id=tutor_id, start=start, end=end, exclude_session_id=exclude_session_id
        )
        if clash is not None:
            raise ConflictError(
                "That tutor is already teaching another session at this time.",
                details={
                    "conflicting_batch": clash.batch.batch_code if clash.batch else None,
                    "starts": clash.session_start_time.isoformat()
                    if clash.session_start_time
                    else None,
                },
            )
