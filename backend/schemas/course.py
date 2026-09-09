"""Course schemas (spec §5).

`category_id`/`department_id` were held back from the request bodies until
the §23 administration endpoints existed to populate them -- an optional
foreign key a caller can never satisfy is a field that looks configurable
and is not, and this codebase has been bitten by decorative fields before.
They land here now that categories, departments and tags are real.

Both are set with an explicit `clear_*` flag rather than by sending null.
With optional fields omitted from a PATCH body, "set this to nothing" and
"do not touch this" are the same JSON, and only one of them is what the
caller meant.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field, field_validator

from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import CourseStatus, Levels

CourseTitle = Annotated[str, Field(min_length=3, max_length=255)]
CourseCode = Annotated[str, Field(min_length=2, max_length=30, pattern=r"^[A-Za-z0-9._-]+$")]


class CourseSummary(APIModel):
    public_id: uuid.UUID
    title: str
    code: str | None = None
    status: CourseStatus
    level: Levels
    duration_hours: int | None = None
    price: float | None = None
    course_picture: str | None = None


class CourseResponse(CourseSummary):
    description: str | None = None
    prerequisites: str | None = None
    course_link: str | None = None
    category_id: uuid.UUID | None = None
    category_name: str | None = None
    department_id: uuid.UUID | None = None
    department_name: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None = None
    tutors: list[str] = Field(
        default_factory=list, description="Usernames of tutors assigned to this course."
    )
    batch_count: int = 0

    @field_validator("tutors", mode="before")
    @classmethod
    def _tutor_names(cls, value: object) -> object:
        if isinstance(value, list):
            return [
                v if isinstance(v, str) else getattr(v, "username", str(v)) for v in value
            ]
        return value


class CourseCreateRequest(RequestModel):
    title: CourseTitle
    code: CourseCode | None = None
    description: str | None = None
    level: Levels = Levels.BEGINNER
    duration_hours: int | None = Field(default=None, ge=0, le=100_000)
    prerequisites: str | None = None
    price: float | None = Field(default=None, ge=0)
    course_link: str | None = Field(default=None, max_length=255)
    course_picture: str | None = Field(default=None, max_length=255)
    category_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None


class CourseUpdateRequest(RequestModel):
    title: CourseTitle | None = None
    code: CourseCode | None = None
    description: str | None = None
    level: Levels | None = None
    duration_hours: int | None = Field(default=None, ge=0, le=100_000)
    prerequisites: str | None = None
    price: float | None = Field(default=None, ge=0)
    course_link: str | None = Field(default=None, max_length=255)
    course_picture: str | None = Field(default=None, max_length=255)
    category_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    clear_category: bool = Field(default=False, description="Uncategorise this course.")
    clear_department: bool = Field(
        default=False, description="Detach this course from its department."
    )


class CourseStatusRequest(RequestModel):
    """Spec §5's lifecycle. Legal transitions are enforced server-side --
    see `services/course_service.py::_ALLOWED_TRANSITIONS`."""

    status: CourseStatus


class CourseTutorsRequest(RequestModel):
    tutors: list[uuid.UUID] = Field(
        description="The complete set of tutor public_ids for this course.",
    )
