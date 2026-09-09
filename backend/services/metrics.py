"""Derived numbers that more than one surface reports.

**One rule, one place.** `attendance_rate` was previously computed inline in
`attendance_service.summarise`. The reports in spec §18 quote the same figure
grouped by course, tutor and month, and a dashboard tile quotes it again — so
without a shared definition there would be three implementations of "what
counts as attendance", and the first time one of them was adjusted the
institution would be quoting two different numbers for the same students.

This codebase has already been bitten by exactly that shape: "is this account
usable?" was written out three times and the three answers differed.
"""

from __future__ import annotations

from decimal import Decimal


def attendance_rate(
    *, present: int, late: int, absent: int, excused: int
) -> float | None:
    """Percentage of assessable sessions actually attended.

    An **excused** absence leaves the denominator rather than counting
    against the student — that is what "excused" means. A student whose only
    records are excused therefore has no meaningful rate at all, and gets
    `None` instead of a misleading 0% or 100%.

    `late` counts as attended: the student was there. Punctuality is a
    separate question and the raw `late` count is always reported alongside.
    """
    total = present + late + absent + excused
    assessable = total - excused
    if assessable <= 0:
        return None
    return round((present + late) / assessable * 100, 2)


def percentage(scored: Decimal | float | None, out_of: Decimal | float | None) -> float | None:
    """`scored / out_of` as a percentage, or None when it cannot be computed.

    Returns None for a zero or missing denominator rather than 0.0: a
    component worth no marks has no percentage, and reporting 0% would put a
    student at the bottom of a distribution for a component nobody was
    graded on.
    """
    if scored is None or out_of is None:
        return None
    denominator = float(out_of)
    if denominator <= 0:
        return None
    return round(float(scored) / denominator * 100, 2)
