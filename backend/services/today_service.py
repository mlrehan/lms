"""Today's classes, as the person asking would describe today.

**"Today" is a local question.** The institution runs across timezones and the
rows are stored in UTC, so a day boundary taken in UTC puts an evening class in
Dhaka on the wrong day for the person teaching it. The window is computed in
the caller's own timezone and then converted, which is the only arrangement
where "today" means what the reader means.

**Three queries, whatever the day looks like.** The sessions, one grouped count
of enrolments, and one window function for the session's ordinal in its batch.
A per-row lookup for the tutor or the headcount would be invisible on a quiet
Tuesday and would be the whole cost of the dashboard at the start of term.

**No meeting link, ever, in this payload.** That is the existing rule for the
dashboard panel and it holds here for the same reason: a listing is drawn for
everyone who can see the class, and a link in it is a link that outlives the
join window. The row says whether a door exists and whether it is open now;
opening it is `POST /sessions/{id}/join`, which checks again.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.logging import get_logger
from backend.core.privacy import visible_username
from backend.models.batch import Batch, BatchSession
from backend.models.enrollment import Enrollments
from backend.models.identity.user import User
from backend.schemas.today import TodayClass, TodayClasses
from backend.services.scope import ScopeResolver
from backend.services.session_service import SessionService
from backend.utils.enums import EnrollmentStatus

logger = get_logger(__name__)


def _zone(user: User) -> ZoneInfo:
    """The caller's timezone, falling back to UTC rather than failing.

    A stale or mistyped zone on a profile must not be able to take the
    dashboard down; showing the wrong day is bad, showing an error is worse,
    and the response says which zone was used so the reader can tell.
    """
    name = (getattr(user, "timezone", None) or "").strip()
    if not name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown timezone on profile", extra={"timezone": name})
        return ZoneInfo("UTC")


class TodayService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.scopes = ScopeResolver(session)
        self.sessions = SessionService(session)

    async def today(self, *, actor: User) -> TodayClasses:
        zone = _zone(actor)
        local_now = datetime.now(zone)
        start_local = datetime.combine(local_now.date(), time.min, tzinfo=zone)
        start = start_local.astimezone(timezone.utc)
        end = (start_local + timedelta(days=1)).astimezone(timezone.utc)

        scope = await self.scopes.visible_session_ids(actor)
        stmt: Select = (
            select(BatchSession)
            .options(
                selectinload(BatchSession.batch).selectinload(Batch.course),
                selectinload(BatchSession.tutor),
            )
            .where(
                BatchSession.session_start_time >= start,
                BatchSession.session_start_time < end,
            )
            .order_by(BatchSession.session_start_time)
        )
        rows = list(
            (await self.session.execute(scope.apply(stmt, BatchSession.id)))
            .scalars()
            .unique()
        )
        if not rows:
            return TodayClasses(timezone=str(zone), date=local_now.date(), classes=[])

        batch_ids = {r.batch_id for r in rows}
        enrolled = await self._enrolled_per_batch(batch_ids)
        ordinals = await self._ordinal_in_batch(batch_ids)

        now = datetime.now(timezone.utc)
        return TodayClasses(
            timezone=str(zone),
            date=local_now.date(),
            classes=[self._row(r, enrolled, ordinals, now, actor) for r in rows],
        )

    async def _enrolled_per_batch(self, batch_ids: set[int]) -> dict[int, int]:
        """One grouped count, not one per class."""
        stmt = (
            select(Enrollments.batch_id, func.count(Enrollments.enrollment_id))
            .where(
                Enrollments.batch_id.in_(batch_ids),
                Enrollments.status == EnrollmentStatus.CONFIRMED,
            )
            .group_by(Enrollments.batch_id)
        )
        return {bid: int(n) for bid, n in (await self.session.execute(stmt)).all()}

    async def _ordinal_in_batch(self, batch_ids: set[int]) -> dict[int, int]:
        """"Session 3 of this batch", computed in the database.

        There is no session-number column -- the number people mean is the
        position in the batch's own order -- so it is a window function rather
        than a stored value that could drift when a class is inserted or moved.
        """
        numbered = (
            select(
                BatchSession.id,
                func.row_number()
                .over(
                    partition_by=BatchSession.batch_id,
                    order_by=BatchSession.session_start_time,
                )
                .label("ordinal"),
            )
            .where(BatchSession.batch_id.in_(batch_ids))
            .subquery()
        )
        stmt = select(numbered.c.id, numbered.c.ordinal)
        return {sid: int(n) for sid, n in (await self.session.execute(stmt)).all()}

    def _row(
        self,
        row: BatchSession,
        enrolled: dict[int, int],
        ordinals: dict[int, int],
        now: datetime,
        actor: User,
    ) -> TodayClass:
        join = self.sessions.join_state(row, actor=actor)
        batch = row.batch
        course = getattr(batch, "course", None)

        starts = row.session_start_time
        ends = row.session_end_time
        if row.cancelled_at is not None:
            status = "cancelled"
        elif ends and now > ends:
            status = "ended"
        elif starts and now >= starts:
            status = "live"
        else:
            status = "upcoming"

        minutes = row.duration_minutes
        if minutes is None and starts and ends:
            minutes = int((ends - starts).total_seconds() // 60)

        return TodayClass(
            public_id=row.public_id,
            course_title=getattr(course, "title", None) or "",
            batch_code=getattr(batch, "batch_code", None) or "",
            session_number=ordinals.get(row.id),
            tutor_name=visible_username(row.tutor) if row.tutor else None,
            enrolled=enrolled.get(row.batch_id, 0),
            starts_at=starts,
            ends_at=ends,
            duration_minutes=minutes,
            platform=getattr(row.platform, "value", row.platform),
            classroom=row.classroom,
            status=status,
            # Whether a door exists -- never the door itself.
            has_meeting_link=bool(row.meeting_link),
            join_opens_at=join.opens_at,
            join_closes_at=join.closes_at,
            can_join_now=join.can_join_now,
        )
