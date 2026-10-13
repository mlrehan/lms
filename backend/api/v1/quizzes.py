"""Quiz endpoints (spec §13).

**The answer key lives behind its own route and its own permission.**
`GET /quizzes/{id}/questions` serves `QuestionForStudent`, whose option
schema has no `is_correct` field at all; `GET /quizzes/{id}/answer-key`
serves `QuestionForAuthor`, which does, and is gated on `quiz.update`.

Two routes rather than one route with an `include_answers` flag, because a
flag makes leaking the answer key a one-character mistake in a query string,
and a permission check that lives *inside* a handler is easier to
accidentally bypass than one attached to the route itself.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Sequence

from fastapi import APIRouter, Depends, Query, Response, status

from backend.core.privacy import visible_username
from backend.api.deps import CurrentUser, require_permissions, resolve_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.quiz import QuestionOption, Question, Quiz, QuizAnswer, QuizAttempt
from backend.schemas.base import Page, PageParams
from backend.schemas.quiz import (
    AUTO_GRADABLE,
    AttemptResponse,
    QuizReleaseResultsRequest,
    AnswerResponse,
    GradeAttemptRequest,
    QuestionCreateRequest,
    QuestionForAuthor,
    QuestionForStudent,
    QuestionUpdateRequest,
    QuizCreateRequest,
    QuizPublishRequest,
    QuizResponse,
    QuizSummary,
    QuizUpdateRequest,
    SubmitAttemptRequest,
)
from backend.services.quiz_service import QuizService
from backend.utils.enums import QuestionType

router = APIRouter(tags=["Quizzes"])


def _student_question(q: Question, options: Sequence[QuestionOption]) -> QuestionForStudent:
    """`options` is passed in because the service decides their order.

    When a quiz shuffles answers that order is per attempt. The `order` sent
    to a student is their position in *this* list rather than the authored
    one, so re-sorting by it is harmless and the authored sequence -- which
    is the answer to an ORDERING question -- never leaves the server.
    """
    matches = _matching_column(q, options)
    return QuestionForStudent(
        public_id=q.public_id,
        question_text=q.question_text,
        question_type=q.question_type,
        points=q.points,
        order=q.order,
        settings=_student_settings(q),
        # Never the explanation: it says why the answer is the answer, and the
        # student is about to be asked for it. It reaches them through their
        # own attempt, once results are released.
        options=[
            {
                "id": o.id,
                "option_text": o.option_text,
                # The position **as served**, not the authored one.
                #
                # `question_options.order` is the answer to an ORDERING
                # question -- sending it alongside a scrambled list would
                # hand the student the sequence they are being asked to
                # reconstruct. It is also what a client would naively sort
                # by, which would undo a shuffle the server just applied.
                # Neither is a risk worth keeping a field for that the person
                # answering has no use for.
                "order": i,
                "match_text": matches[i] if matches else None,
            }
            for i, o in enumerate(options)
        ],
    )


def _student_settings(q: Question) -> object | None:
    """`settings` with the answer key taken out.

    The column is a general-purpose bag -- it carries a code question's
    language and test cases, and it now also carries the *answer* for
    fill-in-the-blank and numeric questions. Serving it whole to the person
    sitting the quiz would hand them the key, which is exactly the leak the
    two separate option schemas in `schemas/quiz.py` exist to prevent. So the
    student's copy is built by removing the keyed fields rather than by
    trusting every future writer of this column to remember.
    """
    if not isinstance(q.settings, dict):
        return q.settings
    withheld = {"accepted", "answer", "case_sensitive", "tolerance"}
    return {k: v for k, v in q.settings.items() if k not in withheld} or None


def _matching_column(q: Question, options: Sequence[QuestionOption]) -> list[str] | None:
    """The right-hand column of a matching question, for the student.

    Returned as a separate, independently ordered list rather than each
    option's own `match_text`: serving a prompt beside the item it pairs with
    *is* serving the answer. The order is derived from the already-shuffled
    option order the service chose for this attempt, so it is stable for one
    sitting and different for the next student.
    """
    if q.question_type is not QuestionType.MATCHING:
        return None
    # Sorted by their own text, so the column's order carries no information
    # about the pairing. Authored order would: the student is told each
    # option's position, so a right-hand column in authored order could be
    # zipped straight back onto the left-hand one.
    #
    # Content-sorted rather than seeded-shuffled because this mapper has no
    # attempt to seed from, and a stable order is required -- a column that
    # reshuffled on every reload would move the answers under a half-finished
    # question.
    return sorted({o.match_text or "" for o in options})


def _author_question(q: Question) -> QuestionForAuthor:
    return QuestionForAuthor(
        public_id=q.public_id,
        question_text=q.question_text,
        question_type=q.question_type,
        points=q.points,
        order=q.order,
        settings=q.settings,
        explanation=q.explanation,
        options=[
            {
                "id": o.id,
                "option_text": o.option_text,
                "order": o.order,
                "is_correct": o.is_correct,
                "match_text": o.match_text,
            }
            for o in sorted(q.options, key=lambda o: (o.order, o.id))
        ],
    )


def _answer_text(answer: QuizAnswer) -> str | None:
    """What the student answered, rendered for a person to read.

    The stored shape is `{"option_ids": [...]}` or `{"text": "..."}`. Only the
    server can turn the first into anything meaningful -- the option rows are
    here and never travel -- which is why this is a mapper and not a job for
    the console.

    An unanswered question returns `None` rather than an empty string: "left
    blank" is a fact a marker needs, and an empty box looks like a rendering
    failure.
    """
    stored = answer.selected_options or {}
    if not isinstance(stored, dict):  # pragma: no cover - defensive
        return str(stored)

    text = stored.get("text")
    if text:
        return str(text)

    by_id = {o.id: o for o in answer.question.options}

    # ORDERING: the sequence the student chose, in their order. Sorting it
    # would render every answer identically and hide the one thing being
    # marked.
    sequence = stored.get("ordered_option_ids")
    if sequence:
        return " → ".join(
            by_id[i].option_text for i in sequence if i in by_id
        ) or None

    # MATCHING: each prompt with what they paired it with.
    pairs = stored.get("matches")
    if pairs:
        rendered = [
            f"{by_id[int(k)].option_text} = {v}"
            for k, v in pairs.items()
            if str(k).isdigit() and int(k) in by_id
        ]
        return "; ".join(rendered) or None

    ids = set(stored.get("option_ids") or [])
    if not ids:
        return None
    chosen = [o.option_text for o in answer.question.options if o.id in ids]
    return ", ".join(chosen) if chosen else None


def _correct_answer(q: Question) -> str | None:
    """The answer key, in words, for a student reviewing a released result.

    One renderer per question type because the key is a different shape for
    each: flagged options, an authored sequence, stored pairs, or a value in
    `settings`. A generic "whatever is in the row" renderer is what produced
    `{"option_ids": [8055]}` on a marker's screen.
    """
    options = sorted(q.options, key=lambda o: (o.order, o.id))

    if q.question_type is QuestionType.ORDERING:
        return " → ".join(o.option_text for o in options) or None
    if q.question_type is QuestionType.MATCHING:
        return "; ".join(f"{o.option_text} = {o.match_text or ''}" for o in options) or None
    if q.question_type is QuestionType.FILL_BLANK:
        raw = q.settings if isinstance(q.settings, dict) else {}
        accepted = [str(a) for a in (raw.get("accepted") or [])]
        return " / ".join(accepted) or None
    if q.question_type is QuestionType.NUMERIC:
        raw = q.settings if isinstance(q.settings, dict) else {}
        if raw.get("answer") is None:
            return None
        tolerance = raw.get("tolerance")
        answer = str(raw["answer"])
        return f"{answer} ± {tolerance}" if tolerance else answer

    correct = [o.option_text for o in options if o.is_correct]
    return ", ".join(correct) or None


def _attempt_response(a: QuizAttempt, *, results_visible: bool = True) -> AttemptResponse:
    """One attempt, as much of it as this reader may see.

    `results_visible` is resolved by the service, not here: it depends on the
    quiz's `show_result_immediately`, whether its results have been released,
    and whether the reader is staff -- and a default of `True` keeps every
    existing caller behaving as it did. Withholding means the score, the pass
    flag, every per-answer mark **and** the answer key are left out: a score
    hidden while the marks are still listed beside each question is not
    hidden at all.
    """
    awaiting = any(ans.score_awarded is None for ans in a.answers)
    quiz = a.quiz
    return AttemptResponse(
        public_id=a.public_id,
        quiz_id=quiz.public_id,
        quiz_title=quiz.title,
        student_id=a.student.public_id,
        student_username=visible_username(a.student),
        attempt_number=a.attempt_number,
        started_at=a.started_at,
        finished_at=a.finished_at,
        score=a.score if results_visible else None,
        is_passed=a.is_passed if results_visible else None,
        submitted_late=a.submitted_late,
        auto_submitted=a.auto_submitted,
        feedback=a.feedback if results_visible else None,
        awaiting_manual_grading=awaiting,
        results_visible=results_visible,
        answers=[
            AnswerResponse(
                question_id=ans.question.public_id,
                question_text=ans.question.question_text,
                question_type=ans.question.question_type,
                answer_text=_answer_text(ans),
                needs_marking=ans.score_awarded is None,
                selected_options=ans.selected_options,
                score_awarded=ans.score_awarded if results_visible else None,
                # Unconditional, unlike the score beside it. What a question
                # is worth is printed on the paper -- `QuestionForStudent`
                # carries `points` while the quiz is being sat -- so it is
                # not a result to withhold. Gating it meant a tutor marking a
                # quiz that holds its marks back could not see the maximum
                # they were marking against, and learned the cap only from
                # the server's refusal.
                points_possible=ans.question.points,
                # Both gated on the quiz's own switches as well as on the
                # result being visible: a tutor may release a mark and still
                # not hand out the paper, which is what reusing the quiz next
                # term depends on.
                correct_answer=(
                    _correct_answer(ans.question)
                    if results_visible and quiz.show_correct_answers
                    else None
                ),
                explanation=(
                    ans.question.explanation
                    if results_visible and quiz.show_explanations
                    else None
                ),
            )
            for ans in a.answers
        ],
    )


# =============================================================================
# QUIZZES
# =============================================================================


@router.get("/quizzes", response_model=Page[QuizSummary], summary="List quizzes")
async def list_quizzes(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.QUIZ, Action.READ)))],
    course_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[QuizSummary]:
    """Course-scoped. Unpublished quizzes are visible only to callers who can
    author them — a student has no business seeing a draft."""
    rows, total = await QuizService(session).list_quizzes(
        params, actor=actor, course_public_id=course_id
    )
    return Page.build([QuizSummary.model_validate(q) for q in rows], total=total, params=params)


@router.post(
    "/courses/{course_id}/quizzes",
    response_model=QuizResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a quiz",
)
async def create_quiz(
    course_id: uuid.UUID,
    payload: QuizCreateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.QUIZ, Action.CREATE)))],
) -> QuizResponse:
    """Always created unpublished — a live quiz with no questions yet is not
    a useful thing to expose."""
    service = QuizService(session)
    return await _quiz_response(service, await service.create(course_id, payload, actor=actor), actor)


async def _quiz_response(service: QuizService, quiz: Quiz, actor) -> QuizResponse:  # type: ignore[no-untyped-def]
    count, total_points = await service.quizzes.question_stats(quiz.id)
    used = await service.attempts.count_for_student(quiz_id=quiz.id, student_id=actor.id)

    # -- what a candidate is told, and what they are not --------------------
    #
    # The fields below describe how the paper is *run*: whether the questions
    # are shuffled, how many are drawn from the bank, whether the answers come
    # back afterwards. They are the author's working notes, and a candidate
    # knowing them is at an advantage -- "answers are shown immediately" and
    # "ten drawn from forty" both change how a quiz is best attempted.
    #
    # Withheld on the server, not merely hidden behind a tab: a tab the client
    # declines to draw is still a payload anybody can read, and that is what
    # this was. What a candidate legitimately needs -- the title, how long
    # they have, how many attempts, the pass mark, the total, when it opens --
    # is not here and is unchanged.
    staff = perm(Module.QUIZ, Action.UPDATE) in resolve_permissions(actor)
    configuration: dict[str, object | None] = (
        {
            "shuffle_questions": quiz.shuffle_questions,
            "shuffle_answers": quiz.shuffle_answers,
            "questions_per_attempt": quiz.questions_per_attempt,
            "show_result_immediately": quiz.show_result_immediately,
            "show_correct_answers": quiz.show_correct_answers,
            "show_explanations": quiz.show_explanations,
            "auto_submit_on_expiry": quiz.auto_submit_on_expiry,
            "is_auto_graded": quiz.is_auto_graded,
            "grading_policy": quiz.grading_policy,
            "weight": quiz.weight,
        }
        if staff
        else dict.fromkeys(
            (
                "shuffle_questions",
                "shuffle_answers",
                "questions_per_attempt",
                "show_result_immediately",
                "show_correct_answers",
                "show_explanations",
                "auto_submit_on_expiry",
                "is_auto_graded",
                "grading_policy",
                "weight",
            )
        )
    )
    return QuizResponse(
        public_id=quiz.public_id,
        title=quiz.title,
        duration_minutes=quiz.duration_minutes,
        attempts_allowed=quiz.attempts_allowed,
        passing_score=quiz.passing_score,
        is_published=quiz.is_published,
        instructions=quiz.instructions,
        shuffle_questions=configuration["shuffle_questions"],  # type: ignore[arg-type]
        is_auto_graded=configuration["is_auto_graded"],  # type: ignore[arg-type]
        grading_policy=configuration["grading_policy"],  # type: ignore[arg-type]
        course_id=quiz.course.public_id,
        course_title=quiz.course.title,
        question_count=count,
        total_points=total_points,
        total_marks=quiz.total_marks,
        # Computed here rather than left to the client: the question list is
        # a separate request the quiz list screen never makes, so a client
        # deriving this would either be wrong or have to fetch the paper.
        marks_remaining=(
            None if quiz.total_marks is None else Decimal(str(quiz.total_marks)) - total_points
        ),
        my_attempts_used=used,
        scope=quiz.scope,
        available_from=quiz.available_from,
        available_until=quiz.available_until,
        shuffle_answers=configuration["shuffle_answers"],  # type: ignore[arg-type]
        questions_per_attempt=configuration["questions_per_attempt"],  # type: ignore[arg-type]
        show_result_immediately=configuration["show_result_immediately"],  # type: ignore[arg-type]
        show_correct_answers=configuration["show_correct_answers"],  # type: ignore[arg-type]
        show_explanations=configuration["show_explanations"],  # type: ignore[arg-type]
        auto_submit_on_expiry=configuration["auto_submit_on_expiry"],  # type: ignore[arg-type]
        results_released_at=quiz.results_released_at,
        weight=configuration["weight"],  # type: ignore[arg-type]
    )


@router.get("/quizzes/{quiz_id}", response_model=QuizResponse, summary="Get one quiz")
async def get_quiz(
    quiz_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.QUIZ, Action.READ)))],
) -> QuizResponse:
    service = QuizService(session)
    return await _quiz_response(service, await service.get(quiz_id, actor=actor), actor)


@router.patch("/quizzes/{quiz_id}", response_model=QuizResponse, summary="Update a quiz")
async def update_quiz(
    quiz_id: uuid.UUID,
    payload: QuizUpdateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.QUIZ, Action.UPDATE)))],
) -> QuizResponse:
    """Refused once anyone has attempted the quiz — changing the pass mark or
    grading policy afterwards rewrites what existing results mean."""
    service = QuizService(session)
    return await _quiz_response(service, await service.update(quiz_id, payload, actor=actor), actor)


@router.put(
    "/quizzes/{quiz_id}/publish", response_model=QuizResponse, summary="Publish or unpublish"
)
async def publish_quiz(
    quiz_id: uuid.UUID,
    payload: QuizPublishRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.QUIZ, Action.UPDATE)))],
) -> QuizResponse:
    """A quiz with no questions cannot be published."""
    service = QuizService(session)
    quiz = await service.set_published(quiz_id, payload.is_published, actor=actor)
    return await _quiz_response(service, quiz, actor)


@router.delete(
    "/quizzes/{quiz_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a quiz"
)
async def delete_quiz(
    quiz_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.QUIZ, Action.DELETE)))],
) -> Response:
    await QuizService(session).delete(quiz_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# QUESTIONS -- student view and answer key are separate routes
# =============================================================================


@router.get(
    "/quizzes/{quiz_id}/questions",
    response_model=list[QuestionForStudent],
    summary="Get the questions (no answer key)",
)
async def list_questions(
    quiz_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.QUIZ, Action.READ)))],
) -> list[QuestionForStudent]:
    """The response schema has no `is_correct` field, so the answer key
    cannot be serialised through this route at all.

    While the caller has an attempt in progress, this is **the paper that
    sitting was served**: the sample `questions_per_attempt` draws, in the
    order the quiz's shuffle settings give it, and stable for that attempt --
    reloading returns the same paper, because a redraw or a reshuffle would
    remap answers already chosen. Before an attempt starts it is the whole
    bank in authored order, which is the honest answer for an author
    previewing.

    Three things are withheld even though the schema could carry them: a
    question's `explanation`, the answer key inside `settings`, and the
    authored position of each option -- which is itself the answer to an
    ordering question.
    """
    rows = await QuizService(session).questions_for_attempt(quiz_id, actor=actor)
    return [_student_question(q, options) for q, options in rows]


@router.get(
    "/quizzes/{quiz_id}/answer-key",
    response_model=list[QuestionForAuthor],
    summary="Get the questions with correct answers",
)
async def get_answer_key(
    quiz_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.QUIZ, Action.UPDATE)))],
) -> list[QuestionForAuthor]:
    """Gated on `quiz.update` (authoring), which students do not hold."""
    rows = await QuizService(session).list_questions(quiz_id, actor=actor)
    return [_author_question(q) for q in rows]


@router.post(
    "/quizzes/{quiz_id}/questions",
    response_model=QuestionForAuthor,
    status_code=status.HTTP_201_CREATED,
    summary="Add a question",
)
async def add_question(
    quiz_id: uuid.UUID,
    payload: QuestionCreateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.QUIZ, Action.UPDATE)))],
) -> QuestionForAuthor:
    """A machine-marked question needs at least two options and at least one
    marked correct — checked here rather than discovered by the first student
    to sit the quiz. Short-answer and essay questions take no options."""
    return _author_question(
        await QuizService(session).add_question(quiz_id, payload, actor=actor)
    )


@router.patch(
    "/questions/{question_id}",
    response_model=QuestionForAuthor,
    summary="Update a question",
)
async def update_question(
    question_id: uuid.UUID,
    payload: QuestionUpdateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.QUIZ, Action.UPDATE)))],
) -> QuestionForAuthor:
    """Supplying `options` replaces them wholesale. Refused once the quiz has
    attempts — editing the answer key afterwards retroactively changes
    whether students' answers were right."""
    return _author_question(
        await QuizService(session).update_question(question_id, payload, actor=actor)
    )


