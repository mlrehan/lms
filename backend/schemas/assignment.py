"""Assignment and submission schemas (spec §12)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import Field, model_validator

from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import (
    AssessmentScope,
    AssessmentState,
    SubmissionState,
    SubmissionType,
)


class AssignmentSummary(APIModel):
    public_id: uuid.UUID
    title: str
    due_date: datetime
    max_score: Decimal
    submission_type: SubmissionType
    allow_late_submissions: bool
    # On the summary, not just the detail: a list of assignments that cannot
    # say which batch each is for is a list a tutor of two batches cannot use.
    scope: AssessmentScope = AssessmentScope.COURSE
    state: AssessmentState = AssessmentState.PUBLISHED


class AssignmentResponse(AssignmentSummary):
    description: str | None = None
    instructions_path: str | None = None
    rubric: Any | None = None
    course_id: uuid.UUID
    course_title: str | None = None
    submission_count: int = 0
    my_submission_id: uuid.UUID | None = Field(
        default=None,
        description="Set when the caller has already submitted, so a client need not fetch the list to know.",
    )

    # -- scope (spec §3) ----------------------------------------------------
    batch_id: uuid.UUID | None = None
    batch_code: str | None = None
    session_id: uuid.UUID | None = None
    scope_description: str | None = Field(
        default=None, description='One line a tutor can read: "Batch LMS-A".'
    )
    eligible_count: int | None = Field(
        default=None, description="How many students this was set for."
    )

    # -- rules (spec §8) ----------------------------------------------------
    publish_at: datetime | None = None
    available_from: datetime | None = None
    passing_score: Decimal | None = None
    weight: Decimal = Decimal("1")
    allowed_file_types: str | None = None
    max_upload_mb: int | None = None
    allow_multiple_submissions: bool = False
    allow_resubmission: bool = False
    late_penalty_percent_per_day: Decimal | None = None


class _AssignmentRules(RequestModel):
    """Validation both create and update need, written once.

    The same two mistakes are worth refusing on either path, and a rule that
    exists only on create is a rule a PATCH can walk straight past.
    """

    @model_validator(mode="after")
    def _coherent(self):  # type: ignore[no-untyped-def]
        opens = getattr(self, "available_from", None)
        due = getattr(self, "due_date", None)
        if opens and due and due <= opens:
            raise ValueError("The deadline must be after the assignment opens.")

        passing = getattr(self, "passing_score", None)
        maximum = getattr(self, "max_score", None)
        if passing is not None and maximum is not None and passing > maximum:
            raise ValueError("The passing mark cannot exceed the maximum score.")
        return self


class AssignmentCreateRequest(_AssignmentRules):
    title: Annotated[str, Field(min_length=3, max_length=255)]
    description: str | None = None
    due_date: datetime
    max_score: Annotated[Decimal, Field(gt=0, le=Decimal("999.99"))]
    submission_type: SubmissionType = SubmissionType.FILE_UPLOAD
    instructions_path: Annotated[str | None, Field(max_length=500)] = None
    # Free-form by design: spec §12 calls for a "grading rubric" without
    # fixing its shape, and different courses grade on different criteria.
    rubric: Any | None = None
    allow_late_submissions: bool = False

    # -- academic scope (spec §3) -------------------------------------------
    # Defaults to COURSE, which is what every assignment created before this
    # existed already is -- so an old client that sends none of these three
    # keeps working unchanged.
    scope: AssessmentScope = AssessmentScope.COURSE
    batch_id: uuid.UUID | None = Field(
        default=None, description="Required when scope is BATCH."
    )
    session_id: uuid.UUID | None = Field(
        default=None, description="Required when scope is SESSION."
    )

    # -- publication (spec §8, §14) -----------------------------------------
    state: AssessmentState = Field(
        default=AssessmentState.PUBLISHED,
        description="DRAFT saves without notifying anybody; PUBLISHED sets it immediately.",
    )
    publish_at: datetime | None = None
    available_from: datetime | None = None

    # -- rules (spec §8) ----------------------------------------------------
    passing_score: Annotated[Decimal | None, Field(ge=0, le=Decimal("999.99"))] = None
    weight: Annotated[Decimal, Field(ge=0, le=Decimal("999.999"))] = Decimal("1")
    allowed_file_types: Annotated[str | None, Field(max_length=255)] = None
    max_upload_mb: Annotated[int | None, Field(ge=1, le=2048)] = None
    allow_multiple_submissions: bool = False
    allow_resubmission: bool = False
    late_penalty_percent_per_day: Annotated[
        Decimal | None, Field(ge=0, le=Decimal("100"))
    ] = None


class AssignmentUpdateRequest(_AssignmentRules):
    title: Annotated[str | None, Field(min_length=3, max_length=255)] = None
    description: str | None = None
    due_date: datetime | None = None
    max_score: Annotated[Decimal | None, Field(gt=0, le=Decimal("999.99"))] = None
    submission_type: SubmissionType | None = None
    instructions_path: Annotated[str | None, Field(max_length=500)] = None
    rubric: Any | None = None
    allow_late_submissions: bool | None = None

    state: AssessmentState | None = None
    publish_at: datetime | None = None
    available_from: datetime | None = None
    passing_score: Annotated[Decimal | None, Field(ge=0, le=Decimal("999.99"))] = None
    weight: Annotated[Decimal | None, Field(ge=0, le=Decimal("999.999"))] = None
    allowed_file_types: Annotated[str | None, Field(max_length=255)] = None
    max_upload_mb: Annotated[int | None, Field(ge=1, le=2048)] = None
    allow_multiple_submissions: bool | None = None
    allow_resubmission: bool | None = None
    late_penalty_percent_per_day: Annotated[Decimal | None, Field(ge=0, le=Decimal("100"))] = None


# =============================================================================
# SUBMISSIONS
# =============================================================================


class SubmissionResponse(APIModel):
    public_id: uuid.UUID
    assignment_id: uuid.UUID
    assignment_title: str | None = None
    student_id: uuid.UUID
    student_username: str | None = None
    submitted_at: datetime
    files: Any | None = None
    content: str | None = None
    grade: Decimal | None = None
    feedback: str | None = None
    graded_at: datetime | None = None
    graded_by_username: str | None = None
    is_late: bool = Field(
        default=False, description="Submitted after the assignment's due date."
    )

    # -- lifecycle (spec §7, §14, §38) --------------------------------------
    state: SubmissionState = SubmissionState.SUBMITTED
    attempt_number: int = 1
    # The mark before any late penalty, so the drill-down shows arithmetic
    # rather than a number nobody can account for.
    raw_grade: Decimal | None = None
    late_penalty_applied: Decimal | None = None
    published_at: datetime | None = None
    # Staff-facing. The router omits these for a student reading their own
    # submission: why a mark was changed is a conversation for the tutor to
    # have, not a field to discover.
    override_reason: str | None = None
    overridden_at: datetime | None = None


class SubmitAssignmentRequest(RequestModel):
    """Spec §12 lets a student "replace before deadline", so re-submitting
    updates the existing row rather than creating a second one (enforced by
    `uq_assignment_submissions_assignment_student`)."""

    content: str | None = None
    files: Any | None = Field(
        default=None,
        description="File metadata, e.g. [{'filename': 'project.zip', 'path': '...'}].",
    )

    @model_validator(mode="after")
    def _something_submitted(self):  # type: ignore[no-untyped-def]
        if not self.content and not self.files:
            # An empty submission is almost certainly a client bug, and
            # accepting it would mark the student as having submitted while
            # handing the tutor nothing to grade.
            raise ValueError("a submission must include content or files")
        return self


class GradeSubmissionRequest(RequestModel):
    grade: Annotated[Decimal, Field(ge=0, le=Decimal("999.99"))]
    feedback: str | None = None
    # Required when changing a mark that has already been given (§24). The
    # service enforces it rather than the schema, because whether it is
    # required depends on the row's current state, which a schema cannot see.
    override_reason: Annotated[str | None, Field(max_length=1000)] = None
    state: SubmissionState | None = Field(
        default=None,
        description="Defaults to GRADED. Marking and releasing are separate acts.",
    )


class PublishResultsRequest(RequestModel):
    """Release marks. Omitting `student_ids` releases every graded submission."""

    student_ids: list[uuid.UUID] | None = None


class ResubmissionRequest(RequestModel):
    reason: Annotated[str, Field(min_length=3, max_length=1000)]


class SubmissionStateRequest(RequestModel):
    """Record an absence or an exemption -- neither of which is a mark."""

    state: SubmissionState
    reason: Annotated[str | None, Field(max_length=1000)] = None
