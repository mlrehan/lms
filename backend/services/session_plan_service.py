"""Previewing and replacing a batch's sessions.

`preview` proposes sessions from the batch's schedule (or, failing that, from what its existing sessions imply) in the
zone the administrator chose, and changes nothing. `replace` then writes what the administrator settled on, in one
transaction.

What replacing will and will not do to sessions that already exist:

* a session that holds **attendance, a recording or notes** is *protected*. It is never deleted, because deleting it
  would delete a record of something that happened. It stays, and a proposed session that starts at the same moment is
  skipped rather than duplicated;
* every other existing session is *replaceable*, and is replaced only when the caller has confirmed it;
* a proposed session that would double-book its tutor (against other batches, against the sessions being kept, or
  against another proposed session) refuses the whole operation, listing every clash, so nothing is half done.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, ValidationError
from backend.models.attendance import Attendance
from backend.models.attendance_sheet import AttendanceSheet
from backend.models.batch import Batch, BatchSession
from backend.models.identity.user import User
from backend.schemas.session_plan import (
    ExistingSessions, PlanPerson, PlannedSessionOut, PlanRequest, PlanResponse, PlanSettingsOut, ReplaceRequest, ReplaceResponse,
)
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.batch_service import BatchService
from backend.services.mail_audience import display_name
from backend.services.session_planner import (
    PlanError, PlanSettings, carry_schedule, infer_from_sessions, plan_sessions, weekday_name, weekdays_from_text, weekdays_to_text, zone,
)
from backend.services.session_service import SessionService
from backend.utils.enums import Platforms

_UTC = timezone.utc


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=_UTC)


def _minute(value: datetime) -> datetime:
    return _aware(value).astimezone(_UTC).replace(second=0, microsecond=0)


class SessionPlanService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.batches = BatchService(session)
        self.sessions = SessionService(session)

    # -- what exists ---------------------------------------------------------

    async def _existing(self, batch_id: int) -> list[BatchSession]:
        stmt = select(BatchSession).where(BatchSession.batch_id == batch_id, BatchSession.cancelled_at.is_(None)).order_by(BatchSession.session_start_time)
        return list((await self.session.execute(stmt)).scalars().unique())

    async def _protection(self, sessions: list[BatchSession]) -> dict[int, list[str]]:
        """Why each session that must not be deleted must not be deleted (absent = free to replace)."""
        if not sessions:
            return {}
        ids = [s.id for s in sessions]
        reasons: dict[int, list[str]] = {}
        marked = (await self.session.execute(select(Attendance.session_id).where(Attendance.session_id.in_(ids)).distinct())).scalars().all()
        for sid in marked:
            reasons.setdefault(sid, []).append("attendance recorded")
        # A draft register is work somebody has started, even before it holds a single finalized mark.
        started = (await self.session.execute(select(AttendanceSheet.session_id).where(AttendanceSheet.session_id.in_(ids)))).scalars().all()
        for sid in started:
            if "attendance recorded" not in reasons.get(sid, []):
                reasons.setdefault(sid, []).append("attendance started")
        for s in sessions:
            if s.recording_link:
                reasons.setdefault(s.id, []).append("has a recording")
            if (s.tutor_notes or "").strip() or (s.student_notes or "").strip():
                reasons.setdefault(s.id, []).append("has notes")
        return reasons

    # -- preview -------------------------------------------------------------

    async def preview(self, batch_public_id: uuid.UUID, req: PlanRequest, *, actor: User) -> PlanResponse:
        batch = await self.batches.get(batch_public_id, actor=actor)
        try:
            zone(req.timezone)
        except PlanError as exc:
            raise ValidationError(str(exc)) from None
        existing = await self._existing(batch.id)
        protection = await self._protection(existing)

        base = self._defaults(batch, existing, req.timezone)
        weekdays = req.weekdays if req.weekdays is not None else base["weekdays"]
        settings = PlanSettings(
            timezone=req.timezone,
            weekdays=sorted(set(weekdays)),
            start_time=req.start_time if req.start_time is not None else base["start_time"],
            duration_minutes=req.duration_minutes if req.duration_minutes is not None else base["duration_minutes"],
            start_date=req.start_date if req.start_date is not None else base["start_date"],
            end_date=req.end_date if req.end_date is not None else base["end_date"],
            sessions=req.sessions if req.sessions is not None else base["sessions"],
            # "5 Thursdays" describes the count itself; an explicit count from the request wins over it.
            weekly_count=base["weekly_count"] if req.sessions is None and req.weekdays is None else None,
        )
        planned, warnings = plan_sessions(settings)

        tutors = Counter(s.tutor_id for s in existing if s.tutor_id)
        default_tutor = None
        if tutors:
            tutor = (await self.session.execute(select(User).where(User.id == tutors.most_common(1)[0][0]))).scalar_one_or_none()
            if tutor is not None:
                default_tutor = PlanPerson(public_id=tutor.public_id, name=display_name(tutor))
        platforms = Counter(s.platform for s in existing if s.platform)
        default_platform = platforms.most_common(1)[0][0] if platforms else None

        return PlanResponse(
            settings=PlanSettingsOut(
                timezone=req.timezone, weekdays=settings.weekdays, training_days=weekdays_to_text(settings.weekdays),
                start_time=settings.start_time.strftime("%H:%M") if settings.start_time else None, duration_minutes=settings.duration_minutes,
                start_date=settings.start_date, end_date=settings.end_date, sessions=settings.sessions, source=base["source"], note=base["note"],
            ),
            sessions=[
                PlannedSessionOut(index=p.index, start_utc=p.start_utc, end_utc=p.end_utc, start_local=p.start_local.strftime("%Y-%m-%dT%H:%M"),  # type: ignore[union-attr]
                                  duration_minutes=p.duration_minutes, weekday=weekday_name(p.start_local.weekday()))  # type: ignore[union-attr]
                for p in planned
            ],
            warnings=warnings,
            existing=ExistingSessions(
                total=len(existing), protected=len(protection), replaceable=len(existing) - len(protection),
                protected_reasons=sorted({r for rs in protection.values() for r in rs}),
                first_start=_aware(existing[0].session_start_time) if existing else None, last_start=_aware(existing[-1].session_start_time) if existing else None,
            ),
            default_tutor=default_tutor, default_platform=default_platform, batch_code=batch.batch_code, course_title=batch.course.title if batch.course else None,
        )

    def _defaults(self, batch: Batch, existing: list[BatchSession], tz: str) -> dict:
        """Where the plan starts from. The batch's own schedule if it has one, else what its sessions imply."""
        out: dict = dict(weekdays=[], start_time=None, duration_minutes=batch.class_duration_minutes, start_date=batch.start_date, end_date=batch.end_date,
                         sessions=batch.number_of_sessions, weekly_count=None, source="nothing yet", note=None)

        days, weekly = weekdays_from_text(batch.training_days)
        if days and batch.training_start_time is not None:
            base_tz = batch.schedule_timezone or tz
            try:
                first = batch.start_date
                if first is not None:
                    while first.weekday() not in days:
                        first += timedelta(days=1)
                    carried = carry_schedule(batch.training_start_time, days, from_tz=base_tz, to_tz=tz, on=first)
                    shift = carried.day_shift
                    out.update(weekdays=carried.weekdays, start_time=carried.clock, weekly_count=weekly, source="the batch's schedule")
                    if batch.start_date is not None:
                        out["start_date"] = batch.start_date + timedelta(days=shift)
                    if batch.end_date is not None:
                        out["end_date"] = batch.end_date + timedelta(days=shift)
                    if base_tz != tz:
                        out["note"] = (f"The batch is scheduled for {batch.training_start_time.strftime('%H:%M')} {base_tz}; "
                                       f"that is {carried.clock.strftime('%H:%M')} in {tz}, so the same moment is proposed.")
                    return out
            except PlanError:
                pass  # a stored zone that no longer resolves: fall through to what the sessions say

        if existing:
            got = infer_from_sessions([(_aware(s.session_start_time), _aware(s.session_end_time) if s.session_end_time else None) for s in existing], tz)
            local_first = _aware(existing[0].session_start_time).astimezone(zone(tz)).date()
            local_last = _aware(existing[-1].session_start_time).astimezone(zone(tz)).date()
            out.update(weekdays=got.weekdays, start_time=got.start_time, duration_minutes=got.duration_minutes or out["duration_minutes"],
                       start_date=local_first, end_date=local_last, sessions=got.count, source="the existing sessions")
        return out

    # -- replace -------------------------------------------------------------

    async def replace(self, batch_public_id: uuid.UUID, req: ReplaceRequest, *, actor: User) -> ReplaceResponse:
        batch = await self.batches.get(batch_public_id, actor=actor)

        rows = []
        for i, r in enumerate(req.sessions, start=1):
            start = _aware(r.start_utc)
            end = _aware(r.end_utc) if r.end_utc else (start + timedelta(minutes=r.duration_minutes) if r.duration_minutes else None)
            if end is None or end <= start:
                raise ValidationError(f"Session {i}: it must end after it starts.")
            minutes = int((end - start).total_seconds() // 60)
            if not (5 <= minutes <= 24 * 60):
                raise ValidationError(f"Session {i}: a class must last between 5 minutes and 24 hours.")
            rows.append((r, start, end, minutes))
        starts = Counter(_minute(s) for _, s, _, _ in rows)
        dupes = sorted(k.isoformat() for k, n in starts.items() if n > 1)
        if dupes:
            raise ValidationError("Two proposed sessions start at the same moment.", details={"duplicate_starts": dupes})

        tutors: dict[uuid.UUID, User] = {}
        for r, *_ in rows:
            if r.tutor_id not in tutors:
                tutors[r.tutor_id] = await self.sessions._resolve_tutor(r.tutor_id)

        existing = await self._existing(batch.id)
        protection = await self._protection(existing)
        protected = [s for s in existing if s.id in protection]
        replaceable = [s for s in existing if s.id not in protection]
        if replaceable and not req.confirm_replace:
            raise ConflictError(
                f"This batch already has {len(replaceable)} session(s) that would be replaced. Confirm to replace them.",
                details={"replaceable": len(replaceable), "protected": len(protected)},
            )

        kept_starts = {_minute(_aware(s.session_start_time)) for s in protected}
        new = [x for x in rows if _minute(x[1]) not in kept_starts]
        skipped = len(rows) - len(new)

        conflicts = await self._clashes(new, tutors, exclude={s.id for s in replaceable})
        if conflicts:
            raise ConflictError("Some sessions would double-book their tutor.", details={"conflicts": conflicts})

        if replaceable:
            await self.session.execute(delete(BatchSession).where(BatchSession.id.in_([s.id for s in replaceable])))
            await self.session.flush()
        for r, start, end, minutes in new:
            self.session.add(BatchSession(
                batch_id=batch.id, tutor_id=tutors[r.tutor_id].id, session_start_time=start, session_end_time=end, duration_minutes=minutes,
                platform=r.platform, classroom=r.classroom, meeting_link=r.meeting_link, origin="MANUAL",
            ))
        await self.session.flush()

        total = int((await self.session.execute(select(func.count()).select_from(BatchSession).where(BatchSession.batch_id == batch.id, BatchSession.cancelled_at.is_(None)))).scalar_one())
        batch.number_of_sessions = total
        if req.schedule is not None:
            self._save_schedule(batch, req, [s for _, s, _, _ in rows])

        audit_service.record(
            self.session, action=AuditAction.UPDATE, actor_user_id=actor.id, actor_email=actor.email, entity_type="batch", entity_id=batch.id,
            details={"sessions_recreated": {"created": len(new), "replaced": len(replaceable), "kept_protected": len(protected), "skipped": skipped}},
        )
        return ReplaceResponse(created=len(new), replaced=len(replaceable), kept_protected=len(protected), skipped=skipped, total_sessions=total)

    def _save_schedule(self, batch: Batch, req: ReplaceRequest, starts: list[datetime]) -> None:
        sched = req.schedule
        assert sched is not None
        try:
            tz = zone(sched.timezone)
        except PlanError:
            return
        local = sorted(s.astimezone(tz) for s in starts)
        if sched.weekdays:
            batch.training_days = weekdays_to_text(sched.weekdays)
        if local:
            batch.training_start_day, batch.training_end_day = weekday_name(local[0].weekday()), weekday_name(local[-1].weekday())
            batch.start_date, batch.end_date = local[0].date(), local[-1].date()
        if sched.start_time is not None:
            batch.training_start_time = sched.start_time
            if sched.duration_minutes:
                total = sched.start_time.hour * 60 + sched.start_time.minute + sched.duration_minutes
                batch.training_end_time = time((total // 60) % 24, total % 60)
        if sched.duration_minutes:
            batch.class_duration_minutes = sched.duration_minutes
        batch.schedule_timezone = sched.timezone

    async def _clashes(self, new: list, tutors: dict[uuid.UUID, User], *, exclude: set[int]) -> list[dict]:
        """Every place a proposed session would double-book its tutor, so all of them can be fixed in one go."""
        if not new:
            return []
        out: list[dict] = []
        by_tutor: dict[int, list[tuple[int, datetime, datetime]]] = {}
        for i, (r, start, end, _m) in enumerate(new, start=1):
            by_tutor.setdefault(tutors[r.tutor_id].id, []).append((i, start, end))

        for tutor_id, proposed in by_tutor.items():
            lo, hi = min(s for _, s, _ in proposed), max(e for _, _, e in proposed)
            stmt = (select(BatchSession).where(BatchSession.tutor_id == tutor_id, BatchSession.cancelled_at.is_(None), BatchSession.session_end_time.is_not(None),
                                               BatchSession.session_start_time < hi, BatchSession.session_end_time > lo))
            if exclude:
                stmt = stmt.where(BatchSession.id.notin_(exclude))
            others = list((await self.session.execute(stmt)).scalars().unique())
            for i, s, e in proposed:
                for o in others:
                    if _aware(o.session_start_time) < e and _aware(o.session_end_time) > s:  # type: ignore[arg-type]
                        out.append({"session": i, "starts": s.isoformat(), "with_batch": o.batch.batch_code if o.batch else None})
                        break
            ordered = sorted(proposed, key=lambda x: x[1])
            for (i, _s1, e1), (j, s2, _e2) in zip(ordered, ordered[1:]):
                if s2 < e1:
                    out.append({"session": j, "starts": s2.isoformat(), "with_batch": "another proposed session", "overlaps_session": i})
        return out
