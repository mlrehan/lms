"""Requests and responses for reusing an assessment, its recipients and its revisions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import AssessmentScope


class CopyTargetInput(RequestModel):
    scope: AssessmentScope
    course_id: uuid.UUID | None = Field(default=None, description="For COURSE or STUDENTS on another course.")
    batch_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    student_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)


class AssessmentCopyRequest(RequestModel):
    targets: list[CopyTargetInput] = Field(min_length=1, max_length=20)
    due_date: datetime | None = Field(default=None, description="Assignments: a new deadline for every copy.")
    scheduled_at: datetime | None = Field(default=None, description="Exams: a new sitting time for every copy.")
    publish: bool = Field(
        default=False,
        description="False saves drafts and tells nobody; true publishes each copy and notifies its students.",
    )


class AssessmentCopyRef(APIModel):
    public_id: uuid.UUID
    title: str
    scope: AssessmentScope
    published: bool


class AssessmentCopyResponse(APIModel):
    copies: list[AssessmentCopyRef]


class RecipientRef(APIModel):
    public_id: uuid.UUID
    name: str


class NameableStudent(APIModel):
    public_id: uuid.UUID
    name: str
    batch_codes: list[str]


class RecipientsResponse(APIModel):
    scope: AssessmentScope
    recipients: list[RecipientRef]


class RecipientsUpdateRequest(RequestModel):
    student_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class RevisionResponse(APIModel):
    revision_no: int
    changed_at: datetime
    changed_by: str | None = None
    material: bool
    notified: int
    changes: dict[str, Any]
