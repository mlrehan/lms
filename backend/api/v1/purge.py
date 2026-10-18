"""Permanent deletion, and the complete system reset.

**Every route here is gated twice: on `system.purge` or `system.reset`, and on
the Super Admin role.** That looks like belt and braces and is deliberate.
`role_permissions` is editable data, so a permission on its own could be
granted to a lesser role by somebody who did not appreciate what they were
handing over; being in the catalogue is what makes the gate discoverable and
auditable, and the role check is the floor underneath it. `require_roles()`'s
own docstring describes this exact case -- an operation whose danger comes from
who you are rather than from a capability one would sensibly delegate.

**Preview and execute are separate requests, and the plan is recomputed in the
second one.** The confirmation phrase carries the real record count, so if
somebody enrols a student between the two, the phrase no longer matches and the
delete is refused rather than quietly taking more than was agreed.

**No second factor and no CAPTCHA**, by instruction. The gate is a Super Admin
session, an explicit permission, a dependency preview, and a typed
confirmation naming the count (or, for a reset, the database). Written down
here so that whoever reads this later knows the depth of the gate instead of
assuming it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from backend.api.deps import CurrentUser, DBSession, UserAgent, require_permissions, require_roles
from backend.core.config import Settings, get_settings
from backend.core.permissions import Action, Module, perm
from backend.schemas.purge import (
    EmptyBatchesResponse,
    PurgeEntitiesResponse,
    PurgeExecuteRequest,
    PurgePreviewRequest,
    PurgePreviewResponse,
    SystemResetPreviewResponse,
    SystemResetRequest,
    SystemResetResponse,
)
from backend.services.purge_admin_service import (
    BLOCKED_ENTITIES,
    ENTITIES,
    PurgeAdminService,
)
from backend.services.system_reset_service import SystemResetService
from backend.utils.enums import Roles

router = APIRouter(prefix="/admin", tags=["Permanent deletion"])

#: Both gates, applied to every route. See the module docstring.
_PURGE_GATE = [
    Depends(require_permissions(perm(Module.SYSTEM, Action.PURGE))),
    Depends(require_roles(Roles.SUPER_ADMIN.value)),
]
_RESET_GATE = [
    Depends(require_permissions(perm(Module.SYSTEM, Action.RESET))),
    Depends(require_roles(Roles.SUPER_ADMIN.value)),
]


# =============================================================================
# Permanent deletion
# =============================================================================


@router.get(
    "/purge/entities",
    response_model=PurgeEntitiesResponse,
    dependencies=_PURGE_GATE,
    summary="What may be permanently deleted, and what may not",
)
async def purge_entities(session: DBSession) -> PurgeEntitiesResponse:
    """The entity list, plus the ones that are refused and why.

    The refusals are returned rather than omitted: a screen that silently
    leaves out what somebody asked for teaches them the feature is broken,
    where one that explains teaches them the rule.
    """
    unsupported = await PurgeAdminService(session).purger.unsupported_constraints()
    return PurgeEntitiesResponse(
        entities=[
            {
                "key": e.key,
                "label": e.label,
                "singular": e.singular,
                "consequence": e.consequence,
            }
            for e in ENTITIES
        ],
        blocked=[{"key": k, "label": label, "reason": reason} for k, label, reason in BLOCKED_ENTITIES],
        unsupported_constraints=unsupported,
    )


@router.post(
    "/purge/preview",
    response_model=PurgePreviewResponse,
    dependencies=_PURGE_GATE,
    summary="What this deletion would destroy",
)
async def purge_preview(
    payload: PurgePreviewRequest,
    session: DBSession,
    actor: CurrentUser,
) -> PurgePreviewResponse:
    """Read-only. Nothing is deleted, and nothing is staged.

    Returns the dependency breakdown, what survives with a reference cleared,
    any protection that would refuse this, and the phrase to type back.
    """
    preview = await PurgeAdminService(session).preview(payload.entity, payload.ids, actor=actor)
    return PurgePreviewResponse(**vars(preview))


@router.post(
    "/purge/execute",
    response_model=PurgePreviewResponse,
    dependencies=_PURGE_GATE,
    summary="Delete permanently",
)
async def purge_execute(
    payload: PurgeExecuteRequest,
    session: DBSession,
    actor: CurrentUser,
    user_agent: UserAgent,
) -> PurgePreviewResponse:
    """Irreversible. One transaction, with its own audit record.

    The plan is recomputed here rather than trusted from the preview, so a
    confirmation phrase that has gone stale is refused instead of authorising
    a larger deletion than the one somebody read.
    """
    result = await PurgeAdminService(session).execute(
        payload.entity,
        payload.ids,
        actor=actor,
        confirmation=payload.confirmation,
        user_agent=user_agent,
    )
    await session.commit()
    return PurgePreviewResponse(**vars(result))


@router.get(
    "/purge/empty-batches",
    response_model=EmptyBatchesResponse,
    dependencies=_PURGE_GATE,
    summary="Batches with nobody enrolled and no register taken",
)
async def purge_empty_batches(session: DBSession) -> EmptyBatchesResponse:
    """Offered because it is the one bulk deletion safe to suggest.

    An empty batch is a scheduling mistake; hunting for them by hand is how
    real ones get deleted by accident.
    """
    return EmptyBatchesResponse(batches=await PurgeAdminService(session).empty_batches())


# =============================================================================
# Complete system reset
# =============================================================================


@router.get(
    "/reset/preview",
    response_model=SystemResetPreviewResponse,
    dependencies=_RESET_GATE,
    summary="What a reset would clear, and whether it can run at all",
)
async def reset_preview(
    session: DBSession,
    settings: Settings = Depends(get_settings),
) -> SystemResetPreviewResponse:
    """Read-only, and safe to call on any installation.

    On an installation where resetting is switched off -- which is the default,
    and always the case in production -- this returns the impact summary with
    `enabled: false` and the blockers that explain it. Showing the figures
    while refusing the action is the point: an operator can see what a reset
    would cost without being able to cause it.
    """
    preview = await SystemResetService(session, settings).preview()
    return SystemResetPreviewResponse(
        database=preview.database,
        environment=preview.environment,
        enabled=preview.enabled,
        blockers=preview.blockers,
        impact=[vars(i) for i in preview.impact],
        total_rows=preview.total_rows,
        preserved=preview.preserved,
        confirmation_phrase=preview.confirmation_phrase,
    )


@router.post(
    "/reset/execute",
    response_model=SystemResetResponse,
    status_code=status.HTTP_200_OK,
    dependencies=_RESET_GATE,
    summary="Reset the installation to a freshly-installed state",
)
async def reset_execute(
    payload: SystemResetRequest,
    session: DBSession,
    actor: CurrentUser,
    user_agent: UserAgent,
    settings: Settings = Depends(get_settings),
) -> SystemResetResponse:
    """Irreversible, and refused unless four separate conditions hold.

    Switched on in deployment configuration; never in production; a verified
    recent backup; and a typed phrase naming this database. Every refusal is
    reported together by `/reset/preview` so they can be arranged in one go.

    The response carries a new password for the one remaining Super Admin
    account. It is shown exactly once and is not recoverable afterwards.
    """
    outcome = await SystemResetService(session, settings).execute(
        actor=actor,
        confirmation=payload.confirmation,
        user_agent=user_agent,
    )
    await session.commit()
    return SystemResetResponse(
        database=outcome.database,
        rows_deleted=outcome.rows_deleted,
        cleared=[vars(i) for i in outcome.cleared],
        seeded=outcome.seeded,
        bootstrap_username=outcome.bootstrap_username,
        bootstrap_password=outcome.bootstrap_password,
        sessions_invalidated=outcome.sessions_invalidated,
        warnings=outcome.warnings,
    )
