"""Role and permission administration (spec §20, §23)."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.core.permissions import ALL_PERMISSIONS
from backend.models.identity.permission import Permission
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.repositories.role import PermissionRepository, RoleRepository
from backend.schemas.role import RoleCreateRequest, RoleUpdateRequest
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.utils.enums import Roles

# The six roles from spec §2 are structural: code, seed data and the
# permission catalog all reference them by name. Renaming or deleting one
# through the API would leave those references pointing at nothing, so the
# API refuses -- custom roles beyond these are free to be edited.
_SYSTEM_ROLES = {r.value for r in Roles}


class RoleService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.roles = RoleRepository(session)
        self.permissions = PermissionRepository(session)

    # -- reads ---------------------------------------------------------------

    async def list_roles(self) -> list[Role]:
        return await self.roles.list_all()

    async def get_role(self, name: str) -> Role:
        role = await self.roles.get_by_name(name)
        if role is None:
            raise NotFoundError("Role not found.")
        return role

    async def list_permissions(self, *, module: str | None = None) -> list[Permission]:
        return await self.permissions.list_all(module=module)

    # -- writes --------------------------------------------------------------

    async def create_role(self, payload: RoleCreateRequest, *, actor: User) -> Role:
        if await self.roles.get_by_name(payload.name):
            raise ConflictError("A role with that name already exists.")

        permissions = await self._resolve_permissions(payload.permissions)

        role = Role(name=payload.name, description=payload.description)
        role.permissions = permissions
        self.session.add(role)
        await self.session.flush()

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="role",
            entity_id=role.id,
            details={"name": role.name, "permissions": sorted(p.name for p in permissions)},
        )
        return role

    async def update_role(self, name: str, payload: RoleUpdateRequest, *, actor: User) -> Role:
        role = await self.get_role(name)
        changes = payload.model_dump(exclude_unset=True)
        for field, value in changes.items():
            setattr(role, field, value)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="role",
            entity_id=role.id,
            details={"fields": sorted(changes)},
        )
        return role

    async def set_permissions(
        self, name: str, permission_names: Sequence[str], *, actor: User
    ) -> Role:
        role = await self.get_role(name)

        if role.name == Roles.SUPER_ADMIN.value:
            # Super Admin holding the whole catalog is the property that
            # guarantees someone can always recover the system. Editing it
            # through the API is how an institution locks itself out.
            # 409, not 422: the payload is fine, the target forbids it.
            raise ConflictError("The SUPER_ADMIN role's permissions cannot be modified.")

        permissions = await self._resolve_permissions(permission_names)
        role.permissions = permissions

        audit_service.record(
            self.session,
            action=AuditAction.PERMISSION_CHANGE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="role",
            entity_id=role.id,
            details={"permissions": sorted(p.name for p in permissions)},
        )
        return role

    async def delete_role(self, name: str, *, actor: User) -> None:
        role = await self.get_role(name)

        if role.name in _SYSTEM_ROLES:
            raise ConflictError("Built-in roles cannot be deleted.")

        holders = await self.roles.count_users(role)
        if holders:
            # Deleting a role out from under its holders would silently strip
            # their access; the caller is told to reassign them first.
            raise ConflictError(
                "This role is still assigned to users.",
                details={"assigned_users": holders},
            )

        entity_id = role.id
        await self.session.delete(role)

        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="role",
            entity_id=entity_id,
            details={"name": name},
        )

    # -- guards --------------------------------------------------------------

    async def _resolve_permissions(self, names: Sequence[str]) -> list[Permission]:
        """Resolve permission names to rows, refusing unknown ones.

        Checked against the code catalog *and* the database: a name absent
        from the catalog is a typo or an invention that nothing enforces, and
        granting it would produce a role that looks more capable than it is.
        """
        unknown_to_catalog = [n for n in names if n not in ALL_PERMISSIONS]
        if unknown_to_catalog:
            raise ValidationError(
                "Unknown permission(s).",
                details={"unknown_permissions": unknown_to_catalog},
            )

        rows = await self.permissions.get_by_names(names)
        found = {p.name for p in rows}
        missing = [n for n in names if n not in found]
        if missing:
            raise ValidationError(
                "Permission(s) exist in the catalog but are not seeded in the database. "
                "Run the seeder.",
                details={"unseeded_permissions": missing},
            )
        return rows
