"""Operational and performance endpoints (spec §24).

Gated on `setting.read` rather than a module of their own: "may this person
see how the system is configured" and "may they see how it is behaving" have
the same audience, and inventing a permission to express a distinction nobody
makes is catalogue growth for its own sake.

Deliberately **not** the Kubernetes probes. `/livez` and `/readyz` stay
unauthenticated, unversioned and outside this router, because a load balancer
is configured against a fixed path and is the wrong audience for anything
beyond yes/no. These endpoints exist for a person diagnosing a problem, and
they expose table sizes and route latencies that a probe has no business
publishing to whoever can reach the port.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.services.ops_service import OpsService

router = APIRouter(prefix="/ops", tags=["Operations"])

_READ = require_permissions(perm(Module.SETTING, Action.READ))


@router.get("/health", summary="Detailed dependency health")
async def health(
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> dict[str, Any]:
    """What `/readyz` answers yes/no to, with the detail behind it — which
    dependency, and how slow. A storage backend that cannot be built shows as
    `degraded` rather than taking this endpoint down with it: reporting the
    fault is the endpoint's job."""
    return await OpsService(session).health()


@router.get("/metrics", summary="Request counts and latency by route")
async def metrics(
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> dict[str, Any]:
    """Per **route template**, never per path — keying on the path makes a
    thousand courses a thousand metrics describing one route.

    In-process and reset by a restart, which the response states: with two
    workers behind a load balancer each answers about itself. Latency is
    bucketed rather than sampled, because keeping every sample would make
    this endpoint the largest allocation in the system.
    """
    return OpsService.metrics()


@router.get("/database", summary="Database size, scans, indexes and pool")
async def database(
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
    limit: Annotated[int, Query(ge=1, le=50)] = 15,
) -> dict[str, Any]:
    """Diagnostic, not authoritative. `pg_stat_*` counters reset on
    `pg_stat_reset()` and on a crash, so "this index has never been used"
    means "not since the counters were last reset".

    `mostly_sequential` is flagged only above a row floor: a sequential scan
    of forty rows is the correct plan, and reporting it sends people to add
    indexes that make writes slower and reads no faster.

    Statement-level timing needs `pg_stat_statements` in
    `shared_preload_libraries` and therefore a server restart. Where it is
    absent the response says so and names the setting, rather than shipping
    an endpoint that installs the extension and then fails on every query
    against its view.
    """
    return await OpsService(session).database(limit=limit)
