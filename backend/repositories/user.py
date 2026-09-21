"""User queries."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from backend.core.privacy import may_see_contact
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams
from backend.utils.enums import UserStatus

if TYPE_CHECKING:  # import cycle: scope.py imports models, not repositories
    from backend.services.scope import Scope


class UserRepository(BaseRepository[User]):
    model = User

    def _with_roles(self) -> Select[tuple[User]]:
        """Eager-load roles and their permissions.

        Every authenticated request resolves the caller's permissions, so
        without this the auth dependency alone would fire one query for the
        user, one for their roles, and one per role for permissions. Loading
        them in one round trip is the difference between ~4 queries and 1 on
        the hottest path in the application.
        """
        return select(User).options(selectinload(User.roles).selectinload(Role.permissions))

    async def get_by_public_id_with_roles(self, public_id: uuid.UUID) -> User | None:
        stmt = self._with_roles().where(User.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id_with_roles(self, user_id: int) -> User | None:
        stmt = self._with_roles().where(User.id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_identifier(self, identifier: str) -> User | None:
        """Resolve a login identifier, which spec §3 allows to be either an
        email address or a username.

        Matching is case-insensitive on both: users do not reliably reproduce
        the casing they registered with, and refusing them for it is a
        support ticket, not a security control.
        """
        normalised = identifier.strip().lower()
        # `lower(NULL)` is NULL in SQL, which equals nothing -- so a user with
        # no email simply fails to match on that branch rather than raising.
        stmt = self._with_roles().where(
            or_(
                func.lower(User.email) == normalised,
                func.lower(User.username) == normalised,
            )
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(func.lower(User.email) == email.strip().lower())
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(func.lower(User.username) == username.strip().lower())
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        query: str | None = None,
        status: UserStatus | None = None,
        role: str | None = None,
        scope: "Scope | None" = None,
    ) -> tuple[Sequence[User], int]:
        stmt = self._with_roles()

        # Row-level scoping, applied before any other filter so an
        # out-of-scope row is never a candidate -- not fetched and then
        # hidden. `scope=None` means the caller has already established that
        # no restriction applies; every request-driven path passes a real
        # Scope so that "forgot to scope" is visible at the call site.
        if scope is not None:
            stmt = scope.apply(stmt, User.id)

        # Deleted accounts are excluded from every listing. The row is kept
        # (audit_logs and enrollments reference it) but it is not a member of
        # the institution any more, and showing it in a roster invites an
        # administrator to "fix" an account that was deliberately removed.
        stmt = stmt.where(User.status != UserStatus.DELETED)

        if status is not None:
            stmt = stmt.where(User.status == status)

        if role:
            stmt = stmt.where(User.roles.any(Role.name == role))

        if query:
            like = f"%{query.strip().lower()}%"
            name_match = [func.lower(User.first_name).like(like), func.lower(User.last_name).like(like)]
            # Matching on the email or login name would let anyone who may not *see* them find out whether a given
            # address exists by trying it, so those two are searchable only by a viewer who may see them.
            contact_match = [func.lower(User.username).like(like), func.lower(User.email).like(like)] if may_see_contact() else []
            stmt = stmt.where(or_(*contact_match, *name_match))

        stmt = stmt.order_by(User.id.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def get_roles_by_names(self, names: Sequence[str]) -> list[Role]:
        if not names:
            return []
        stmt = select(Role).where(Role.name.in_(list(names)))
        return list((await self.session.execute(stmt)).scalars().all())
