"""Read-through access to LAIT's corporate managers and their delegates.

Two upstream endpoints, surfaced unchanged in substance:

    GET /api/GetDelegateManagers
    GET /api/GetDelegateManagers/{customer_id}/Delegates

**Read-through, not a sync.** Nothing is written. The LMS already has its own
record of who looks after whom -- `manager_students`, which an administrator
asserts and `ScopeResolver` enforces -- and that is deliberately *not* derived
from this feed. These endpoints answer a different question: what does the
upstream system say right now? Which is what somebody reconciling the two
needs, and what nothing in the console could previously show.

Tagged **Corporate managers**, beside `/manager-links`, which is the LMS's
own record of the same relationship. Somebody checking one wants the other,
and every summary here says "held by LAIT" so the two are not confused.

Gated on `organization.read`. A delegate manager is a company's contact and
their delegates are that company's employees, so this is the corporate
directory, and the permission that governs it is the one that already governs
organizations. It is deliberately **not** `user.sync`: that grant starts
writes, and reading a list should not require the authority to overwrite the
roster.

The upstream key never appears here. It is held in `LaitSettings`, read by
`LaitClient` at request time into a header, and no response or error from
this module carries a body, a URL or a header from the external call --
`LaitApiError` is constructed from a status and a path by design.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from backend.api.deps import CurrentUser, require_permissions
from backend.core.config import get_settings
from backend.core.errors import NotFoundError, ServiceUnavailableError
from backend.core.logging import get_logger
from backend.core.permissions import Action, Module, perm
from backend.core.privacy import may_see_contact
from backend.integrations.lait_client import LaitApiError, LaitClient
from backend.schemas.lait_delegates import (
    DelegateListResponse,
    DelegateManagerResponse,
    DelegateResponse,
)

logger = get_logger("lait.delegates.api")
router = APIRouter(prefix="/integrations/lait", tags=["Corporate managers"])

_READ = Annotated[
    CurrentUser, Depends(require_permissions(perm(Module.ORGANIZATION, Action.READ)))
]


def _client() -> LaitClient:
    """A client for this request, or a 503 naming the configuration.

    `LaitClient` refuses to construct without a key and a base URL. Answering
    503 rather than 500 is the honest status: the service is reachable, this
    one integration is not switched on, and that is an operator's problem
    rather than a caller's.
    """
    try:
        return LaitClient(get_settings().lait)
    except LaitApiError as exc:
        raise ServiceUnavailableError(str(exc)) from exc


def _full_name(row: dict) -> str | None:
    parts = [row.get(key) for key in ("title", "first_name", "middle_name", "last_name")]
    joined = " ".join(str(part).strip() for part in parts if str(part or "").strip())
    return joined or None


def _manager(row: dict, *, show_email: bool) -> DelegateManagerResponse:
    return DelegateManagerResponse(
        customer_id=int(row.get("customer_id") or 0),
        unique_key=row.get("unique_key"),
        full_name=_full_name(row),
        first_name=row.get("first_name") or None,
        last_name=row.get("last_name") or None,
        company_name=row.get("company_name") or None,
        designation=row.get("designation") or None,
        is_active=row.get("is_active"),
        date_created=row.get("date_created"),
        date_modified=row.get("date_modified"),
        # `username` upstream *is* the email address. Withheld from anybody
        # who may not read contact details, exactly as the LMS's own
        # directories withhold it -- an external source is not a way around
        # the rule.
        email=(row.get("username") or None) if show_email else None,
    )


async def _call(what: str, coroutine):  # type: ignore[no-untyped-def]
    """Run one upstream call, turning its failures into honest statuses.

    A refused key, a timeout and a 500 upstream are all "this integration is
    not answering", which is 503 -- not 500, which would say the fault is
    here. The exception's message carries a status and a path and never a
    response body, so logging it cannot leak somebody's name or address.
    """
    try:
        return await coroutine
    except LaitApiError as exc:
        logger.warning("lait.%s failed", what, extra={"status": exc.status})
        raise ServiceUnavailableError(
            f"The LAIT service did not answer ({exc.status or 'no response'})."
        ) from exc


@router.get(
    "/delegate-managers",
    response_model=list[DelegateManagerResponse],
    summary="Corporate managers held by LAIT",
)
async def delegate_managers(actor: _READ) -> list[DelegateManagerResponse]:
    """Every delegate manager upstream, newest fields as LAIT reports them.

    `customer_id` is the key the companion endpoint takes.

    Email addresses appear only for callers holding `user.view_contact`;
    everybody else sees `null`, which means withheld rather than absent.
    """
    # `may_see_contact()` with no owner asks the plain question -- does this
    # viewer hold `user.view_contact` -- rather than "is this their own
    # record", which has no meaning for a row that belongs to another system.
    show_email = may_see_contact()
    client = _client()
    try:
        rows = await _call("delegate_managers", client.delegate_managers())
    finally:
        await client.aclose()
    return [_manager(row, show_email=show_email) for row in rows]


@router.get(
    "/delegate-managers/{customer_id}/delegates",
    response_model=DelegateListResponse,
    summary="The students under one corporate manager",
    responses={status.HTTP_404_NOT_FOUND: {"description": "LAIT has no manager with that id."}},
)
async def delegate_manager_students(
    actor: _READ,
    customer_id: Annotated[int, Path(ge=1, description="The manager's LAIT `customer_id`.")],
) -> DelegateListResponse:
    """The delegates LAIT lists under this manager.

    A manager with nobody returns `count: 0`; a `customer_id` LAIT has never
    heard of returns **404**. Upstream distinguishes the two and so does this,
    rather than flattening both to an empty list.
    """
    client = _client()
    try:
        rows = await _call(
            "delegate_manager_students", client.delegate_manager_students(customer_id)
        )
    finally:
        await client.aclose()

    if rows is None:
        raise NotFoundError("LAIT has no delegate manager with that id.")

    return DelegateListResponse(
        customer_id=customer_id,
        count=len(rows),
        delegates=[
            DelegateResponse(
                customer_id=int(row.get("customer_id") or customer_id),
                student_id=row.get("student_id"),
                unique_key=row.get("unique_key"),
                delegate_name=row.get("delegate_name") or None,
                status_id=row.get("status_id"),
                status_details=row.get("status_details") or None,
                date_added=row.get("date_added"),
            )
            for row in rows
        ],
    )
