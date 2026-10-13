"""Assignment and submission endpoints (spec §12)."""

from __future__ import annotations

import uuid
from typing import Annotated

from typing import Sequence

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status

from backend.core.privacy import visible_username
from backend.api.deps import CurrentUser, require_permissions, resolve_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.assignment import (
    Assignment,
    AssignmentSubmission,
    AssignmentSubmissionFile,
)
from backend.schemas.assignment import (
    AssignmentCreateRequest,
    AssignmentResponse,
    AssignmentSummary,
    AssignmentUpdateRequest,
    GradeSubmissionRequest,
    PublishResultsRequest,
    ResubmissionRequest,
    SubmissionFileResponse,
    SubmissionResponse,
    SubmissionStateRequest,
    SubmitAssignmentRequest,
)
from backend.api.v1.resources import _stream
from backend.schemas.base import Page, PageParams
from backend.services.assessment_scope import AssessmentTarget, describe as describe_scope
from backend.services.assignment_service import AssignmentService

router = APIRouter(tags=["Assignments"])


def _assignment_response(
    a: Assignment,
    *,
    submission_count: int = 0,
    my_submission_id: uuid.UUID | None = None,
    eligible_count: int | None = None,
    staff: bool = True,
) -> AssignmentResponse:
    """One assignment.

    `staff=False` withholds three fields a candidate has no use for and some
    claim on nothing:

    * **`instructions_path`** is a storage key. Nothing in the console reads
      it -- the generated types are its only other mention -- so it was a
      decorative field that happened to describe the server's filesystem to
      every student set the work. The same shape as the submission `path`
      that `assignment_submission_files` replaced.
    * **`submission_count`** and **`eligible_count`** are facts about the
      cohort: how many classmates have handed in, and how many were set it.
      A tutor runs the assignment and needs both; a candidate is being told
      about other people.

    Everything a student actually needs -- the brief, the deadline, what it
    is out of, the accepted file types and size, the late penalty, the pass
    mark -- is unchanged.
    """
    return AssignmentResponse(
        public_id=a.public_id,
        title=a.title,
        due_date=a.due_date,
        max_score=a.max_score,
        submission_type=a.submission_type,
        allow_late_submissions=a.allow_late_submissions,
        description=a.description,
        instructions_path=a.instructions_path if staff else None,
        rubric=a.rubric,
        course_id=a.course.public_id,
        course_title=a.course.title,
        submission_count=submission_count if staff else 0,
        my_submission_id=my_submission_id,
        scope=a.scope,
        state=a.state,
        batch_id=a.batch.public_id if a.batch else None,
        batch_code=a.batch.batch_code if a.batch else None,
        session_id=a.session.public_id if a.session else None,
        scope_description=describe_scope(
            AssessmentTarget.of(a), batch_code=a.batch.batch_code if a.batch else None
        ),
        eligible_count=eligible_count if staff else None,
        publish_at=a.publish_at,
        available_from=a.available_from,
        passing_score=a.passing_score,
        weight=a.weight,
        allowed_file_types=a.allowed_file_types,
        max_upload_mb=a.max_upload_mb,
        allow_multiple_submissions=a.allow_multiple_submissions,
        allow_resubmission=a.allow_resubmission,
        late_penalty_percent_per_day=a.late_penalty_percent_per_day,
    )


def _file_response(f: AssignmentSubmissionFile) -> SubmissionFileResponse:
    return SubmissionFileResponse(
        public_id=f.public_id,
        filename=f.filename,
        mime_type=f.mime_type,
        size=f.size,
        uploaded_at=f.uploaded_at,
        download_url=f"/submission-files/{f.public_id}/download",
    )


async def _with_files(
    service: AssignmentService, s: AssignmentSubmission, *, staff: bool = True
) -> SubmissionResponse:
    """One submission, with whatever is attached to it."""
    files = await service.files_for_submissions([s.id])
    return _submission_response(s, staff=staff, files=files.get(s.id, []))


def _submission_response(
    s: AssignmentSubmission,
    *,
    staff: bool = True,
    files: Sequence[AssignmentSubmissionFile] = (),
) -> SubmissionResponse:
    """One submission.

    `staff=False` omits the override trail. Why a mark was changed is a
    conversation for the tutor to have with the student, not a field the
    student discovers in an API response -- §24 says audit detail is not for
    them.
    """
    return SubmissionResponse(
        public_id=s.public_id,
        assignment_id=s.assignment.public_id,
        assignment_title=s.assignment.title,
        student_id=s.student.public_id,
        student_username=visible_username(s.student),
        submitted_at=s.submitted_at,
        files=[_file_response(f) for f in files],
        content=s.content,
        grade=s.grade,
        feedback=s.feedback,
        graded_at=s.graded_at,
        graded_by_username=visible_username(s.grader) if s.grader else None,
        is_late=bool(s.submitted_at and s.assignment.due_date and s.submitted_at > s.assignment.due_date),
        state=s.state,
        attempt_number=s.attempt_number,
        raw_grade=s.raw_grade,
        late_penalty_applied=s.late_penalty_applied,
        published_at=s.published_at,
        override_reason=s.override_reason if staff else None,
        overridden_at=s.overridden_at if staff else None,
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
        # The one read a candidate makes. Setting coursework is what makes
        # somebody staff here -- reading it is not.
        staff=perm(Module.ASSIGNMENT, Action.UPDATE) in resolve_permissions(actor),
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
    service = AssignmentService(session)
    return await _with_files(service, await service.submit(assignment_id, payload, actor=actor))


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
    files = await AssignmentService(session).files_for_submissions([s.id for s in rows])
    return Page.build(
        [_submission_response(s, files=files.get(s.id, [])) for s in rows],
        total=total,
        params=params,
    )


@router.post(
    "/assignments/{assignment_id}/attachments",
    response_model=SubmissionFileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach a file to your own work",
)
async def attach_submission_file(
    assignment_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ASSIGNMENT, Action.SUBMIT)))
    ],
    file: Annotated[UploadFile, File()],
) -> SubmissionFileResponse:
    """Multipart, one file per call, before submitting.

    The caller is always the owner -- there is no student id -- and the
    storage key is generated server-side. `files` used to be a JSON blob in
    the submit body carrying a client-chosen `path`, so a submission could
    name bytes nobody had written.

    Checked against the platform's upload rules *and* the assignment's own
    (`allowed_file_types`, `max_upload_mb`), because those are the limits the
    student was told about.
    """
    row = await AssignmentService(session).attach_file(assignment_id, upload=file, actor=actor)
    return _file_response(row)


