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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.permissions import Action, Module, perm
from backend.models import (
    Assignment,
    AssignmentSubmission,
    Attendance,
    Batch,
    BatchSession,
    Course,
    Enrollments,
    Organization,
    OrganizationManager,
)
from backend.models.identity.user import User
from backend.repositories.announcement import AnnouncementRepository
from backend.repositories.messaging import NotificationRepository
from backend.services.mail_service import MailService
from backend.repositories.reporting import ReportingRepository
from backend.schemas.base import PageParams
from backend.schemas.reporting import (
    AssignmentBrief,
    CarePanel,
    CorporateAtRiskEmployee,
    CorporateCourseSummary,
    CorporatePanel,
    DashboardResponse,
    InstitutionPanel,
    PersonalPanel,
    SessionBrief,
    StudentPanel,
    TeachingPanel,
)
from backend.services.metrics import attendance_rate
from backend.services.scope import ScopeResolver
from backend.services.session_service import SessionService
from backend.utils.enums import AttendanceStatus, EnrollmentStatus


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
        self.mail = MailService(session)
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
        corporate = None
        # The caller themselves are always in `cared_for_student_ids`; a panel
        # about "the people in my care" or corporate workforce only means something
        # once somebody else is in it.
        others = enrollment.cared_for_student_ids - {actor.id}
        if others and held.intersection({_ATTENDANCE_READ, _ASSIGNMENT_READ}):
            if actor.is_corporate_manager:
                corporate = await self._corporate(actor, student_ids=others, now=now)
                panels.append("corporate")
                # Also populate care for backward compatibility
                care = CarePanel(
                    people=corporate.total_employees,
                    attendance_rate=corporate.attendance_rate,
                    assignments_overdue=corporate.assignments_overdue,
                    upcoming_sessions=corporate.upcoming_sessions,
                )
            else:
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
            corporate=corporate,
            institution=institution,
        )

    # -- panels --------------------------------------------------------------

    async def _personal(self, actor: User, *, held: set[str], now: datetime) -> PersonalPanel:
        messages = (
            await self.mail.unread_count(actor) if _MESSAGE_READ in held else 0
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
                actor=actor,
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
                batch_ids=batch_ids, tutor_id=None, now=now, actor=actor
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
                actor=actor,
            ),
        )

    async def _corporate(
        self, actor: User, *, student_ids: frozenset[int] | set[int], now: datetime
    ) -> CorporatePanel:
        ids = sorted(student_ids)

        # 1. Organization name, code & manager title
        org_name = None
        org_code = None
        mgr_title = "Corporate Manager"
        org_res = await self.session.execute(
            select(Organization.name, Organization.code, OrganizationManager.title)
            .join(OrganizationManager, OrganizationManager.organization_id == Organization.id)
            .where(
                OrganizationManager.user_id == actor.id,
                OrganizationManager.is_active.is_(True),
            )
        )
        org_row = org_res.first()
        if org_row:
            org_name = org_row[0]
            org_code = org_row[1]
            if org_row[2]:
                mgr_title = org_row[2]
        elif actor.company:
            org_name = actor.company
        else:
            org_name = "Corporate Workforce"

        # 2. Overall attendance rate across team
        counts = await self.reports.attendance_counts(
            visibility=await self.scopes.attendance_visibility(actor), student_ids=ids
        )
        overall_att_rate = _rate(counts)

        # 3. Overall overdue assignments
        _, overdue_count = await self.reports.outstanding_assignments(student_ids=ids, now=now)

        # 4. Enrolled courses per student
        enr_all_res = await self.session.execute(
            select(Enrollments.student_id, Course.title, Batch.batch_code)
            .join(Batch, Batch.id == Enrollments.batch_id)
            .join(Course, Course.id == Batch.course_id)
            .where(Enrollments.student_id.in_(ids))
        )
        student_courses_map: dict[int, list[str]] = {}
        all_enrollments_count = 0
        for sid, ctitle, bcode in enr_all_res.all():
            all_enrollments_count += 1
            if sid not in student_courses_map:
                student_courses_map[sid] = []
            student_courses_map[sid].append(f"{ctitle} ({bcode})")

        # 5. Active courses and cohorts with tutors
        enr_res = await self.session.execute(
            select(
                Course.title,
                Course.code,
                Batch.batch_code,
                Batch.start_date,
                Batch.end_date,
                func.count(Enrollments.enrollment_id),
            )
            .join(Batch, Batch.id == Enrollments.batch_id)
            .join(Course, Course.id == Batch.course_id)
            .where(
                Enrollments.student_id.in_(ids),
                Enrollments.status.in_((EnrollmentStatus.CONFIRMED, EnrollmentStatus.PENDING)),
            )
            .group_by(
                Course.title,
                Course.code,
                Batch.batch_code,
                Batch.start_date,
                Batch.end_date,
            )
            .order_by(Course.title, Batch.batch_code)
        )
        course_summaries: list[CorporateCourseSummary] = []
        active_enrollments = 0
        for row in enr_res.all():
            ctitle, ccode, bcode, sdate, edate, cnt = row
            active_enrollments += int(cnt)

            tutor_res = await self.session.execute(
                select(User.first_name, User.last_name)
                .join(BatchSession, BatchSession.tutor_id == User.id)
                .join(Batch, Batch.id == BatchSession.batch_id)
                .where(Batch.batch_code == bcode)
                .limit(1)
            )
            tutor_row = tutor_res.first()
            tutor_name = f"{tutor_row[0]} {tutor_row[1]}" if tutor_row else "Primary Instructor"

            course_summaries.append(
                CorporateCourseSummary(
                    course_title=ctitle,
                    course_code=ccode,
                    batch_code=bcode,
                    enrollment_count=int(cnt),
                    tutor_name=tutor_name,
                    start_date=sdate,
                    end_date=edate,
                )
            )

        # 6. At-risk employee identification
        # Grouped attendance by student
        student_att_res = await self.session.execute(
            select(
                Attendance.student_id,
                func.count().filter(Attendance.status == AttendanceStatus.PRESENT),
                func.count().filter(Attendance.status == AttendanceStatus.LATE),
                func.count().filter(Attendance.status == AttendanceStatus.ABSENT),
                func.count().filter(Attendance.status == AttendanceStatus.EXCUSED),
            )
            .where(Attendance.student_id.in_(ids))
            .group_by(Attendance.student_id)
        )
        student_att_map: dict[int, tuple[float | None, int, int]] = {}
        for sid, p, l, a, e in student_att_res.all():
            pr = p or 0
            lr = l or 0
            ar = a or 0
            er = e or 0
            tot = pr + lr + ar + er
            rate = attendance_rate(present=pr, late=lr, absent=ar, excused=er)
            student_att_map[sid] = (rate, tot, pr + lr)

        # Overdue assignments per student
        enrolled_courses = (
            select(Batch.course_id, Enrollments.student_id)
            .join(Enrollments, Enrollments.batch_id == Batch.id)
            .where(
                Enrollments.student_id.in_(ids),
                Enrollments.status.in_((EnrollmentStatus.CONFIRMED, EnrollmentStatus.PENDING)),
            )
            .distinct()
            .subquery()
        )
        submitted = (
            select(AssignmentSubmission.id)
            .where(
                AssignmentSubmission.assignment_id == Assignment.id,
                AssignmentSubmission.student_id == enrolled_courses.c.student_id,
            )
            .exists()
        )
        overdue_stmt = (
            select(enrolled_courses.c.student_id, func.count())
            .select_from(Assignment)
            .join(enrolled_courses, Assignment.course_id == enrolled_courses.c.course_id)
            .where(~submitted, Assignment.due_date < now)
            .group_by(enrolled_courses.c.student_id)
        )
        student_overdue_res = await self.session.execute(overdue_stmt)
        student_overdue_map = {row[0]: int(row[1]) for row in student_overdue_res.all()}

        # User entities
        users_res = await self.session.execute(select(User).where(User.id.in_(ids)))
        users_map = {u.id: u for u in users_res.scalars().all()}

        at_risk_list: list[CorporateAtRiskEmployee] = []
        for sid in ids:
            u = users_map.get(sid)
            if not u:
                continue
            name = u.full_name or u.username or f"Employee #{sid}"
            rate_info = student_att_map.get(sid, (0.0, 0, 0))
            student_overdue = student_overdue_map.get(sid, 0)

            rate, tot, att = rate_info

            reasons: list[str] = []
            is_critical = False

            if rate is not None and rate < 75.0:
                if rate < 50.0:
                    is_critical = True
                reasons.append(f"{rate:.1f}% attendance ({att}/{tot} sessions)")

            if student_overdue > 0:
                reasons.append(f"{student_overdue} overdue deliverable{'s' if student_overdue > 1 else ''}")

            if reasons:
                at_risk_list.append(
                    CorporateAtRiskEmployee(
                        user_id=u.id,
                        full_name=name,
                        email=u.email or "",
                        attendance_rate=rate,
                        attended_sessions=att,
                        total_sessions=tot,
                        assignments_overdue=student_overdue,
                        enrolled_courses=student_courses_map.get(sid, []),
                        risk_level="critical" if is_critical else "warning",
                        risk_reason=", ".join(reasons),
                    )
                )

        # Sort: critical first, then lowest attendance rate
        at_risk_list.sort(
            key=lambda x: (
                0 if x.risk_level == "critical" else 1,
                x.attendance_rate if x.attendance_rate is not None else 999.0,
            )
        )

        # 7. Composite workforce training health score
        health_score = 100
        if overall_att_rate is not None and overall_att_rate < 75.0:
            health_score -= int((75.0 - overall_att_rate) * 1.2)
        if ids:
            health_score -= int((len(at_risk_list) / len(ids)) * 25)
        health_score -= min(15, overdue_count * 5)
        health_score = max(20, min(100, health_score))
        health_status = (
            "Optimal"
            if health_score >= 85
            else "Satisfactory"
            if health_score >= 75
            else "Needs Attention"
            if health_score >= 50
            else "Critical Action"
        )

        batch_scope = await self.scopes.visible_batch_ids(actor)
        upcoming = await self._sessions(
            batch_ids=None if batch_scope.unrestricted else sorted(batch_scope.ids),
            tutor_id=None,
            now=now,
            actor=actor,
        )

        return CorporatePanel(
            organization_name=org_name,
            organization_code=org_code,
            manager_title=mgr_title,
            total_employees=len(ids),
            total_enrollments=all_enrollments_count or active_enrollments,
            active_enrollments=active_enrollments,
            attendance_rate=overall_att_rate,
            assignments_overdue=overdue_count,
            at_risk_count=len(at_risk_list),
            health_score=health_score,
            health_status=health_status,
            at_risk_employees=at_risk_list,
            active_courses=course_summaries,
            upcoming_sessions=upcoming,
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
        self, *, batch_ids: list[int] | None, tutor_id: int | None, now: datetime, actor: User
    ) -> list[SessionBrief]:
        rows = await self.reports.upcoming_sessions(
            batch_ids=batch_ids, tutor_id=tutor_id, now=now, limit=_UPCOMING
        )
        # One service decides joinability everywhere, so the dashboard's button
        # and the session page's button can never disagree about the same class.
        sessions = SessionService(self.session)
        briefs = []
        for s, b, c in rows:
            state = sessions.join_state(s, actor=actor)
            briefs.append(
                SessionBrief(
                    public_id=s.public_id,
                    batch_code=b.batch_code,
                    course_title=c.title,
                    starts_at=s.session_start_time,
                    ends_at=s.session_end_time,
                    classroom=s.classroom,
                    join_opens_at=state.opens_at,
                    join_closes_at=state.closes_at,
                    can_join_now=state.can_join_now,
                )
            )
        return briefs


def _rate(counts: dict[AttendanceStatus, int]) -> float | None:
    """Unpack a status->count map into the one shared rate rule."""
    return attendance_rate(
        present=counts.get(AttendanceStatus.PRESENT, 0),
        late=counts.get(AttendanceStatus.LATE, 0),
        absent=counts.get(AttendanceStatus.ABSENT, 0),
        excused=counts.get(AttendanceStatus.EXCUSED, 0),
    )
