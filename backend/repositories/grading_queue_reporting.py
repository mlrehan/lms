"""What is waiting to be marked (spec §34's Tutor Grading Status).

The coursework report already answers this for assignments, as a by-product
of measuring submission. It cannot answer it for quizzes and exams, because
those have no "expected student" shape to measure against -- a quiz nobody
attempted is not a quiz with marking outstanding.

So this is a queue, not a rate: three counts per group, each the number of
things a human still has to look at.

**Each type's definition of "waiting" is its own, and they are not
interchangeable:**

* an *assignment submission* that has arrived and has no mark;
* a finished *quiz attempt* with no score -- which is how an auto-graded quiz
  reports that something in it needed a person;
* an *exam result* row with no marks recorded, which is the offline case:
  somebody sat a paper and the mark has not been entered.

An exam with no result rows at all is **not** counted. Nobody has said those
students sat it, so there is nothing to mark and a queue that invented one
would show every future exam as outstanding work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.exam import Exam, ExamResult
from backend.models.quiz import Quiz, QuizAttempt
from backend.repositories.reporting import MAX_GROUPS
from backend.utils.enums import AssessmentState, SubmissionState

if TYPE_CHECKING:  # pragma: no cover
    from backend.services.scope import WorkVisibility


# Handed in and still somebody's job. Stated as the states that *are*
# waiting rather than as "not graded", because `SubmissionState` has eleven
# values and several of them -- absent, exempted, not started -- are neither
# marked nor outstanding.
_ARRIVED = (
    SubmissionState.SUBMITTED,
    SubmissionState.LATE,
    SubmissionState.UNDER_REVIEW,
    SubmissionState.RESUBMISSION_REQUIRED,
)


class GradingQueueRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def queue_by(
        self,
        group: str,
        *,
        visibility: "WorkVisibility",
        course_id: int | None = None,
        batch_id: int | None = None,
    ) -> list[tuple[str, str, dict[str, float | int | None]]]:
        """``[(key, label, {assignments, quizzes, exams, total})]``.

        Three independent counts unioned into one shape rather than three
        endpoints, so "what is outstanding" is a single question with a single
        answer. A tutor holding a queue of 2 assignments and 40 quiz attempts
        needs to see both numbers at once to know where the afternoon goes.
        """
        parts = [
            self._assignments(visibility, course_id, batch_id),
            self._quizzes(visibility, course_id, batch_id),
            self._exams(visibility, course_id, batch_id),
        ]

        totals: dict[tuple[str, str], dict[str, int]] = {}
        for kind, stmt in zip(("assignments", "quizzes", "exams"), parts, strict=True):
            grouped = self._group(stmt, group)
            for key, label, count in (await self.session.execute(grouped)).all():
                bucket = totals.setdefault(
                    (str(key), str(label)),
                    {"assignments": 0, "quizzes": 0, "exams": 0},
                )
                bucket[kind] = int(count)

        out: list[tuple[str, str, dict[str, float | int | None]]] = []
        for (key, label), counts in sorted(totals.items(), key=lambda item: item[0][1]):
            out.append(
                (
                    key,
                    label,
                    {**counts, "total": sum(counts.values())},
                )
            )
        # Groups with nothing outstanding never appear: an empty queue is
        # absence of work, and listing every course with a zero turns the
        # answer into a directory nobody can scan.
        return out[:MAX_GROUPS]

    # -- one statement per assessment type -----------------------------------
    #
    # Each selects (course_id, batch_id, 1) so `_group` can key them the same
    # way. `batch_id` is nullable: a course-wide assessment belongs to no
    # single batch, and is counted under the course rather than invented into
    # one.

    def _assignments(
        self, visibility: "WorkVisibility", course_id: int | None, batch_id: int | None
    ) -> Select:
        stmt = (
            select(
                Assignment.course_id.label("course_id"),
                Assignment.batch_id.label("batch_id"),
            )
            .select_from(AssignmentSubmission)
            .join(Assignment, Assignment.id == AssignmentSubmission.assignment_id)
            .where(
                Assignment.state != AssessmentState.DRAFT,
                # `_ARRIVED` alone. A `not_in(_MARKED)` beside it reads as
                # extra safety and is not: the two sets are disjoint, so the
                # second clause can never exclude a row the first admitted,
                # and no test could ever distinguish it from its absence.
                AssignmentSubmission.state.in_(_ARRIVED),
            )
        )
        stmt = visibility.apply(
            stmt,
            course_column=Assignment.course_id,
            student_column=AssignmentSubmission.student_id,
        )
        return self._narrow(stmt, Assignment, course_id, batch_id)

    def _quizzes(
        self, visibility: "WorkVisibility", course_id: int | None, batch_id: int | None
    ) -> Select:
        stmt = (
            select(Quiz.course_id.label("course_id"), Quiz.batch_id.label("batch_id"))
            .select_from(QuizAttempt)
            .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
            .where(
                # Finished, because an attempt still in progress is the
                # student's work outstanding, not the tutor's.
                QuizAttempt.finished_at.is_not(None),
                QuizAttempt.score.is_(None),
            )
        )
        stmt = visibility.apply(
            stmt, course_column=Quiz.course_id, student_column=QuizAttempt.student_id
        )
        return self._narrow(stmt, Quiz, course_id, batch_id)

    def _exams(
        self, visibility: "WorkVisibility", course_id: int | None, batch_id: int | None
    ) -> Select:
        stmt = (
            select(Exam.course_id.label("course_id"), Exam.batch_id.label("batch_id"))
            .select_from(ExamResult)
            .join(Exam, Exam.id == ExamResult.exam_id)
            .where(ExamResult.marks_obtained.is_(None))
        )
        stmt = visibility.apply(
            stmt, course_column=Exam.course_id, student_column=ExamResult.student_id
        )
        return self._narrow(stmt, Exam, course_id, batch_id)

    @staticmethod
    def _narrow(stmt: Select, model: type, course_id: int | None, batch_id: int | None) -> Select:
        if course_id is not None:
            stmt = stmt.where(model.course_id == course_id)
        if batch_id is not None:
            stmt = stmt.where(model.batch_id == batch_id)
        return stmt

    @staticmethod
    def _group(stmt: Select, group: str) -> Select:
        inner = stmt.subquery()
        if group == "course":
            return (
                select(Course.public_id, Course.title, func.count())
                .select_from(inner)
                .join(Course, Course.id == inner.c.course_id)
                .group_by(Course.public_id, Course.title)
            )
        if group == "batch":
            # An `INNER` join drops course-wide work, which has no batch --
            # correct here, because "which batch is behind" cannot answer for
            # an assessment set across all of them.
            return (
                select(Batch.public_id, Batch.batch_code, func.count())
                .select_from(inner)
                .join(Batch, Batch.id == inner.c.batch_id)
                .group_by(Batch.public_id, Batch.batch_code)
            )
        raise ValueError(f"Unsupported grouping: {group}")  # pragma: no cover
