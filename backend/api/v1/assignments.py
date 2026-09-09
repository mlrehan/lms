"""Assignment and submission endpoints (spec §12)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.assignment import Assignment, AssignmentSubmission
from backend.schemas.assignment import (
    AssignmentCreateRequest,
    AssignmentResponse,
    AssignmentSummary,
    AssignmentUpdateRequest,
    GradeSubmissionRequest,
    SubmissionResponse,
    SubmitAssignmentRequest,
)
from backend.schemas.base import Page, PageParams
from backend.services.assignment_service import AssignmentService

router = APIRouter(tags=["Assignments"])


def _assignment_response(
    a: Assignment, *, submission_count: int = 0, my_submission_id: uuid.UUID | None = None
) -> AssignmentResponse:
    return AssignmentResponse(
        public_id=a.public_id,
        title=a.title,
        due_date=a.due_date,
        max_score=a.max_score,
        submission_type=a.submission_type,
        allow_late_submissions=a.allow_late_submissions,
        description=a.description,
        instructions_path=a.instructions_path,
        rubric=a.rubric,
        course_id=a.course.public_id,
        course_title=a.course.title,
        submission_count=submission_count,
        my_submission_id=my_submission_id,
    )


def _submission_response(s: AssignmentSubmission) -> SubmissionResponse:
    return SubmissionResponse(
        public_id=s.public_id,
        assignment_id=s.assignment.public_id,
        assignment_title=s.assignment.title,
        student_id=s.student.public_id,
        student_username=s.student.username,
        submitted_at=s.submitted_at,
        files=s.files,
        content=s.content,
        grade=s.grade,
        feedback=s.feedback,
        graded_at=s.graded_at,
        graded_by_username=s.grader.username if s.grader else None,
        is_late=bool(s.submitted_at and s.assignment.due_date and s.submitted_at > s.assignment.due_date),
    )


# =============================================================================
# ASSIGNMENTS
# =============================================================================


@router.get("/assignments", response_model=Page[AssignmentSummary], summary="List assignments")
async def list_assignments(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ASSIGNMENT, Action.READ)))
    ],
    course_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[AssignmentSummary]:
    """Row-scoped by course: a Tutor sees assignments for courses they teach,
    a Student for courses they are enrolled in, a Guardian for their ward's."""
    rows, total = await AssignmentService(session).list_assignments(
        params, actor=actor, course_public_id=course_id
    )
    return Page.build(
        [AssignmentSummary.model_validate(a) for a in rows], total=total, params=params
    )


@router.post(
    "/courses/{course_id}/assignments",
    response_model=AssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an assignment",
)
async def create_assignment(
    course_id: uuid.UUID,
    payload: AssignmentCreateRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ASSIGNMENT, Action.CREATE)))
    ],
) -> AssignmentResponse:
    return _assignment_response(
        await AssignmentService(session).create(course_id, payload, actor=actor)
    )


@router.get(
    "/assignments/{assignment_id}",
    response_model=AssignmentResponse,
    summary="Get one assignment",
)
async def get_assignment(
    assignment_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ASSIGNMENT, Action.READ)))
    ],
) -> AssignmentResponse:
    service = AssignmentService(session)
    row = await service.get(assignment_id, actor=actor)
    mine = await service.submissions.get_for_student(
        assignment_id=row.id, student_id=actor.id
    )
    return _assignment_response(
        row,
        submission_count=await service.assignments.count_submissions(row.id),
        my_submission_id=mine.public_id if mine else None,
    )


@router.patch(
    "/assignments/{assignment_id}",
    response_model=AssignmentResponse,
    summary="Update an assignment",
)
async def update_assignment(
    assignment_id: uuid.UUID,
    payload: AssignmentUpdateRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ASSIGNMENT, Action.UPDATE)))
    ],
) -> AssignmentResponse:
    """`max_score` cannot be lowered below a grade already awarded."""
    return _assignment_response(
        await AssignmentService(session).update(assignment_id, payload, actor=actor)
    )


@router.delete(
    "/assignments/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an assignment",
)
async def delete_assignment(
    assignment_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ASSIGNMENT, Action.DELETE)))
    ],
) -> Response:
    """Refused once submissions exist — they hold students' work and marks."""
    await AssignmentService(session).delete(assignment_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# SUBMISSIONS
# =============================================================================


@router.put(
    "/assignments/{assignment_id}/submission",
    response_model=SubmissionResponse,
    summary="Submit or replace your own work",
)
async def submit_assignment(
    assignment_id: uuid.UUID,
    payload: SubmitAssignmentRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ASSIGNMENT, Action.SUBMIT)))
    ],
) -> SubmissionResponse:
    """Always the caller's own submission — there is no `student_id` in the
    body, so submitting on someone else's behalf isn't expressible.

    Spec §12's "replace before deadline": re-submitting updates the existing
    row rather than adding a second. Refused after the due date unless the
    assignment allows late work, and refused outright once graded — replacing
    marked work would silently invalidate the grade beside it.
    """
    return _submission_response(
        await AssignmentService(session).submit(assignment_id, payload, actor=actor)
    )


@router.get(
    "/submissions", response_model=Page[SubmissionResponse], summary="List submissions"
)
async def list_submissions(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ASSIGNMENT, Action.READ)))
    ],
    assignment_id: Annotated[uuid.UUID | None, Query()] = None,
    student_id: Annotated[uuid.UUID | None, Query()] = None,
    graded: Annotated[bool | None, Query(description="Filter to graded or ungraded work.")] = None,
) -> Page[SubmissionResponse]:
    """Scoped like enrollments: a Tutor sees submissions for courses they
    teach; a Guardian or Corporate Manager sees those of the people in their
    care; a Student sees their own."""
    rows, total = await AssignmentService(session).list_submissions(
        params,
        actor=actor,
        assignment_public_id=assignment_id,
        student_public_id=student_id,
        graded=graded,
    )
    return Page.build([_submission_response(s) for s in rows], total=total, params=params)


@router.get(
    "/submissions/{submission_id}",
    response_model=SubmissionResponse,
    summary="Get one submission",
)
async def get_submission(
    submission_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ASSIGNMENT, Action.READ)))
    ],
) -> SubmissionResponse:
    return _submission_response(
        await AssignmentService(session).get_submission(submission_id, actor=actor)
    )


@router.put(
    "/submissions/{submission_id}/grade",
    response_model=SubmissionResponse,
    summary="Grade a submission",
)
async def grade_submission(
    submission_id: uuid.UUID,
    payload: GradeSubmissionRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ASSIGNMENT, Action.GRADE)))
    ],
) -> SubmissionResponse:
    """The grade cannot exceed the assignment's `max_score`."""
    return _submission_response(
        await AssignmentService(session).grade(submission_id, payload, actor=actor)
    )
