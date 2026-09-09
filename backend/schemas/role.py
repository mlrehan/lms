"""Role and permission schemas (spec §20, §23).

Roles and permissions are addressed by **name**, not by a UUID: they are a
fixed, code-defined catalog (`backend/core/permissions.py`) rather than user
data. `/roles/TUTOR` and `/permissions/course.create` are stable across
environments and readable in a log or a bug report, where a UUID would tell
nobody anything and would differ between dev and production.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from backend.schemas.base import APIModel, RequestModel

RoleName = Annotated[str, Field(min_length=2, max_length=50, pattern=r"^[A-Z][A-Z0-9_]*$")]


class PermissionResponse(APIModel):
    name: str
    description: str | None = None
    module: str | None = None
    action: str | None = None


class RoleSummary(APIModel):
    name: str
    description: str | None = None


class RoleResponse(RoleSummary):
    permissions: list[str] = Field(default_factory=list)


class RoleCreateRequest(RequestModel):
    name: RoleName = Field(description="Uppercase identifier, e.g. TEACHING_ASSISTANT.")
    description: str | None = Field(default=None, max_length=255)
    permissions: list[str] = Field(
        default_factory=list,
        description="Permission names to grant. Each must exist in the catalog.",
    )


class RoleUpdateRequest(RequestModel):
    description: str | None = Field(default=None, max_length=255)


class RolePermissionsRequest(RequestModel):
    permissions: list[str] = Field(
        description="The complete set of permission names this role should hold.",
    )
