"""Audit trail endpoints (spec §19)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.schemas.audit import (
    AuditCatalogResponse,
    AuditLogResponse,
    ExportFormat,
)
from backend.schemas.base import Page, PageParams
from backend.repositories.audit import ENTITY_TYPES, FILTERABLE_ENTITY_TYPES
from backend.services.audit_query_service import (
    KNOWN_ACTIONS,
    SECURITY_ACTIONS,
    AuditQueryService,
)

router = APIRouter(prefix="/audit-logs", tags=["Audit"])

_READ = require_permissions(perm(Module.AUDIT, Action.READ))
_EXPORT = require_permissions(
    perm(Module.AUDIT, Action.READ), perm(Module.AUDIT, Action.EXPORT)
)


@router.get("/catalog", response_model=AuditCatalogResponse, summary="Filter vocabulary")
async def catalog(
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> AuditCatalogResponse:
    """The action and entity-type vocabulary, so a filter UI never hardcodes
    it and silently stops offering an action added later.

    `filterable_entity_types` is the subset addressable by id — `role` is
    excluded because roles are named, not numbered, everywhere in this API,
    and their internal id is not something to expose to make one query
    parameter uniform.
    """
    return AuditCatalogResponse(
        actions=list(KNOWN_ACTIONS),
        security_actions=list(SECURITY_ACTIONS),
        entity_types=ENTITY_TYPES,
        filterable_entity_types=FILTERABLE_ENTITY_TYPES,
    )


@router.get("", response_model=Page[AuditLogResponse], summary="Search the audit trail")
async def list_audit_logs(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(_READ)],
    action: Annotated[list[str] | None, Query(description="Repeatable.")] = None,
    actor_id: Annotated[uuid.UUID | None, Query()] = None,
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    entity_id: Annotated[
        uuid.UUID | None, Query(description="Requires entity_type.")
    ] = None,
    success: Annotated[bool | None, Query()] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query(description="Exclusive.")] = None,
    q: Annotated[
        str | None, Query(max_length=100, description="Actor email, IP or request id.")
    ] = None,
) -> Page[AuditLogResponse]:
    """Newest first, and **not row-scoped** — see
    `services/audit_query_service.py` for why a partial audit log is worse
    than none. `audit.read` is held by Administrators and Super Admins only.

    Identifiers in the response are public ids resolved at read time; the
    internal keys the table stores never appear. An entity that has since
    been deleted comes back with a null `entity_id` and whatever label the
    row still carries — the record of what happened to it outlives it.
    """
    rows, total, _ = await AuditQueryService(session).search(
        params,
        actions=action,
        actor_id=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        success=success,
        date_from=date_from,
        date_to=date_to,
        query=q,
    )
    return Page.build(rows, total=total, params=params)


@router.get("/export", summary="Export the audit trail as CSV")
async def export_audit_logs(
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_EXPORT)],
    action: Annotated[list[str] | None, Query()] = None,
    actor_id: Annotated[uuid.UUID | None, Query()] = None,
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    entity_id: Annotated[uuid.UUID | None, Query()] = None,
    success: Annotated[bool | None, Query()] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    format: Annotated[ExportFormat, Query()] = ExportFormat.CSV,
) -> Response:
    """Needs `audit.read` **and** `audit.export`. Unlike a report, this is
    necessarily row-level — an auditor needs the individual events — so it is
    bounded instead: one capped slab, with `X-Export-Truncated` and
    `X-Export-Total` telling the caller when the file is short of the truth.
    A CSV body has nowhere to carry that, so it goes in the headers rather
    than being left for someone to notice.
    """
    service = AuditQueryService(session)
    rows, total, truncated = await service.search(
        PageParams(limit=1, offset=0),
        actions=action,
        actor_id=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        success=success,
        date_from=date_from,
        date_to=date_to,
        query=q,
        export=True,
    )
    return Response(
        content=service.to_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="audit-log.csv"',
            "X-Export-Total": str(total),
            "X-Export-Rows": str(len(rows)),
            "X-Export-Truncated": "true" if truncated else "false",
        },
    )


@router.get("/{log_id}", response_model=AuditLogResponse, summary="Get one audit record")
async def get_audit_log(
    log_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> AuditLogResponse:
    return await AuditQueryService(session).get(log_id)
