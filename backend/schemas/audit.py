"""Audit trail and security schemas (spec §19–§20).

**No internal integer identifier appears in any response here**, which takes
deliberate work rather than being free: `audit_logs.entity_id` stores the
*internal* primary key of whatever the action touched, because that is the
only id that still exists once the row it describes is gone. The read path
resolves it back to the entity's `public_id` (or, for a table keyed by a
natural name, that name) and returns `entity_id` as a **string** — never the
integer it is stored as.

Four audited entity types have no `public_id` at all — `role`,
`grade_band`, `resource_permission`, `system_setting`. Those rows carry a
resolved `entity_label` and a null `entity_id`, and cannot be filtered by id.
Stated here rather than discovered: the alternative was leaking an enumerable
integer for four types to keep one query parameter uniform.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import Field

from backend.schemas.base import APIModel


class ExportFormat(str, Enum):
    JSON = "json"
    CSV = "csv"


class AuditLogResponse(APIModel):
    public_id: uuid.UUID
    action: str
    success: bool = True

    actor_id: uuid.UUID | None = Field(
        default=None, description="Null for an action by a since-deleted account."
    )
    actor_email: str | None = None
    actor_username: str | None = None

    entity_type: str | None = None
    entity_id: str | None = Field(
        default=None,
        description="The entity's public identifier, resolved at read time. "
        "Null when the entity has been deleted or its table has no public id.",
    )
    entity_label: str | None = Field(
        default=None, description="Human-readable name, e.g. a course title. Best effort."
    )

    details: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    created_at: datetime


class AuditCatalogResponse(APIModel):
    """What a filter UI needs, so it never hardcodes the vocabulary."""

    actions: list[str]
    security_actions: list[str] = Field(
        description="The subset surfaced by /security/events."
    )
    entity_types: list[str]
    filterable_entity_types: list[str] = Field(
        description="Entity types whose rows can be filtered by id (the rest have no public id)."
    )


# =============================================================================
# SECURITY
# =============================================================================


class SecuritySummaryResponse(APIModel):
    window_hours: int
    failed_logins: int
    accounts_locked_now: int
    lockout_events: int
    token_reuse_detections: int
    permission_changes: int
    active_sessions: int
    generated_at: datetime


class LockedAccountResponse(APIModel):
    public_id: uuid.UUID
    username: str
    email: str | None = None
    full_name: str | None = None
    failed_login_attempts: int = 0
    locked_until: datetime | None = Field(
        default=None, description="Null means the lock has no expiry and needs an unlock."
    )
    is_expired: bool = Field(
        default=False,
        description="The lock has lapsed; the next successful sign-in clears it.",
    )


class AdminSessionResponse(APIModel):
    public_id: uuid.UUID
    user_id: uuid.UUID
    username: str
    created_at: datetime | None = None
    expires_at: datetime | None = None
    user_agent: str | None = None
    ip_address: str | None = None


class RevocationResponse(APIModel):
    revoked: int


class UnlockResponse(APIModel):
    public_id: uuid.UUID
    username: str
    was_locked: bool = Field(
        description="False when the account was already usable; the call is still a success."
    )
