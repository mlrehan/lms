"""Aggregate queries for dashboards and reports (spec §17–§18).

**Every aggregate here takes the same scope object the corresponding listing
takes.** A count computed over rows the caller cannot see leaks exactly the
information the row filter exists to withhold, one number at a time: "how
many students failed" is a smaller answer than the list, not a safer one. So
`AttendanceVisibility`, `WorkVisibility` and `EnrollmentVisibility` are
required arguments, never optional narrowings — there is no way to call these
and accidentally aggregate the whole institution.

**Reports return groups, not rows.** There is no "export every attendance
record" query in this module, and that is deliberate: the row-level views
already exist with paging and scoping, and an endpoint that dumps them all
into one response is a data-exfiltration tool with a friendly name. Grouping
also bounds the result naturally — there are only so many courses, tutors or
months.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Sequence

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.attendance import Attendance
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.gradebook import GradeBookEntry
from backend.models.identity.user import User
from backend.models.quiz import Quiz, QuizAttempt
from backend.utils.enums import (
    AttendanceStatus,
    CourseStatus,
    EnrollmentStatus,
    UserStatus,
)

if TYPE_CHECKING:
    from backend.services.scope import (
        AttendanceVisibility,
        EnrollmentVisibility,
        Scope,
        WorkVisibility,
    )

# A grouped report is bounded by its number of groups, but "group by student"
# across an institution the spec sizes at 10,000+ is still a page nobody
# reads. The cap is applied in the query and reported back as `truncated`,
# rather than silently returning a prefix that looks complete.
MAX_GROUPS = 500


def _month(column: Any) -> Any:
    """`YYYY-MM` for a timestamp column, as a groupable text value."""
    return func.to_char(func.date_trunc("month", column), "YYYY-MM")


class ReportingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- attendance ----------------------------------------------------------

    def _attendance_base(
        self,
        visibility: "AttendanceVisibility",
        *,
        date_from: date | None,
        date_to: date | None,
        course_id: int | None,
        batch_id: int | None,
    ) -> Select[Any]:
        stmt = (
            select(Attendance)
            .join(BatchSession, Attendance.session_id == BatchSession.id)
            .join(Batch, BatchSession.batch_id == Batch.id)
        )
        stmt = visibility.apply(
            stmt, session_column=Attendance.session_id, student_column=Attendance.student_id
        )
        # Ranged on the *session's* scheduled time, not on when the mark was
        # recorded: a register filled in late still belongs to the class it
        # describes, and a report keyed on data entry would move rows between
        # months depending on when a tutor got round to it.
        if date_from is not None:
            stmt = stmt.where(BatchSession.session_start_time >= date_from)
        if date_to is not None:
            stmt = stmt.where(BatchSession.session_start_time < date_to)
        if batch_id is not None:
            stmt = stmt.where(Batch.id == batch_id)
        if course_id is not None:
            stmt = stmt.where(Batch.course_id == course_id)
        return stmt

    async def attendance_by(
        self,
        group: str,
        *,
        visibility: "AttendanceVisibility",
        date_from: date | None = None,
        date_to: date | None = None,
        course_id: int | None = None,
        batch_id: int | None = None,
    ) -> list[tuple[str, str, dict[AttendanceStatus, int]]]:
        """``[(key, label, {status: count})]`` for the requested grouping."""
        base = self._attendance_base(
            visibility,
            date_from=date_from,
            date_to=date_to,
            course_id=course_id,
            batch_id=batch_id,
        )

        if group == "course":
            base = base.join(Course, Batch.course_id == Course.id)
            key_col, label_col = Course.public_id, Course.title
        elif group == "batch":
            key_col, label_col = Batch.public_id, Batch.batch_code
        elif group == "tutor":
            base = base.join(User, BatchSession.tutor_id == User.id)
            key_col, label_col = User.public_id, User.username
        elif group == "student":
            base = base.join(User, Attendance.student_id == User.id)
            key_col, label_col = User.public_id, User.username
        elif group == "month":
            key_col = _month(BatchSession.session_start_time)
            label_col = key_col
        else:  # pragma: no cover - the enum bounds this
            raise ValueError(f"Unsupported grouping: {group}")

        stmt = (
            base.with_only_columns(
                key_col.label("key"),
                label_col.label("label"),
                Attendance.status,
                func.count().label("n"),
            )
            .group_by(key_col, label_col, Attendance.status)
            .order_by(label_col)
        )

        buckets: dict[str, tuple[str, dict[AttendanceStatus, int]]] = {}
        for key, label, status, count in (await self.session.execute(stmt)).all():
            entry = buckets.setdefault(str(key), (str(label), {}))
            entry[1][status] = int(count)
        return [(k, v[0], v[1]) for k, v in buckets.items()]

    # -- enrollment ----------------------------------------------------------

    async def enrollment_by(
        self,
        group: str,
        *,
        visibility: "EnrollmentVisibility",
        date_from: date | None = None,
        date_to: date | None = None,
        course_id: int | None = None,
    ) -> list[tuple[str, str, dict[str, int]]]:
        base = select(Enrollments).join(Batch, Enrollments.batch_id == Batch.id)
        base = visibility.apply(
            base, batch_column=Enrollments.batch_id, student_column=Enrollments.student_id
        )
        if date_from is not None:
            base = base.where(Enrollments.enrollment_date >= date_from)
        if date_to is not None:
            base = base.where(Enrollments.enrollment_date < date_to)
        if course_id is not None:
            base = base.where(Batch.course_id == course_id)

        if group == "course":
            base = base.join(Course, Batch.course_id == Course.id)
            key_col, label_col = Course.public_id, Course.title
        elif group == "batch":
            key_col, label_col = Batch.public_id, Batch.batch_code
        elif group == "status":
            key_col = label_col = Enrollments.status
        elif group == "month":
            key_col = _month(Enrollments.enrollment_date)
            label_col = key_col
        else:  # pragma: no cover
            raise ValueError(f"Unsupported grouping: {group}")

        stmt = (
            base.with_only_columns(
                key_col.label("key"),
                label_col.label("label"),
                Enrollments.status,
                func.count().label("n"),
            )
            .group_by(key_col, label_col, Enrollments.status)
            .order_by(label_col)
        )

        buckets: dict[str, tuple[str, dict[str, int]]] = {}
        for key, label, status, count in (await self.session.execute(stmt)).all():
            name = status.value if hasattr(status, "value") else str(status)
            entry = buckets.setdefault(str(getattr(key, "value", key)), (str(getattr(label, "value", label)), {}))
            entry[1][name] = int(count)
        return [(k, v[0], v[1]) for k, v in buckets.items()]

    # -- performance ---------------------------------------------------------

    async def performance_by(
        self,
        group: str,
        *,
        visibility: "WorkVisibility",
        course_id: int | None = None,
        batch_id: int | None = None,
    ) -> list[tuple[str, str, dict[str, float | int | None]]]:
        """Mean percentage and spread per group, from `gradebook_entries`.

        Averaged as `SUM(score) / SUM(max_score)`, not as the mean of each
        row's percentage: a 1-mark quiz and a 100-mark exam are not equal
        halves of a student's performance, and averaging percentages would
        make them so.
        """
        base = (
            select(GradeBookEntry)
            .join(Batch, GradeBookEntry.batch_id == Batch.id)
        )
        base = visibility.apply(
            base, course_column=Batch.course_id, student_column=GradeBookEntry.student_id
        )
        if batch_id is not None:
            base = base.where(GradeBookEntry.batch_id == batch_id)
        if course_id is not None:
            base = base.where(Batch.course_id == course_id)

        if group == "course":
            base = base.join(Course, Batch.course_id == Course.id)
            key_col, label_col = Course.public_id, Course.title
        elif group == "batch":
            key_col, label_col = Batch.public_id, Batch.batch_code
        elif group == "component":
            key_col = label_col = GradeBookEntry.component_type
        elif group == "student":
            base = base.join(User, GradeBookEntry.student_id == User.id)
            key_col, label_col = User.public_id, User.username
        else:  # pragma: no cover
            raise ValueError(f"Unsupported grouping: {group}")

        stmt = (
            base.with_only_columns(
                key_col.label("key"),
                label_col.label("label"),
                func.count().label("entries"),
                func.count(func.distinct(GradeBookEntry.student_id)).label("students"),
                func.sum(GradeBookEntry.score).label("scored"),
                func.sum(GradeBookEntry.max_score).label("available"),
            )
            .group_by(key_col, label_col)
            .order_by(label_col)
            .limit(MAX_GROUPS + 1)
        )

        out: list[tuple[str, str, dict[str, float | int | None]]] = []
        for key, label, entries, students, scored, available in (
            await self.session.execute(stmt)
        ).all():
            out.append(
                (
                    str(getattr(key, "value", key)),
                    str(getattr(label, "value", label)),
                    {
                        "entries": int(entries),
                        "students": int(students),
                        "scored": float(scored) if scored is not None else None,
                        "available": float(available) if available is not None else None,
                    },
                )
            )
        return out

    # -- dashboard tiles -----------------------------------------------------

    async def attendance_counts(
        self,
        *,
        visibility: "AttendanceVisibility",
        student_ids: Sequence[int] | None = None,
        since: datetime | None = None,
    ) -> dict[AttendanceStatus, int]:
        stmt = visibility.apply(
            select(Attendance.status, func.count()).select_from(Attendance),
            session_column=Attendance.session_id,
            student_column=Attendance.student_id,
        )
        if student_ids is not None:
            if not student_ids:
                from sqlalchemy import false

                stmt = stmt.where(false())
            else:
                stmt = stmt.where(Attendance.student_id.in_(student_ids))
        if since is not None:
            stmt = stmt.where(
                Attendance.session_id.in_(
                    select(BatchSession.id).where(BatchSession.session_start_time >= since)
                )
            )
        rows = (await self.session.execute(stmt.group_by(Attendance.status))).all()
        return {status: int(count) for status, count in rows}

    async def upcoming_sessions(
        self,
        *,
        batch_ids: Sequence[int] | None = None,
        tutor_id: int | None = None,
        now: datetime,
        limit: int = 5,
    ) -> list[tuple[BatchSession, Batch, Course]]:
        stmt = (
            select(BatchSession, Batch, Course)
            .join(Batch, BatchSession.batch_id == Batch.id)
            .join(Course, Batch.course_id == Course.id)
            .where(BatchSession.session_start_time >= now, BatchSession.cancelled_at.is_(None))
        )
        if tutor_id is not None:
            stmt = stmt.where(BatchSession.tutor_id == tutor_id)
        if batch_ids is not None:
            if not batch_ids:
                return []
            stmt = stmt.where(BatchSession.batch_id.in_(batch_ids))
        stmt = stmt.order_by(BatchSession.session_start_time.asc()).limit(limit)
        return [(a, b, c) for a, b, c in (await self.session.execute(stmt)).all()]

    async def session_count(
        self, *, batch_ids: Sequence[int] | None, tutor_id: int | None,
        start: datetime, end: datetime,
    ) -> int:
        stmt = select(func.count()).select_from(BatchSession).where(
            BatchSession.session_start_time >= start,
            BatchSession.session_start_time < end,
        )
        if tutor_id is not None:
            stmt = stmt.where(BatchSession.tutor_id == tutor_id)
        if batch_ids is not None:
            if not batch_ids:
                return 0
            stmt = stmt.where(BatchSession.batch_id.in_(batch_ids))
        return int((await self.session.execute(stmt)).scalar_one())

    async def outstanding_assignments(
        self, *, student_ids: Sequence[int], now: datetime
    ) -> tuple[int, int]:
        """``(outstanding, overdue)`` for these students.

        "Outstanding" is an assignment on a course the student is enrolled in
        with no submission row of their own — computed as a NOT EXISTS rather
        than an outer join, so a student with several enrollments onto the
        same course cannot be counted twice for one piece of work.
        """
        if not student_ids:
            return 0, 0

        enrolled_courses = (
            select(Batch.course_id, Enrollments.student_id)
            .join(Enrollments, Enrollments.batch_id == Batch.id)
            .where(
                Enrollments.student_id.in_(student_ids),
                Enrollments.status.in_(
                    (EnrollmentStatus.CONFIRMED, EnrollmentStatus.PENDING)
                ),
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

        stmt = (
            select(
                func.count(),
                func.count().filter(Assignment.due_date < now),
            )
            .select_from(Assignment)
            .join(enrolled_courses, Assignment.course_id == enrolled_courses.c.course_id)
            .where(~submitted)
        )
        row = (await self.session.execute(stmt)).one()
        return int(row[0]), int(row[1])

    async def next_deadlines(
        self, *, student_ids: Sequence[int], now: datetime, limit: int = 5
    ) -> list[tuple[Assignment, Course, bool]]:
        if not student_ids:
            return []

        enrolled_courses = (
            select(Batch.course_id, Enrollments.student_id)
            .join(Enrollments, Enrollments.batch_id == Batch.id)
            .where(Enrollments.student_id.in_(student_ids))
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
        stmt = (
            select(Assignment, Course)
            .join(enrolled_courses, Assignment.course_id == enrolled_courses.c.course_id)
            .join(Course, Assignment.course_id == Course.id)
            .where(~submitted)
            .order_by(Assignment.due_date.asc())
            .limit(limit)
        )
        return [
            (a, c, a.due_date is not None and a.due_date < now)
            for a, c in (await self.session.execute(stmt)).all()
        ]

    async def ungraded_submissions(self, *, course_ids: Sequence[int] | None) -> int:
        stmt = (
            select(func.count())
            .select_from(AssignmentSubmission)
            .join(Assignment, AssignmentSubmission.assignment_id == Assignment.id)
            .where(AssignmentSubmission.grade.is_(None))
        )
        if course_ids is not None:
            if not course_ids:
                return 0
            stmt = stmt.where(Assignment.course_id.in_(course_ids))
        return int((await self.session.execute(stmt)).scalar_one())

    async def ungraded_quiz_attempts(self, *, course_ids: Sequence[int] | None) -> int:
        stmt = (
            select(func.count())
            .select_from(QuizAttempt)
            .join(Quiz, QuizAttempt.quiz_id == Quiz.id)
            .where(QuizAttempt.finished_at.is_not(None), QuizAttempt.score.is_(None))
        )
        if course_ids is not None:
            if not course_ids:
                return 0
            stmt = stmt.where(Quiz.course_id.in_(course_ids))
        return int((await self.session.execute(stmt)).scalar_one())

    async def student_totals(self, *, student_id: int) -> tuple[int, int]:
        """``(enrolled_batches, distinct_courses)`` for one student."""
        stmt = (
            select(
                func.count(func.distinct(Enrollments.batch_id)),
                func.count(func.distinct(Batch.course_id)),
            )
            .select_from(Enrollments)
            .join(Batch, Enrollments.batch_id == Batch.id)
            .where(
                Enrollments.student_id == student_id,
                Enrollments.status.in_(
                    (EnrollmentStatus.CONFIRMED, EnrollmentStatus.PENDING)
                ),
            )
        )
        row = (await self.session.execute(stmt)).one()
        return int(row[0]), int(row[1])

    async def average_score(self, *, student_ids: Sequence[int]) -> float | None:
        if not student_ids:
            return None
        stmt = select(
            func.sum(GradeBookEntry.score), func.sum(GradeBookEntry.max_score)
        ).where(GradeBookEntry.student_id.in_(student_ids))
        scored, available = (await self.session.execute(stmt)).one()
        from backend.services.metrics import percentage

        return percentage(scored, available)

    async def taught_totals(self, *, batch_ids: Sequence[int]) -> tuple[int, int]:
        """``(distinct_courses, distinct_students)`` across these batches."""
        if not batch_ids:
            return 0, 0
        courses = (
            await self.session.execute(
                select(func.count(func.distinct(Batch.course_id))).where(
                    Batch.id.in_(batch_ids)
                )
            )
        ).scalar_one()
        students = (
            await self.session.execute(
                select(func.count(func.distinct(Enrollments.student_id))).where(
                    Enrollments.batch_id.in_(batch_ids)
                )
            )
        ).scalar_one()
        return int(courses), int(students)

    # -- institution ---------------------------------------------------------

    async def institution_counts(self) -> dict[str, int]:
        users = dict(
            (await self.session.execute(
                select(User.status, func.count()).group_by(User.status)
            )).all()
        )
        courses = dict(
            (await self.session.execute(
                select(Course.status, func.count())
                .where(Course.is_deleted.is_(False))
                .group_by(Course.status)
            )).all()
        )
        batches = (
            await self.session.execute(
                select(func.count()).select_from(Batch).where(Batch.is_active.is_(True))
            )
        ).scalar_one()
        enrollments = (
            await self.session.execute(
                select(func.count())
                .select_from(Enrollments)
                .where(Enrollments.status == EnrollmentStatus.CONFIRMED)
            )
        ).scalar_one()

        return {
            "active_users": int(users.get(UserStatus.ACTIVE, 0)),
            "suspended_users": int(users.get(UserStatus.SUSPENDED, 0)),
            "courses_published": int(courses.get(CourseStatus.PUBLISHED, 0))
            + int(courses.get(CourseStatus.RUNNING, 0)),
            "courses_draft": int(courses.get(CourseStatus.DRAFT, 0)),
            "active_batches": int(batches),
            "enrollments_confirmed": int(enrollments),
        }
