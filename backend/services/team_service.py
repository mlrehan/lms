"""The people in a viewer's care: a corporate manager's employees, or a guardian's wards.

Who is "in care" is not decided here. It is `EnrollmentVisibility.cared_for_student_ids` -- the same set the
enrolment, attendance and dashboard queries already use -- minus the viewer themselves, so a manager can see
exactly the people the rest of the system already lets them see, and asking for anybody else is a 404 rather
than a 403 (an id outside the set must not be provable to exist).

Every figure is computed for the whole set at once, grouped by student, rather than once per person: a
manager with 300 employees costs the same handful of queries as one with three.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import NotFoundError
from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.attendance import Attendance
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.gradebook import GradeBookEntry, Transcript
from backend.models.guardian import StudentGuardian
from backend.models.identity.user import User
from backend.models.organization import Organization, OrganizationMembership
from backend.schemas.team import (
    TeamAssignment,
    TeamAttendanceBreakdown,
    TeamAttendanceRecord,
    TeamEnrollment,
    TeamMemberDetail,
    TeamMemberSummary,
    TeamNextSession,
    TeamOverview,
)
from backend.services.metrics import attendance_rate
from backend.services.scope import ScopeResolver
from backend.utils.enums import AttendanceStatus, EnrollmentStatus

_ACTIVE = (EnrollmentStatus.PENDING, EnrollmentStatus.CONFIRMED)
_LIVE = (EnrollmentStatus.PENDING, EnrollmentStatus.CONFIRMED, EnrollmentStatus.COMPLETED)
# Below this, or with anything overdue, a person is flagged for the manager's attention.
ATTENDANCE_FLOOR = 75.0
_MIN_RECORDED = 3  # a rate over one or two sessions is noise, not a warning


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _name(u: User) -> str:
    return " ".join(p for p in (u.first_name, u.last_name) if p) or u.username


def _value(x: object) -> str:
    return x.value if hasattr(x, "value") else str(x)  # type: ignore[union-attr]


def _rate(counts: dict[AttendanceStatus, int]) -> float | None:
    return attendance_rate(
        present=counts.get(AttendanceStatus.PRESENT, 0),
        late=counts.get(AttendanceStatus.LATE, 0),
        absent=counts.get(AttendanceStatus.ABSENT, 0),
        excused=counts.get(AttendanceStatus.EXCUSED, 0),
    )


def attention(rate: float | None, recorded: int, overdue: int) -> list[str]:
    """Why a person needs looking at. Empty means they are fine (or there is nothing to judge yet)."""
    reasons: list[str] = []
    if rate is not None and recorded >= _MIN_RECORDED and rate < ATTENDANCE_FLOOR:
        reasons.append(f"Attendance is {rate:.0f}% (below {ATTENDANCE_FLOOR:.0f}%)")
    if overdue:
        reasons.append(f"{overdue} assignment{'s' if overdue != 1 else ''} overdue")
    return reasons


class TeamService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.scopes = ScopeResolver(session)

    async def _people(self, actor: User) -> list[int]:
        cared = (await self.scopes.enrollment_visibility(actor)).cared_for_student_ids
        return sorted(cared - {actor.id})

    # -- list ----------------------------------------------------------------

    async def overview(self, *, actor: User) -> TeamOverview:
        items = await self._summaries(actor, await self._people(actor))
        items.sort(key=lambda m: (not m.needs_attention, m.full_name.lower()))
        rates = [m.attendance_rate for m in items if m.attendance_rate is not None]
        return TeamOverview(
            people=len(items),
            needing_attention=sum(1 for m in items if m.needs_attention),
            average_attendance_rate=round(sum(rates) / len(rates), 1) if rates else None,
            assignments_overdue=sum(m.assignments_overdue for m in items),
            items=items,
        )

    async def _summaries(self, actor: User, ids: list[int]) -> list[TeamMemberSummary]:
        if not ids:
            return []
        s, now = self.session, _now()
        users = {u.id: u for u in (await s.execute(select(User).where(User.id.in_(ids)))).scalars()}

        membership = {
            m.user_id: (org, m)
            for m, org in (
                await s.execute(
                    select(OrganizationMembership, Organization)
                    .join(Organization, Organization.id == OrganizationMembership.organization_id)
                    .where(OrganizationMembership.user_id.in_(ids))
                )
            ).all()
        }
        relation = {
            link.student_id: link.relationship_type
            for link in (
                await s.execute(select(StudentGuardian).where(StudentGuardian.guardian_id == actor.id, StudentGuardian.student_id.in_(ids)))
            ).scalars()
        }

        active: dict[int, int] = {}
        completed: dict[int, int] = {}
        courses: dict[int, list[str]] = {}
        for sid, status, title in (
            await s.execute(
                select(Enrollments.student_id, Enrollments.status, Course.title)
                .join(Batch, Batch.id == Enrollments.batch_id)
                .join(Course, Course.id == Batch.course_id)
                .where(Enrollments.student_id.in_(ids), Enrollments.status.in_((*_ACTIVE, EnrollmentStatus.COMPLETED)))
            )
        ).all():
            if status == EnrollmentStatus.COMPLETED:
                completed[sid] = completed.get(sid, 0) + 1
            else:
                active[sid] = active.get(sid, 0) + 1
                courses.setdefault(sid, []).append(title)

        counts: dict[int, dict[AttendanceStatus, int]] = {}
        for sid, status, n in (
            await s.execute(
                select(Attendance.student_id, Attendance.status, func.count())
                .where(Attendance.student_id.in_(ids))
                .group_by(Attendance.student_id, Attendance.status)
            )
        ).all():
            counts.setdefault(sid, {})[status] = int(n)

        # Assignments on courses they are enrolled on: total, submitted, overdue (no submission and past due).
        enrolled = (
            select(Batch.course_id.label("course_id"), Enrollments.student_id.label("student_id"))
            .join(Enrollments, Enrollments.batch_id == Batch.id)
            .where(Enrollments.student_id.in_(ids), Enrollments.status.in_(_LIVE))
            .distinct()
            .subquery()
        )
        work = {
            sid: (int(t), int(sub), int(over))
            for sid, t, sub, over in (
                await s.execute(
                    select(
                        enrolled.c.student_id,
                        func.count(Assignment.id),
                        func.count(AssignmentSubmission.id),
                        func.count(Assignment.id).filter(AssignmentSubmission.id.is_(None), Assignment.due_date < now),
                    )
                    .select_from(Assignment)
                    .join(enrolled, enrolled.c.course_id == Assignment.course_id)
                    .outerjoin(
                        AssignmentSubmission,
                        (AssignmentSubmission.assignment_id == Assignment.id) & (AssignmentSubmission.student_id == enrolled.c.student_id),
                    )
                    .group_by(enrolled.c.student_id)
                )
            ).all()
        }

        score = {
            sid: (float(got) / float(mx) * 100 if mx else None)
            for sid, got, mx in (
                await s.execute(
                    select(GradeBookEntry.student_id, func.sum(GradeBookEntry.score), func.sum(GradeBookEntry.max_score))
                    .where(GradeBookEntry.student_id.in_(ids))
                    .group_by(GradeBookEntry.student_id)
                )
            ).all()
        }

        gpa: dict[int, float] = {}
        for sid, value in (
            await s.execute(
                select(Transcript.student_id, Transcript.gpa)
                .where(Transcript.student_id.in_(ids), Transcript.gpa.is_not(None))
                .order_by(Transcript.generated_at)
            )
        ).all():
            gpa[sid] = float(value)  # oldest first, so the latest transcript wins

        nxt: dict[int, TeamNextSession] = {}
        for sid, start, code, title in (
            await s.execute(
                select(Enrollments.student_id, BatchSession.session_start_time, Batch.batch_code, Course.title)
                .join(Batch, Batch.id == Enrollments.batch_id)
                .join(Course, Course.id == Batch.course_id)
                .join(BatchSession, BatchSession.batch_id == Batch.id)
                .where(
                    Enrollments.student_id.in_(ids),
                    Enrollments.status.in_(_ACTIVE),
                    BatchSession.cancelled_at.is_(None),
                    BatchSession.session_start_time > now,
                )
                .order_by(BatchSession.session_start_time)
            )
        ).all():
            nxt.setdefault(sid, TeamNextSession(start=start, batch_code=code, course_title=title))

        out: list[TeamMemberSummary] = []
        for uid in ids:
            u = users.get(uid)
            if u is None:
                continue
            org, member = membership.get(uid, (None, None))
            c = counts.get(uid, {})
            rate, recorded = _rate(c), sum(c.values())
            total, submitted, overdue = work.get(uid, (0, 0, 0))
            reasons = attention(rate, recorded, overdue)
            out.append(
                TeamMemberSummary(
                    public_id=u.public_id,
                    full_name=_name(u),
                    status=_value(u.status),
                    last_login=u.last_login,
                    organization=org.name if org else None,
                    department=member.department if member else None,
                    employee_code=member.employee_code if member else None,
                    relationship=relation.get(uid),
                    enrollments_active=active.get(uid, 0),
                    enrollments_completed=completed.get(uid, 0),
                    courses=sorted(set(courses.get(uid, [])))[:5],
                    attendance_rate=rate,
                    sessions_recorded=recorded,
                    assignments_total=total,
                    assignments_submitted=submitted,
                    assignments_overdue=overdue,
                    average_score=round(score[uid], 1) if score.get(uid) is not None else None,
                    gpa=gpa.get(uid),
                    next_session=nxt.get(uid),
                    needs_attention=bool(reasons),
                    attention_reasons=reasons,
                )
            )
        return out

    # -- one person ----------------------------------------------------------

    async def member(self, public_id: uuid.UUID, *, actor: User) -> TeamMemberDetail:
        ids = await self._people(actor)
        s = self.session
        uid = (await s.execute(select(User.id).where(User.public_id == public_id))).scalar_one_or_none()
        if uid is None or uid not in ids:
            raise NotFoundError("Person not found.")
        summary = (await self._summaries(actor, [uid]))[0]
        now = _now()

        att: dict[int, dict[AttendanceStatus, int]] = {}
        for bid, status, n in (
            await s.execute(
                select(BatchSession.batch_id, Attendance.status, func.count())
                .join(BatchSession, BatchSession.id == Attendance.session_id)
                .where(Attendance.student_id == uid)
                .group_by(BatchSession.batch_id, Attendance.status)
            )
        ).all():
            att.setdefault(bid, {})[status] = int(n)
        scores = {
            bid: (float(got) / float(mx) * 100 if mx else None)
            for bid, got, mx in (
                await s.execute(
                    select(GradeBookEntry.batch_id, func.sum(GradeBookEntry.score), func.sum(GradeBookEntry.max_score))
                    .where(GradeBookEntry.student_id == uid)
                    .group_by(GradeBookEntry.batch_id)
                )
            ).all()
        }
        transcripts = {
            t.batch_id: t
            for t in (await s.execute(select(Transcript).where(Transcript.student_id == uid).order_by(Transcript.generated_at))).scalars()
        }

        enrollments: list[TeamEnrollment] = []
        for e, b, c in (
            await s.execute(
                select(Enrollments, Batch, Course)
                .join(Batch, Batch.id == Enrollments.batch_id)
                .join(Course, Course.id == Batch.course_id)
                .where(Enrollments.student_id == uid, Enrollments.status.in_(_LIVE))
                .order_by(Enrollments.enrollment_date.desc())
            )
        ).all():
            counts = att.get(b.id, {})
            tr = transcripts.get(b.id)
            enrollments.append(
                TeamEnrollment(
                    batch_id=b.public_id,
                    batch_code=b.batch_code,
                    course_title=c.title,
                    status=_value(e.status),
                    enrolled_at=e.enrollment_date,
                    attendance=TeamAttendanceBreakdown(
                        present=counts.get(AttendanceStatus.PRESENT, 0),
                        late=counts.get(AttendanceStatus.LATE, 0),
                        absent=counts.get(AttendanceStatus.ABSENT, 0),
                        excused=counts.get(AttendanceStatus.EXCUSED, 0),
                    ),
                    attendance_rate=_rate(counts),
                    score_percent=round(scores[b.id], 1) if scores.get(b.id) is not None else None,
                    overall_grade=tr.overall_grade if tr else None,
                    gpa=float(tr.gpa) if tr and tr.gpa is not None else None,
                )
            )

        enrolled_courses = (
            select(Batch.course_id)
            .join(Enrollments, Enrollments.batch_id == Batch.id)
            .where(Enrollments.student_id == uid, Enrollments.status.in_(_LIVE))
            .distinct()
        )
        assignments: list[TeamAssignment] = []
        for a, sub, c in (
            await s.execute(
                select(Assignment, AssignmentSubmission, Course)
                .join(Course, Course.id == Assignment.course_id)
                .outerjoin(AssignmentSubmission, (AssignmentSubmission.assignment_id == Assignment.id) & (AssignmentSubmission.student_id == uid))
                .where(Assignment.course_id.in_(enrolled_courses))
                .order_by(Assignment.due_date.desc())
                .limit(50)
            )
        ).all():
            status = ("GRADED" if sub.grade is not None else "SUBMITTED") if sub else ("OVERDUE" if a.due_date < now else "PENDING")
            assignments.append(
                TeamAssignment(
                    title=a.title,
                    course_title=c.title,
                    due_date=a.due_date,
                    status=status,
                    submitted_at=sub.submitted_at if sub else None,
                    grade=float(sub.grade) if sub and sub.grade is not None else None,
                    max_score=float(a.max_score),
                )
            )

        recent = [
            TeamAttendanceRecord(session_start=start, batch_code=code, course_title=title, status=_value(st))
            for start, code, title, st in (
                await s.execute(
                    select(BatchSession.session_start_time, Batch.batch_code, Course.title, Attendance.status)
                    .join(BatchSession, BatchSession.id == Attendance.session_id)
                    .join(Batch, Batch.id == BatchSession.batch_id)
                    .join(Course, Course.id == Batch.course_id)
                    .where(Attendance.student_id == uid)
                    .order_by(BatchSession.session_start_time.desc())
                    .limit(20)
                )
            ).all()
        ]

        return TeamMemberDetail(**summary.model_dump(), enrollments=enrollments, assignments=assignments, recent_attendance=recent)
