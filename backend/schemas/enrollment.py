"""Enrollment schemas (spec §7)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import EnrollmentStatus, PerformanceLevel


class EnrollmentResponse(APIModel):
    public_id: uuid.UUID
    status: EnrollmentStatus
    enrollment_date: datetime | None = None
    is_transfer: bool = False

    student_id: uuid.UUID = Field(description="public_id of the enrolled student.")
    student_username: str | None = None
    batch_id: uuid.UUID = Field(description="public_id of the batch.")
    batch_code: str | None = None
    course_title: str | None = None

    organization_id: uuid.UUID | None = Field(
        default=None,
        description="Set when a corporate organization sponsored this enrollment.",
    )
    performance_level: PerformanceLevel | None = None
    can_download_certificate: bool = False
    previous_enrollment_id: uuid.UUID | None = Field(
        default=None,
        description="Set on a transfer, pointing at the enrollment this one replaced.",
    )


class EnrollRequest(RequestModel):
    student_id: uuid.UUID
    batch_id: uuid.UUID
    confirmed: bool = Field(
        default=False,
        description=(
            "Create the enrollment already CONFIRMED rather than PENDING. "
            "An administrator enrolling someone directly is the approval step."
        ),
    )


class TransferRequest(RequestModel):
    """Spec §7 'Transfer batches'.

    Records history rather than overwriting: the existing enrollment is
    closed and a new row is created pointing back at it, so "which batch was
    this student in during March" stays answerable.
    """

    target_batch_id: uuid.UUID


class EnrollmentStatusRequest(RequestModel):
    status: EnrollmentStatus
