"""Coursework completion aggregates (spec §34–§35).

Three of the reports §34 asks for -- *Assignment Submission*, *Missing
Assignment* and *Tutor Grading Status* -- are the same query read in three
ways, so this is one grouped aggregate rather than three endpoints. §3 says
the same thing about assessments themselves: the duplication is what drifts.

**The denominator is eligible students, not submission rows.** This is the
whole point of the report and the easy thing to get wrong: counting over
`assignment_submissions` gives a submission rate of 100% by construction,
because a student who never submitted has no row to count. The population
comes from `covers_batch` -- the one definition of who an assessment is set
for -- and submissions are LEFT JOINed onto it, so "missing" is a real
number rather than an absence nobody queried.

**One submission row per student per assignment**, enforced by
`uq_assignment_submissions_assignment_student`: a replacement updates the row
rather than adding one, so no deduplication is needed here and none is done.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Numeric, and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.user import User
from backend.repositories.enrollment import ACTIVE_STATUSES
from backend.repositories.reporting import MAX_GROUPS, _round
from backend.services.assessment_scope import covers_batch
from backend.utils.enums import AssessmentState, SubmissionState

if TYPE_CHECKING:  # pragma: no cover
    from backend.services.scope import WorkVisibility


# A submission that has reached a mark. `GRADED` and `PUBLISHED` are
# different facts -- the second is the student being allowed to see it -- and
# both mean the tutor's work is done, which is what "awaiting grading"
# measures.
_MARKED_STATES = (SubmissionState.GRADED, SubmissionState.PUBLISHED)


class CourseworkReportingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def coursework_by(
        self,
        group: str,
        *,
        visibility: "WorkVisibility",
        course_id: int | None = None,
        batch_id: int | None = None,
    ) -> list[tuple[str, str, dict[str, float | int | None]]]:
        """Submission, lateness, grading and pass counts per group.

        Draft assignments are excluded. A draft has not been set for anybody,
        so counting its "missing submissions" would invent work nobody was
        asked to do and put every student in the chase list.
        """
        # One row per (published assignment, eligible student) -- the
        # population the rates are measured against.
        expected = (
            select(
                Assignment.id.label("assignment_id"),
                Assignment.course_id.label("course_id"),
                Assignment.passing_score.label("passing_score"),
                Batch.id.label("batch_id"),
                Enrollments.student_id.label("student_id"),
            )
            # `select_from` names the left side: the column list mentions
            # three entities, so without it SQLAlchemy cannot tell which one
            # the join hangs off.
            .select_from(Assignment)
            .join(Batch, covers_batch(Assignment, Batch))
            .join(
                Enrollments,
                and_(
                    Enrollments.batch_id == Batch.id,
                    Enrollments.status.in_(ACTIVE_STATUSES),
                ),
            )
            .where(Assignment.state != AssessmentState.DRAFT)
        )
        if course_id is not None:
            expected = expected.where(Assignment.course_id == course_id)
        if batch_id is not None:
            expected = expected.where(Batch.id == batch_id)

        expected = visibility.apply(
            expected,
            course_column=Assignment.course_id,
            student_column=Enrollments.student_id,
        ).subquery("expected")

        # One row per (assignment, student) is guaranteed by the schema.
        #
        # This started life as a `DISTINCT ON` picking the highest
        # `attempt_number`, on the assumption that resubmission accumulates
        # rows. It does not: `uq_assignment_submissions_assignment_student`
        # means a replacement *updates* the row in place and `attempt_number`
        # is a counter on it. The deduplication was therefore a sort the
        # database could never need, guarding a case it refuses to store --
        # and untestable, since the fixture that would have exercised it is
        # rejected by the constraint.
        latest = (
            select(
                AssignmentSubmission.assignment_id,
                AssignmentSubmission.student_id,
                AssignmentSubmission.state,
                AssignmentSubmission.grade,
                AssignmentSubmission.graded_at,
            )
            .subquery("latest")
        )

        # The FROM chain is built as one join expression rather than by
        # chaining `.join()` onto a select: with two subqueries in play
        # SQLAlchemy cannot tell which side a later join hangs off, and
        # refuses to guess.
        from_obj = expected.outerjoin(
            latest,
            and_(
                latest.c.assignment_id == expected.c.assignment_id,
                latest.c.student_id == expected.c.student_id,
            ),
        )

        if group == "course":
            from_obj = from_obj.join(Course, Course.id == expected.c.course_id)
            key_col, label_col = Course.public_id, Course.title
        elif group == "batch":
            from_obj = from_obj.join(Batch, Batch.id == expected.c.batch_id)
            key_col, label_col = Batch.public_id, Batch.batch_code
        elif group == "assignment":
            from_obj = from_obj.join(Assignment, Assignment.id == expected.c.assignment_id)
            key_col, label_col = Assignment.public_id, Assignment.title
        elif group == "student":
            from_obj = from_obj.join(User, User.id == expected.c.student_id)
            key_col, label_col = User.public_id, User.username
        else:  # pragma: no cover - the enum is validated at the route
            raise ValueError(f"Unsupported grouping: {group}")

        submitted = latest.c.state.is_not(None)
        marked = latest.c.state.in_(_MARKED_STATES)

        def count_when(condition: Any) -> Any:
            return func.count(case((condition, 1)))

        stmt = (
            select(
                key_col.label("key"),
                label_col.label("label"),
                func.count().label("expected"),
                count_when(submitted).label("submitted"),
                count_when(latest.c.state == SubmissionState.LATE).label("late"),
                count_when(marked).label("marked"),
                # A mark can only be compared with a threshold where the
                # assignment has one; without it the student is left out of
                # the pass rate rather than counted as a failure.
                count_when(
                    and_(marked, expected.c.passing_score.is_not(None))
                ).label("pass_assessed"),
                count_when(
                    and_(
                        marked,
                        expected.c.passing_score.is_not(None),
                        latest.c.grade >= expected.c.passing_score,
                    )
                ).label("passed"),
            )
            .select_from(from_obj)
            .group_by(key_col, label_col)
            .order_by(label_col)
            .limit(MAX_GROUPS + 1)
        )

        out: list[tuple[str, str, dict[str, float | int | None]]] = []
        for key, label, expected_n, submitted_n, late_n, marked_n, assessed_n, passed_n in (
            await self.session.execute(stmt)
        ).all():
            expected_n = int(expected_n)
            submitted_n = int(submitted_n)
            marked_n = int(marked_n)
            assessed_n = int(assessed_n)
            out.append(
                (
                    str(getattr(key, "value", key)),
                    str(getattr(label, "value", label)),
                    {
                        "expected": expected_n,
                        "submitted": submitted_n,
                        # The actionable number: who to chase.
                        "missing": expected_n - submitted_n,
                        "late": int(late_n),
                        "awaiting_grading": submitted_n - marked_n,
                        "submission_rate": _rate(submitted_n, expected_n),
                        "pass_rate": _rate(int(passed_n), assessed_n),
                    },
                )
            )
        return out


def _rate(part: int, whole: int) -> float | None:
    """A percentage, or None when there is nothing to measure.

    `None`, never 0: "no assignments have been set" and "nobody submitted"
    are different facts, and §38 is explicit that the second must not be
    rendered as the first. A cohort with no coursework yet showing a 0%
    submission rate is a chase list nobody needs to act on.
    """
    if whole <= 0:
        return None
    return _round(part / whole * 100)
