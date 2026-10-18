"""The numbers on the sidebar badges.

**One request, not fourteen.** Every badge is answered by a single endpoint,
because the alternative is fourteen round trips on every page load and on every
realtime hint. The cost is therefore one connection held briefly rather than
fourteen acquired in parallel.

**A key the caller may not see is absent, not zero.** Returning `0` for a
count somebody is not entitled to would be a lie that happens to be safe today
and a leak the moment the number stops being zero -- and a client cannot tell
"you have none" from "you may not know". Absence is unambiguous: the console
renders no badge at all.

**Counts go through the same scope objects the listings use.** A badge saying
47 beside a screen that lists 3 is worse than no badge, and an unscoped
aggregate is a leak rather than a summary: it tells a tutor how many batches
exist in the institution. Everything here is built from `ScopeResolver`, so a
badge and the screen behind it can only ever disagree if the listing is wrong.

**An assessment badge means "what is waiting for *you*".** That is a different
query per role, deliberately:

* a student sees work they have not handed in;
* somebody who marks sees work waiting to be marked;
* a guardian or corporate manager sees neither, because neither is their
  responsibility -- they are watching somebody else do it, and a number they
  cannot act on is noise. The key is omitted for them.

Reading that as "the badge means different things to different people" is
correct, and is the point: the badge answers "is there anything for me to do
here?", which is the only question a sidebar badge can usefully answer.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.permissions import Action, Module, perm
from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.exam import Exam, ExamResult
from backend.models.guardian import StudentGuardian
from backend.models.identity.permission import Permission
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.notification import Announcement, AnnouncementRead
from backend.models.quiz import Quiz, QuizAttempt
from backend.repositories.messaging import NotificationRepository
from backend.services.mail_service import MailService
from backend.services.scope import ScopeResolver
from backend.utils.enums import (
    AssessmentState,
    EnrollmentStatus,
    SubmissionState,
    UserStatus,
)

_ANNOUNCEMENT_READ = perm(Module.ANNOUNCEMENT, Action.READ)
_ASSIGNMENT_GRADE = perm(Module.ASSIGNMENT, Action.GRADE)
_ASSIGNMENT_READ = perm(Module.ASSIGNMENT, Action.READ)
_ASSIGNMENT_SUBMIT = perm(Module.ASSIGNMENT, Action.SUBMIT)
_BATCH_READ = perm(Module.BATCH, Action.READ)
_ENROLLMENT_READ = perm(Module.ENROLLMENT, Action.READ)
_EXAM_GRADE = perm(Module.EXAM, Action.GRADE)
_EXAM_READ = perm(Module.EXAM, Action.READ)
_GUARDIAN_READ = perm(Module.GUARDIAN, Action.READ)
_MESSAGE_READ = perm(Module.MESSAGE, Action.READ)
_NOTIFICATION_READ = perm(Module.NOTIFICATION, Action.READ)
_PERMISSION_READ = perm(Module.PERMISSION, Action.READ)
_QUIZ_ATTEMPT = perm(Module.QUIZ, Action.ATTEMPT)
_QUIZ_GRADE = perm(Module.QUIZ, Action.GRADE)
_QUIZ_READ = perm(Module.QUIZ, Action.READ)
_ROLE_READ = perm(Module.ROLE, Action.READ)
_SESSION_READ = perm(Module.SESSION, Action.READ)

#: States that mean the student has done their part. Anything else is
#: outstanding from their point of view -- `RESUBMISSION_REQUIRED` very much
#: included, since the work has come back to them.
_HANDED_IN = {
    SubmissionState.SUBMITTED,
    SubmissionState.LATE,
    SubmissionState.UNDER_REVIEW,
    SubmissionState.GRADED,
    SubmissionState.PUBLISHED,
    SubmissionState.ABSENT,
    SubmissionState.EXEMPTED,
    SubmissionState.REASSESSED,
}

#: Waiting for a human to look at it.
_AWAITING_MARKING = {
    SubmissionState.SUBMITTED,
    SubmissionState.LATE,
    SubmissionState.UNDER_REVIEW,
}

#: An assessment a student can actually see and act on.
_LIVE = {AssessmentState.PUBLISHED}


def applicable_badges(held: set[str], *, unrestricted: bool) -> set[str]:
    """Which badge keys this permission set may see at all.

    Pure, and separate from counting them, because *which* numbers a caller may
    see is the security question and *what* those numbers are is merely
    arithmetic. Keeping the rule here means it can be checked against every
    role without a database, and the service below asks this function rather
    than repeating the conditions -- so the rule and the behaviour cannot drift.

    The institution-wide totals are gated on seeing the whole institution
    (`institution.view_all`), not on a role name: the console's rule throughout
    is that access follows what a caller may do. In this deployment that means
    Super Admin and Administrator.
    """
    keys: set[str] = set()

    if unrestricted:
        keys |= {"courses", "users"}
        if _ROLE_READ in held:
            keys.add("roles")
        if _PERMISSION_READ in held:
            keys.add("permissions")
        if _GUARDIAN_READ in held:
            keys.add("guardians")

    if _BATCH_READ in held:
        keys.add("batches")
    if _SESSION_READ in held:
        keys.add("sessions")
    if _ENROLLMENT_READ in held:
        keys.add("enrollments")
    if _MESSAGE_READ in held:
        keys.add("messages")
    if _NOTIFICATION_READ in held:
        keys.add("notifications")
    if _ANNOUNCEMENT_READ in held:
        keys.add("announcements")

    # An assessment badge answers "what is waiting for me?", so it exists only
    # for somebody with a part to play. A guardian or corporate manager is
    # watching somebody else do the work: a number they cannot act on is noise,
    # and the key is omitted rather than sent as zero.
    marks = bool({_ASSIGNMENT_GRADE, _QUIZ_GRADE, _EXAM_GRADE} & held)
    if marks:
        if _ASSIGNMENT_GRADE in held and _ASSIGNMENT_READ in held:
            keys.add("assignments")
        if _QUIZ_GRADE in held and _QUIZ_READ in held:
            keys.add("quizzes")
        if _EXAM_GRADE in held and _EXAM_READ in held:
            keys.add("exams")
        return keys

    if {_ASSIGNMENT_SUBMIT, _QUIZ_ATTEMPT} & held:
        if _ASSIGNMENT_SUBMIT in held and _ASSIGNMENT_READ in held:
            keys.add("assignments")
        if _QUIZ_ATTEMPT in held and _QUIZ_READ in held:
            keys.add("quizzes")
        if _EXAM_READ in held:
            keys.add("exams")
    return keys


class SidebarCountsService:
    """Every badge, for one caller, in one pass."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.scopes = ScopeResolver(session)
        self.notifications = NotificationRepository(session)
        self.mail = MailService(session)

    async def _count(self, stmt: Select) -> int:
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def counts(self, *, actor: User) -> dict[str, int]:
        held = ScopeResolver.held_permissions(actor)
        unrestricted = ScopeResolver.is_unrestricted(actor)
        allowed = applicable_badges(held, unrestricted=unrestricted)
        out: dict[str, int] = {}
        now = datetime.now(timezone.utc)

        # --- institution-wide totals -------------------------------------
        # Gated on *seeing the whole institution*, not on a role name: the
        # console's rule is that access follows what a caller may do. In this
        # deployment that means Super Admin and Administrator, the two roles
        # that hold `institution.view_all`.
        if "courses" in allowed:
            out["courses"] = await self._count(
                select(func.count(Course.id)).where(Course.is_deleted.is_(False))
            )
        if "users" in allowed:
            out["users"] = await self._count(
                select(func.count(User.id)).where(
                    User.deleted_at.is_(None), User.status != UserStatus.DELETED
                )
            )
        if "roles" in allowed:
            out["roles"] = await self._count(select(func.count(Role.id)))
        if "permissions" in allowed:
            out["permissions"] = await self._count(select(func.count(Permission.id)))
        if "guardians" in allowed:
            out["guardians"] = await self._count(select(func.count(StudentGuardian.id)))

        # --- things the caller can reach ---------------------------------
        if "batches" in allowed:
            scope = await self.scopes.visible_batch_ids(actor)
            out["batches"] = await self._count(
                scope.apply(
                    select(func.count(Batch.id)),
                    Batch.id,
                )
            )
        if "sessions" in allowed:
            scope = await self.scopes.visible_session_ids(actor)
            out["sessions"] = await self._count(
                scope.apply(select(func.count(BatchSession.id)), BatchSession.id)
            )
        if "enrollments" in allowed:
            visibility = await self.scopes.enrollment_visibility(actor)
            out["enrollments"] = await self._count(
                visibility.apply(
                    select(func.count(Enrollments.enrollment_id)),
                    batch_column=Enrollments.batch_id,
                    student_column=Enrollments.student_id,
                )
            )

        # --- unread ------------------------------------------------------
        if "messages" in allowed:
            out["messages"] = await self.mail.unread_count(actor)
        if "notifications" in allowed:
            out["notifications"] = await self.notifications.unread_count(actor.id)
        if "announcements" in allowed:
            out["announcements"] = await self._unread_announcements(actor, now)

        # --- work waiting for this person --------------------------------
        await self._assessment_counts(actor, held, allowed, out, now)
        return out

    async def _unread_announcements(self, actor: User, now: datetime) -> int:
        """Live announcements this person has not opened.

        The audience filter is deliberately the permissive half of the feed's:
        an announcement with no course, batch or role scope is for everybody,
        and a role-scoped one is for that role. Narrowing further here would
        make the badge disagree with the screen, which is the one thing a badge
        must never do.
        """
        role_names = {r.name for r in (actor.roles or [])}
        read = select(AnnouncementRead.announcement_id).where(
            AnnouncementRead.user_id == actor.id
        )
        stmt = (
            select(func.count(Announcement.id))
            .where(
                Announcement.start_at <= now,
                (Announcement.end_at.is_(None)) | (Announcement.end_at >= now),
                Announcement.id.not_in(read),
                (Announcement.role_scope.is_(None))
                | (Announcement.role_scope.in_(role_names)),
            )
        )
        return await self._count(stmt)

    async def _assessment_counts(
        self,
        actor: User,
        held: set[str],
        allowed: set[str],
        out: dict[str, int],
        now: datetime,
    ) -> None:
        """Assignments, quizzes and examinations -- per responsibility.

        Somebody who both studies and marks (a Super Admin holds every
        permission) is counted as a marker: that is the hat they are wearing on
        the screen the badge sits beside.
        """
        marks = {_ASSIGNMENT_GRADE, _QUIZ_GRADE, _EXAM_GRADE} & held
        studies = {_ASSIGNMENT_SUBMIT, _QUIZ_ATTEMPT} & held

        if marks:
            work = await self.scopes.work_visibility(actor)
            if "assignments" in allowed:
                out["assignments"] = await self._count(
                    work.apply(
                        select(func.count(AssignmentSubmission.id))
                        .join(Assignment, Assignment.id == AssignmentSubmission.assignment_id)
                        .where(AssignmentSubmission.state.in_(_AWAITING_MARKING)),
                        course_column=Assignment.course_id,
                        student_column=AssignmentSubmission.student_id,
                    )
                )
            if "quizzes" in allowed:
                out["quizzes"] = await self._count(
                    work.apply(
                        select(func.count(QuizAttempt.id))
                        .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
                        .where(
                            QuizAttempt.finished_at.is_not(None),
                            QuizAttempt.score.is_(None),
                        ),
                        course_column=Quiz.course_id,
                        student_column=QuizAttempt.student_id,
                    )
                )
            if "exams" in allowed:
                # An examination still waiting for its marks to be released.
                courses = await self.scopes.visible_course_ids(actor)
                out["exams"] = await self._count(
                    courses.apply(
                        select(func.count(Exam.id)).where(
                            Exam.scheduled_at <= now,
                            Exam.id.not_in(
                                select(ExamResult.exam_id).where(
                                    ExamResult.is_published.is_(True)
                                )
                            ),
                        ),
                        Exam.course_id,
                    )
                )
            return

        if not studies:
            # A guardian or corporate manager watches somebody else do the
            # work. A number they cannot act on is noise, so there is no key.
            return

        batches = select(Enrollments.batch_id).where(
            Enrollments.student_id == actor.id,
            Enrollments.status == EnrollmentStatus.CONFIRMED,
        )
        if "assignments" in allowed:
            done = select(AssignmentSubmission.assignment_id).where(
                AssignmentSubmission.student_id == actor.id,
                AssignmentSubmission.state.in_(_HANDED_IN),
            )
            out["assignments"] = await self._count(
                select(func.count(Assignment.id)).where(
                    Assignment.batch_id.in_(batches),
                    Assignment.state.in_(_LIVE),
                    Assignment.id.not_in(done),
                )
            )
        if "quizzes" in allowed:
            attempted = select(QuizAttempt.quiz_id).where(
                QuizAttempt.student_id == actor.id,
                QuizAttempt.finished_at.is_not(None),
            )
            out["quizzes"] = await self._count(
                select(func.count(Quiz.id)).where(
                    Quiz.batch_id.in_(batches),
                    Quiz.is_published.is_(True),
                    Quiz.id.not_in(attempted),
                )
            )
        if "exams" in allowed:
            # A student does not "submit" an examination -- it is sat, and the
            # marks are recorded by staff. The useful number is therefore the
            # one they can act on: scheduled examinations still ahead of them.
            sat = select(ExamResult.exam_id).where(ExamResult.student_id == actor.id)
            out["exams"] = await self._count(
                select(func.count(Exam.id)).where(
                    Exam.batch_id.in_(batches),
                    Exam.is_published.is_(True),
                    Exam.scheduled_at >= now,
                    Exam.id.not_in(sat),
                )
            )