@router.delete(
    "/questions/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a question",
)
async def delete_question(
    question_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.QUIZ, Action.UPDATE)))],
) -> Response:
    await QuizService(session).delete_question(question_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# ATTEMPTS
# =============================================================================


@router.post(
    "/quizzes/{quiz_id}/attempts",
    response_model=AttemptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start an attempt",
)
async def start_attempt(
    quiz_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.QUIZ, Action.ATTEMPT)))],
) -> AttemptResponse:
    """Requires the quiz to be published and the caller enrolled in its
    course. Refused if an attempt is already in progress — otherwise the
    attempt limit is bypassed by opening several and submitting the best."""
    return _attempt_response(await QuizService(session).start_attempt(quiz_id, actor=actor))


@router.post(
    "/attempts/{attempt_id}/submit",
    response_model=AttemptResponse,
    summary="Submit an attempt for grading",
)
async def submit_attempt(
    attempt_id: uuid.UUID,
    payload: SubmitAttemptRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.QUIZ, Action.ATTEMPT)))],
) -> AttemptResponse:
    """Auto-grades MCQ and true/false immediately. Short-answer and essay
    questions are left unscored (`null`, not `0`) for a tutor to mark, and
    `score` stays null until they have — reporting a total that ignores an
    ungraded essay would understate the student.

    A submission arriving after the time limit is still graded rather than
    discarded (a network blip must not destroy someone's work) but is stamped
    `submitted_late` so the tutor can see it.
    """
    service = QuizService(session)
    attempt = await service.submit_attempt(attempt_id, payload.answers, actor=actor)
    return _attempt_response(
        attempt, results_visible=await service.results_visible_to(attempt, actor=actor)
    )


