"""Role-aware dashboard (spec §17).

**A dashboard needs no permission of its own, and that is the design.** It is
an assembly of things the caller can already reach, so the endpoint is open to
any authenticated user and each *panel* is gated on the permission for its own
data. Gating the whole thing on `report.read` would have been the obvious
move and is exactly backwards: neither Student nor Guardian holds it, so the
two roles whose dashboard matters most would have been locked out of their
own.

**A missing permission removes a panel; it never fails the request.** A
dashboard that returns 403 because one tile is unavailable is useless, and the
403 tells the caller nothing they can act on. `panels` names what came back,
so a client renders what it was given rather than guessing from the role.

**Panels are computed only for callers they apply to.** A plain Administrator
never runs the student queries; a student never runs the institution ones. The
cost of the endpoint is therefore proportional to how many hats the caller
actually wears, not to how many the product supports.

Every number goes through the same scope objects the listings use — see
`repositories/reporting.py` for why an unscoped aggregate is a leak rather
than a summary.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.permissions import Action, Module, perm
from backend.models.identity.user import User
from backend.repositories.announcement import AnnouncementRepository
from backend.repositories.messaging import MessageRepository, NotificationRepository
from backend.repositories.reporting import ReportingRepository
from backend.schemas.base import PageParams
from backend.schemas.reporting import (
    AssignmentBrief,
    CarePanel,
    DashboardResponse,
    InstitutionPanel,
    PersonalPanel,
    SessionBrief,
    StudentPanel,
    TeachingPanel,
)
from backend.services.metrics import attendance_rate
from backend.services.scope import ScopeResolver
from backend.utils.enums import AttendanceStatus

_ATTENDANCE_READ = perm(Module.ATTENDANCE, Action.READ)
_ASSIGNMENT_READ = perm(Module.ASSIGNMENT, Action.READ)
_GRADE_READ = perm(Module.GRADE, Action.READ)
_MESSAGE_READ = perm(Module.MESSAGE, Action.READ)
_NOTIFICATION_READ = perm(Module.NOTIFICATION, Action.READ)
_ANNOUNCEMENT_READ = perm(Module.ANNOUNCEMENT, Action.READ)
_SESSION_READ = perm(Module.SESSION, Action.READ)

_UPCOMING = 5
_INSTITUTION_ATTENDANCE_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.reports = ReportingRepository(session)
        self.scopes = ScopeResolver(session)
        self.messages = MessageRepository(session)
        self.notifications = NotificationRepository(session)
        self.announcements = AnnouncementRepository(session)

    async def build(self, *, actor: User) -> DashboardResponse:
        now = _now()
        held = ScopeResolver.held_permissions(actor)
        panels: list[str] = ["personal"]

        personal = await self._personal(actor, held=held, now=now)

        enrollment = await self.scopes.enrollment_visibility(actor)
        unrestricted = ScopeResolver.is_unrestricted(actor)

        student = None
        batches, _ = await self.reports.student_totals(student_id=actor.id)
        if batches:
            student = await self._student(actor, held=held, now=now)
            panels.append("student")

        teaching = None
        if enrollment.taught_batch_ids:
            teaching = await self._teaching(actor, now=now)
            panels.append("teaching")

        care = None
        # The caller themselves are always in `cared_for_student_ids`; a panel
        # about "the people in my care" only means something once somebody
        # else is in it.
        others = enrollment.cared_for_student_ids - {actor.id}
        if others and held.intersection({_ATTENDANCE_READ, _ASSIGNMENT_READ}):
            care = await self._care(actor, student_ids=others, now=now)
            panels.append("care")

        institution = None
        if unrestricted:
            institution = await self._institution(actor, now=now)
            panels.append("institution")

        return DashboardResponse(
            generated_at=now,
            panels=panels,
            personal=personal,
            student=student,
            teaching=teaching,
            care=care,
            institution=institution,
        )

    # -- panels --------------------------------------------------------------

    async def _personal(self, actor: User, *, held: set[str], now: datetime) -> PersonalPanel:
        messages = (
            await self.messages.unread_count(actor.id) if _MESSAGE_READ in held else 0
        )
        notifications = (
            await self.notifications.unread_count(actor.id)
            if _NOTIFICATION_READ in held
            else 0
        )

        announcements = 0
        if _ANNOUNCEMENT_READ in held:
            unrestricted = ScopeResolver.is_unrestricted(actor)
            # Only the total is wanted, so one row is fetched and the count
            # comes from the paginator -- a `limit=1` query rather than
            # loading a feed nobody reads.
            _, announcements = await self.announcements.search(
                PageParams(limit=1, offset=0),
                now=now,
                audience_filter=not unrestricted,
                course_scope=None if unrestricted else await self.scopes.visible_course_ids(actor),
                batch_scope=None if unrestricted else await self.scopes.visible_batch_ids(actor),
                role_names={(r.name or "").upper() for r in (actor.roles or [])},
            )

        return PersonalPanel(
            unread_messages=messages,
            unread_notifications=notifications,
            live_announcements=announcements,
        )

    async def _student(self, actor: User, *, held: set[str], now: datetime) -> StudentPanel:
        batches, courses = await self.reports.student_totals(student_id=actor.id)

        rate = None
        if _ATTENDANCE_READ in held:
            counts = await self.reports.attendance_counts(
                visibility=await self.scopes.attendance_visibility(actor),
                student_ids=[actor.id],
            )
            rate = _rate(counts)

        average = None
        if _GRADE_READ in held:
            average = await self.reports.average_score(student_ids=[actor.id])

        outstanding = overdue = 0
        deadlines: list[AssignmentBrief] = []
        if _ASSIGNMENT_READ in held:
            outstanding, overdue = await self.reports.outstanding_assignments(
                student_ids=[actor.id], now=now
            )
            deadlines = [
                AssignmentBrief(
                    public_id=a.public_id,
                    title=a.title,
                    course_title=c.title,
                    due_date=a.due_date,
                    is_overdue=late,
                )
                for a, c, late in await self.reports.next_deadlines(
                    student_ids=[actor.id], now=now, limit=_UPCOMING
                )
            ]

        upcoming: list[SessionBrief] = []
        if _SESSION_READ in held:
            batch_scope = await self.scopes.visible_batch_ids(actor)
            upcoming = await self._sessions(
                batch_ids=None if batch_scope.unrestricted else sorted(batch_scope.ids),
                tutor_id=None,
                now=now,
            )

        return StudentPanel(
            enrolled_batches=batches,
            active_courses=courses,
            attendance_rate=rate,
            average_score=average,
            assignments_outstanding=outstanding,
            assignments_overdue=overdue,
            upcoming_sessions=upcoming,
            next_deadlines=deadlines,
        )

    async def _teaching(self, actor: User, *, now: datetime) -> TeachingPanel:
        enrollment = await self.scopes.enrollment_visibility(actor)
        batch_ids = sorted(enrollment.taught_batch_ids)

        courses, students = await self.reports.taught_totals(batch_ids=batch_ids)
        work = await self.scopes.work_visibility(actor)
        course_ids = sorted(work.taught_course_ids)

        week = await self.reports.session_count(
            batch_ids=batch_ids, tutor_id=None, start=now, end=now + timedelta(days=7)
        )

        return TeachingPanel(
            batches_taught=len(batch_ids),
            courses_taught=courses,
            students_taught=students,
            sessions_next_7_days=week,
            submissions_awaiting_grading=await self.reports.ungraded_submissions(
                course_ids=course_ids
            ),
            quiz_attempts_awaiting_grading=await self.reports.ungraded_quiz_attempts(
                course_ids=course_ids
            ),
            upcoming_sessions=await self._sessions(
                batch_ids=batch_ids, tutor_id=None, now=now
            ),
        )

    async def _care(
        self, actor: User, *, student_ids: frozenset[int] | set[int], now: datetime
    ) -> CarePanel:
        ids = sorted(student_ids)
        counts = await self.reports.attendance_counts(
            visibility=await self.scopes.attendance_visibility(actor), student_ids=ids
        )
        _, overdue = await self.reports.outstanding_assignments(student_ids=ids, now=now)

        batch_scope = await self.scopes.visible_batch_ids(actor)
        return CarePanel(
            people=len(ids),
            attendance_rate=_rate(counts),
            assignments_overdue=overdue,
            upcoming_sessions=await self._sessions(
                batch_ids=None if batch_scope.unrestricted else sorted(batch_scope.ids),
                tutor_id=None,
                now=now,
            ),
        )

    async def _institution(self, actor: User, *, now: datetime) -> InstitutionPanel:
        counts = await self.reports.institution_counts()
        attendance = await self.reports.attendance_counts(
            visibility=await self.scopes.attendance_visibility(actor),
            since=now - timedelta(days=_INSTITUTION_ATTENDANCE_DAYS),
        )
        return InstitutionPanel(
            **counts,
            attendance_rate_30d=_rate(attendance),
            submissions_awaiting_grading=await self.reports.ungraded_submissions(
                course_ids=None
            ),
        )

    # -- helpers -------------------------------------------------------------

    async def _sessions(
        self, *, batch_ids: list[int] | None, tutor_id: int | None, now: datetime
    ) -> list[SessionBrief]:
        rows = await self.reports.upcoming_sessions(
            batch_ids=batch_ids, tutor_id=tutor_id, now=now, limit=_UPCOMING
        )
        return [
            SessionBrief(
                public_id=s.public_id,
                batch_code=b.batch_code,
                course_title=c.title,
                starts_at=s.session_start_time,
                ends_at=s.session_end_time,
                classroom=s.classroom,
                meeting_link=s.meeting_link,
            )
            for s, b, c in rows
        ]


def _rate(counts: dict[AttendanceStatus, int]) -> float | None:
    """Unpack a status->count map into the one shared rate rule."""
    return attendance_rate(
        present=counts.get(AttendanceStatus.PRESENT, 0),
        late=counts.get(AttendanceStatus.LATE, 0),
        absent=counts.get(AttendanceStatus.ABSENT, 0),
        excused=counts.get(AttendanceStatus.EXCUSED, 0),
    )
