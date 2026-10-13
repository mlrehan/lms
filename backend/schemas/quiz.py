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
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Sequence

from pydantic import Field, model_validator

from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import AssessmentScope, QuestionType

# Types whose answer key is a set of options, one or more of them flagged
# correct.
CHOICE_TYPES = frozenset(
    {QuestionType.MCQ_SINGLE, QuestionType.MCQ_MULTIPLE, QuestionType.TRUE_FALSE}
)
# Types whose options are the *material* rather than the key: the key is the
# authored order (ORDERING) or the pairing (MATCHING), and `is_correct` means
# nothing for either.
SEQUENCE_TYPES = frozenset({QuestionType.ORDERING, QuestionType.MATCHING})
# Types with no options at all, whose key lives in `question.settings`.
KEYED_TYPES = frozenset({QuestionType.FILL_BLANK, QuestionType.NUMERIC})

# Question types a machine can mark. SHORT_ANSWER and ESSAY are deliberately
# absent: grading free text is a human's job, and pretending otherwise would
# silently mark real answers wrong.
AUTO_GRADABLE = CHOICE_TYPES | SEQUENCE_TYPES | KEYED_TYPES

# Types that take options. Distinct from AUTO_GRADABLE, which it is tempting
# to reuse: fill-in-the-blank and numeric are machine-marked and take none.
OPTION_TYPES = CHOICE_TYPES | SEQUENCE_TYPES


def _texts(options: "Sequence[Any]") -> list[str]:
    return [str(_field(o, "option_text") or "").strip() for o in options]


def _field(option: Any, name: str) -> Any:
    """Read a field from either an `OptionInput` or a plain dict.

    The same rules are checked in two places and the shapes differ: pydantic
    models when a request is parsed, dicts when the service re-checks an
    update. One reader rather than two copies of the rules.
    """
    if isinstance(option, dict):
        return option.get(name)
    return getattr(option, name, None)


def answer_key_problem(
    question_type: QuestionType,
    options: "Sequence[Any]",
    settings: Any | None = None,
) -> str | None:
    """Why this question could never be answered correctly, or `None`.

    One rule set, two callers: the request schemas raise it as a pydantic
    `ValueError`, and `QuizService` raises it as a `ValidationError` when a
    question is edited. Returned as a message rather than raised so neither
    caller has to catch the other's exception type.

    Every branch exists because the question would otherwise be unanswerable
    or unmarkable -- caught here rather than discovered by the first student
    to sit the quiz.
    """
    correct = [o for o in options if _field(o, "is_correct")]

    if question_type in CHOICE_TYPES:
        if len(options) < 2:
            return f"{question_type.value} requires at least two options"
        if not correct:
            return f"{question_type.value} requires at least one correct option"
        if question_type in (QuestionType.MCQ_SINGLE, QuestionType.TRUE_FALSE) and len(correct) > 1:
            return f"{question_type.value} allows exactly one correct option"
        return None

    if question_type is QuestionType.ORDERING:
        if len(options) < 2:
            return "ORDERING requires at least two items to put in order"
        orders = [_field(o, "order") for o in options]
        if len(set(orders)) != len(orders):
            # The authored `order` *is* the answer. Two items sharing a
            # position makes the correct sequence ambiguous, and the student
            # would be marked against whichever one the database returned
            # first.
            return "ORDERING requires a distinct position for every item"
        return None

    if question_type is QuestionType.MATCHING:
        if len(options) < 2:
            return "MATCHING requires at least two pairs"
        if any(not str(_field(o, "match_text") or "").strip() for o in options):
            return "MATCHING requires a match for every item"
        if len(set(_texts(options))) != len(options):
            # Two identical prompts cannot be told apart in the answer, which
            # is keyed by what the student was shown.
            return "MATCHING requires every item to be different"
        return None

    if question_type is QuestionType.FILL_BLANK:
        if options:
            return "FILL_BLANK takes accepted answers, not options"
        accepted = (settings or {}).get("accepted") if isinstance(settings, dict) else None
        if not isinstance(accepted, list) or not [a for a in accepted if str(a).strip()]:
            return (
                "FILL_BLANK requires settings.accepted -- a list of answers that count as correct"
            )
        return None

    if question_type is QuestionType.NUMERIC:
        if options:
            return "NUMERIC takes a numeric answer, not options"
        raw = (settings or {}) if isinstance(settings, dict) else {}
        if "answer" not in raw:
            return "NUMERIC requires settings.answer"
        try:
            Decimal(str(raw["answer"]))
        except (InvalidOperation, ValueError):
            return "NUMERIC requires settings.answer to be a number"
        if "tolerance" in raw and raw["tolerance"] is not None:
            try:
                if Decimal(str(raw["tolerance"])) < 0:
                    return "NUMERIC tolerance cannot be negative"
            except (InvalidOperation, ValueError):
                return "NUMERIC requires settings.tolerance to be a number"
        return None

    if options:
        return f"{question_type.value} is graded manually and takes no options"
    return None


