"""Quiz schemas (spec §13).

**The single most important thing in this module is that `is_correct` never
reaches a student.** That is enforced by having two entirely separate option
schemas -- `OptionForStudent` has no `is_correct` field *at all*, so no
serialisation path, no `model_dump`, and no future edit to a shared class can
leak it. A single schema with the field conditionally excluded would be one
careless change away from handing out the answer key, which is why it isn't
done that way. The two shapes are served by two different routes under two
different permissions (see `api/v1/quizzes.py`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import Field, model_validator

from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import QuestionType

# Question types a machine can mark. SHORT_ANSWER and ESSAY are deliberately
# absent: grading free text is a human's job, and pretending otherwise would
# silently mark real answers wrong.
AUTO_GRADABLE = frozenset(
    {QuestionType.MCQ_SINGLE, QuestionType.MCQ_MULTIPLE, QuestionType.TRUE_FALSE}
)


class QuizSummary(APIModel):
    public_id: uuid.UUID
    title: str
    duration_minutes: int | None = None
    attempts_allowed: int
    passing_score: Decimal
    is_published: bool


class QuizResponse(QuizSummary):
    instructions: str | None = None
    shuffle_questions: bool
    is_auto_graded: bool
    grading_policy: Any | None = None
    course_id: uuid.UUID
    course_title: str | None = None
    question_count: int = 0
    total_points: Decimal = Decimal("0")
    my_attempts_used: int = Field(
        default=0, description="How many attempts the caller has already made."
    )


class QuizCreateRequest(RequestModel):
    title: Annotated[str, Field(min_length=3, max_length=255)]
    instructions: str | None = None
    duration_minutes: Annotated[int | None, Field(ge=1, le=24 * 60)] = None
    attempts_allowed: Annotated[int, Field(ge=1, le=100)] = 1
    passing_score: Annotated[Decimal, Field(ge=0, le=Decimal("999.99"))]
    shuffle_questions: bool = False
    is_auto_graded: bool = True
    grading_policy: Any | None = Field(
        default=None,
        description="e.g. {'negative_marking': 0.25} to deduct a quarter of a question's points per wrong answer.",
    )


class QuizUpdateRequest(RequestModel):
    title: Annotated[str | None, Field(min_length=3, max_length=255)] = None
    instructions: str | None = None
    duration_minutes: Annotated[int | None, Field(ge=1, le=24 * 60)] = None
    attempts_allowed: Annotated[int | None, Field(ge=1, le=100)] = None
    passing_score: Annotated[Decimal | None, Field(ge=0, le=Decimal("999.99"))] = None
    shuffle_questions: bool | None = None
    is_auto_graded: bool | None = None
    grading_policy: Any | None = None


class QuizPublishRequest(RequestModel):
    is_published: bool


# =============================================================================
# QUESTIONS -- two shapes, and the difference is a security boundary
# =============================================================================


class OptionForStudent(APIModel):
    """No `is_correct`. Not hidden, not excluded -- absent."""

    public_id: uuid.UUID | None = None
    id: int
    option_text: str
    order: int


class OptionForAuthor(OptionForStudent):
    is_correct: bool


class QuestionForStudent(APIModel):
    public_id: uuid.UUID
    question_text: str
    question_type: QuestionType
    points: Decimal
    order: int
    settings: Any | None = None
    options: list[OptionForStudent] = Field(default_factory=list)


class QuestionForAuthor(APIModel):
    public_id: uuid.UUID
    question_text: str
    question_type: QuestionType
    points: Decimal
    order: int
    settings: Any | None = None
    options: list[OptionForAuthor] = Field(default_factory=list)


class OptionInput(RequestModel):
    option_text: Annotated[str, Field(min_length=1)]
    is_correct: bool = False
    order: Annotated[int, Field(ge=0)] = 0


class QuestionCreateRequest(RequestModel):
    question_text: Annotated[str, Field(min_length=1)]
    question_type: QuestionType
    points: Annotated[Decimal, Field(gt=0, le=Decimal("999.99"))]
    order: Annotated[int, Field(ge=0)] = 0
    settings: Any | None = None
    options: list[OptionInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def _options_match_type(self):  # type: ignore[no-untyped-def]
        """A machine-marked question with no correct answer marked can never
        be answered correctly -- caught here rather than discovered by the
        first student to sit the quiz."""
        needs_options = self.question_type in AUTO_GRADABLE
        correct = [o for o in self.options if o.is_correct]

        if needs_options:
            if len(self.options) < 2:
                raise ValueError(
                    f"{self.question_type.value} requires at least two options"
                )
            if not correct:
                raise ValueError(
                    f"{self.question_type.value} requires at least one correct option"
                )
            if self.question_type in (QuestionType.MCQ_SINGLE, QuestionType.TRUE_FALSE) and len(correct) > 1:
                raise ValueError(
                    f"{self.question_type.value} allows exactly one correct option"
                )
        elif self.options:
            raise ValueError(
                f"{self.question_type.value} is graded manually and takes no options"
            )
        return self


class QuestionUpdateRequest(RequestModel):
    """Options are replaced wholesale when supplied, rather than patched
    individually: a partial option edit has no stable identity to key on
    once orders shift, and half-updated answer keys are worse than none."""

    question_text: Annotated[str | None, Field(min_length=1)] = None
    points: Annotated[Decimal | None, Field(gt=0, le=Decimal("999.99"))] = None
    order: Annotated[int | None, Field(ge=0)] = None
    settings: Any | None = None
    options: list[OptionInput] | None = None


# =============================================================================
# ATTEMPTS
# =============================================================================


class AnswerInput(RequestModel):
    question_id: uuid.UUID
    # Option ids for MCQ/true-false; free text for short answer/essay.
    selected_option_ids: list[int] | None = None
    text_answer: str | None = None


class SubmitAttemptRequest(RequestModel):
    answers: list[AnswerInput] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def _no_duplicate_questions(self):  # type: ignore[no-untyped-def]
        seen = {a.question_id for a in self.answers}
        if len(seen) != len(self.answers):
            raise ValueError("each question may be answered only once per submission")
        return self


class AnswerResponse(APIModel):
    question_id: uuid.UUID
    question_text: str | None = None
    selected_options: Any | None = None
    score_awarded: Decimal | None = None


class AttemptResponse(APIModel):
    public_id: uuid.UUID
    quiz_id: uuid.UUID
    quiz_title: str | None = None
    student_id: uuid.UUID
    student_username: str | None = None
    attempt_number: int
    started_at: datetime
    finished_at: datetime | None = None
    score: Decimal | None = None
    is_passed: bool | None = None
    submitted_late: bool = False
    feedback: str | None = None
    awaiting_manual_grading: bool = Field(
        default=False,
        description="True when the attempt contains short-answer/essay questions a tutor has not yet scored.",
    )
    answers: list[AnswerResponse] = Field(default_factory=list)


class GradeAnswerInput(RequestModel):
    question_id: uuid.UUID
    score_awarded: Annotated[Decimal, Field(ge=0, le=Decimal("999.99"))]


class GradeAttemptRequest(RequestModel):
    """Manual scoring for the questions auto-grading cannot mark."""

    answers: list[GradeAnswerInput] = Field(min_length=1, max_length=500)
    feedback: str | None = None
