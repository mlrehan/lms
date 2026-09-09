"""Corporate organization schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import EmailStr, Field

from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import OrganizationMembershipStatus

OrgName = Annotated[str, Field(min_length=2, max_length=255)]
OrgCode = Annotated[str, Field(min_length=2, max_length=30, pattern=r"^[A-Za-z0-9._-]+$")]


class OrganizationSummary(APIModel):
    public_id: uuid.UUID
    name: str
    code: str | None = None
    is_active: bool


class OrganizationResponse(OrganizationSummary):
    contact_email: str | None = None
    contact_phone: str | None = None
    created_at: datetime
    manager_count: int = 0
    member_count: int = Field(
        default=0, description="Employees currently invited, active or suspended."
    )


class OrganizationCreateRequest(RequestModel):
    name: OrgName
    code: OrgCode | None = None
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=75)


class OrganizationUpdateRequest(RequestModel):
    name: OrgName | None = None
    code: OrgCode | None = None
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=75)
    is_active: bool | None = None


# =============================================================================
# MANAGERS
# =============================================================================


class ManagerResponse(APIModel):
    public_id: uuid.UUID
    user_id: uuid.UUID
    username: str
    full_name: str | None = None
    email: str | None = None
    title: str | None = None
    is_active: bool
    invited_at: datetime | None = None


class AppointManagerRequest(RequestModel):
    user_id: uuid.UUID = Field(description="A user holding the CORPORATE_MANAGER role.")
    title: str | None = Field(default=None, max_length=100, description="e.g. 'L&D Manager'.")


# =============================================================================
# MEMBERSHIPS (employees)
# =============================================================================


class MembershipResponse(APIModel):
    public_id: uuid.UUID
    user_id: uuid.UUID
    username: str
    full_name: str | None = None
    email: str | None = None
    employee_code: str | None = None
    department: str | None = None
    status: OrganizationMembershipStatus
    invited_at: datetime | None = None
    joined_at: datetime | None = None
    organization_id: uuid.UUID
    organization_name: str | None = None


class AddMemberRequest(RequestModel):
    user_id: uuid.UUID = Field(description="A user holding the STUDENT role.")
    employee_code: str | None = Field(default=None, max_length=50)
    department: str | None = Field(default=None, max_length=100)
    activate_immediately: bool = Field(
        default=False,
        description=(
            "Create the membership ACTIVE rather than INVITED. An "
            "administrator adding a known employee is the acceptance step."
        ),
    )


class MembershipStatusRequest(RequestModel):
    status: OrganizationMembershipStatus
