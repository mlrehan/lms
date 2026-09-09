"""Seed the permission catalog, the six built-in roles, and their grants.

Idempotent by design -- safe to run on every deploy. It reconciles the
database against `backend/core/permissions.py` rather than assuming an empty
table, so adding a permission to the catalog and re-running is the supported
way to roll one out.

What it deliberately does **not** do is delete permissions that have
disappeared from the catalog. A permission row may still be referenced by a
custom role an administrator created; removing it silently would strip that
role's authority with no record of why. Stale rows are reported instead.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.logging import get_logger
from backend.core.permissions import ALL_PERMISSIONS, ROLE_DESCRIPTIONS, ROLE_PERMISSIONS
from backend.models.identity.permission import Permission
from backend.models.identity.role import Role

logger = get_logger(__name__)


async def seed_permissions(session: AsyncSession) -> tuple[int, int]:
    """Insert missing permissions and refresh descriptions on existing ones.

    Returns ``(created, updated)``.
    """
    existing = {
        p.name: p for p in (await session.execute(select(Permission))).scalars().all()
    }

    created = 0
    updated = 0

    for name, description in ALL_PERMISSIONS.items():
        module, _, action = name.partition(".")
        row = existing.get(name)

        if row is None:
            session.add(
                Permission(name=name, description=description, module=module, action=action)
            )
            created += 1
            continue

        # Keep the derived columns in step with the name, so a catalog
        # correction propagates instead of leaving a half-updated row.
        if (row.description, row.module, row.action) != (description, module, action):
            row.description = description
            row.module = module
            row.action = action
            updated += 1

    await session.flush()

    stale = sorted(set(existing) - set(ALL_PERMISSIONS))
    if stale:
        logger.warning(
            "Permissions exist in the database but not in the catalog; left in place",
            extra={"stale_permissions": stale},
        )

    return created, updated


async def seed_roles(session: AsyncSession) -> tuple[int, int]:
    """Create the built-in roles and reconcile their permission grants.

    Returns ``(created, regranted)``.
    """
    permissions = {
        p.name: p for p in (await session.execute(select(Permission))).scalars().all()
    }

    existing = {
        r.name: r
        for r in (
            await session.execute(select(Role).options(selectinload(Role.permissions)))
        )
        .scalars()
        .unique()
        .all()
    }

    created = 0
    regranted = 0

    for role_name, granted_names in ROLE_PERMISSIONS.items():
        role = existing.get(role_name)
        is_new = role is None

        if role is None:
            role = Role(name=role_name, description=ROLE_DESCRIPTIONS.get(role_name))
            # Initialise the collection in memory *before* the object becomes
            # persistent. Reading `role.permissions` on a flushed-but-not-
            # loaded instance triggers a lazy SELECT, which under asyncio
            # raises MissingGreenlet rather than quietly issuing the query.
            role.permissions = []
            session.add(role)
            created += 1
        elif role.description != ROLE_DESCRIPTIONS.get(role_name):
            role.description = ROLE_DESCRIPTIONS.get(role_name)

        desired = {permissions[n] for n in granted_names if n in permissions}
        # A brand-new role holds nothing yet, and asking the database would
        # mean loading a collection we already know is empty.
        current: set[Permission] = set() if is_new else set(role.permissions or [])

        if desired != current:
            # Built-in roles are declared in code, so the code wins: an
            # out-of-band grant added directly in the database is reverted
            # here rather than silently accumulating.
            role.permissions = sorted(desired, key=lambda p: p.name)
            regranted += 1

    await session.flush()
    return created, regranted


async def seed_identity(session: AsyncSession) -> dict[str, int]:
    perms_created, perms_updated = await seed_permissions(session)
    roles_created, roles_regranted = await seed_roles(session)
    return {
        "permissions_created": perms_created,
        "permissions_updated": perms_updated,
        "roles_created": roles_created,
        "roles_regranted": roles_regranted,
    }
