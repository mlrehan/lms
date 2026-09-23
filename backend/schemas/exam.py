"""Examination schemas (spec §14)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import AssessmentScope, ExamType


class ExamSummary(APIModel):
    public_id: uuid.UUID
    title: str
    exam_type: ExamType
    scheduled_at: datetime
    duration_minutes: int | None = None
    total_marks: Decimal
    passing_marks: Decimal
    is_published: bool


class ExamResponse(ExamSummary):
    venue_or_link: str | None = None
    instructions: str | None = None
    course_id: uuid.UUID | None = None
    course_title: str | None = None
    batch_id: uuid.UUID | None = None
    batch_code: str | None = None
    invigilators: list[str] = Field(
        default_factory=list, description="Usernames of assigned invigilators."
    )
    result_count: int = 0
    published_result_count: int = 0


class _ExamMarks(RequestModel):
    @model_validator(mode="after")
    def _passing_within_total(self):  # type: ignore[no-untyped-def]
        total = getattr(self, "total_marks", None)
        passing = getattr(self, "passing_marks", None)
        if total is not None and passing is not None and passing > total:
            raise ValueError("passing_marks cannot exceed total_marks")
        return self


class ExamCreateRequest(_ExamMarks):
    title: Annotated[str, Field(min_length=3, max_length=255)]
    exam_type: ExamType
    scheduled_at: datetime
    total_marks: Annotated[Decimal, Field(gt=0, le=Decimal("9999.99"))]
    passing_marks: Annotated[Decimal, Field(ge=0, le=Decimal("9999.99"))]
    duration_minutes: Annotated[int | None, Field(ge=1, le=24 * 60)] = None
    venue_or_link: Annotated[str | None, Field(max_length=500)] = None
    instructions: str | None = None
    course_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None

    # -- academic scope (spec §3) -------------------------------------------
    # Explicit now, rather than inferred from which of course_id/batch_id was
    # set. COURSE with a batch named is a different intent from BATCH, and an
    # inference rule cannot tell them apart.
    scope: AssessmentScope = AssessmentScope.COURSE

    # §10: both examination styles feed the same grade book. This only decides
    # which workflow a screen offers -- answering in the LMS, or a tutor
    # entering marks after a physical sitting.
    is_online: bool = False
    weight: Annotated[Decimal, Field(ge=0, le=Decimal("999.999"))] = Decimal("1")

    @model_validator(mode="after")
    def _anchored(self):  # type: ignore[no-untyped-def]
        """Mirrors the `anchored_to_course_or_batch` CHECK constraint: an
        exam attached to neither is unreachable by every scoping query and
        therefore invisible to everyone but an unrestricted admin. Caught
        here so the caller gets a readable 422 rather than an IntegrityError."""
        if self.course_id is None and self.batch_id is None:
            raise ValueError("an exam must be attached to a course, a batch, or both")
        return self


class ExamUpdateRequest(_ExamMarks):
    title: Annotated[str | None, Field(min_length=3, max_length=255)] = None
    exam_type: ExamType | None = None
    scheduled_at: datetime | None = None
    total_marks: Annotated[Decimal | None, Field(gt=0, le=Decimal("9999.99"))] = None
    passing_marks: Annotated[Decimal | None, Field(ge=0, le=Decimal("9999.99"))] = None
    duration_minutes: Annotated[int | None, Field(ge=1, le=24 * 60)] = None
    venue_or_link: Annotated[str | None, Field(max_length=500)] = None
    instructions: str | None = None


class ExamPublishRequest(RequestModel):
    is_published: bool


class ExamInvigilatorsRequest(RequestModel):
    invigilators: list[uuid.UUID] = Field(
        description="The complete set of tutor public_ids invigilating this exam.",
    )


# =============================================================================
# RESULTS
# =============================================================================


class ExamResultResponse(APIModel):
    public_id: uuid.UUID
    exam_id: uuid.UUID
    exam_title: str | None = None
    student_id: uuid.UUID
    student_username: str | None = None
    marks_obtained: Decimal | None = None
    grade: str | None = None
    remarks: str | None = None
    is_published: bool
    total_marks: Decimal | None = None
    passing_marks: Decimal | None = None
    is_passed: bool | None = Field(
        default=None,
        description="Derived from marks_obtained vs the exam's passing_marks; null until marked.",
    )


class ExamResultEntry(RequestModel):
    student_id: uuid.UUID
    marks_obtained: Annotated[Decimal, Field(ge=0, le=Decimal("9999.99"))]
    grade: Annotated[str | None, Field(max_length=5)] = None
    remarks: str | None = None


class RecordExamResultsRequest(RequestModel):
    """Bulk, like attendance marking: an examiner enters a whole cohort's
    marks in one pass, and a per-student endpoint would mean one request per
    candidate with a half-entered mark sheet if any failed."""

    entries: list[ExamResultEntry] = Field(min_length=1, max_length=500)

    @field_validator("entries")
    @classmethod
    def _no_duplicate_students(cls, entries: list[ExamResultEntry]) -> list[ExamResultEntry]:
        seen = {e.student_id for e in entries}
        if len(seen) != len(entries):
            raise ValueError("each student may appear only once per request")
        return entries


class PublishResultsRequest(RequestModel):
    is_published: bool = Field(
        description="Publish or retract every recorded result for this exam.",
    )
