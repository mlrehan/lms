"""Grade distribution (spec §34).

The report an average cannot replace. A cohort averaging 68% might be
thirty students clustered at 68, or fifteen at 85 and fifteen at 50 — the
same mean, and completely different teaching problems. Only the shape says
which.

**Counted against the enrolled roster, not against the marks.** A
distribution over "students who have marks" quietly omits the ones nobody
has assessed, and a class where half the cohort is unassessed produces a
confident-looking curve drawn from the other half. Unassessed students get
their own row instead, so the reader can see how much of the cohort the
shape actually describes.

**Empty bands are rows too.** A distribution with "B: 0" between two
populated bands is the interesting part; dropping it leaves a reader to
infer a gap that was never shown.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Numeric, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.batch import Batch
from backend.models.enrollment import Enrollments
from backend.models.gradebook import GradeBand, GradeBookEntry
from backend.repositories.enrollment import ACTIVE_STATUSES

if TYPE_CHECKING:  # pragma: no cover
    from backend.services.scope import WorkVisibility


class DistributionReportingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def distribution(
        self,
        *,
        visibility: "WorkVisibility",
        scheme_id: int,
        course_id: int | None,
        batch_id: int | None,
    ) -> tuple[list[tuple[str, str, int]], int]:
        """``([(letter, label, students)], unassessed)`` for one grading scheme.

        The caller resolves the scheme, because which one applies is §13's
        course-override-then-default rule and that lives in
        `GradingSchemeService.for_course` — resolving it again here is how the
        two would come to disagree.
        """
        roster = (
            select(
                Enrollments.student_id.label("student_id"),
                Enrollments.batch_id.label("batch_id"),
            )
            .join(Batch, Batch.id == Enrollments.batch_id)
            .where(Enrollments.status.in_(ACTIVE_STATUSES))
        )
        if batch_id is not None:
            roster = roster.where(Enrollments.batch_id == batch_id)
        else:
            # §3's "all *active* batches of that course": a closed cohort is
            # not part of this course's current shape.
            roster = roster.where(Batch.course_id == course_id, Batch.is_active.is_(True))

        roster = visibility.apply(
            roster, course_column=Batch.course_id, student_column=Enrollments.student_id
        ).subquery("roster")

        # Marks are matched on the (student, batch) pair, not on the student
        # alone: a student enrolled in two batches would otherwise have the
        # other batch's marks folded into this cohort's distribution.
        per_student = (
            select(
                roster.c.student_id.label("student_id"),
                func.sum(GradeBookEntry.score).label("scored"),
                func.sum(GradeBookEntry.max_score).label("available"),
            )
            .select_from(roster)
            .outerjoin(
                GradeBookEntry,
                and_(
                    GradeBookEntry.student_id == roster.c.student_id,
                    GradeBookEntry.batch_id == roster.c.batch_id,
                ),
            )
            .group_by(roster.c.student_id)
            .subquery("per_student")
        )

        pct = (
            100.0
            * func.cast(per_student.c.scored, Numeric)
            / func.nullif(func.cast(per_student.c.available, Numeric), 0)
        ).label("pct")

        scored = select(per_student.c.student_id, pct).subquery("scored")

        # Bands on the left so a band nobody reached still produces a row.
        banded = (
            select(
                GradeBand.letter_grade.label("letter"),
                GradeBand.min_score.label("min_score"),
                GradeBand.max_score.label("max_score"),
                func.count(scored.c.student_id).label("students"),
            )
            .select_from(GradeBand)
            .outerjoin(
                scored,
                and_(
                    scored.c.pct >= GradeBand.min_score,
                    scored.c.pct <= GradeBand.max_score,
                ),
            )
            .where(GradeBand.scheme_id == scheme_id)
            .group_by(GradeBand.letter_grade, GradeBand.min_score, GradeBand.max_score)
            .order_by(GradeBand.min_score.desc())
        )

        rows = [
            (
                str(letter),
                f"{letter} ({_trim(low)}–{_trim(high)}%)",
                int(students),
            )
            for letter, low, high, students in (await self.session.execute(banded)).all()
        ]

        unassessed = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(scored).where(scored.c.pct.is_(None))
                )
            ).scalar_one()
        )
        return rows, unassessed


def _trim(value: object) -> str:
    """`50.00` reads as `50`; a band boundary is not a measurement."""
    text = f"{float(str(value)):.2f}".rstrip("0").rstrip(".")
    return text or "0"
