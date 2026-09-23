"""Class performance marks (spec §11).

People are names only (`core/privacy.py`): a tutor filling in a grid sees who is
in their class, not how to contact them.

**Every criterion is optional, and that is the point.** A tutor who assessed
participation should not have to invent a presentation mark to save the sheet --
a blank criterion is excluded from the average, the same rule the calculation
engine applies to an unassessed component (§38). `null` therefore means "not
assessed" and `0` means "assessed, scored zero", and the two must stay
distinguishable all the way from this schema to the transcript.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import Field

from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import ResultState

#: 0 is a legitimate mark, so the lower bound is inclusive. The upper bound is
#: *not* declared here: it is `max_score` on the row, which the tutor sets, and
#: a fixed ceiling of 10 in the schema would silently refuse an institution that
#: marks practical work out of 20. The service checks against the real ceiling.
Score = Annotated[Decimal | None, Field(default=None, ge=0)]


class MarkPerson(APIModel):
    public_id: uuid.UUID
    name: str


class CriterionScores(APIModel):
    """§11's eight named criteria."""

    participation: Decimal | None = None
    interaction: Decimal | None = None
    preparation: Decimal | None = None
    practical: Decimal | None = None
    presentation: Decimal | None = None
    teamwork: Decimal | None = None
    communication: Decimal | None = None
    professionalism: Decimal | None = None


class ClassPerformanceEntry(RequestModel):
    """One student's row on the grid."""

    student_id: uuid.UUID
    participation: Score
    interaction: Score
    preparation: Score
    practical: Score
    presentation: Score
    teamwork: Score
    communication: Score
    professionalism: Score
    overall_score: Score = Field(
        default=None,
        description=(
            "The tutor's own figure for the class. Null means 'average the "
            "criteria above', which is what most tutors want."
        ),
    )
    comment: str | None = Field(default=None, max_length=2000)
    custom_scores: dict[str, Decimal] | None = Field(
        default=None,
        description="Institution-specific criteria, as {name: score}.",
    )


class SaveClassPerformanceRequest(RequestModel):
    entries: list[ClassPerformanceEntry] = Field(min_length=1)
    max_score: Decimal | None = Field(
        default=None,
        gt=0,
        description=(
            "What each criterion is marked out of. Applies to every row in this "
            "request; omitted, existing rows keep their own and new ones get 10."
        ),
    )


class SetClassPerformanceStateRequest(RequestModel):
    state: ResultState
    student_id: uuid.UUID | None = Field(
        default=None,
        description="Release or withdraw one student's mark instead of the whole class.",
    )


class ClassPerformanceMarkResponse(CriterionScores):
    public_id: uuid.UUID
    student: MarkPerson
    max_score: Decimal
    overall_score: Decimal | None = Field(
        default=None, description="The tutor's own figure, if they gave one."
    )
    average: Decimal | None = Field(
        default=None,
        description=(
            "The score the calculation engine will actually use: the tutor's "
            "own figure, or the mean of the criteria they filled in. Null when "
            "nothing has been assessed -- which is excluded from the weighted "
            "result, never counted as zero."
        ),
    )
    comment: str | None = None
    custom_scores: dict[str, Any] | None = None
    state: ResultState
    recorded_by: MarkPerson | None = None
    recorded_at: datetime | None = None
    updated_at: datetime | None = None


class ClassPerformanceSheetRow(APIModel):
    student: MarkPerson
    mark: ClassPerformanceMarkResponse | None = Field(
        default=None, description="Null until somebody has assessed this student."
    )


class ClassPerformanceSheetSession(APIModel):
    public_id: uuid.UUID
    session_start_time: datetime | None = None
    session_end_time: datetime | None = None
    classroom: str | None = None
    batch_code: str | None = None
    course_title: str | None = None
    assigned_tutor: MarkPerson | None = None


class ClassPerformanceSheetResponse(APIModel):
    session: ClassPerformanceSheetSession
    rows: list[ClassPerformanceSheetRow]
    can_edit: bool = Field(
        description=(
            "Whether this caller may record marks here. False for a reader, and "
            "false for a tutor who is not the session's assigned tutor -- the "
            "backend refuses the write either way; this only stops the console "
            "offering a form that cannot be saved."
        )
    )
    would_be_on_behalf: bool = Field(
        default=False,
        description=(
            "True when the caller may record but is not the assigned tutor -- "
            "the academic office correcting a record. Recorded in the audit "
            "trail and worth saying out loud on the screen."
        ),
    )
    state: ResultState | None = Field(
        default=None,
        description=(
            "The common state of the marks recorded so far, or null when they "
            "disagree (or none exist). A sheet part-released is a real state and "
            "is reported honestly rather than rounded to one value."
        ),
    )
    marked: int = 0
    total: int = 0


class StudentClassPerformanceResponse(APIModel):
    """§37's drill-down: every class behind one student's `PRACTICAL` figure."""

    marks: list[ClassPerformanceMarkResponse]
    sessions: int = 0
    average: Decimal | None = Field(
        default=None,
        description=(
            "The mean of the sessions that carry a score, as a percentage of "
            "`max_score`. Sessions with nothing assessed are excluded, not "
            "counted as zero."
        ),
    )