@router.get(
    "/assignments/{assignment_id}/attachments",
    response_model=list[SubmissionFileResponse],
    summary="Your own attachments on this assignment",
)
async def list_submission_files(
    assignment_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ASSIGNMENT, Action.READ)))
    ],
) -> list[SubmissionFileResponse]:
    """What the caller has attached but may not have submitted yet. A tutor
    reads a student's files from the submission, not from here."""
    rows = await AssignmentService(session).attachments_for(assignment_id, actor=actor)
    return [_file_response(f) for f in rows]


@router.get(
    "/submission-files/{file_id}/download",
    summary="Download an attached file",
)
async def download_submission_file(
    file_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ASSIGNMENT, Action.READ)))
    ],
):
    """Re-authorised on every request: the student who attached it, or
    whoever may mark that assignment. Streamed through this server rather
    than redirected to a presigned URL -- a presigned URL outlives the check
    that produced it, and a student's work is not something to leave a
    standing link to."""
    row = await AssignmentService(session).resolve_attachment(file_id, actor=actor)
    return await _stream(row.path, filename=row.filename, mime_type=row.mime_type)


@router.delete(
    "/submission-files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a file you attached",
)
async def remove_submission_file(
    file_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ASSIGNMENT, Action.SUBMIT)))
    ],
) -> Response:
    """The student's own, and only before it has been marked."""
    await AssignmentService(session).remove_attachment(file_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    service = AssignmentService(session)
    return await _with_files(service, await service.get_submission(submission_id, actor=actor))


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
    service = AssignmentService(session)
    return await _with_files(service, await service.grade(submission_id, payload, actor=actor))

# =============================================================================
# RESULT LIFECYCLE (spec §14)
# =============================================================================
# Marking and releasing are separate acts, so they are separate endpoints with
# separate permissions. A tutor who may enter a mark does not automatically
# make it visible to the student and their guardian the same instant -- that is
# what leaves room for an institution's review step.


@router.post(
    "/assignments/{assignment_id}/publish-results",
    summary="Release graded marks to students",
)
async def publish_assignment_results(
    assignment_id: uuid.UUID,
    payload: PublishResultsRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ASSIGNMENT, Action.PUBLISH)))
    ],
) -> dict[str, int]:
    """Publishes every graded submission, or only the students named.

    Submissions that are not yet graded are skipped rather than refused: a
    tutor releasing a batch of marks should not be blocked by the three
    students who never submitted.
    """
    service = AssignmentService(session)
    student_ids = None
    if payload.student_ids:
        student_ids = [
            (await service._load_user(pid)).id for pid in payload.student_ids
        ]
    released = await service.publish_results(
        assignment_id, actor=actor, student_ids=student_ids
    )
    return {"published": released}


@router.post(
    "/submissions/{submission_id}/request-resubmission",
    response_model=SubmissionResponse,
    summary="Hand work back for another attempt",
)
async def request_resubmission(
    submission_id: uuid.UUID,
    payload: ResubmissionRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ASSIGNMENT, Action.GRADE)))
    ],
) -> SubmissionResponse:
    """A distinct state rather than deleting the mark: the student needs to
    know they were asked, and the performance engine needs to know this
    component is not finished."""
    service = AssignmentService(session)
    return await _with_files(
        service,
        await service.request_resubmission(submission_id, actor=actor, reason=payload.reason),
    )


@router.put(
    "/submissions/{submission_id}/state",
    response_model=SubmissionResponse,
    summary="Record an absence or an exemption",
)
async def set_submission_state(
    submission_id: uuid.UUID,
    payload: SubmissionStateRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ASSIGNMENT, Action.GRADE)))
    ],
) -> SubmissionResponse:
    """Neither an absence nor an exemption is a mark, and neither is a missing
    submission. §38 requires them to be distinguishable from a zero; this is
    where a tutor says which applies.

    An exemption removes the component from the student's weighted total. An
    absence counts as a nil result. They are not interchangeable.
    """
    return _submission_response(
        await AssignmentService(session).set_submission_state(
            submission_id, actor=actor, state=payload.state, reason=payload.reason
        )
    )