class QuizSummary(APIModel):
    public_id: uuid.UUID
    title: str
    duration_minutes: int | None = None
    attempts_allowed: int
    passing_score: Decimal
    is_published: bool
    # On the summary as well as the detail: a tutor of two batches cannot use
    # a list that will not say which batch each quiz is for.
    scope: AssessmentScope = AssessmentScope.COURSE
    available_from: datetime | None = None
    available_until: datetime | None = None


class QuizResponse(QuizSummary):
    instructions: str | None = None
    # Nullable, and that *is* the answer for a candidate: these describe how
    # the paper is run, which is the author's business. `None` means withheld,
    # not "off" -- a client that renders a missing shuffle flag as "questions
    # are in order" would be stating something it was not told.
    shuffle_questions: bool | None = None
    is_auto_graded: bool | None = None
    grading_policy: Any | None = None
    course_id: uuid.UUID
    course_title: str | None = None
    question_count: int = 0
    total_points: Decimal = Decimal("0")
    total_marks: Decimal | None = Field(
        default=None,
        description=(
            "The paper's stated total, which question marks are checked "
            "against. Null means no stated ceiling -- which is what every "
            "quiz written before this field had, and what they keep."
        ),
    )
    #: What is still unallocated. Computed rather than left to the client,
    #: because the client would otherwise have to re-derive it from the
    #: question list it may not have loaded.
    marks_remaining: Decimal | None = Field(
        default=None,
        description="`total_marks` minus the questions written so far; null when there is no total.",
    )
    my_attempts_used: int = Field(
        default=0, description="How many attempts the caller has already made."
    )
    # Every one of these was stored and returned by nothing, so the console
    # could not show a tutor what they had set, let alone let them change it.
    shuffle_answers: bool | None = None
    questions_per_attempt: int | None = None
    show_result_immediately: bool | None = None
    show_correct_answers: bool | None = None
    show_explanations: bool | None = None
    auto_submit_on_expiry: bool | None = None
    results_released_at: datetime | None = None
    weight: Decimal | None = Decimal("1")