@router.get("/attempts", response_model=Page[AttemptResponse], summary="List quiz attempts")
async def list_attempts(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.GRADE, Action.READ)))],
    quiz_id: Annotated[uuid.UUID | None, Query()] = None,
    student_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[AttemptResponse]:
    """Gated on `grade.read` rather than `quiz.read`: an attempt is a result,
    and a Guardian holds the former but not the latter."""
    service = QuizService(session)
    rows, total = await service.list_attempts(
        params, actor=actor, quiz_public_id=quiz_id, student_public_id=student_id
    )
    # Resolved per row: one page can span quizzes with different settings,
    # and deciding once for the page would withhold every mark on it as soon
    # as one quiz withheld its own.
    items = [
        _attempt_response(a, results_visible=await service.results_visible_to(a, actor=actor))
        for a in rows
    ]
    return Page.build(items, total=total, params=params)


@router.get(
    "/attempts/{attempt_id}", response_model=AttemptResponse, summary="Get one attempt"
)
async def get_attempt(
    attempt_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.GRADE, Action.READ)))],
) -> AttemptResponse:
    service = QuizService(session)
    attempt = await service.get_attempt(attempt_id, actor=actor)
    return _attempt_response(
        attempt, results_visible=await service.results_visible_to(attempt, actor=actor)
    )


