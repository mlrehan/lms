"""Grade book, grade bands and transcripts (spec §15)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import Field, model_validator

from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import GradeComponentType


# =============================================================================
# GRADE BANDS
# =============================================================================


class GradeBandResponse(APIModel):
    id: int
    min_score: Decimal
    max_score: Decimal
    letter_grade: str
    gpa_points: Decimal


class _BandRange(RequestModel):
    @model_validator(mode="after")
    def _min_le_max(self):  # type: ignore[no-untyped-def]
        lo, hi = getattr(self, "min_score", None), getattr(self, "max_score", None)
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("min_score cannot exceed max_score")
        return self


class GradeBandCreateRequest(_BandRange):
    min_score: Annotated[Decimal, Field(ge=0, le=Decimal("100"))]
    max_score: Annotated[Decimal, Field(ge=0, le=Decimal("100"))]
    letter_grade: Annotated[str, Field(min_length=1, max_length=5)]
    gpa_points: Annotated[Decimal, Field(ge=0, le=Decimal("9.99"))]


class GradeBandUpdateRequest(_BandRange):
    min_score: Annotated[Decimal | None, Field(ge=0, le=Decimal("100"))] = None
    max_score: Annotated[Decimal | None, Field(ge=0, le=Decimal("100"))] = None
    letter_grade: Annotated[str | None, Field(min_length=1, max_length=5)] = None
    gpa_points: Annotated[Decimal | None, Field(ge=0, le=Decimal("9.99"))] = None


# =============================================================================
# GRADE BOOK ENTRIES
# =============================================================================


class GradeBookEntryResponse(APIModel):
    public_id: uuid.UUID
    student_id: uuid.UUID
    student_username: str | None = None
    batch_id: uuid.UUID
    batch_code: str | None = None
    component_type: GradeComponentType
    reference_id: int | None = None
    score: Decimal
    max_score: Decimal
    weight: Decimal
    percentage: Decimal | None = Field(
        default=None, description="score / max_score as a percentage; null when max_score is 0."
    )
    recorded_at: datetime


class GradeBookEntryCreateRequest(RequestModel):
    """A manually-recorded contribution -- PRACTICAL marks in particular have
    no source row for `sync` to derive them from."""

    student_id: uuid.UUID
    component_type: GradeComponentType
    score: Annotated[Decimal, Field(ge=0, le=Decimal("9999.99"))]
    max_score: Annotated[Decimal, Field(gt=0, le=Decimal("9999.99"))]
    weight: Annotated[Decimal, Field(gt=0, le=Decimal("9.999"))] = Decimal("1")

    @model_validator(mode="after")
    def _score_within_max(self):  # type: ignore[no-untyped-def]
        if self.score > self.max_score:
            raise ValueError("score cannot exceed max_score")
        return self


class GradeBookEntryUpdateRequest(RequestModel):
    score: Annotated[Decimal | None, Field(ge=0, le=Decimal("9999.99"))] = None
    max_score: Annotated[Decimal | None, Field(gt=0, le=Decimal("9999.99"))] = None
    weight: Annotated[Decimal | None, Field(gt=0, le=Decimal("9.999"))] = None


class ComponentBreakdown(APIModel):
    component_type: GradeComponentType
    entries: int
    earned: Decimal
    available: Decimal
    percentage: Decimal | None = None
    weight: Decimal


class GradeBookSummaryResponse(APIModel):
    """A student's standing in one batch, computed from their entries."""

    student_id: uuid.UUID
    student_username: str | None = None
    batch_id: uuid.UUID
    batch_code: str | None = None
    components: list[ComponentBreakdown] = Field(default_factory=list)
    weighted_percentage: Decimal | None = Field(
        default=None, description="Weighted average across components; null when nothing is recorded."
    )
    letter_grade: str | None = None
    gpa_points: Decimal | None = None


class SyncResultResponse(APIModel):
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    students_covered: int = 0
    skipped_ungraded: int = Field(
        default=0,
        description="Source rows deliberately not synced because they are not marked yet.",
    )


# =============================================================================
# TRANSCRIPTS
# =============================================================================


class TranscriptResponse(APIModel):
    public_id: uuid.UUID
    student_id: uuid.UUID
    student_username: str | None = None
    batch_id: uuid.UUID
    batch_code: str | None = None
    course_id: uuid.UUID
    course_title: str | None = None
    gpa: Decimal | None = None
    overall_grade: str | None = None
    generated_at: datetime
    is_final: bool

    # -- the official record (spec §5) --------------------------------------
    final_percentage: Decimal | None = Field(
        default=None,
        description=(
            "Null while the course is incomplete. A transcript never reports a "
            "mid-course standing as a final result (spec §38)."
        ),
    )
    total_marks_earned: Decimal | None = None
    total_marks_possible: Decimal | None = None
    is_pass: bool | None = None
    scheme_name: str | None = Field(
        default=None,
        description="The grading policy that produced these figures. Schemes change.",
    )
    sessions_total: int | None = None
    sessions_attended: int | None = None
    attendance_percentage: Decimal | None = None
    breakdown: list[dict] | None = Field(
        default=None,
        description="The per-component arithmetic as it stood at issue (spec §37).",
    )
    issued_at: datetime | None = None
    issued_by_username: str | None = Field(
        default=None, description="Who certified it (spec §5's verification)."
    )
    is_complete: bool = Field(
        default=False,
        description="True when every weighted component was assessed at issue.",
    )


class GenerateTranscriptsResponse(APIModel):
    generated: int = 0
    updated: int = 0
    skipped_final: int = Field(
        default=0, description="Transcripts left alone because they are already finalised."
    )
    skipped_no_grades: int = Field(
        default=0,
        description=(
            "Students with nothing to certify -- no grading scheme configured for "
            "the course, or no published marks in any weighted component."
        ),
    )


class FinaliseTranscriptRequest(RequestModel):
    is_final: bool
