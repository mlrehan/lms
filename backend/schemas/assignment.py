"""Assignment and submission schemas (spec §12)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import Field, model_validator

from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import SubmissionType


class AssignmentSummary(APIModel):
    public_id: uuid.UUID
    title: str
    due_date: datetime
    max_score: Decimal
    submission_type: SubmissionType
    allow_late_submissions: bool


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


class AssignmentCreateRequest(RequestModel):
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


class AssignmentUpdateRequest(RequestModel):
    title: Annotated[str | None, Field(min_length=3, max_length=255)] = None
    description: str | None = None
    due_date: datetime | None = None
    max_score: Annotated[Decimal | None, Field(gt=0, le=Decimal("999.99"))] = None
    submission_type: SubmissionType | None = None
    instructions_path: Annotated[str | None, Field(max_length=500)] = None
    rubric: Any | None = None
    allow_late_submissions: bool | None = None


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
