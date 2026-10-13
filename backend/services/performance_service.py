"""A student's weighted result, gathered from the records that already exist.

This is the service the whole academic system was missing. The pieces were all
there -- graded submissions, quiz attempts, exam results, attendance, and since
this phase a grading scheme with real weights -- and nothing put them together.
The grade book wrote `weight = 1` on every row because there was nowhere to read
a weight from, so its "weighted average" was a straight average and said so in
its own docstring.

**It reads, it does not store.** §23's single source of truth: attendance comes
from the attendance register, assignment marks from graded submissions, quiz
scores from attempts, examination marks from results. Nothing here writes a
second copy of any of them, so there is no second copy to fall out of step.

**Only released marks reach the people a mark is about.** A student, a guardian
and a corporate manager see published results; staff see everything, because a
tutor who cannot see their own unreleased marking cannot do their job. That is
one flag through `evaluate`, not a filter each caller remembers.

**The breakdown is the return value, not a second calculation.** §37's
drill-down -- `82 × 15% = 12.30` -- is what `core.performance` already produces;
this service only supplies the marks and hands the answer back.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import NotFoundError
from backend.core.performance import Mark, Performance, evaluate
from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.attendance import Attendance
from backend.models.batch import Batch, BatchSession
from backend.models.class_performance import ClassPerformanceMark
from backend.models.enrollment import Enrollments
from backend.models.exam import Exam, ExamResult
from backend.models.identity.user import User
from backend.models.quiz import Question, Quiz, QuizAttempt
from backend.services.grading_scheme_service import GradingSchemeService
from backend.services.scope import ScopeResolver
from backend.utils.enums import (
    AttendanceStatus,
    GradeComponentType as C,
    ResultState,
    SubmissionState,
)

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")

#: Attendance statuses that count as having turned up. `LATE` counts: arriving
#: late is not the same as not arriving, and an institution that wants to
#: penalise it can do so through its own weighting rather than by having this
#: module quietly treat the two as identical.
_PRESENT = {AttendanceStatus.PRESENT, AttendanceStatus.LATE}


@dataclass(frozen=True)
class StudentPerformance:
    """One student's standing in one batch, with everything a screen needs."""

    student_id: int
    batch_id: int
    performance: Performance
    scheme_name: str | None
    #: Attendance is shown in its own right as well as weighted (§15), because
    #: "18 of 20 sessions" is the figure people actually discuss.
    sessions_total: int
    sessions_attended: int

    @property
    def attendance_percentage(self) -> Decimal | None:
        if not self.sessions_total:
            return None
        return (Decimal(self.sessions_attended) / Decimal(self.sessions_total)) * _HUNDRED


class PerformanceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.schemes = GradingSchemeService(session)
        self.scopes = ScopeResolver(session)

    # -- authorisation --------------------------------------------------------

    async def assert_may_view(self, *, actor: User, student_id: int) -> None:
        """Refuse a student who is not this caller's to look at.

        Reuses `visible_student_ids`, which already encodes the whole rule: a
        tutor sees the students they teach, a guardian their wards, a manager
        their employees, a student themselves. Writing a fresh check here would
        be a second answer to a question the system has already answered.

        404, not 403: §32's "Gradebook information cannot be accessed using
        manipulated IDs" means the id must not be confirmed to exist either.
        """
        scope = await self.scopes.visible_student_ids(actor)
        if not scope.allows(student_id):
            raise NotFoundError("Student not found.")

    @staticmethod
    def sees_unreleased(actor: User) -> bool:
        """May this caller see marks that have not been published?

        Staff may; the student, their guardian and their corporate manager may
        not. §14 is explicit, and it is the difference between a tutor working
        through a pile of marking and a parent seeing a provisional grade.
        """
        held = ScopeResolver.held_permissions(actor)
        return "grade.update" in held or "grade.publish" in held

    # -- gathering the marks --------------------------------------------------

    async def _assignment_marks(
        self, *, student_id: int, batch_id: int, course_id: int, released_only: bool
    ) -> list[Mark]:
        """Graded submissions, as the engine sees them.

        Scope-aware: an assignment set for another batch is not this student's
        to be measured against, so the join follows the same three columns the
        eligibility resolver reads.
        """
        # Columns, not entities. Selecting `AssignmentSubmission` and
        # `Assignment` as ORM objects made this 710 queries for eight
        # students: every row dragged its relationships in, and a `User`
        # reached that way dragged its own. Nothing here reads anything but
        # these five values. See `_exam_marks` for the measurement.
        stmt = (
            select(
                AssignmentSubmission.grade,
                AssignmentSubmission.state,
                Assignment.max_score,
                Assignment.weight,
                Assignment.title,
            )
            .join(Assignment, Assignment.id == AssignmentSubmission.assignment_id)
            .where(
                AssignmentSubmission.student_id == student_id,
                Assignment.course_id == course_id,
                # Course-wide, this batch's, or one of this batch's sessions.
                (Assignment.batch_id.is_(None)) | (Assignment.batch_id == batch_id),
            )
        )
        rows = (await self.session.execute(stmt)).all()

        marks: list[Mark] = []
        for grade, state, max_score, weight, title in rows:
            if released_only and not state.is_visible_to_student:
                continue
            marks.append(
                Mark(
                    component_type=C.ASSIGNMENT,
                    earned=Decimal(grade) if grade is not None else None,
                    possible=Decimal(max_score),
                    state=state,
                    weight=Decimal(weight or 1),
                    label=title,
                )
            )
        return marks

    async def _quiz_marks(
        self, *, student_id: int, batch_id: int, course_id: int, released_only: bool
    ) -> list[Mark]:
        """The **best** attempt per quiz.

        Not the average and not the latest: a quiz that allows three attempts
        is offering three chances at the same mark, and averaging them would
        penalise a student for using the attempts they were given.
        """
        best = (
            select(
                QuizAttempt.quiz_id.label("quiz_id"),
                func.max(QuizAttempt.score).label("score"),
            )
            .where(QuizAttempt.student_id == student_id, QuizAttempt.finished_at.isnot(None))
            .group_by(QuizAttempt.quiz_id)
            .subquery()
        )
        # The quiz's own total, as a correlated subquery rather than a
        # follow-up query per quiz per student.
        points = (
            select(func.coalesce(func.sum(Question.points), 0))
            .where(Question.quiz_id == Quiz.id)
            .correlate(Quiz)
            .scalar_subquery()
        )
        stmt = (
            select(
                Quiz.is_published,
                Quiz.weight,
                Quiz.title,
                best.c.score,
                points.label("total_points"),
            )
            .join(best, best.c.quiz_id == Quiz.id)
            .where(
                Quiz.course_id == course_id,
                (Quiz.batch_id.is_(None)) | (Quiz.batch_id == batch_id),
            )
        )
        rows = (await self.session.execute(stmt)).all()

        marks: list[Mark] = []
        for is_published, weight, title, score, total_points in rows:
            if released_only and not is_published:
                continue
            if Decimal(total_points or 0) <= _ZERO:
                # A quiz with no questions has nothing to contribute. Its
                # total is no longer the denominator (see below), but a quiz
                # with no marked questions cannot have produced a meaningful
                # percentage either, so it stays out.
                continue
            marks.append(
                Mark(
                    component_type=C.QUIZ,
                    earned=Decimal(score) if score is not None else None,
                    # **100, not the quiz's raw points.** `QuizAttempt.score`
                    # is already a percentage -- the model says so, and the
                    # grade book's own writer pairs it with `max_score=100`.
                    # Dividing a percentage by the question total was the
                    # defect: an 80% attempt on a 12-point quiz contributed
                    # 666% to the quiz component, and with any quiz in a
                    # scheme the whole overall mark was wrong. Nothing caught
                    # it because the engine's tests build marks by hand and
                    # the service's tests had no quiz in them at all.
                    possible=_HUNDRED,
                    state=SubmissionState.GRADED if score is not None else SubmissionState.PENDING,
                    weight=Decimal(weight or 1),
                    label=title,
                )
            )
        return marks

    async def _exam_marks(
        self, *, student_id: int, batch_id: int, course_id: int, released_only: bool
    ) -> list[Mark]:
        # Columns, not entities, and this is where it was measured: as ORM
        # objects this single query cost **1,070 queries and 5 seconds** for
        # eight students, because `Exam` eager-loads its course, batch,
        # invigilators and *every result*, and each result eager-loads its
        # student, whose own class then eager-loaded twenty collections of
        # its own.
        stmt = (
            select(
                ExamResult.marks_obtained,
                ExamResult.is_published,
                ExamResult.state,
                Exam.total_marks,
                Exam.weight,
                Exam.title,
            )
            .join(Exam, Exam.id == ExamResult.exam_id)
            .where(
                ExamResult.student_id == student_id,
                (Exam.course_id == course_id) | (Exam.batch_id == batch_id),
            )
        )
        rows = (await self.session.execute(stmt)).all()

        marks: list[Mark] = []
        for marks_obtained, is_published, state, total_marks, weight, title in rows:
            if released_only and not is_published:
                continue
            marks.append(
                Mark(
                    component_type=C.FINAL_EXAM,
                    earned=(
                        Decimal(marks_obtained) if marks_obtained is not None else None
                    ),
                    possible=Decimal(total_marks),
                    state=state,
                    weight=Decimal(weight or 1),
                    label=title,
                )
            )
        return marks

    async def _attendance_mark(self, *, student_id: int, batch_id: int) -> tuple[Mark | None, int, int]:
        """Attendance as a percentage, read from the register (§12).

        Never copied into the grade book as a stored figure -- §12 forbids
        duplicating it, and a stored copy would be wrong the moment a tutor
        corrected a register.
        """
        total = (
            await self.session.execute(
                select(func.count())
                .select_from(BatchSession)
                .where(BatchSession.batch_id == batch_id, BatchSession.cancelled_at.is_(None))
            )
        ).scalar_one()

        attended = (
            await self.session.execute(
                select(func.count())
                .select_from(Attendance)
                .join(BatchSession, BatchSession.id == Attendance.session_id)
                .where(
                    BatchSession.batch_id == batch_id,
                    Attendance.student_id == student_id,
                    Attendance.status.in_(_PRESENT),
                )
            )
        ).scalar_one()

        if not total:
            # A batch with no sessions scheduled has no attendance to measure.
            # Reporting 0% would be a statement about the student; there is no
            # statement to make.
            return None, 0, 0

        return (
            Mark(
                component_type=C.ATTENDANCE,
                earned=Decimal(attended),
                possible=Decimal(total),
                label=f"{attended} of {total} sessions",
            ),
            total,
            int(attended),
        )

    async def _class_performance_marks(
        self, *, student_id: int, batch_id: int, released_only: bool
    ) -> list[Mark]:
        """A tutor's per-session assessment (§11), averaged across the sessions.

        Only finalised rows count when the reader is not staff: a tutor's
        working notes on how somebody participated are not something a guardian
        should be reading mid-term.
        """
        stmt = (
            select(ClassPerformanceMark)
            .join(BatchSession, BatchSession.id == ClassPerformanceMark.session_id)
            .where(
                BatchSession.batch_id == batch_id,
                ClassPerformanceMark.student_id == student_id,
            )
        )
        rows = list((await self.session.execute(stmt)).scalars().unique().all())

        marks: list[Mark] = []
        for row in rows:
            if released_only and row.state not in {ResultState.FINALIZED, ResultState.PUBLISHED}:
                continue
            score = self._class_overall(row)
            if score is None:
                continue
            marks.append(
                Mark(
                    component_type=C.PRACTICAL,
                    earned=score,
                    possible=Decimal(row.max_score),
                    label="Class performance",
                )
            )
        return marks

    @staticmethod
    def _class_overall(row: ClassPerformanceMark) -> Decimal | None:
        """The tutor's own figure, or the mean of the criteria they filled in.

        A criterion left blank is excluded rather than counted as zero -- the
        same rule the engine applies everywhere, and the reason a tutor who
        only assessed participation is not recording seven zeros.
        """
        if row.overall_score is not None:
            return Decimal(row.overall_score)

        values = [
            Decimal(v)
            for v in (
                row.participation, row.interaction, row.preparation, row.practical,
                row.presentation, row.teamwork, row.communication, row.professionalism,
            )
            if v is not None
        ]
        if not values:
            return None
        return sum(values, _ZERO) / Decimal(len(values))

    # -- the answer ----------------------------------------------------------

    async def for_student(
        self, *, student_id: int, batch_id: int, actor: User
    ) -> StudentPerformance:
        """One student's weighted standing in one batch, and how it was reached."""
        await self.assert_may_view(actor=actor, student_id=student_id)
        return await self._evaluate(
            student_id=student_id,
            batch_id=batch_id,
            released_only=not self.sees_unreleased(actor),
        )

    async def _evaluate(
        self, *, student_id: int, batch_id: int, released_only: bool
    ) -> StudentPerformance:
        """Gather and weigh. Takes the release decision as a value rather than
        an actor, so the one caller that must never be flexible about it --
        transcript generation -- cannot be."""
        # The course id and nothing else. Loading the `Batch` entity pulled in
        # its tutor reviews, and each review its student and tutor, and each
        # of those a user -- eight times over for a grid of eight students,
        # for one integer.
        course_id = (
            await self.session.execute(
                select(Batch.course_id).where(Batch.id == batch_id)
            )
        ).scalar_one_or_none()
        if course_id is None:
            raise NotFoundError("Batch not found.")

        scheme_row = await self.schemes.for_course(course_id)
        scheme = await self.schemes.as_engine_scheme(scheme_row)

        attendance, total_sessions, attended = await self._attendance_mark(
            student_id=student_id, batch_id=batch_id
        )
        marks: list[Mark] = [
            *await self._assignment_marks(
                student_id=student_id, batch_id=batch_id,
                course_id=course_id, released_only=released_only,
            ),
            *await self._quiz_marks(
                student_id=student_id, batch_id=batch_id,
                course_id=course_id, released_only=released_only,
            ),
            *await self._exam_marks(
                student_id=student_id, batch_id=batch_id,
                course_id=course_id, released_only=released_only,
            ),
            *await self._class_performance_marks(
                student_id=student_id, batch_id=batch_id, released_only=released_only
            ),
        ]
        if attendance is not None:
            marks.append(attendance)

        return StudentPerformance(
            student_id=student_id,
            batch_id=batch_id,
            performance=evaluate(marks, scheme),
            scheme_name=scheme_row.name if scheme_row else None,
            sessions_total=total_sessions,
            sessions_attended=attended,
        )

    async def for_transcript(self, *, student_id: int, batch_id: int) -> StudentPerformance:
        """The figures an official transcript may carry (§5).

        **Published marks only, and not because a caller remembered to ask.**
        `for_student` derives that from who is looking, which is right for a
        screen -- a tutor should see their own work in progress. It is exactly
        wrong here: the Super Admin generating a transcript has permission to
        see unreleased marking, so routing transcript generation through the
        actor-aware path would put draft marks on an official document for the
        one person most likely to be issuing it.

        So this method takes no actor at all for that decision. There is no
        argument to get wrong. §5's "Draft marks must never appear on an
        official transcript" is a property of the call, not of the caller.
        """
        return await self._evaluate(student_id=student_id, batch_id=batch_id, released_only=True)

    async def for_batch(self, *, batch_id: int, actor: User) -> list[StudentPerformance]:
        """Everyone in a batch, for the grade book grid (§36).

        One pass per student rather than one query for everything, and that is
        a deliberate limit rather than an oversight: the aggregation is over
        four sources with different shapes, and a single query returning them
        all would be unreadable and no faster on a batch of thirty. It is bounded
        by a roster, which is the same bound the notification fan-out accepts.
        """
        students = (
            await self.session.execute(
                select(Enrollments.student_id).where(Enrollments.batch_id == batch_id)
            )
        ).scalars().all()

        out: list[StudentPerformance] = []
        for student_id in sorted(set(students)):
            try:
                out.append(
                    await self.for_student(student_id=student_id, batch_id=batch_id, actor=actor)
                )
            except NotFoundError:
                # A student this caller may not see. Skipped rather than
                # refused: a tutor viewing a batch grid should see their own
                # students, not an error because somebody else's is in it.
                continue
        return out
