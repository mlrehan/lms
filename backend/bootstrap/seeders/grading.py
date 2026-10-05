"""A usable starting point for grading, on a fresh install.

**Why this is a seeder and not part of the migration.** The migration that
created the institution's default scheme deliberately left it empty: it runs
against databases that already hold real students, and inventing "examinations
are 45%" there would silently re-grade all of them on upgrade. A seeder runs
where an operator is setting the system up, and the difference matters.

**§6 forbids hard-coding the percentages, and this does not hard-code them.**
What it writes is a starting point that the Grading schemes screen exists to
change -- fully editable, shown with a running total, and never re-applied once
somebody has set their own. The alternative, shipping with nothing, means every
performance figure in the product reports "not configured" until someone has
found the screen, which is honest but not helpful.

**It only ever acts on a scheme that has no components at all.** Anything else
would overwrite an institution's own policy on the next deploy -- the worst
possible behaviour for this particular table, because the change is invisible
until somebody queries a grade.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.gradebook import GradeBand
from backend.models.grading import GradingScheme, GradingSchemeComponent
from backend.utils.enums import GradeComponentType as C

#: A conventional starting split, offered rather than imposed. Every figure is
#: editable on the Grading schemes screen, and the screen shows the running
#: total precisely so an institution can rearrange it into its own policy.
_STARTING_WEIGHTS: tuple[tuple[C, Decimal, str], ...] = (
    (C.ASSIGNMENT, Decimal("30"), "Assignments"),
    (C.QUIZ, Decimal("10"), "Quizzes"),
    (C.FINAL_EXAM, Decimal("40"), "Examinations"),
    (C.ATTENDANCE, Decimal("10"), "Attendance"),
    (C.PRACTICAL, Decimal("10"), "Class performance"),
)

#: A letter ladder is far less contentious than a weighting -- it only names a
#: percentage, and an institution that disagrees is renaming rather than
#: re-grading. Seeded for the same reason: a scheme with no bands reports a
#: bare percentage and no grade at all.
_STARTING_BANDS: tuple[tuple[str, str, str, str, bool], ...] = (
    ("90", "100", "A+", "4.00", True),
    ("80", "89.99", "A", "3.70", True),
    ("70", "79.99", "B", "3.00", True),
    ("60", "69.99", "C", "2.30", True),
    ("50", "59.99", "D", "1.70", True),
    ("0", "49.99", "F", "0.00", False),
)


async def seed_grading(session: AsyncSession) -> dict[str, int]:
    """Give the default scheme a starting configuration, once. Idempotent."""
    scheme = (
        await session.execute(
            select(GradingScheme).where(GradingScheme.is_default.is_(True))
        )
    ).scalar_one_or_none()

    if scheme is None:
        # No default at all. The academic-foundation migration inserts one,
        # so this should be unreachable -- and on a real database it was not:
        # the row was absent and this returned `skipped`, leaving an
        # institution with no grading scheme at all. Nothing then had a letter
        # grade, transcripts could compute no overall result, and the grade
        # distribution refused to draw.
        #
        # Creating it here cannot race the migration: a migration runs once
        # and before this, and `uq_grading_schemes_one_default` refuses a
        # second default outright rather than letting two exist. Reporting a
        # problem nobody reads is worse than repairing it.
        scheme = GradingScheme(
            name="Institution default",
            description=(
                "Created automatically. Set component weightings before "
                "relying on overall performance."
            ),
            is_default=True,
            is_active=True,
        )
        session.add(scheme)
        await session.flush()
        created_default = 1
    else:
        created_default = 0

    components = int(
        (
            await session.execute(
                select(func.count())
                .select_from(GradingSchemeComponent)
                .where(GradingSchemeComponent.scheme_id == scheme.id)
            )
        ).scalar_one()
    )
    bands = int(
        (
            await session.execute(
                select(func.count()).select_from(GradeBand).where(GradeBand.scheme_id == scheme.id)
            )
        ).scalar_one()
    )

    created_components = 0
    if components == 0:
        # Only when there is nothing. An institution that has set its own
        # weights must never find them replaced by a deploy.
        for component_type, weight, label in _STARTING_WEIGHTS:
            session.add(
                GradingSchemeComponent(
                    scheme_id=scheme.id,
                    component_type=component_type,
                    label=label,
                    weight_percentage=weight,
                )
            )
            created_components += 1

    created_bands = 0
    if bands == 0:
        for low, high, letter, gpa, is_pass in _STARTING_BANDS:
            session.add(
                GradeBand(
                    scheme_id=scheme.id,
                    min_score=Decimal(low),
                    max_score=Decimal(high),
                    letter_grade=letter,
                    gpa_points=Decimal(gpa),
                    is_pass=is_pass,
                )
            )
            created_bands += 1

    if created_components:
        # Activated only when this seeder is the one that configured it: the
        # weights it just wrote total 100, which is the condition `activate`
        # would check anyway. A scheme somebody else left half-configured is
        # left exactly as they left it.
        scheme.is_active = True
        scheme.updated_at = datetime.now(UTC)

    await session.flush()
    return {
        "schemes_created": created_default,
        "components_created": created_components,
        "bands_created": created_bands,
        "skipped": 0,
    }
