"""Role and permission queries."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from backend.models.identity.permission import Permission
from backend.models.identity.role import Role
from backend.models.identity.user_role import UserRole
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams

user_roles_table = UserRole.__table__


class RoleRepository(BaseRepository[Role]):
    model = Role

    async def get_by_name(self, name: str) -> Role | None:
        stmt = (
            select(Role)
            .options(selectinload(Role.permissions))
            .where(Role.name == name)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def count_users(self, role: Role) -> int:
        """Count holders without loading them.

        `role.users` is not eager-loaded (a role may be held by thousands of
        people, and no caller needs the objects), so touching it under
        asyncio raises MissingGreenlet. A COUNT answers the only question
        anyone actually asks of it.
        """
        stmt = (
            select(func.count())
            .select_from(user_roles_table)
            .where(user_roles_table.c.role_id == role.id)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def list_all(self) -> list[Role]:
        stmt = (
            select(Role)
            .options(selectinload(Role.permissions))
            .order_by(Role.name)
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def list_page(self, params: PageParams) -> tuple[Sequence[Role], int]:
        stmt = (
            select(Role)
            .options(selectinload(Role.permissions))
            .order_by(Role.name)
        )
        return await self.paginate(stmt, params)  # type: ignore[return-value]


class PermissionRepository(BaseRepository[Permission]):
    model = Permission

    async def get_by_name(self, name: str) -> Permission | None:
        stmt = select(Permission).where(Permission.name == name)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_names(self, names: Sequence[str]) -> list[Permission]:
        if not names:
            return []
        stmt = select(Permission).where(Permission.name.in_(list(names)))
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_all(self, *, module: str | None = None) -> list[Permission]:
        stmt = select(Permission).order_by(Permission.module, Permission.action)
        if module:
            stmt = stmt.where(Permission.module == module)
        return list((await self.session.execute(stmt)).scalars().all())
