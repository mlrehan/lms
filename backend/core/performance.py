"""The one place a weighted academic result is worked out (spec §7, §37, §38).

Every screen that shows an overall mark calls this. That is the entire point:
the alternative -- a gradebook page, a transcript and a student dashboard each
doing their own arithmetic -- is three numbers for one student that disagree
with each other, and no way to say which is right.

Pure functions over explicit inputs, like `core/live_class.py`. No session, no
queries, no ORM objects: the service layer gathers the rows, this decides what
they add up to, and every step is testable without a database.

---

**Three rules, and each is the answer to a way this goes wrong.**

**1. A missing mark is not a zero.** §38 is emphatic, and the failure it
describes is the common one: an examination that has not happened yet, counted
as 0 out of 45, turns an excellent student into a failing one on their own
dashboard. `MissingMarkPolicy.EXCLUDE` removes an unassessed component from the
denominator instead, so the answer becomes "82% of the 55 marks assessed so
far", which is both true and useful. `ZERO` exists because some institutions
genuinely do mark non-submission as zero -- but it is a choice they make, not a
default they inherit.

**2. "Current" and "final" are different numbers and must never be conflated.**
A student with 82% of their assessed work done well is not an 82% student yet.
`current_percentage` is out of what has been assessed; `final_percentage` is
`None` until every weighted component has a mark. A UI that shows one where it
means the other is the single most misleading thing this module could produce.

**3. Every number shows its working.** `ComponentBreakdown` carries the
percentage, the weight, the contribution and -- when a component was left out --
the reason. §37's drill-down is not a separate feature to build later; it is the
return value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Sequence

from backend.utils.enums import (
    GradeComponentType,
    MissingMarkPolicy,
    SubmissionState,
)

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")

#: Two decimal places, half-up. Academic marks are published, appealed and
#: printed on transcripts, so the rounding has to be stated once and applied
#: everywhere rather than left to whatever each caller's formatter does.
_CENTS = Decimal("0.01")


def _round(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- inputs ---


@dataclass(frozen=True)
class Mark:
    """One piece of assessed work, as the engine needs to see it.

    `earned is None` means *no mark exists* -- which is different from
    `earned == 0`, and the distinction is the whole of §38. `state` says which
    kind of "no mark" it is: not yet assessed, absent, or exempted.
    """

    component_type: GradeComponentType
    earned: Decimal | None
    possible: Decimal
    state: SubmissionState = SubmissionState.GRADED
    #: This piece of work's pull *within* its component. Two assignments in a
    #: course need not be worth the same; how much the assignment component is
    #: worth overall is a separate, scheme-level decision.
    weight: Decimal = Decimal("1")
    label: str | None = None

    @property
    def is_scored(self) -> bool:
        return self.earned is not None and self.possible > _ZERO

    @property
    def percentage(self) -> Decimal | None:
        if not self.is_scored:
            return None
        assert self.earned is not None
        return (self.earned / self.possible) * _HUNDRED


@dataclass(frozen=True)
class ComponentWeight:
    """What a scheme says one component is worth."""

    component_type: GradeComponentType
    weight_percentage: Decimal
    label: str | None = None
    is_mandatory: bool = False
    passing_percentage: Decimal | None = None


@dataclass(frozen=True)
class Band:
    """A slice of the grade scale."""

    min_score: Decimal
    max_score: Decimal
    letter_grade: str
    gpa_points: Decimal
    is_pass: bool = True

    def contains(self, percentage: Decimal) -> bool:
        return self.min_score <= percentage <= self.max_score


@dataclass(frozen=True)
class Scheme:
    """The academic policy a result is computed under."""

    components: Sequence[ComponentWeight]
    bands: Sequence[Band] = field(default_factory=tuple)
    passing_percentage: Decimal = Decimal("50")
    missing_mark_policy: MissingMarkPolicy = MissingMarkPolicy.EXCLUDE

    @property
    def total_weight(self) -> Decimal:
        return sum((c.weight_percentage for c in self.components), _ZERO)

    @property
    def is_configured(self) -> bool:
        """A scheme with no weights cannot produce a meaningful result.

        Reported rather than worked around: the migration deliberately creates
        the default scheme empty, because inventing "examinations are 45%" on
        an institution's behalf would silently re-grade every student.
        """
        return bool(self.components) and self.total_weight > _ZERO


# --------------------------------------------------------------- outputs ---


@dataclass(frozen=True)
class ComponentBreakdown:
    """One line of §37's drill-down: `82 × 15% = 12.30`."""

    component_type: GradeComponentType
    label: str
    weight_percentage: Decimal
    #: The student's mark in this component, out of 100. `None` when nothing
    #: has been assessed and the policy excludes it.
    percentage: Decimal | None
    #: `percentage × weight ÷ 100`. `None` when the component does not count.
    contribution: Decimal | None
    #: How many pieces of work fed this line, and how many had marks. Shown so
    #: "82%" is visibly "82% of the three assignments marked so far".
    marks_total: int
    marks_scored: int
    counted: bool
    #: Why it was left out, in words a tutor can act on. Empty when it counted.
    excluded_reason: str = ""
    is_mandatory: bool = False
    meets_component_pass: bool | None = None


