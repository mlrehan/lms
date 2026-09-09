"""Enrollment endpoints (spec §7)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.enrollment import Enrollments
from backend.schemas.base import Page, PageParams
from backend.schemas.enrollment import (
    EnrollRequest,
    EnrollmentResponse,
    EnrollmentStatusRequest,
    TransferRequest,
)
from backend.services.enrollment_service import EnrollmentService
from backend.utils.enums import EnrollmentStatus

router = APIRouter(prefix="/enrollments", tags=["Enrollments"])


def _response(e: Enrollments) -> EnrollmentResponse:
    """Built explicitly: the ORM's `student_id`/`batch_id` are integer
    foreign keys, while the API exposes the corresponding `public_id`s."""
    return EnrollmentResponse(
        public_id=e.public_id,
        status=e.status,
        enrollment_date=e.enrollment_date,
        is_transfer=e.is_transfer,
        student_id=e.student.public_id,
        student_username=e.student.username,
        batch_id=e.batch.public_id,
        batch_code=e.batch.batch_code,
        course_title=e.batch.course.title if e.batch.course else None,
        organization_id=e.organization.public_id if e.organization else None,
        performance_level=e.performance_level,
        can_download_certificate=e.can_download_certificate,
        # Deliberately the integer id is NOT exposed here; a transfer chain is
        # followed by re-reading the enrollment list for the student.
        previous_enrollment_id=None,
    )


@router.get("", response_model=Page[EnrollmentResponse], summary="List enrollments")
async def list_enrollments(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ENROLLMENT, Action.READ)))
    ],
    batch_id: Annotated[uuid.UUID | None, Query()] = None,
    student_id: Annotated[uuid.UUID | None, Query()] = None,
    enrollment_status: Annotated[EnrollmentStatus | None, Query(alias="status")] = None,
) -> Page[EnrollmentResponse]:
    """Row-scoped, and the two scopes differ by design: a Tutor sees
    enrollments *in the batches they teach*, while a Guardian or Corporate
    Manager sees *every* enrollment of the people they are responsible for.
    A tutor has no standing to see that one of her students also takes an
    unrelated course elsewhere."""
    rows, total = await EnrollmentService(session).list_enrollments(
        params,
        actor=actor,
        batch_public_id=batch_id,
        student_public_id=student_id,
        status=enrollment_status,
    )
    return Page.build([_response(r) for r in rows], total=total, params=params)


@router.post(
    "",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enroll a student in a batch",
)
async def enroll(
    payload: EnrollRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ENROLLMENT, Action.CREATE)))
    ],
) -> EnrollmentResponse:
    """Checks batch capacity under a row lock, refuses a duplicate live
    enrollment, and requires the course to be Published or Running.

    When the caller is a Corporate Manager, the sponsoring organization is
    derived from *their own* managed organization -- it is never accepted
    from the request body, or anyone could attribute an enrollment to a
    company they have nothing to do with.
    """
    enrollment = await EnrollmentService(session).enroll(
        student_public_id=payload.student_id,
        batch_public_id=payload.batch_id,
        confirmed=payload.confirmed,
        actor=actor,
    )
    return _response(enrollment)


@router.get("/{enrollment_id}", response_model=EnrollmentResponse, summary="Get one enrollment")
async def get_enrollment(
    enrollment_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ENROLLMENT, Action.READ)))
    ],
) -> EnrollmentResponse:
    return _response(await EnrollmentService(session).get(enrollment_id, actor=actor))


@router.put(
    "/{enrollment_id}/status",
    response_model=EnrollmentResponse,
    summary="Confirm, complete, withdraw or cancel",
)
async def set_enrollment_status(
    enrollment_id: uuid.UUID,
    payload: EnrollmentStatusRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ENROLLMENT, Action.UPDATE)))
    ],
) -> EnrollmentResponse:
    """Pending → Confirmed → Completed, with Dropped and Cancelled as exits.
    Cancelling is only possible from Pending: a confirmed student who leaves
    has *dropped*, and collapsing the two would lose the difference between
    someone who never started and someone who withdrew part-way."""
    return _response(
        await EnrollmentService(session).set_status(enrollment_id, payload.status, actor=actor)
    )


@router.post(
    "/{enrollment_id}/transfer",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Transfer a student to another batch",
)
async def transfer_enrollment(
    enrollment_id: uuid.UUID,
    payload: TransferRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ENROLLMENT, Action.UPDATE)))
    ],
) -> EnrollmentResponse:
    """Closes the original enrollment and creates a new one linked back to
    it, rather than rewriting `batch_id` in place -- so the fact that the
    student was ever in the first batch, and the attendance and grades
    recorded there, keep their context. Returns the new enrollment."""
    return _response(
        await EnrollmentService(session).transfer(
            enrollment_id, target_batch_public_id=payload.target_batch_id, actor=actor
        )
    )
