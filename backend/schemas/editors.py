"""Editor links and the mapping behind them."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from backend.schemas.base import APIModel, RequestModel

EditorKey = Literal["sql", "python"]


class EditorLinkResponse(APIModel):
    key: EditorKey
    label: str
    url: str


class CourseEditorRow(APIModel):
    """One course's effective answer, and where it came from."""

    public_id: uuid.UUID
    title: str
    category: str | None = None
    editors: list[EditorKey] = Field(default_factory=list)
    inherited: bool = Field(
        description=(
            "True when these came from the course's category. False means the "
            "course states its own answer -- including an explicit 'no editor', "
            "which is different from having nothing set."
        )
    )


class CategoryEditorRow(APIModel):
    public_id: uuid.UUID
    name: str
    editors: list[EditorKey] = Field(default_factory=list)


class EditorMapping(APIModel):
    categories: list[CategoryEditorRow] = Field(default_factory=list)
    courses: list[CourseEditorRow] = Field(default_factory=list)


class SetCourseEditorsRequest(RequestModel):
    editors: list[EditorKey] = Field(
        default_factory=list,
        description=(
            "The complete set, not an addition. An empty list on a course "
            "clears its override and returns it to inheriting its category."
        ),
    )
