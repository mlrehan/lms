"""Corporate manager ↔ student link schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field

from backend.schemas.base import APIModel, RequestModel


class ManagedStudentResponse(APIModel):
    public_id: uuid.UUID
    manager_id: uuid.UUID
    manager_username: str
    manager_name: str | None = None
    student_id: uuid.UUID
    student_username: str
    student_name: str | None = None
    relationship_type: str | None = None
    is_primary: bool = False
    created_at: datetime | None = None
    #: The company the student works for, if any. Shown because it is the
    #: thing somebody reading this list expects to see -- and it is now
    #: informational only: it no longer decides who may see whom, and a link
    #: can exist without it.
    organization: str | None = None


class CreateManagedStudentRequest(RequestModel):
    manager_id: uuid.UUID = Field(description="A user holding the CORPORATE_MANAGER role.")
    student_id: uuid.UUID = Field(description="A user holding the STUDENT role.")
    relationship_type: Annotated[str | None, Field(max_length=50)] = Field(
        default=None, description="e.g. 'Line manager', 'L&D sponsor'."
    )
    is_primary: bool = Field(
        default=False,
        description="Marks the first point of contact when a student has several managers.",
    )


class UpdateManagedStudentRequest(RequestModel):
    relationship_type: Annotated[str | None, Field(max_length=50)] = None
    is_primary: bool | None = None