@router.put(
    "/quizzes/{quiz_id}/results",
    response_model=QuizResponse,
    summary="Release or withhold quiz results",
)
async def release_quiz_results(
    quiz_id: uuid.UUID,
    payload: QuizReleaseResultsRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.QUIZ, Action.GRADE)))],
) -> QuizResponse:
    """The separate, deliberate act §14 asks for — for quizzes.

    Only meaningful on a quiz with `show_result_immediately` off; one that
    shows marks as it makes them is already released, and this refuses rather
    than pretending to do something.

    Releasing notifies the students who have a marked attempt, and their
    guardians. Withholding is deliberately quiet.
    """
    service = QuizService(session)
    quiz = await service.release_results(quiz_id, payload.is_released, actor=actor)
    return await _quiz_response(service, quiz, actor)


@router.post(
    "/quizzes/{quiz_id}/close-expired-attempts",
    summary="Close attempts whose time has run out",
)
async def close_expired_attempts(
    quiz_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.QUIZ, Action.GRADE)))],
) -> dict[str, int]:
    """Finalise attempts the clock ended but nobody submitted.

    An attempt is normally closed by its owner's next attempt at the quiz;
    a student who has used every attempt never triggers that, so without this
    their abandoned sitting stays "in progress" and the tutor is left waiting
    for a result that cannot arrive. There is no scheduler here, so it is a
    button.

    Only applies to quizzes with `auto_submit_on_expiry` set — where the
    timer is advisory, an unsubmitted attempt is still the student's to
    submit.
    """
    return {"closed": await QuizService(session).close_expired_attempts(quiz_id, actor=actor)}


@router.put(
    "/attempts/{attempt_id}/grade",
    response_model=AttemptResponse,
    summary="Manually grade an attempt",
)
async def grade_attempt(
    attempt_id: uuid.UUID,
    payload: GradeAttemptRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.QUIZ, Action.GRADE)))],
) -> AttemptResponse:
    """Scores the questions auto-grading cannot mark. Once every answer has a
    score, the attempt's percentage and pass flag are recomputed."""
    service = QuizService(session)
    attempt = await service.grade_attempt(attempt_id, payload, actor=actor)
    return _attempt_response(
        attempt, results_visible=await service.results_visible_to(attempt, actor=actor)
    )
