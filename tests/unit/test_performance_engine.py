"""What a student's mark actually is.

Every screen that shows an overall result calls `evaluate`. If it is wrong, it
is wrong identically everywhere, on a number people appeal against and print on
transcripts -- so these tests are arithmetic first and behaviour second.

The spec's own worked example (§37) is here verbatim, because a rounding rule
that is nearly right produces a figure nobody can reconcile against the one
their tutor quoted.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.core.performance import (
    Band,
    ComponentWeight,
    Mark,
    Performance,
    Scheme,
    evaluate,
)
from backend.utils.enums import (
    GradeComponentType as C,
    MissingMarkPolicy,
    SubmissionState as S,
)

D = Decimal


def _bands() -> list[Band]:
    return [
        Band(D("90"), D("100"), "A+", D("4.0")),
        Band(D("80"), D("89.99"), "A", D("3.7")),
        Band(D("70"), D("79.99"), "B", D("3.0")),
        Band(D("60"), D("69.99"), "C", D("2.3")),
        Band(D("50"), D("59.99"), "D", D("1.7")),
        Band(D("0"), D("49.99"), "F", D("0"), is_pass=False),
    ]


def _spec_scheme(**over) -> Scheme:
    """§6's example weighting, which is also §37's worked example."""
    return Scheme(
        components=[
            ComponentWeight(C.ASSIGNMENT, D("15")),
            ComponentWeight(C.QUIZ, D("10")),
            ComponentWeight(C.FINAL_EXAM, D("45")),
            ComponentWeight(C.ATTENDANCE, D("10")),
            ComponentWeight(C.PRACTICAL, D("20")),
        ],
        bands=_bands(),
        **over,
    )


def _mark(component: C, pct: str, **over) -> Mark:
    return Mark(component_type=component, earned=D(pct), possible=D("100"), **over)


# --------------------------------------------------------------- arithmetic ---


def test_the_specs_own_worked_example() -> None:
    """§37, to the penny.

    Assignments 82×15% = 12.30, Quizzes 90×10% = 9.00,
    Examinations 76×45% = 34.20, Attendance 95×10% = 9.50,
    Practical 88×20% = 17.60  ->  82.60
    """
    result = evaluate(
        [
            _mark(C.ASSIGNMENT, "82"),
            _mark(C.QUIZ, "90"),
            _mark(C.FINAL_EXAM, "76"),
            _mark(C.ATTENDANCE, "95"),
            _mark(C.PRACTICAL, "88"),
        ],
        _spec_scheme(),
    )

    lines = {b.component_type: b.contribution for b in result.components}
    assert lines[C.ASSIGNMENT] == D("12.30")
    assert lines[C.QUIZ] == D("9.00")
    assert lines[C.FINAL_EXAM] == D("34.20")
    assert lines[C.ATTENDANCE] == D("9.50")
    assert lines[C.PRACTICAL] == D("17.60")

    assert result.final_percentage == D("82.60")
    assert result.grade == "A"
    assert result.is_pass is True


def test_the_breakdown_adds_up_to_the_total() -> None:
    """The drill-down is not a decorative re-derivation: if the lines and the
    headline disagree, one of them is lying and nobody can tell which."""
    result = evaluate(
        [_mark(C.ASSIGNMENT, "70"), _mark(C.QUIZ, "60"), _mark(C.FINAL_EXAM, "90"),
         _mark(C.ATTENDANCE, "100"), _mark(C.PRACTICAL, "55")],
        _spec_scheme(),
    )
    assert sum(b.contribution for b in result.components if b.contribution) == result.final_percentage


def test_several_marks_in_one_component_are_averaged_by_their_own_weight() -> None:
    """Two assignments, one worth double. (60×1 + 90×2) / 3 = 80."""
    result = evaluate(
        [
            Mark(C.ASSIGNMENT, D("60"), D("100"), weight=D("1")),
            Mark(C.ASSIGNMENT, D("90"), D("100"), weight=D("2")),
        ],
        Scheme(components=[ComponentWeight(C.ASSIGNMENT, D("100"))], bands=_bands()),
    )
    assert result.components[0].percentage == D("80.00")


def test_a_mark_out_of_something_other_than_a_hundred() -> None:
    """Tutors mark out of 20, out of 5, out of whatever suits the task."""
    result = evaluate(
        [Mark(C.PRACTICAL, D("17"), D("20"))],
        Scheme(components=[ComponentWeight(C.PRACTICAL, D("100"))], bands=_bands()),
    )
    assert result.components[0].percentage == D("85.00")


# ------------------------------------------------------- missing data (§38) ---


def test_an_unassessed_component_is_excluded_not_zeroed() -> None:
    """The failure §38 exists to prevent: an examination that has not happened
    yet, counted as 0/45, turns a strong student into a failing one."""
    result = evaluate(
        [_mark(C.ASSIGNMENT, "82"), _mark(C.QUIZ, "90")],
        _spec_scheme(),
    )

    exam = next(b for b in result.components if b.component_type is C.FINAL_EXAM)
    assert exam.counted is False
    assert exam.contribution is None
    assert "excluded" in exam.excluded_reason.lower()

    # 82×15 + 90×10 = 21.30 over the 25 assessed -> 85.2%
    assert result.assessed_weight == D("25.00")
    assert result.current_percentage == D("85.20")


def test_a_final_mark_is_withheld_until_everything_is_assessed() -> None:
    """§38's "Projected/Final Performance: Not Yet Available". Returning a
    number here would be the single most misleading thing this module could
    do -- it reads as a finished result."""
    partial = evaluate([_mark(C.ASSIGNMENT, "82")], _spec_scheme())
    assert partial.current_percentage is not None
    assert partial.final_percentage is None
    assert partial.is_complete is False


def test_the_zero_policy_is_available_when_an_institution_wants_it() -> None:
    """Some institutions really do mark non-submission as zero. It is a choice
    they make, not a default they inherit."""
    marks = [_mark(C.ASSIGNMENT, "82"), _mark(C.QUIZ, "90")]
    scheme = _spec_scheme(missing_mark_policy=MissingMarkPolicy.ZERO)
    result = evaluate(marks, scheme)

    # Everything is now assessed, because the unmarked components score zero.
    assert result.assessed_weight == D("100.00")
    assert result.final_percentage == D("21.30")
    assert result.is_pass is False


def test_an_exemption_is_removed_from_the_total_even_when_it_has_a_mark() -> None:
    """A student who sat the exam, scored 30, and was then exempted on appeal.

    The mark **must** carry a score for this test to mean anything. An exempted
    row with no score is indistinguishable from one nobody has marked yet, so
    the first version of this test passed with the exemption rule deleted
    entirely -- it was exercising the missing-mark path, not the exemption
    path. Here, deleting the rule lets 30 drag the average down and the
    assertion fails, which is what a test of this rule should do.
    """
    result = evaluate(
        [
            _mark(C.ASSIGNMENT, "82"),
            Mark(C.FINAL_EXAM, D("30"), D("100"), state=S.EXEMPTED),
        ],
        _spec_scheme(),
    )
    exam = next(b for b in result.components if b.component_type is C.FINAL_EXAM)
    assert exam.counted is False
    assert exam.percentage is None
    # Only the assignment counted, so the standing is the assignment's own mark.
    assert result.assessed_weight == D("15.00")
    assert result.current_percentage == D("82.00")


def test_an_absence_does_count_as_a_nil_result() -> None:
    """The mirror of the test above, and the reason the two states are
    separate: an absence is a decision the institution made, not a gap."""
    result = evaluate(
        [Mark(C.FINAL_EXAM, D("0"), D("100"), state=S.ABSENT)],
        Scheme(components=[ComponentWeight(C.FINAL_EXAM, D("100"))], bands=_bands()),
    )
    assert result.components[0].counted is True
    assert result.final_percentage == D("0.00")
    assert result.is_pass is False


# ------------------------------------------------------ unconfigured scheme ---


def test_an_unweighted_scheme_reports_itself_rather_than_returning_zero() -> None:
    """The migration creates the institution's default scheme with no weights
    on purpose -- inventing "examinations are 45%" would silently re-grade
    everybody. A zero here would look like a student who failed everything."""
    result = evaluate([_mark(C.ASSIGNMENT, "82")], Scheme(components=[], bands=_bands()))
    assert result.unconfigured is True
    assert result.current_percentage is None
    assert result.final_percentage is None
    assert result.grade is None
    assert result.components[0].percentage == D("82.00")  # still shows what is known


# ------------------------------------------------------- mandatory components ---


def test_failing_a_mandatory_component_fails_the_course() -> None:
    """"You must pass the final examination regardless of your coursework" is
    an ordinary rule, and a weighted total alone cannot express it."""
    scheme = Scheme(
        components=[
            ComponentWeight(C.ASSIGNMENT, D("60")),
            ComponentWeight(C.FINAL_EXAM, D("40"), is_mandatory=True, passing_percentage=D("40")),
        ],
        bands=_bands(),
    )
    result = evaluate([_mark(C.ASSIGNMENT, "95"), _mark(C.FINAL_EXAM, "30")], scheme)

    assert result.final_percentage == D("69.00")   # comfortably over 50
    assert result.is_pass is False                  # and still a fail
    assert result.failed_mandatory == (C.FINAL_EXAM,)


def test_passing_the_mandatory_component_leaves_the_pass_intact() -> None:
    """Without this, "is_pass is False" above could be true for any reason."""
    scheme = Scheme(
        components=[
            ComponentWeight(C.ASSIGNMENT, D("60")),
            ComponentWeight(C.FINAL_EXAM, D("40"), is_mandatory=True, passing_percentage=D("40")),
        ],
        bands=_bands(),
    )
    result = evaluate([_mark(C.ASSIGNMENT, "95"), _mark(C.FINAL_EXAM, "45")], scheme)
    assert result.is_pass is True
    assert result.failed_mandatory == ()


# ---------------------------------------------------------------- grading ---


@pytest.mark.parametrize(
    ("pct", "letter", "passing"),
    [("95", "A+", True), ("85", "A", True), ("75", "B", True),
     ("65", "C", True), ("55", "D", True), ("30", "F", False)],
)
def test_the_band_decides_the_letter_and_whether_it_is_a_pass(pct, letter, passing) -> None:
    result = evaluate(
        [_mark(C.ASSIGNMENT, pct)],
        Scheme(components=[ComponentWeight(C.ASSIGNMENT, D("100"))], bands=_bands()),
    )
    assert result.grade == letter
    assert result.is_pass is passing


def test_without_bands_the_scheme_threshold_decides() -> None:
    """A percentage-only scheme is a legitimate configuration; it should not
    need a letter ladder it does not use."""
    scheme = Scheme(components=[ComponentWeight(C.ASSIGNMENT, D("100"))], passing_percentage=D("40"))
    assert evaluate([_mark(C.ASSIGNMENT, "45")], scheme).is_pass is True
    assert evaluate([_mark(C.ASSIGNMENT, "35")], scheme).is_pass is False


def test_the_grade_mid_course_is_quoted_against_what_has_been_assessed() -> None:
    """A tutor looking at a gradebook in week six wants "currently a B", not a
    blank cell -- and it must not be presented as final."""
    result = evaluate([_mark(C.ASSIGNMENT, "75")], _spec_scheme())
    assert result.grade == "B"
    assert result.final_percentage is None
