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
from datetime import date, datetime
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
    course_image: str | None = Field(
        default=None, validation_alias="course_image_url",
        description="Full-size image: an external URL, or an API path for an uploaded one.",
    )
    small_course_image: str | None = Field(
        default=None, validation_alias="small_course_image_url",
        description="Thumbnail: an external URL, or an API path for an uploaded one.",
    )


class CourseBatchBrief(APIModel):
    public_id: uuid.UUID
    batch_code: str
    is_active: bool
    start_date: date | None = None
    end_date: date | None = None
    capacity: int | None = None
    total_enrollments: int = 0


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
    batches: list[CourseBatchBrief] = Field(default_factory=list)

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
    course_image: str | None = Field(default=None, max_length=500)
    small_course_image: str | None = Field(default=None, max_length=500)
    category_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None

    @field_validator("course_image", "small_course_image")
    @classmethod
    def _external_url_only(cls, value: str | None) -> str | None:
        return _http_url(value)


class CourseUpdateRequest(RequestModel):
    title: CourseTitle | None = None
    code: CourseCode | None = None
    description: str | None = None
    level: Levels | None = None
    duration_hours: int | None = Field(default=None, ge=0, le=100_000)
    prerequisites: str | None = None
    price: float | None = Field(default=None, ge=0)
    course_link: str | None = Field(default=None, max_length=255)
    course_image: str | None = Field(default=None, max_length=500)
    small_course_image: str | None = Field(default=None, max_length=500)
    category_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None

    @field_validator("course_image", "small_course_image")
    @classmethod
    def _external_url_only(cls, value: str | None) -> str | None:
        return _http_url(value)
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


def _http_url(value: str | None) -> str | None:
    """Image fields accept an external http(s) URL and nothing else.

    An *uploaded* image is stored as a storage key and is set only by the upload
    endpoint. If a request body could set a key directly, the image endpoint
    would serve whatever stored object it named -- another course's file, an
    avatar, a resource -- to anyone who can read the course.
    """
    if value is None or value == "":
        return None
    if not value.lower().startswith(("http://", "https://")):
        raise ValueError("Use an http(s) URL, or upload the image instead.")
    return value


class CodeSuggestion(APIModel):
    code: str


class LinkPreviewRequest(RequestModel):
    url: str = Field(max_length=500)


class LinkPreviewResponse(APIModel):
    """What the course page says, offered as suggestions -- nothing is saved."""

    price: float | None = None
    duration_hours: int | None = None
    level: Levels | None = None
    prerequisites: str | None = None
