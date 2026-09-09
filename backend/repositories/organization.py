"""Corporate organization queries."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from backend.models.organization import (
    Organization,
    OrganizationManager,
    OrganizationMembership,
)
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams
from backend.utils.enums import OrganizationMembershipStatus

if TYPE_CHECKING:
    from backend.services.scope import Scope

# The statuses that mean "this person is currently one of ours". Matches the
# partial unique index `uq_organization_memberships_active_user`, so the
# service and the database agree on what "already employed somewhere" means.
CURRENT_MEMBERSHIP_STATUSES = (
    OrganizationMembershipStatus.INVITED,
    OrganizationMembershipStatus.ACTIVE,
    OrganizationMembershipStatus.SUSPENDED,
)


class OrganizationRepository(BaseRepository[Organization]):
    model = Organization

    def _base(self) -> Select[tuple[Organization]]:
        return select(Organization).where(Organization.is_deleted.is_(False))

    async def get_by_public_id_active(self, public_id: uuid.UUID) -> Organization | None:
        stmt = self._base().where(Organization.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_name(self, name: str) -> Organization | None:
        stmt = self._base().where(func.lower(Organization.name) == name.strip().lower())
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_code(self, code: str) -> Organization | None:
        stmt = self._base().where(func.lower(Organization.code) == code.strip().lower())
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        scope: "Scope",
        query: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[Sequence[Organization], int]:
        stmt = scope.apply(self._base(), Organization.id)

        if is_active is not None:
            stmt = stmt.where(Organization.is_active.is_(is_active))
        if query:
            like = f"%{query.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Organization.name).like(like),
                    func.lower(Organization.code).like(like),
                )
            )

        stmt = stmt.order_by(Organization.name)
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def count_active_managers(self, organization_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(OrganizationManager)
            .where(
                OrganizationManager.organization_id == organization_id,
                OrganizationManager.is_active.is_(True),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_current_members(self, organization_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(OrganizationMembership)
            .where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.status.in_(CURRENT_MEMBERSHIP_STATUSES),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())


class OrganizationManagerRepository(BaseRepository[OrganizationManager]):
    model = OrganizationManager

    def _base(self) -> Select[tuple[OrganizationManager]]:
        return select(OrganizationManager).options(
            selectinload(OrganizationManager.user),
            selectinload(OrganizationManager.organization),
        )

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> OrganizationManager | None:
        stmt = self._base().where(OrganizationManager.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_organization(
        self, organization_id: int, *, include_inactive: bool = False
    ) -> list[OrganizationManager]:
        stmt = self._base().where(OrganizationManager.organization_id == organization_id)
        if not include_inactive:
            stmt = stmt.where(OrganizationManager.is_active.is_(True))
        stmt = stmt.order_by(OrganizationManager.id)
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def get_active_for_user(self, user_id: int) -> OrganizationManager | None:
        """A user manages at most one organization at a time -- see the
        partial unique index `uq_organization_managers_active_user`."""
        stmt = self._base().where(
            OrganizationManager.user_id == user_id,
            OrganizationManager.is_active.is_(True),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class OrganizationMembershipRepository(BaseRepository[OrganizationMembership]):
    model = OrganizationMembership

    def _base(self) -> Select[tuple[OrganizationMembership]]:
        return select(OrganizationMembership).options(
            selectinload(OrganizationMembership.user),
            selectinload(OrganizationMembership.organization),
        )

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> OrganizationMembership | None:
        stmt = self._base().where(OrganizationMembership.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_current_for_user(self, user_id: int) -> OrganizationMembership | None:
        stmt = self._base().where(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.status.in_(CURRENT_MEMBERSHIP_STATUSES),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        scope: "Scope",
        organization_id: int | None = None,
        status: OrganizationMembershipStatus | None = None,
    ) -> tuple[Sequence[OrganizationMembership], int]:
        stmt = scope.apply(self._base(), OrganizationMembership.organization_id)

        if organization_id is not None:
            stmt = stmt.where(OrganizationMembership.organization_id == organization_id)
        if status is not None:
            stmt = stmt.where(OrganizationMembership.status == status)

        stmt = stmt.order_by(OrganizationMembership.id.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]
