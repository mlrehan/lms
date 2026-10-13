"""Everything about one class session, for the calendar's detail view.

Who may see what is decided here, once, and it reuses the rules the rest of the system already has
rather than inventing a calendar-specific one:

* the *session* must be visible to the caller (the same row scope as the session list);
* the *roster* is the set of enrolments the caller may read (`EnrollmentVisibility`): everyone for an
  administrator, a tutor's own batches, a student's own row, a guardian's wards, a corporate
  manager's employees. So a student never sees classmates and a guardian never sees other children;
* each student's *guardians and managers* (by name), tutor notes and the head-count are shown to administrators and
  the batch's tutors only;
* *email addresses and phone numbers* are shown to nobody but the Super Admin (`core/privacy.py`), tutors included:
  a tutor is told who is in their class, not how to contact them outside the platform.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import NotFoundError
from backend.core.privacy import may_see_contact
from backend.models.attendance import Attendance
from backend.models.batch import BatchSession
from backend.models.enrollment import Enrollments
from backend.models.guardian import StudentGuardian
from backend.models.identity.user import User
from backend.models.organization import ManagedStudent, Organization
from backend.services.scope import ScopeResolver
from backend.services.session_service import SessionService
from backend.utils.enums import EnrollmentStatus

_ROSTER_STATUSES = (EnrollmentStatus.PENDING, EnrollmentStatus.CONFIRMED, EnrollmentStatus.COMPLETED)
_ROSTER_CAP = 500


def _name(user: User) -> str:
    return " ".join(p for p in (user.first_name, user.last_name) if p) or user.username


def _person(user: User, *, contacts: bool, detail: str | None = None) -> dict[str, Any]:
    return {
        "public_id": user.public_id,
        "name": _name(user),
        "email": user.email if contacts else None,
        "phone": (user.mobile or user.phone_number) if contacts else None,
        "detail": detail,
    }


class SessionOverviewService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.scopes = ScopeResolver(session)

    async def overview(self, public_id: uuid.UUID, *, actor: User) -> dict[str, Any]:
        row: BatchSession = await SessionService(self.session).get(public_id, actor=actor)  # 404 if not visible
        batch, course, tutor = row.batch, row.batch.course, row.tutor

        # "Session 3 of 12": position among the batch's live sessions, ties broken by id so it is stable.
        live = (BatchSession.batch_id == row.batch_id) & BatchSession.cancelled_at.is_(None)
        total = int((await self.session.execute(select(func.count()).select_from(BatchSession).where(live))).scalar_one())
        number = int((await self.session.execute(
            select(func.count()).select_from(BatchSession).where(
                live,
                (BatchSession.session_start_time < row.session_start_time)
                | ((BatchSession.session_start_time == row.session_start_time) & (BatchSession.id <= row.id)),
            )
        )).scalar_one())

        visibility = await self.scopes.enrollment_visibility(actor)
        taught = row.batch_id in visibility.taught_batch_ids
        staff = visibility.unrestricted or taught          # sees the whole batch, guardians and managers *by name*
        contacts = may_see_contact()                       # email / phone: Super Admin only (core/privacy.py)

        stmt = visibility.apply(
            select(Enrollments, User)
            .join(User, User.id == Enrollments.student_id)
            .where(Enrollments.batch_id == row.batch_id, Enrollments.status.in_(_ROSTER_STATUSES)),
            batch_column=Enrollments.batch_id, student_column=Enrollments.student_id,
        ).order_by(User.first_name, User.last_name, User.username).limit(_ROSTER_CAP)
        enrolments = (await self.session.execute(stmt)).all()

        student_ids = [u.id for _, u in enrolments]
        attendance = {}
        if student_ids:
            attendance = {sid: st for sid, st in (await self.session.execute(
                select(Attendance.student_id, Attendance.status).where(Attendance.session_id == row.id, Attendance.student_id.in_(student_ids))
            )).all()}

        guardians: dict[int, list[dict[str, Any]]] = {}
        managers: dict[int, list[dict[str, Any]]] = {}
        orgs: dict[int, str] = {}
        if staff and student_ids:
            for link in (await self.session.execute(select(StudentGuardian).where(StudentGuardian.student_id.in_(student_ids)))).scalars():
                guardians.setdefault(link.student_id, []).append(_person(link.guardian, contacts=contacts, detail=link.relationship_type))
            # The manager beside a student is *their* manager, read from the
            # direct link -- not "every manager at the company that paid for
            # this enrolment", which is what listing them by sponsoring
            # organization meant. The company name is still shown, from the
            # enrolment's own sponsorship record.
            org_ids = {e.organization_id for e, _ in enrolments if e.organization_id}
            if org_ids:
                orgs = {o.id: o.name for o in (await self.session.execute(select(Organization).where(Organization.id.in_(org_ids)))).scalars()}
            for link in (await self.session.execute(
                select(ManagedStudent).where(ManagedStudent.student_id.in_(student_ids))
            )).scalars():
                managers.setdefault(link.student_id, []).append(
                    _person(link.manager, contacts=contacts, detail=link.relationship_type)
                )

        roster = [
            {
                "student": _person(u, contacts=contacts),
                "enrollment_status": e.status.value if hasattr(e.status, "value") else str(e.status),
                "attendance": (attendance[u.id].value if hasattr(attendance[u.id], "value") else str(attendance[u.id])) if u.id in attendance else None,
                "organization": orgs.get(e.organization_id) if e.organization_id else None,
                "guardians": guardians.get(u.id, []),
                "managers": managers.get(u.id, []),
            }
            for e, u in enrolments
        ]
        counts: dict[str, int] = {}
        for st in attendance.values():
            key = st.value if hasattr(st, "value") else str(st)
            counts[key] = counts.get(key, 0) + 1

        # The live head-count, not `batches.total_enrollments`, which is a cached figure that can lag. Shown only
        # to people who see the whole batch anyway; a student or guardian gets no class-size number.
        enrolled = None
        if staff:
            enrolled = int((await self.session.execute(
                select(func.count()).select_from(Enrollments).where(Enrollments.batch_id == row.batch_id, Enrollments.status.in_(_ROSTER_STATUSES))
            )).scalar_one())

        sessions = SessionService(self.session)
        manage = sessions.can_manage(actor)
        join = sessions.join_state(row, actor=actor)

        return {
            "public_id": row.public_id,
            "number": number, "total": total,
            "session_start_time": row.session_start_time,
            "session_end_time": row.session_end_time,
            "duration_minutes": row.duration_minutes,
            "platform": row.platform, "classroom": row.classroom,
            # Withheld from anyone who cannot edit the session -- see
            # `SessionService._response`. A roster panel that quietly carried
            # the link would defeat the join window it draws the countdown for.
            "meeting_link": row.meeting_link if manage else None,
            "recording_link": row.recording_link if manage else None,
            "can_manage": manage,
            "join_opens_at": join.opens_at,
            "join_closes_at": join.closes_at,
            "can_join_now": join.can_join_now,
            "has_recording": bool(row.recording_resource_id) or (manage and bool(row.recording_link)),
            "student_notes": row.student_notes,
            "tutor_notes": row.tutor_notes if staff else None,
            "origin": row.origin, "in_google": bool(row.google_event_id),
            "course": {"public_id": course.public_id, "title": course.title, "code": course.code, "level": course.level.value if hasattr(course.level, "value") else str(course.level)},
            "batch": {
                "public_id": batch.public_id, "batch_code": batch.batch_code, "capacity": batch.capacity, "enrolled": enrolled,
                "start_date": batch.start_date, "end_date": batch.end_date, "is_active": batch.is_active,
            },
            "tutor": _person(tutor, contacts=contacts),
            "roster": roster,
            "roster_is_partial": not visibility.unrestricted and not taught,
            "attendance_counts": counts if staff else {},
            "can_see_contacts": contacts,
        }
