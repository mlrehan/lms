"""Guardian ↔ student link schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field

from backend.schemas.base import APIModel, RequestModel


class GuardianLinkResponse(APIModel):
    public_id: uuid.UUID
    guardian_id: uuid.UUID
    guardian_username: str
    guardian_name: str | None = None
    student_id: uuid.UUID
    student_username: str
    student_name: str | None = None
    relationship_type: str | None = None
    is_primary: bool = False
    created_at: datetime | None = None


class CreateGuardianLinkRequest(RequestModel):
    guardian_id: uuid.UUID = Field(description="A user holding the GUARDIAN role.")
    student_id: uuid.UUID = Field(description="A user holding the STUDENT role.")
    relationship_type: Annotated[str | None, Field(max_length=50)] = Field(
        default=None, description="e.g. 'Parent', 'Legal Guardian'."
    )
    is_primary: bool = Field(
        default=False,
        description="Marks the main point of contact when a student has several guardians.",
    )


class UpdateGuardianLinkRequest(RequestModel):
    relationship_type: Annotated[str | None, Field(max_length=50)] = None
    is_primary: bool | None = None
