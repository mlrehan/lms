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
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.core.privacy import visible_username
from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.quiz import Question, Quiz, QuizAttempt
from backend.schemas.base import Page, PageParams
from backend.schemas.quiz import (
    AUTO_GRADABLE,
    AttemptResponse,
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

router = APIRouter(tags=["Quizzes"])


def _student_question(q: Question) -> QuestionForStudent:
    return QuestionForStudent(
        public_id=q.public_id,
        question_text=q.question_text,
        question_type=q.question_type,
        points=q.points,
        order=q.order,
        settings=q.settings,
        options=[
            {"id": o.id, "option_text": o.option_text, "order": o.order}
            for o in sorted(q.options, key=lambda o: (o.order, o.id))
        ],
    )


def _author_question(q: Question) -> QuestionForAuthor:
    return QuestionForAuthor(
        public_id=q.public_id,
        question_text=q.question_text,
        question_type=q.question_type,
        points=q.points,
        order=q.order,
        settings=q.settings,
        options=[
            {
                "id": o.id,
                "option_text": o.option_text,
                "order": o.order,
                "is_correct": o.is_correct,
            }
            for o in sorted(q.options, key=lambda o: (o.order, o.id))
        ],
    )


def _attempt_response(a: QuizAttempt) -> AttemptResponse:
    awaiting = any(ans.score_awarded is None for ans in a.answers)
    return AttemptResponse(
        public_id=a.public_id,
        quiz_id=a.quiz.public_id,
        quiz_title=a.quiz.title,
        student_id=a.student.public_id,
        student_username=visible_username(a.student),
        attempt_number=a.attempt_number,
        started_at=a.started_at,
        finished_at=a.finished_at,
        score=a.score,
        is_passed=a.is_passed,
        submitted_late=a.submitted_late,
        feedback=a.feedback,
        awaiting_manual_grading=awaiting,
        answers=[
            AnswerResponse(
                question_id=ans.question.public_id,
                question_text=ans.question.question_text,
                selected_options=ans.selected_options,
                score_awarded=ans.score_awarded,
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
    return QuizResponse(
        public_id=quiz.public_id,
        title=quiz.title,
        duration_minutes=quiz.duration_minutes,
        attempts_allowed=quiz.attempts_allowed,
        passing_score=quiz.passing_score,
        is_published=quiz.is_published,
        instructions=quiz.instructions,
        shuffle_questions=quiz.shuffle_questions,
        is_auto_graded=quiz.is_auto_graded,
        grading_policy=quiz.grading_policy,
        course_id=quiz.course.public_id,
        course_title=quiz.course.title,
        question_count=count,
        total_points=total_points,
        my_attempts_used=used,
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
    cannot be serialised through this route at all."""
    rows = await QuizService(session).list_questions(quiz_id, actor=actor)
    return [_student_question(q) for q in rows]


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
    return _attempt_response(
        await QuizService(session).submit_attempt(attempt_id, payload.answers, actor=actor)
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
    rows, total = await QuizService(session).list_attempts(
        params, actor=actor, quiz_public_id=quiz_id, student_public_id=student_id
    )
    return Page.build([_attempt_response(a) for a in rows], total=total, params=params)


@router.get(
    "/attempts/{attempt_id}", response_model=AttemptResponse, summary="Get one attempt"
)
async def get_attempt(
    attempt_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.GRADE, Action.READ)))],
) -> AttemptResponse:
    return _attempt_response(await QuizService(session).get_attempt(attempt_id, actor=actor))


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
    return _attempt_response(
        await QuizService(session).grade_attempt(attempt_id, payload, actor=actor)
    )
