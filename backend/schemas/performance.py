"""Student performance, and how it was arrived at (spec §15, §37, §38)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import Field

from backend.schemas.base import APIModel
from backend.utils.enums import GradeComponentType


class ComponentLine(APIModel):
    """One line of the drill-down: `82 x 15% = 12.30`."""

    component_type: GradeComponentType
    label: str
    weight_percentage: Decimal
    percentage: Decimal | None = Field(
        default=None, description="The student's mark in this component, out of 100."
    )
    contribution: Decimal | None = Field(
        default=None,
        description="percentage x weight / 100. Null when the component does not count.",
    )
    marks_total: int
    marks_scored: int
    counted: bool
    excluded_reason: str = Field(
        default="", description="Why it was left out, in words a tutor can act on."
    )
    is_mandatory: bool = False
    meets_component_pass: bool | None = None


class PerformanceResponse(APIModel):
    """A student's standing, with every figure it was built from."""

    student_id: uuid.UUID
    student_name: str | None = None
    batch_id: uuid.UUID
    batch_code: str | None = None
    scheme_name: str | None = None

    components: list[ComponentLine]

    assessed_weight: Decimal = Field(
        description="The share of the scheme's 100 that has been assessed (spec 38)."
    )
    total_weight: Decimal

    current_percentage: Decimal | None = Field(
        default=None,
        description="The mark out of what has been assessed. The figure to show mid-course.",
    )
    final_percentage: Decimal | None = Field(
        default=None,
        description=(
            "The mark out of the whole scheme. Null until every weighted component "
            "has been assessed -- spec 38's 'Not Yet Available'. A client must not "
            "substitute current_percentage here; they mean different things."
        ),
    )

    grade: str | None = None
    gpa: Decimal | None = None
    is_pass: bool | None = None
    unconfigured: bool = Field(
        default=False,
        description="True when no grading scheme is configured. Every figure above is null.",
    )
    failed_mandatory: list[GradeComponentType] = []

    sessions_total: int = 0
    sessions_attended: int = 0
    attendance_percentage: Decimal | None = None