class QuizCreateRequest(RequestModel):
    title: Annotated[str, Field(min_length=3, max_length=255)]
    instructions: str | None = None
    duration_minutes: Annotated[int | None, Field(ge=1, le=24 * 60)] = None
    attempts_allowed: Annotated[int, Field(ge=1, le=100)] = 1
    passing_score: Annotated[Decimal, Field(ge=0, le=Decimal("999.99"))]
    total_marks: Annotated[Decimal | None, Field(gt=0, le=Decimal("9999.99"))] = Field(
        default=None,
        description="Optional. The paper's total; question marks are refused past it.",
    )
    shuffle_questions: bool = False
    is_auto_graded: bool = True
    grading_policy: Any | None = Field(
        default=None,
        description="e.g. {'negative_marking': 0.25} to deduct a quarter of a question's points per wrong answer.",
    )

    # -- academic scope (spec §3) -------------------------------------------
    # Identical to the assignment's, because it is the same concept resolved by
    # the same service. COURSE is the default, so an existing client that sends
    # none of these keeps the behaviour it has today.
    scope: AssessmentScope = AssessmentScope.COURSE
    batch_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None

    # -- availability and result visibility (spec §9) ------------------------
    available_from: datetime | None = None
    available_until: datetime | None = None
    shuffle_answers: bool = False
    questions_per_attempt: Annotated[int | None, Field(ge=1, le=500)] = Field(
        default=None,
        description="Draw this many at random from the bank. Null means every question.",
    )
    show_result_immediately: bool = True
    show_correct_answers: bool = False
    show_explanations: bool = False
    auto_submit_on_expiry: bool = True
    weight: Annotated[Decimal, Field(ge=0, le=Decimal("999.999"))] = Decimal("1")

    @model_validator(mode="after")
    def _window_is_coherent(self):  # type: ignore[no-untyped-def]
        if self.available_from and self.available_until and self.available_until <= self.available_from:
            raise ValueError("The quiz must close after it opens.")
        return self


class QuizUpdateRequest(RequestModel):
    title: Annotated[str | None, Field(min_length=3, max_length=255)] = None
    instructions: str | None = None
    duration_minutes: Annotated[int | None, Field(ge=1, le=24 * 60)] = None
    attempts_allowed: Annotated[int | None, Field(ge=1, le=100)] = None
    passing_score: Annotated[Decimal | None, Field(ge=0, le=Decimal("999.99"))] = None
    total_marks: Annotated[Decimal | None, Field(gt=0, le=Decimal("9999.99"))] = None
    shuffle_questions: bool | None = None
    is_auto_graded: bool | None = None
    grading_policy: Any | None = None
    # The settings a tutor could set once, at creation, and never afterwards.
    # Still refused once the quiz has attempts, like every other field here:
    # drawing a different number of questions, or withholding results, after
    # people have sat it changes what their marks mean.
    available_from: datetime | None = None
    available_until: datetime | None = None
    shuffle_answers: bool | None = None
    questions_per_attempt: Annotated[int | None, Field(ge=1, le=500)] = None
    show_result_immediately: bool | None = None
    show_correct_answers: bool | None = None
    show_explanations: bool | None = None
    auto_submit_on_expiry: bool | None = None
    weight: Annotated[Decimal | None, Field(ge=0, le=Decimal("999.999"))] = None


class QuizReleaseResultsRequest(RequestModel):
    """§14's separate, deliberate act -- for quizzes this time.

    Only meaningful to a quiz with `show_result_immediately` off; a quiz that
    shows results as it marks them is already released by definition, and the
    service says so rather than silently accepting.
    """

    is_released: bool = True


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
    #: MATCHING only, and it is *not* this option's own answer: the service
    #: sends the right-hand column shuffled, so the `match_text` arriving
    #: beside a prompt belongs to some other prompt. Serving them in their
    #: authored pairing would hand over the whole answer key.
    match_text: str | None = None


class OptionForAuthor(OptionForStudent):
    is_correct: bool


class QuestionForStudent(APIModel):
    public_id: uuid.UUID
    question_text: str
    question_type: QuestionType
    points: Decimal
    order: int
    settings: Any | None = None
    explanation: str | None = None
    options: list[OptionForStudent] = Field(default_factory=list)


class QuestionForAuthor(APIModel):
    public_id: uuid.UUID
    question_text: str
    question_type: QuestionType
    points: Decimal
    order: int
    settings: Any | None = None
    explanation: str | None = None
    options: list[OptionForAuthor] = Field(default_factory=list)


class OptionInput(RequestModel):
    option_text: Annotated[str, Field(min_length=1)]
    is_correct: bool = False
    order: Annotated[int, Field(ge=0)] = 0
    #: MATCHING: the right-hand item this prompt pairs with.
    match_text: Annotated[str | None, Field(max_length=500)] = None


