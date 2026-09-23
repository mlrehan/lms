"""Bootstrap entry points: seed the identity catalog and the first admin."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.bootstrap.seeders.geo import seed_geo
from backend.bootstrap.seeders.grading import seed_grading
from backend.bootstrap.seeders.identity import seed_identity
from backend.core.logging import get_logger
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.security import password as pwd
from backend.utils.enums import Roles, UserStatus

logger = get_logger(__name__)


async def bootstrap_identity(session: AsyncSession) -> dict[str, int]:
    """Seed permissions, roles and grants. Idempotent."""
    result = await seed_identity(session)
    logger.info("Identity catalog seeded", extra=result)
    return result


async def bootstrap_geo(session: AsyncSession) -> dict[str, int]:
    """Seed countries, cities and timezones. Idempotent; safe to run on
    every deploy alongside `bootstrap_identity`."""
    result = await seed_geo(session)
    logger.info("Geo reference data seeded", extra=result)
    return result


async def bootstrap_grading(session: AsyncSession) -> dict[str, int]:
    """Give the institution's default grading scheme a usable starting point.

    Idempotent, and deliberately timid: it only touches a scheme that has no
    components at all, so an institution's own weightings are never replaced by
    a deploy. See the seeder's own docstring for why this is not in a migration.
    """
    result = await seed_grading(session)
    logger.info("Grading defaults seeded", extra=result)
    return result


async def ensure_super_admin(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    raw_password: str,
) -> tuple[User, bool]:
    """Create the first Super Admin, or return the existing one.

    Returns ``(user, created)``. Never overwrites an existing account's
    password: a bootstrap command that silently resets the administrator's
    credentials every time it runs is a way to lose control of an
    environment, not a convenience.
    """
    existing = (
        await session.execute(select(User).where(func.lower(User.username) == username.lower()))
    ).scalar_one_or_none()

    if existing is not None:
        return existing, False

    role = (
        await session.execute(select(Role).where(Role.name == Roles.SUPER_ADMIN.value))
    ).scalar_one_or_none()
    if role is None:
        raise RuntimeError(
            "The SUPER_ADMIN role does not exist. Run the identity seeder first."
        )

    user = User(
        username=username,
        email=email.lower(),
        slug=await User.generate_slug(username, session),
        hashed_password=pwd.hash_password(raw_password),
        first_name="Super",
        last_name="Admin",
        status=UserStatus.ACTIVE,
        can_login=True,  # a Super Admin created here is meant to sign in
    )
    user.roles = [role]
    session.add(user)
    await session.flush()

    logger.info("Super admin created", extra={"username": username})
    return user, True
