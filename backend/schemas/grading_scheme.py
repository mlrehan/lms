"""Grading schemes: what counts, how much, and what to call the result (§6, §13)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import Field, model_validator

from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import (
    GradeComponentType,
    GradeScaleType,
    MissingMarkPolicy,
)


class ComponentWeightPayload(RequestModel):
    component_type: GradeComponentType
    label: Annotated[str | None, Field(max_length=80)] = None
    weight_percentage: Annotated[Decimal, Field(ge=0, le=Decimal("100"))]
    is_mandatory: bool = Field(
        default=False,
        description="A component that must be passed in its own right, whatever the total.",
    )
    passing_percentage: Annotated[Decimal | None, Field(ge=0, le=Decimal("100"))] = None


class BandPayload(RequestModel):
    min_score: Annotated[Decimal, Field(ge=0, le=Decimal("100"))]
    max_score: Annotated[Decimal, Field(ge=0, le=Decimal("100"))]
    letter_grade: Annotated[str, Field(min_length=1, max_length=5)]
    gpa_points: Annotated[Decimal, Field(ge=0, le=Decimal("9.99"))]
    is_pass: bool = True

    @model_validator(mode="after")
    def _ordered(self):  # type: ignore[no-untyped-def]
        if self.max_score < self.min_score:
            raise ValueError("A band's maximum cannot be below its minimum.")
        return self


class ComponentWeightResponse(APIModel):
    public_id: uuid.UUID
    component_type: GradeComponentType
    label: str | None = None
    weight_percentage: Decimal
    is_mandatory: bool = False
    passing_percentage: Decimal | None = None


class BandResponse(APIModel):
    min_score: Decimal
    max_score: Decimal
    letter_grade: str
    gpa_points: Decimal
    is_pass: bool = True


class GradingSchemeSummary(APIModel):
    public_id: uuid.UUID
    name: str
    description: str | None = None
    is_default: bool
    is_active: bool
    scale_type: GradeScaleType
    missing_mark_policy: MissingMarkPolicy
    passing_percentage: Decimal
    total_weight: Decimal = Field(
        description=(
            "The component weights added up. Shown because a scheme that does "
            "not total 100 cannot be activated, and an operator editing one "
            "needs to see how far off they are without doing the sum."
        )
    )
    component_count: int = 0


class GradingSchemeResponse(GradingSchemeSummary):
    components: list[ComponentWeightResponse] = []
    bands: list[BandResponse] = []
    courses_using: int = Field(
        default=0,
        description=(
            "How many courses this scheme grades. Shown before a change, "
            "because editing a weight re-grades every student in every one of "
            "them at once."
        ),
    )
    batches_using: int = Field(
        default=0,
        description="How many batches name this scheme as their own, overriding their course's.",
    )
    applied_to_courses: list["SchemeUsage"] = []
    applied_to_batches: list["SchemeUsage"] = []


class SchemeUsage(APIModel):
    public_id: uuid.UUID
    label: str
    course_title: str | None = None


class AssignSchemeRequest(RequestModel):
    scheme_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "An activated scheme's public_id, or null to stop overriding: a course "
            "then uses the institution default, a batch its course's scheme."
        ),
    )


class SchemeAssignment(APIModel):
    """What a course or batch is graded under, and why."""

    own_scheme_id: uuid.UUID | None = Field(
        default=None, description="The scheme this record names itself; null when it inherits."
    )
    own_scheme_name: str | None = None
    effective_scheme_id: uuid.UUID | None = None
    effective_scheme_name: str | None = None
    source: str = Field(
        description="BATCH, COURSE, DEFAULT or NONE -- where the effective scheme came from."
    )


class GradingSchemeCreateRequest(RequestModel):
    name: Annotated[str, Field(min_length=2, max_length=120)]
    description: str | None = None
    scale_type: GradeScaleType = GradeScaleType.PERCENTAGE
    missing_mark_policy: MissingMarkPolicy = Field(
        default=MissingMarkPolicy.EXCLUDE,
        description=(
            "EXCLUDE leaves unassessed work out of the total, which is the "
            "honest default. ZERO marks it as nothing -- a real policy some "
            "institutions hold, but never one to inherit by accident."
        ),
    )
    passing_percentage: Annotated[Decimal, Field(ge=0, le=Decimal("100"))] = Decimal("50")


class GradingSchemeUpdateRequest(RequestModel):
    name: Annotated[str | None, Field(min_length=2, max_length=120)] = None
    description: str | None = None
    scale_type: GradeScaleType | None = None
    missing_mark_policy: MissingMarkPolicy | None = None
    passing_percentage: Annotated[Decimal | None, Field(ge=0, le=Decimal("100"))] = None


class SetComponentsRequest(RequestModel):
    """Replace the whole set.

    Wholesale rather than one at a time because the set is what has to add up:
    five individual edits mean four intermediate states that do not total 100,
    and a concurrent reader would see one of them.
    """

    components: list[ComponentWeightPayload] = Field(max_length=20)


class SetBandsRequest(RequestModel):
    bands: list[BandPayload] = Field(max_length=30)


GradingSchemeResponse.model_rebuild()
