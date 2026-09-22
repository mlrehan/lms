"""Notifications and their preferences (spec §21).

Originally written alongside the one-to-one messaging service, which `mail_service.py` has since replaced
because a message arriving was the only thing that emitted one. It is not a
messaging concern: a grade, an enrolment and a security event all produce
notifications, and none of them should have to import the message service to
say so.

**Creation is still not an endpoint.** A notification is something the system
emits as a consequence of an event; an API that lets a client place arbitrary
text in somebody else's tray is a phishing surface carrying the institution's
branding. Services call :meth:`NotificationService.emit`, inside the same
transaction as the thing being announced, so a tray can never hold "your
grade was recorded" for a mark whose insert rolled back.

**Preferences are consulted at emit time, and they fail open.** If the
preference lookup itself fails, the notification is sent: not telling someone
about their grade because a settings query timed out is a worse outcome than
one unwanted row. And four security types cannot be switched off at all --
see `core/notification_types.py` for why a suppressible compromise warning is
worse than none.

Only the `SYSTEM` channel is ever written. `NotificationChannel` also models
EMAIL, SMS and PUSH; **no transport exists for any of them**, so the
preferences API deliberately does not offer per-channel toggles. A switch
that changes nothing is the decorative-field pattern, and on a notification
setting it would have people believing they had turned email on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Iterable, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import NotFoundError, ValidationError
from backend.core.events import EventKind, RealtimeEvent, queue_event
from backend.core.logging import get_logger
from backend.core.notification_types import (
    ALL_TYPES,
    MANDATORY_TYPES,
    NotificationKind,
    assert_known,
)
from backend.models.guardian import StudentGuardian
from backend.models.identity.user import User
from backend.models.notification import Notification, NotificationPreference
from backend.repositories.messaging import NotificationRepository
from backend.schemas.base import PageParams
from backend.utils.enums import NotificationChannel

logger = get_logger(__name__)

# A single event may address a batch's roster, but never an institution.
# Announcements are the broadcast channel and have their own feed; a
# notification is a personal event, and fanning one out past this many people
# means the wrong mechanism was chosen.
MAX_FANOUT = 500


def _now() -> datetime:
    return datetime.now(UTC)


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.notifications = NotificationRepository(session)

    # -- emitting ------------------------------------------------------------

    def emit(
        self,
        *,
        user_id: int,
        type_: str,
        title: str,
        body: str,
        meta: dict[str, Any] | None = None,
        channel: NotificationChannel = NotificationChannel.SYSTEM,
    ) -> Notification:
        """Stage one notification in the caller's transaction.

        Synchronous and unfiltered by preference — this is the low-level form
        kept for the message path, which predates preferences. New emitters
        should use :meth:`notify`, which honours opt-outs.
        """
        assert_known(type_)
        notification = Notification(
            user_id=user_id,
            channel=channel,
            type=type_,
            title=title[:255],
            body=body,
            meta=meta,
            is_read=False,
            sent_at=_now(),
        )
        self.session.add(notification)

        # Queued, not published: `queue_event` releases it only if this
        # transaction commits. A notification is staged inside the caller's
        # transaction precisely so a tray cannot announce something that rolled
        # back, and a chime that beat the commit would undo that guarantee in
        # the most visible way available.
        #
        # `title` and `type` travel with it because both were composed for this
        # recipient by us; nothing here is another person's data, so no privacy
        # rule is being routed around. Anything richer is re-read by the client.
        queue_event(
            self.session.sync_session,
            RealtimeEvent(
                kind=EventKind.NOTIFICATION_CREATED,
                user_id=user_id,
                data={"type": type_, "title": notification.title},
            ),
        )
        return notification

    async def notify(
        self,
        *,
        user_id: int,
        type_: str,
        title: str,
        body: str,
        meta: dict[str, Any] | None = None,
    ) -> Notification | None:
        """Emit unless this person has switched this type off.

        Returns `None` when suppressed, so a caller can tell "sent" from
        "deliberately not sent" — which matters when the next line wants to
        count what was delivered.
        """
        if not await self.wants(user_id, type_):
            return None
        return self.emit(user_id=user_id, type_=type_, title=title, body=body, meta=meta)

    async def notify_many(
        self,
        user_ids: Sequence[int],
        *,
        type_: str,
        title: str,
        body: str,
        meta: dict[str, Any] | None = None,
    ) -> int:
        """Fan one event out to a bounded audience. Returns how many were sent.

        The opt-out set is fetched **once** for the whole audience rather than
        per recipient: a roster of forty otherwise means forty preference
        queries inside one request, and the cost lands on the tutor who
        published the assignment.
        """
        assert_known(type_)
        recipients = list(dict.fromkeys(user_ids))
        if not recipients:
            return 0
        if len(recipients) > MAX_FANOUT:
            raise ValidationError(
                "Too many recipients for a notification; use an announcement.",
                details={"recipients": len(recipients), "limit": MAX_FANOUT},
            )

        opted_out = await self._opted_out(recipients, type_)
        sent = 0
        for user_id in recipients:
            if user_id in opted_out:
                continue
            self.emit(user_id=user_id, type_=type_, title=title, body=body, meta=meta)
            sent += 1
        return sent

    async def notify_guardians_of(
        self,
        student_ids: Sequence[int],
        *,
        type_: str,
        title: str,
        body: str,
        meta: dict[str, Any] | None = None,
    ) -> int:
        """Tell the guardians of these students, naming the child. Returns how many were sent.

        `title` and `body` are templates and may use `{student}`, which is substituted with the child's
        display name. Naming them is the point: a parent of two told only that "a student in your care" was
        set work has to go and find out which, and a guardian of two children in the same course would
        otherwise receive two identical rows.

        Emitted as its own fan-out rather than by appending guardians to the student list, so a large course
        cannot push the combined audience past `MAX_FANOUT` and fail the very thing being announced. It is
        also best effort: a guardian's copy is secondary to the student's own notification, and a failure
        resolving the links must not roll back the grade or the enrolment that prompted it.
        """
        assert_known(type_)
        wanted = list(dict.fromkeys(student_ids))
        if not wanted:
            return 0

        rows = (
            await self.session.execute(
                select(StudentGuardian.guardian_id, StudentGuardian.student_id, User)
                .join(User, User.id == StudentGuardian.student_id)
                .where(StudentGuardian.student_id.in_(wanted))
            )
        ).all()
        # A self-link would have somebody told about their own work in the third person.
        pairs = [(g, s, u) for g, s, u in rows if g != s]
        if not pairs:
            return 0
        if len(pairs) > MAX_FANOUT:
            raise ValidationError(
                "Too many guardians for a notification; use an announcement.",
                details={"recipients": len(pairs), "limit": MAX_FANOUT},
            )

        opted_out = await self._opted_out([g for g, _, _ in pairs], type_)
        sent = 0
        for guardian_id, student_id, student in pairs:
            if guardian_id in opted_out:
                continue
            name = " ".join(p for p in (student.first_name, student.last_name) if p) or student.username
            self.emit(
                user_id=guardian_id,
                type_=type_,
                title=title.format(student=name),
                body=body.format(student=name),
                meta={**(meta or {}), "student_id": str(student.public_id)},
            )
            sent += 1
        return sent

    # -- preferences ---------------------------------------------------------

    async def wants(self, user_id: int, type_: str) -> bool:
        assert_known(type_)
        if type_ in MANDATORY_TYPES:
            return True
        try:
            return user_id not in await self._opted_out([user_id], type_)
        except Exception:  # noqa: BLE001 - see the module docstring
            # Fails open: a settings query that misbehaves must not swallow
            # the news it was asked about.
            logger.exception(
                "Notification preference lookup failed; sending anyway",
                extra={"user_id": user_id, "notification_type": type_},
            )
            return True

    async def _opted_out(self, user_ids: Sequence[int], type_: str) -> set[int]:
        if type_ in MANDATORY_TYPES or not user_ids:
            return set()
        stmt = select(NotificationPreference.user_id).where(
            NotificationPreference.user_id.in_(user_ids),
            NotificationPreference.notification_type == type_,
            NotificationPreference.enabled.is_(False),
        )
        return set((await self.session.execute(stmt)).scalars().all())

    async def preferences(self, *, actor: User) -> list[tuple[NotificationKind, bool]]:
        """Every registered type with this user's setting.

        Built from the catalogue rather than from the stored rows: a type
        added since the user last touched their settings must still appear,
        switched on, instead of being invisible until somebody backfills.
        """
        stmt = select(NotificationPreference).where(
            NotificationPreference.user_id == actor.id
        )
        stored = {
            row.notification_type: row.enabled
            for row in (await self.session.execute(stmt)).scalars().all()
        }
        return [
            (kind, True if kind.mandatory else stored.get(code, True))
            for code, kind in ALL_TYPES.items()
        ]

    async def set_preference(
        self, *, actor: User, type_: str, enabled: bool
    ) -> tuple[NotificationKind, bool]:
        kind = ALL_TYPES.get(type_)
        if kind is None:
            raise NotFoundError("Unknown notification type.")
        if kind.mandatory and not enabled:
            raise ValidationError(
                "This notification cannot be switched off.",
                details={"notification_type": type_, "category": kind.category},
            )

        stmt = select(NotificationPreference).where(
            NotificationPreference.user_id == actor.id,
            NotificationPreference.notification_type == type_,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()

        if enabled:
            # "On" is the absence of a row, so switching back on deletes
            # rather than storing `enabled=True` -- one representation of one
            # state, and the table stays a list of exceptions.
            if row is not None:
                await self.session.delete(row)
        elif row is None:
            self.session.add(
                NotificationPreference(
                    user_id=actor.id, notification_type=type_, enabled=False
                )
            )
        else:
            row.enabled = False

        return kind, enabled

    async def reset_preferences(self, *, actor: User) -> int:
        result = await self.session.execute(
            delete(NotificationPreference).where(
                NotificationPreference.user_id == actor.id
            )
        )
        return int(result.rowcount or 0)

    # -- reads ---------------------------------------------------------------

    async def list_own(
        self,
        params: PageParams,
        *,
        actor: User,
        unread_only: bool = False,
        type_: str | None = None,
    ) -> tuple[Sequence[Notification], int]:
        return await self.notifications.search(
            params, user_id=actor.id, unread_only=unread_only, type_=type_
        )

    async def unread_count(self, *, actor: User) -> int:
        return await self.notifications.unread_count(actor.id)

    async def mark_read(self, public_id: uuid.UUID, *, actor: User) -> Notification:
        notification = await self.notifications.get_own(public_id, user_id=actor.id)
        if notification is None:
            # Scoped by user_id in the query itself, so somebody else's
            # notification is indistinguishable from one that never existed.
            raise NotFoundError("Notification not found.")
        if not notification.is_read:
            notification.is_read = True
        return notification

    async def mark_all_read(self, *, actor: User) -> int:
        return await self.notifications.mark_all_read(actor.id)


def recipients_of(rows: Iterable[Any], attribute: str = "student_id") -> list[int]:
    """Pull a recipient list off a set of rows, de-duplicated, order kept."""
    return list(dict.fromkeys(getattr(r, attribute) for r in rows))
