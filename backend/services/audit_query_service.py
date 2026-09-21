"""Reading the audit trail (spec §19).

Writing it lives in `audit_service.py` and is called from thirty places;
this module only reads, and the split is deliberate — nothing here can
write, so no future edit to a query path can quietly append to the log.

**There is no scoped variant of this endpoint, and that is the decision.**
Everywhere else in this codebase a read is narrowed to what the caller is
connected to. The audit trail is not: `audit.read` is held by
Administrators and Super Admins only, and a *partial* audit log is worse
than none — an administrator investigating an incident who is silently shown
two thirds of the evidence will draw a confident, wrong conclusion. The
control on this surface is who holds the permission, not what the query
hides from them.

**What the log must never become is a way to read content.** `details` is
written by each service and this module does not filter it, so the rule is
enforced at the *write* sites and stated here as the contract: an audit row
records that a message was sent and to whom, never its body; that a
credential was rotated, never its value. Reviewing new `details=` payloads
against that rule is part of adding a new audited action.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.privacy import may_see_contact
from backend.core.errors import NotFoundError, ValidationError
from backend.models.audit import AuditLog
from backend.repositories.audit import (
    ENTITY_KINDS,
    AuditRepository,
    ResolvedEntity,
)
from backend.schemas.audit import AuditLogResponse
from backend.schemas.base import PageParams
from backend.services.audit_service import AuditAction

# Actions surfaced by /security/events. Successful LOGIN and LOGOUT are
# deliberately absent: they are the highest-volume rows in the table and
# including them would bury the eight kinds of event somebody opens this
# screen to find. They remain one filter away on /audit-logs.
SECURITY_ACTIONS: tuple[str, ...] = (
    AuditAction.LOGIN_FAILED,
    AuditAction.ACCOUNT_LOCKED,
    AuditAction.TOKEN_REUSE_DETECTED,
    AuditAction.PASSWORD_CHANGED,
    AuditAction.PASSWORD_RESET_BY_ADMIN,
    AuditAction.PERMISSION_CHANGE,
    AuditAction.LOGOUT_ALL,
    AuditAction.SESSION_REVOKED,
)

# Every action the platform writes, for a filter UI that must not hardcode
# the list. Derived from the constants rather than typed out twice.
KNOWN_ACTIONS: tuple[str, ...] = tuple(
    sorted(
        value
        for name, value in vars(AuditAction).items()
        if not name.startswith("_") and isinstance(value, str)
    )
)

# A CSV export is row-level by nature -- unlike a report, which returns
# groups, an auditor needs the individual events. So it is bounded instead:
# one slab, capped, and the caller is told when the file is short of the
# truth rather than handed a prefix that looks complete.
MAX_EXPORT_ROWS = 10_000


class AuditQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logs = AuditRepository(session)

    async def search(
        self,
        params: PageParams,
        *,
        actions: Sequence[str] | None = None,
        actor_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        success: bool | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        query: str | None = None,
        export: bool = False,
    ) -> tuple[list[AuditLogResponse], int, bool]:
        """Returns `(rows, total, truncated)`."""
        actor_pk = await self._actor_pk(actor_id) if actor_id else None
        entity_pk = None
        if entity_id is not None:
            if entity_type is None:
                # Ids are only unique within a type, and resolving one
                # without knowing which table to look in would mean guessing.
                raise ValidationError(
                    "entity_type is required when filtering by entity_id."
                )
            entity_pk = await self.logs.entity_pk(entity_type, entity_id)
            if entity_pk is None:
                kind = ENTITY_KINDS.get(entity_type)
                if kind is None or not kind.addressable:
                    raise ValidationError(
                        f"Audit rows for '{entity_type}' cannot be filtered by id.",
                        details={"entity_type": entity_type},
                    )
                # The entity is gone. Its audit rows survive it and are still
                # the answer to "what happened to it", but there is no id
                # left to resolve, so the caller is told rather than handed a
                # silently empty page.
                raise NotFoundError(
                    "That record no longer exists, so its audit trail cannot be "
                    "located by id. Filter by entity_type and a date range instead."
                )

        rows, total = await self.logs.search(
            params,
            actions=actions,
            actor_id=actor_pk,
            entity_type=entity_type,
            entity_id=entity_pk,
            success=success,
            date_from=date_from,
            date_to=date_to,
            query=query,
            limit_override=MAX_EXPORT_ROWS if export else None,
        )

        return await self._to_responses(rows), total, export and total > MAX_EXPORT_ROWS

    async def get(self, public_id: uuid.UUID) -> AuditLogResponse:
        row = await self.logs.get_by_public_id_full(public_id)
        if row is None:
            raise NotFoundError("Audit record not found.")
        return (await self._to_responses([row]))[0]

    # -- rendering -----------------------------------------------------------

    async def _to_responses(self, rows: Sequence[AuditLog]) -> list[AuditLogResponse]:
        """Resolve identities for a whole page in two batches, not per row."""
        actors = await self.logs.resolve_actors(
            {r.actor_user_id for r in rows if r.actor_user_id is not None}
        )
        entities = await self.logs.resolve_entities(
            [
                (r.entity_type, r.entity_id)
                for r in rows
                if r.entity_type is not None and r.entity_id is not None
            ]
        )

        out: list[AuditLogResponse] = []
        for row in rows:
            actor = actors.get(row.actor_user_id) if row.actor_user_id is not None else None
            entity: ResolvedEntity | None = None
            if row.entity_type is not None and row.entity_id is not None:
                entity = entities.get((row.entity_type, row.entity_id))

            out.append(
                AuditLogResponse(
                    public_id=row.public_id,
                    action=row.action,
                    success=row.success,
                    actor_id=actor[0] if actor else None,
                    actor_email=row.actor_email if may_see_contact() else None,
                    actor_username=actor[1] if actor else None,
                    entity_type=row.entity_type,
                    # `str(...)`, never the stored integer: the internal
                    # primary key does not leave the process.
                    entity_id=str(entity.public_id) if entity and entity.public_id else None,
                    entity_label=entity.label if entity else None,
                    details=row.details,
                    ip_address=row.ip_address,
                    user_agent=row.user_agent,
                    request_id=row.request_id,
                    created_at=row.created_at,
                )
            )
        return out

    @staticmethod
    def to_csv(rows: Sequence[AuditLogResponse]) -> str:
        """`details` is serialised as JSON in one cell.

        Flattening it into columns would give the file a different shape for
        every filter, which is exactly what makes a CSV unusable to the
        auditor it exists for.
        """
        import json

        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(
            [
                "timestamp",
                "action",
                "success",
                "actor_email",
                "actor_username",
                "entity_type",
                "entity_id",
                "entity_label",
                "ip_address",
                "request_id",
                "details",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.created_at.astimezone(UTC).isoformat() if row.created_at else "",
                    row.action,
                    "true" if row.success else "false",
                    row.actor_email or "",
                    row.actor_username or "",
                    row.entity_type or "",
                    row.entity_id or "",
                    row.entity_label or "",
                    row.ip_address or "",
                    row.request_id or "",
                    json.dumps(row.details, separators=(",", ":")) if row.details else "",
                ]
            )
        return buffer.getvalue()

    # -- helpers -------------------------------------------------------------

    async def _actor_pk(self, public_id: uuid.UUID) -> int:
        pk = await self.logs.entity_pk("user", public_id)
        if pk is None:
            raise NotFoundError("User not found.")
        return pk
