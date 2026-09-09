"""Academic administration schemas (spec §23).

Every response carries a `usage_count` — how many rows still point at this
piece of reference data. It is not decoration: deleting a department or a
category is refused while anything references it, and an administrator who
can only find that out by trying is being made to guess.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from pydantic import Field, model_validator

from backend.schemas.base import APIModel, RequestModel

Label = Annotated[str, Field(min_length=1, max_length=20)]
Name = Annotated[str, Field(min_length=1, max_length=150)]
SettingKey = Annotated[
    str,
    Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:[._][a-z0-9]+)*$",
        description="Lowercase dotted key, e.g. 'grading.pass_mark'.",
    ),
]


class _DateWindow(RequestModel):
    @model_validator(mode="after")
    def _end_after_start(self):  # type: ignore[no-untyped-def]
        start, end = getattr(self, "start_date", None), getattr(self, "end_date", None)
        if start and end and end <= start:
            raise ValueError("end_date must be after start_date")
        return self


# =============================================================================
# ACADEMIC YEAR
# =============================================================================


class AcademicYearResponse(APIModel):
    public_id: uuid.UUID
    label: str
    start_date: date
    end_date: date
    is_current: bool = False
    semester_count: int = 0
    batch_count: int = Field(
        default=0, description="Batches scheduled into this year; blocks deletion."
    )


class AcademicYearCreateRequest(_DateWindow):
    label: Label = Field(description="e.g. '2025-2026'.")
    start_date: date
    end_date: date
    is_current: bool = Field(
        default=False,
        description="Promoting a year to current demotes whichever held it.",
    )


class AcademicYearUpdateRequest(_DateWindow):
    label: Label | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None


# =============================================================================
# SEMESTER
# =============================================================================


class SemesterResponse(APIModel):
    public_id: uuid.UUID
    academic_year_id: uuid.UUID
    academic_year_label: str | None = None
    name: str
    start_date: date
    end_date: date
    batch_count: int = 0


class SemesterCreateRequest(_DateWindow):
    academic_year_id: uuid.UUID
    name: Annotated[str, Field(min_length=1, max_length=50)] = Field(
        description="e.g. 'Fall', 'Spring'. Unique within its academic year."
    )
    start_date: date
    end_date: date


class SemesterUpdateRequest(_DateWindow):
    name: Annotated[str | None, Field(min_length=1, max_length=50)] = None
    start_date: date | None = None
    end_date: date | None = None


# =============================================================================
# DEPARTMENT
# =============================================================================


class DepartmentResponse(APIModel):
    public_id: uuid.UUID
    name: str
    code: str | None = None
    head_tutor_id: uuid.UUID | None = None
    head_tutor_username: str | None = None
    course_count: int = 0


class DepartmentCreateRequest(RequestModel):
    name: Name
    code: Annotated[str | None, Field(min_length=1, max_length=20)] = None
    head_tutor_id: uuid.UUID | None = Field(
        default=None, description="Must be a user holding the TUTOR role."
    )


class DepartmentUpdateRequest(RequestModel):
    name: Name | None = None
    code: Annotated[str | None, Field(min_length=1, max_length=20)] = None
    head_tutor_id: uuid.UUID | None = None
    clear_head_tutor: bool = Field(
        default=False,
        description=(
            "Vacate the post. A separate flag because `head_tutor_id: null` is "
            "indistinguishable from 'not sent' once optional fields are omitted."
        ),
    )


# =============================================================================
# CATEGORY
# =============================================================================


class CategoryResponse(APIModel):
    public_id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None
    parent_name: str | None = None
    child_count: int = 0
    course_count: int = 0


class CategoryCreateRequest(RequestModel):
    name: Name
    parent_id: uuid.UUID | None = Field(
        default=None, description="Omit for a top-level category."
    )


class CategoryUpdateRequest(RequestModel):
    name: Name | None = None
    parent_id: uuid.UUID | None = None
    make_top_level: bool = Field(
        default=False, description="Detach from its parent. Overrides `parent_id`."
    )


# =============================================================================
# TAG
# =============================================================================


class TagResponse(APIModel):
    public_id: uuid.UUID
    name: str
    course_count: int = 0


class TagWriteRequest(RequestModel):
    name: Annotated[str, Field(min_length=1, max_length=50)]


class SetCourseTagsRequest(RequestModel):
    tag_ids: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=50,
        description="The complete set. Tags omitted here are removed.",
    )


# =============================================================================
# SYSTEM SETTING
# =============================================================================


class SettingResponse(APIModel):
    key: str
    value: str | None = None
    description: str | None = None


class SettingWriteRequest(RequestModel):
    value: Annotated[str | None, Field(max_length=10_000)] = None
    description: Annotated[str | None, Field(max_length=255)] = None