@dataclass(frozen=True)
class Performance:
    """What a student's weighted result actually is, and how it was reached."""

    components: tuple[ComponentBreakdown, ...]

    #: The share of the scheme's 100 that has been assessed. §38's
    #: "Completed weighted components: 35/100".
    assessed_weight: Decimal
    total_weight: Decimal

    #: The mark **out of what has been assessed**. This is the number to show a
    #: student mid-course; it answers "how am I doing".
    current_percentage: Decimal | None

    #: The mark **out of the whole scheme**. `None` until every weighted
    #: component has been assessed -- that is §38's "Projected/Final
    #: Performance: Not Yet Available", and returning a number here early is
    #: the misleading behaviour the whole module exists to avoid.
    final_percentage: Decimal | None

    grade: str | None
    gpa: Decimal | None
    is_pass: bool | None

    #: True when the scheme has no weights configured. Every figure above is
    #: `None` in that case, and a caller must say so rather than show a zero.
    unconfigured: bool = False
    #: Components marked mandatory that the student has not passed. A student
    #: can clear the overall threshold and still fail on one of these.
    failed_mandatory: tuple[GradeComponentType, ...] = ()

    @property
    def is_complete(self) -> bool:
        return self.final_percentage is not None


# ---------------------------------------------------------------- engine ---


def _component_percentage(marks: Sequence[Mark]) -> tuple[Decimal | None, int, int]:
    """Weighted mean of the scored marks in one component.

    Returns `(percentage, total, scored)`. Unscored marks are simply absent
    from the mean -- deciding whether their absence should drag the component
    down is the *policy's* job, made once in `evaluate`, not something to
    re-decide per component.
    """
    total = len(marks)
    scored = [m for m in marks if m.is_scored]
    if not scored:
        return None, total, 0

    weight_sum = sum((m.weight for m in scored), _ZERO)
    if weight_sum <= _ZERO:
        return None, total, len(scored)

    weighted = sum(((m.percentage or _ZERO) * m.weight for m in scored), _ZERO)
    return weighted / weight_sum, total, len(scored)


def _counts(mark: Mark) -> bool:
    """Is this mark a number the result should include?

    `ABSENT` counts: an absence is a nil result the institution has decided
    about, not a gap in the record.

    Exemption is deliberately **not** checked here. It is handled once, in
    `evaluate`, where an exempted mark is dropped before it reaches a
    component -- so a second check in this function would be unreachable. Two
    guards where one cannot fire is worse than one, because a reader counts two
    defences and a mutation test proves only one of them exists.
    """
    return mark.is_scored or mark.state.counts_toward_grade


def _band_for(bands: Sequence[Band], percentage: Decimal) -> Band | None:
    for band in bands:
        if band.contains(percentage):
            return band
    return None


