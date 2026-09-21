"""Taking attendance as a piece of work: draft it, submit it, correct it -- and leave a trail.

The rules, in one place:

* **Who may take it.** The session's *assigned tutor*. Anybody else needs `attendance.override` (the Super Admin) and
  is then acting *on behalf of* the assigned tutor: that is recorded on the sheet and on every event, beside who
  actually did it. An Administrator can look but not take a register.
* **Draft is not attendance.** A draft lives on the sheet and is written to `attendances` only when submitted, so an
  unfinished register cannot move any attendance percentage.
* **Submitting needs a complete register** (every enrolled student marked) -- an unmarked student would otherwise be
  silently absent from the record. The legacy `PUT /sessions/{id}/attendance` may submit a partial one, as before.
* **Everything after that is an edit, and edits are events**: who, when, on whose behalf, and exactly which students
  went from what to what.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import and_, case, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from backend.core.permissions import Action, Module, perm
from backend.models.attendance import Attendance
from backend.models.attendance_sheet import AttendanceSheet, AttendanceSheetEvent
from backend.models.batch import Batch, BatchSession
from backend.models.enrollment import Enrollments
from backend.models.identity.user import User
from backend.repositories.enrollment import ACTIVE_STATUSES
from backend.schemas.attendance_sheet import (
    QueueItem, SaveSheetRequest, SheetBatch, SheetChange, SheetEvent, SheetMeta, SheetPermissions, SheetPerson, SheetRow, SheetSession, SheetState,
    SheetSummary, SheetView,
)
from backend.schemas.base import PageParams
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.mail_audience import display_name
from backend.services.metrics import attendance_rate
from backend.services.scope import ScopeResolver
from backend.services.session_service import SessionService
from backend.utils.enums import AttendanceStatus

_OVERRIDE = perm(Module.ATTENDANCE, Action.OVERRIDE)
# A class counts as "pending" once it has started, or is about to.
_PENDING_LEAD = timedelta(hours=1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _person(u: User) -> SheetPerson:
    return SheetPerson(public_id=u.public_id, name=display_name(u))


class AttendanceSheetService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.sessions = SessionService(session)
        self.scopes = ScopeResolver(session)

    # -- authority -----------------------------------------------------------

    @staticmethod
    def _can_override(actor: User) -> bool:
        return _OVERRIDE in ScopeResolver.held_permissions(actor)

    def _permissions(self, actor: User, batch_session: BatchSession) -> SheetPermissions:
        assigned = batch_session.tutor_id == actor.id
        override = self._can_override(actor)
        return SheetPermissions(can_edit=assigned or override, is_assigned_tutor=assigned, would_be_on_behalf=override and not assigned)

    # -- loading -------------------------------------------------------------

    async def _sheet(self, session_id: int) -> AttendanceSheet | None:
        return (await self.session.execute(select(AttendanceSheet).where(AttendanceSheet.session_id == session_id))).scalar_one_or_none()

    async def _roster(self, batch_id: int) -> list[User]:
        rows = await self.session.execute(
            select(User).join(Enrollments, Enrollments.student_id == User.id).where(Enrollments.batch_id == batch_id, Enrollments.status.in_(ACTIVE_STATUSES))
            .order_by(User.first_name, User.last_name, User.id)
        )
        return list(rows.scalars().unique())

    async def _rows(self, session_id: int) -> dict[int, Attendance]:
        return {a.student_id: a for a in (await self.session.execute(select(Attendance).where(Attendance.session_id == session_id))).scalars().unique()}

    async def _users(self, ids: set[int]) -> dict[int, User]:
        if not ids:
            return {}
        return {u.id: u for u in (await self.session.execute(select(User).where(User.id.in_(ids)))).scalars().unique()}

    # -- the sheet -----------------------------------------------------------

    async def view(self, actor: User, session_public_id: uuid.UUID) -> SheetView:
        bs = await self.sessions.get(session_public_id, actor=actor)
        return await self._build(actor, bs)

    async def _build(self, actor: User, bs: BatchSession) -> SheetView:
        sheet = await self._sheet(bs.id)
        roster = await self._roster(bs.batch_id)
        saved = await self._rows(bs.id)

        drafted: dict[str, dict] = {}
        if sheet is not None and sheet.status == "DRAFT":
            drafted = {d["student_id"]: d for d in (sheet.draft or [])}

        rows: list[SheetRow] = []
        for u in roster:
            if sheet is not None and sheet.status == "DRAFT":
                d = drafted.get(str(u.public_id))
                status, remarks = (AttendanceStatus(d["status"]) if d and d.get("status") else None), (d.get("remarks") if d else None)
            else:
                a = saved.get(u.id)
                status, remarks = (a.status, a.remarks) if a else (None, None)
            rows.append(SheetRow(student=_person(u), status=status, remarks=remarks))

        legacy = sheet is None and bool(saved)
        state = SheetState.FINALIZED if legacy or (sheet is not None and sheet.status == "FINALIZED") else SheetState.DRAFT if sheet is not None else SheetState.NOT_STARTED

        ids = {bs.tutor_id}
        if sheet is not None:
            ids |= {i for i in (sheet.assigned_tutor_id, sheet.created_by_id, sheet.updated_by_id, sheet.finalized_by_id) if i}
        users = await self._users(ids)
        person = lambda i: _person(users[i]) if i and i in users else None  # noqa: E731

        meta = SheetMeta(
            state=state, assigned_tutor=person(bs.tutor_id),  # type: ignore[arg-type]
            started_by=person(sheet.created_by_id) if sheet else None, started_at=sheet.created_at if sheet else None,
            last_saved_by=person(sheet.updated_by_id or sheet.created_by_id) if sheet else None, last_saved_at=(sheet.updated_at or sheet.created_at) if sheet else None,
            finalized_by=person(sheet.finalized_by_id) if sheet else None, finalized_at=sheet.finalized_at if sheet else None,
            submitted_on_behalf=bool(sheet and sheet.submitted_on_behalf), legacy=legacy,
        )
        return SheetView(
            session=SheetSession(public_id=bs.public_id, start_time=bs.session_start_time, end_time=bs.session_end_time, platform=bs.platform, classroom=bs.classroom, cancelled=bs.cancelled_at is not None),
            batch=SheetBatch(public_id=bs.batch.public_id, batch_code=bs.batch.batch_code, course_title=bs.batch.course.title if bs.batch.course else None, enrolled=len(roster)),
            meta=meta, permissions=self._permissions(actor, bs), notes=sheet.notes if sheet else None, roster=rows, summary=self._summary(rows),
        )

    @staticmethod
    def _summary(rows: Sequence[SheetRow]) -> SheetSummary:
        c = {s: 0 for s in AttendanceStatus}
        unmarked = 0
        for r in rows:
            if r.status is None:
                unmarked += 1
            else:
                c[r.status] += 1
        return SheetSummary(present=c[AttendanceStatus.PRESENT], late=c[AttendanceStatus.LATE], absent=c[AttendanceStatus.ABSENT], excused=c[AttendanceStatus.EXCUSED],
                            unmarked=unmarked, total=len(rows),
                            rate=attendance_rate(present=c[AttendanceStatus.PRESENT], late=c[AttendanceStatus.LATE], absent=c[AttendanceStatus.ABSENT], excused=c[AttendanceStatus.EXCUSED]))

    # -- saving --------------------------------------------------------------

    async def save(self, actor: User, session_public_id: uuid.UUID, payload: SaveSheetRequest, *, require_complete: bool = True) -> SheetView:
        bs = await self.sessions.get(session_public_id, actor=actor)
        if bs.cancelled_at is not None:
            raise ConflictError("This session was cancelled; attendance cannot be recorded for it.")
        perms = self._permissions(actor, bs)
        if not perms.can_edit:
            raise AuthorizationError("Only the session's assigned tutor can take its attendance.")
        on_behalf = not perms.is_assigned_tutor

        roster = await self._roster(bs.batch_id)
        by_public = {u.public_id: u for u in roster}
        unknown = [e.student_id for e in payload.entries if e.student_id not in by_public]
        if unknown:
            raise ValidationError("Some students are not enrolled in this session's batch.", details={"not_enrolled": len(unknown)})

        sheet = await self._sheet(bs.id)
        saved = await self._rows(bs.id)
        legacy = sheet is None and bool(saved)
        finalized = legacy or (sheet is not None and sheet.status == "FINALIZED")
        now = _now()

        if not payload.submit and finalized:
            raise ConflictError("This register was already submitted. Submit your changes to correct it.")

        if sheet is None:
            sheet = AttendanceSheet(session_id=bs.id, status="FINALIZED" if legacy else "DRAFT", assigned_tutor_id=bs.tutor_id, created_by_id=actor.id, submitted_on_behalf=False)
            self.session.add(sheet)
            await self.session.flush()
            if not legacy:
                self._event(sheet, "STARTED", actor, bs, on_behalf, now, changes={"counts": {}})

        # The marks as they will stand after this request.
        if finalized:
            current = {u.public_id: (a.status, a.remarks) for u in roster if (a := saved.get(u.id))}
        else:
            current = {}
            for d in (sheet.draft or []):
                if d.get("status"):
                    current[uuid.UUID(d["student_id"])] = (AttendanceStatus(d["status"]), d.get("remarks"))
        for e in payload.entries:
            if e.status is None:
                current.pop(e.student_id, None)
            else:
                current[e.student_id] = (e.status, e.remarks)

        sheet.updated_by_id, sheet.updated_at = actor.id, now
        if payload.notes is not None:
            notes_changed = (sheet.notes or "") != payload.notes
            sheet.notes = payload.notes or None
        else:
            notes_changed = False

        if not payload.submit:
            sheet.draft = [{"student_id": str(pid), "status": st.value, "remarks": rem} for pid, (st, rem) in current.items()]
            await self.session.flush()
            return await self._build(actor, bs)

        if require_complete:
            missing = [u for u in roster if u.public_id not in current]
            if missing:
                raise ValidationError(f"{len(missing)} student(s) have not been marked. Mark everyone before submitting.", details={"unmarked": len(missing)})

        changes: list[SheetChange] = []
        for pid, (st, rem) in current.items():
            user = by_public[pid]
            old = saved.get(user.id)
            if old is None:
                self.session.add(Attendance(session_id=bs.id, student_id=user.id, recorded_by=actor.id, status=st, remarks=rem, updated_by_id=actor.id, updated_at=now))
                changes.append(SheetChange(student=display_name(user), was=None, now=st.value, remarks_changed=bool(rem)))
            elif old.status != st or (old.remarks or "") != (rem or ""):
                changes.append(SheetChange(student=display_name(user), was=old.status.value, now=st.value, remarks_changed=(old.remarks or "") != (rem or "")))
                old.status, old.remarks, old.updated_by_id, old.updated_at = st, rem, actor.id, now

        counts = {s.value: sum(1 for st, _ in current.values() if st == s) for s in AttendanceStatus}
        first_submission = not finalized
        sheet.status, sheet.draft = "FINALIZED", None
        if first_submission:
            sheet.finalized_by_id, sheet.finalized_at, sheet.submitted_on_behalf = actor.id, now, on_behalf
            self._event(sheet, "FINALIZED", actor, bs, on_behalf, now, changes={"counts": counts})
        elif changes or notes_changed:
            self._event(sheet, "EDITED", actor, bs, on_behalf, now, changes={
                "counts": counts, "notes_changed": notes_changed,
                "changed": [c.model_dump() for c in changes],
            })

        audit_service.record(
            self.session, action=AuditAction.UPDATE, actor_user_id=actor.id, actor_email=actor.email, entity_type="batch_session", entity_id=bs.id,
            details={"attendance": "submitted" if first_submission else "edited", "on_behalf_of_tutor": on_behalf, "marked": len(current), "changed": len(changes)},
        )
        await self.session.flush()
        return await self._build(actor, bs)

    def _event(self, sheet: AttendanceSheet, action: str, actor: User, bs: BatchSession, on_behalf: bool, at: datetime, *, changes: dict) -> None:
        self.session.add(AttendanceSheetEvent(sheet_id=sheet.id, action=action, actor_id=actor.id, assigned_tutor_id=bs.tutor_id, on_behalf=on_behalf, at=at, changes=changes))

    # -- history -------------------------------------------------------------

    async def history(self, actor: User, session_public_id: uuid.UUID) -> list[SheetEvent]:
        bs = await self.sessions.get(session_public_id, actor=actor)
        sheet = await self._sheet(bs.id)
        if sheet is None:
            return []
        events = list((await self.session.execute(select(AttendanceSheetEvent).where(AttendanceSheetEvent.sheet_id == sheet.id).order_by(AttendanceSheetEvent.id.desc()))).scalars())
        users = await self._users({e.actor_id for e in events} | {e.assigned_tutor_id for e in events})
        out = []
        for e in events:
            ch = e.changes or {}
            out.append(SheetEvent(
                action=e.action, at=e.at, actor=_person(users[e.actor_id]), assigned_tutor=_person(users[e.assigned_tutor_id]), on_behalf=e.on_behalf,
                counts=ch.get("counts", {}), notes_changed=bool(ch.get("notes_changed")), changes=[SheetChange(**c) for c in ch.get("changed", [])],
            ))
        return out

    # -- the work queue ------------------------------------------------------

    async def queue(
        self, actor: User, params: PageParams, *, batch_public_id: uuid.UUID | None, tutor_public_id: uuid.UUID | None, state: str | None,
        starts_from: datetime | None, starts_to: datetime | None,
    ) -> tuple[list[QueueItem], int]:
        """The sessions this person may take or review attendance for.

        A tutor sees only the sessions **assigned to them**. An administrator or the Super Admin sees every session,
        and can narrow by batch and tutor -- the Batch -> Session -> Tutor path the Super Admin works down.
        """
        unrestricted = ScopeResolver.is_unrestricted(actor)
        enrolled = (select(func.count()).select_from(Enrollments).where(Enrollments.batch_id == BatchSession.batch_id, Enrollments.status.in_(ACTIVE_STATUSES)).correlate(BatchSession).scalar_subquery())
        has_rows = exists().where(Attendance.session_id == BatchSession.id)
        state_expr = case(
            (AttendanceSheet.status == "FINALIZED", "FINALIZED"), (AttendanceSheet.status == "DRAFT", "DRAFT"),
            (has_rows, "FINALIZED"), else_="NOT_STARTED",
        )

        where = [BatchSession.cancelled_at.is_(None)]
        if not unrestricted:
            where.append(BatchSession.tutor_id == actor.id)
        if batch_public_id is not None:
            where.append(Batch.public_id == batch_public_id)
        if tutor_public_id is not None:
            where.append(BatchSession.tutor_id == select(User.id).where(User.public_id == tutor_public_id).scalar_subquery())
        if starts_from is not None:
            where.append(BatchSession.session_start_time >= starts_from)
        if starts_to is not None:
            where.append(BatchSession.session_start_time <= starts_to)
        if state == "PENDING":
            where.append(state_expr != "FINALIZED")
            where.append(BatchSession.session_start_time <= _now() + _PENDING_LEAD)
        elif state in ("NOT_STARTED", "DRAFT", "FINALIZED"):
            where.append(state_expr == state)

        base = select(BatchSession, Batch, AttendanceSheet, state_expr.label("st"), enrolled.label("enrolled")).join(Batch, Batch.id == BatchSession.batch_id).outerjoin(
            AttendanceSheet, AttendanceSheet.session_id == BatchSession.id).where(and_(*where))
        total = int((await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
        rows = (await self.session.execute(base.order_by(BatchSession.session_start_time.desc(), BatchSession.id.desc()).limit(params.limit).offset(params.offset))).all()

        users = await self._users({bs.tutor_id for bs, *_ in rows})
        override = self._can_override(actor)
        items: list[QueueItem] = []
        for bs, batch, sheet, st, n in rows:
            marked = len(sheet.draft or []) if sheet is not None and sheet.status == "DRAFT" else (int(n or 0) if st == "FINALIZED" else 0)
            items.append(QueueItem(
                session_id=bs.public_id, start_time=bs.session_start_time, end_time=bs.session_end_time, batch_id=batch.public_id, batch_code=batch.batch_code,
                course_title=batch.course.title if batch.course else None, tutor=_person(users[bs.tutor_id]), enrolled=int(n or 0), state=SheetState(st), marked=marked,
                submitted_on_behalf=bool(sheet and sheet.submitted_on_behalf), finalized_at=sheet.finalized_at if sheet else None,
                can_edit=bs.tutor_id == actor.id or override,
            ))
        return items, total