class QuestionCreateRequest(RequestModel):
    question_text: Annotated[str, Field(min_length=1)]
    question_type: QuestionType
    points: Annotated[Decimal, Field(gt=0, le=Decimal("999.99"))]
    order: Annotated[int, Field(ge=0)] = 0
    settings: Any | None = None
    explanation: Annotated[str | None, Field(max_length=2000)] = None
    options: list[OptionInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def _options_match_type(self):  # type: ignore[no-untyped-def]
        problem = answer_key_problem(self.question_type, self.options, self.settings)
        if problem:
            raise ValueError(problem)
        return self


class QuestionUpdateRequest(RequestModel):
    """Options are replaced wholesale when supplied, rather than patched
    individually: a partial option edit has no stable identity to key on
    once orders shift, and half-updated answer keys are worse than none."""

    question_text: Annotated[str | None, Field(min_length=1)] = None
    points: Annotated[Decimal | None, Field(gt=0, le=Decimal("999.99"))] = None
    order: Annotated[int | None, Field(ge=0)] = None
    settings: Any | None = None
    explanation: Annotated[str | None, Field(max_length=2000)] = None
    options: list[OptionInput] | None = None


# =============================================================================
# ATTEMPTS
# =============================================================================


class AnswerInput(RequestModel):
    question_id: uuid.UUID
    # Option ids for MCQ/true-false; free text for short answer, essay,
    # fill-in-the-blank and numeric.
    #
    # ORDERING reuses `selected_option_ids` and **the order matters**: the
    # list is the sequence the student put the items in, which is why the
    # service stores it as given rather than sorted.
    selected_option_ids: list[int] | None = None
    text_answer: str | None = None
    #: MATCHING: option id (as a string, because JSON object keys are
    #: strings) to the right-hand text the student paired with it.
    matches: dict[str, str] | None = None


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
    question_type: QuestionType | None = None
    #: What the student actually answered, in words.
    #:
    #: `selected_options` is the stored payload -- `{"option_ids": [8055]}`
    #: for a choice, `{"text": "..."}` for an essay -- and a marker was being
    #: shown it verbatim: an internal row id tells a tutor nothing about which
    #: option the student picked, and an essay arrived wrapped in JSON. The
    #: option text lives on the server and never reached the client at all, so
    #: no amount of work in the console could have fixed it.
    answer_text: str | None = None
    #: True when a person still has to score this one. The marker's form shows
    #: a box only for these, rather than inviting a tutor to overwrite a mark
    #: auto-grading already made.
    needs_marking: bool = False
    selected_options: Any | None = None
    score_awarded: Decimal | None = None
    #: The answer key, and why -- present only once the quiz's results are
    #: visible to this reader *and* the quiz is set to show them. Absent, not
    #: null-filled, is the point: a student reading the response while
    #: results are withheld finds no field at all to inspect.
    correct_answer: str | None = None
    explanation: str | None = None
    points_possible: Decimal | None = None


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
    #: Closed by the clock rather than by the student. Different from
    #: `submitted_late`, which means the timer was advisory and they
    #: submitted by hand afterwards.
    auto_submitted: bool = False
    feedback: str | None = None
    awaiting_manual_grading: bool = Field(
        default=False,
        description="True when the attempt contains short-answer/essay questions a tutor has not yet scored.",
    )
    answers: list[AnswerResponse] = Field(default_factory=list)
    #: False when the quiz withholds results until they are released (§9's
    #: `show_result_immediately`). The score and pass flag are then omitted
    #: for the student and their care circle, and staff see them as always.
    results_visible: bool = True


class GradeAnswerInput(RequestModel):
    question_id: uuid.UUID
    score_awarded: Annotated[Decimal, Field(ge=0, le=Decimal("999.99"))]


class GradeAttemptRequest(RequestModel):
    """Manual scoring for the questions auto-grading cannot mark."""

    answers: list[GradeAnswerInput] = Field(min_length=1, max_length=500)
    feedback: str | None = None