def evaluate(marks: Iterable[Mark], scheme: Scheme) -> Performance:
    """Work out one student's weighted result, showing every step.

    The only function that decides what an overall mark is. Callers hand it the
    marks they have gathered and the scheme in force; it returns both the number
    and the reasoning behind it.
    """
    by_component: dict[GradeComponentType, list[Mark]] = {}
    for mark in marks:
        if mark.state is SubmissionState.EXEMPTED:
            # Dropped before it reaches a component, so it cannot affect the
            # mean *or* the denominator.
            continue
        by_component.setdefault(mark.component_type, []).append(mark)

    if not scheme.is_configured:
        # Honest emptiness. A zero here would look like a student who failed
        # everything, when the truth is that nobody has set the weightings.
        return Performance(
            components=tuple(
                ComponentBreakdown(
                    component_type=ct,
                    label=ct.value.replace("_", " ").title(),
                    weight_percentage=_ZERO,
                    percentage=_component_percentage(ms)[0],
                    contribution=None,
                    marks_total=len(ms),
                    marks_scored=len([m for m in ms if m.is_scored]),
                    counted=False,
                    excluded_reason="No grading scheme is configured.",
                )
                for ct, ms in sorted(by_component.items(), key=lambda kv: kv[0].value)
            ),
            assessed_weight=_ZERO,
            total_weight=_ZERO,
            current_percentage=None,
            final_percentage=None,
            grade=None,
            gpa=None,
            is_pass=None,
            unconfigured=True,
        )

    breakdowns: list[ComponentBreakdown] = []
    assessed_weight = _ZERO
    earned_weighted = _ZERO
    failed_mandatory: list[GradeComponentType] = []

    for weight in scheme.components:
        marks_for = [m for m in by_component.get(weight.component_type, []) if _counts(m)]
        percentage, total, scored = _component_percentage(marks_for)
        label = weight.label or weight.component_type.value.replace("_", " ").title()

        counted = percentage is not None
        reason = ""

        if percentage is None:
            if scheme.missing_mark_policy is MissingMarkPolicy.ZERO:
                # The institution's explicit choice: unassessed work scores
                # nothing and still occupies its share of the total.
                percentage, counted = _ZERO, True
                reason = ""
            else:
                reason = (
                    "Not yet assessed — excluded from the total."
                    if total == 0
                    else "No marks recorded yet — excluded from the total."
                )

        contribution = None
        if counted and percentage is not None:
            contribution = (percentage * weight.weight_percentage) / _HUNDRED
            assessed_weight += weight.weight_percentage
            earned_weighted += contribution

        meets = None
        if weight.passing_percentage is not None and percentage is not None:
            meets = percentage >= weight.passing_percentage
            if weight.is_mandatory and not meets:
                failed_mandatory.append(weight.component_type)

        breakdowns.append(
            ComponentBreakdown(
                component_type=weight.component_type,
                label=label,
                weight_percentage=_round(weight.weight_percentage),
                percentage=_round(percentage) if percentage is not None else None,
                contribution=_round(contribution) if contribution is not None else None,
                marks_total=total,
                marks_scored=scored,
                counted=counted,
                excluded_reason=reason,
                is_mandatory=weight.is_mandatory,
                meets_component_pass=meets,
            )
        )

    # "How am I doing" -- out of the work assessed so far.
    current = (earned_weighted / assessed_weight) * _HUNDRED if assessed_weight > _ZERO else None

    # "What did I get" -- only once every weighted component has a mark.
    # Compared against the scheme's own total rather than 100, because a scheme
    # whose weights sum to 90 is misconfigured and should not silently produce
    # a final mark as though it summed correctly.
    complete = assessed_weight >= scheme.total_weight and scheme.total_weight > _ZERO
    final = earned_weighted if complete else None

    # The grade is quoted against the number that exists. Mid-course that is
    # the current standing, which is what a tutor looking at a gradebook wants;
    # it becomes the final grade the moment the last component lands.
    basis = final if final is not None else current
    band = _band_for(scheme.bands, basis) if basis is not None else None

    is_pass = None
    if basis is not None:
        is_pass = (band.is_pass if band is not None else basis >= scheme.passing_percentage)
        if failed_mandatory:
            # A mandatory component not passed fails the whole thing, however
            # good the weighted total looks.
            is_pass = False

    return Performance(
        components=tuple(breakdowns),
        assessed_weight=_round(assessed_weight),
        total_weight=_round(scheme.total_weight),
        current_percentage=_round(current) if current is not None else None,
        final_percentage=_round(final) if final is not None else None,
        grade=band.letter_grade if band else None,
        gpa=band.gpa_points if band else None,
        is_pass=is_pass,
        failed_mandatory=tuple(failed_mandatory),
    )
