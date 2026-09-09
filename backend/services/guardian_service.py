"""Guardian ↔ student links.

Creating a link is an administrative act, never self-service: "I am this
child's guardian" is a claim, and the institution has to be the one asserting
it. The GUARDIAN role holds `guardian.read` only -- see
`core/permissions.py`.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.models.guardian import StudentGuardian
from backend.models.identity.user import User
from backend.repositories.guardian import GuardianRepository
from backend.schemas.base import PageParams
from backend.schemas.guardian import CreateGuardianLinkRequest, UpdateGuardianLinkRequest
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.scope import ScopeResolver
from backend.utils.enums import Roles


class GuardianService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.links = GuardianRepository(session)
        self.scopes = ScopeResolver(session)

    # -- reads ---------------------------------------------------------------

    async def list_links(
        self,
        params: PageParams,
        *,
        actor: User,
        guardian_public_id: uuid.UUID | None = None,
        student_public_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[StudentGuardian], int]:
        guardian_id = None
        if guardian_public_id is not None:
            guardian_id = (await self._load_user(guardian_public_id)).id

        student_id = None
        if student_public_id is not None:
            student_id = (await self._load_user(student_public_id)).id

        unrestricted = ScopeResolver.is_unrestricted(actor)
        return await self.links.search(
            params,
            unrestricted=unrestricted,
            own_user_id=actor.id,
            guardian_id=guardian_id,
            student_id=student_id,
        )

    async def get(self, public_id: uuid.UUID, *, actor: User) -> StudentGuardian:
        link = await self.links.get_by_public_id_full(public_id)
        if link is None:
            raise NotFoundError("Guardian link not found.")

        if not ScopeResolver.is_unrestricted(actor):
            if actor.id not in (link.guardian_id, link.student_id):
                # 404 rather than 403: whether a particular child has a
                # guardian on file is not a fact to confirm to a stranger.
                raise NotFoundError("Guardian link not found.")
        return link

    # -- writes --------------------------------------------------------------

    async def create(
        self, payload: CreateGuardianLinkRequest, *, actor: User
    ) -> StudentGuardian:
        guardian = await self._load_user(payload.guardian_id)
        student = await self._load_user(payload.student_id)

        if guardian.id == student.id:
            raise ValidationError("A user cannot be their own guardian.")

        self._assert_has_role(guardian, Roles.GUARDIAN)
        self._assert_has_role(student, Roles.STUDENT)

        if await self.links.get_link(guardian_id=guardian.id, student_id=student.id):
            raise ConflictError("This guardian is already linked to this student.")

        if payload.is_primary:
            await self._clear_primary(student.id)

        link = StudentGuardian(
            guardian_id=guardian.id,
            student_id=student.id,
            relationship_type=payload.relationship_type,
            is_primary=payload.is_primary,
        )
        await self.links.add_and_flush(link)

        audit_service.record(
            self.session,
            action=AuditAction.PERMISSION_CHANGE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="student_guardian",
            entity_id=link.id,
            details={
                "guardian": guardian.username,
                "student": student.username,
                "relationship": payload.relationship_type,
            },
        )
        return await self.links.get_by_public_id_full(link.public_id)  # type: ignore[return-value]

    async def update(
        self, public_id: uuid.UUID, payload: UpdateGuardianLinkRequest, *, actor: User
    ) -> StudentGuardian:
        link = await self.get(public_id, actor=actor)
        changes = payload.model_dump(exclude_unset=True)

        if changes.get("is_primary"):
            # Only one primary contact per student; promoting this one
            # demotes whichever guardian previously held it.
            await self._clear_primary(link.student_id, except_link_id=link.id)

        for field, value in changes.items():
            setattr(link, field, value)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="student_guardian",
            entity_id=link.id,
            details={"fields": sorted(changes)},
        )
        return link

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        link = await self.links.get_by_public_id_full(public_id)
        if link is None:
            raise NotFoundError("Guardian link not found.")

        guardian_name = link.guardian.username
        student_name = link.student.username
        entity_id = link.id

        # A hard delete: unlike an organization membership, a guardianship
        # that has ended leaves nothing behind that needs its context kept --
        # and continuing to store who used to be able to read a child's
        # records, indefinitely, is data nobody asked us to hold.
        await self.session.delete(link)

        audit_service.record(
            self.session,
            action=AuditAction.PERMISSION_CHANGE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="student_guardian",
            entity_id=entity_id,
            details={"unlinked_guardian": guardian_name, "student": student_name},
        )

    # -- helpers -------------------------------------------------------------

    async def _clear_primary(self, student_id: int, *, except_link_id: int | None = None) -> None:
        stmt = (
            update(StudentGuardian)
            .where(
                StudentGuardian.student_id == student_id,
                StudentGuardian.is_primary.is_(True),
            )
            .values(is_primary=False)
        )
        if except_link_id is not None:
            stmt = stmt.where(StudentGuardian.id != except_link_id)
        await self.session.execute(stmt)

    async def _load_user(self, public_id: uuid.UUID) -> User:
        stmt = select(User).where(User.public_id == public_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise NotFoundError("User not found.")
        return user

    @staticmethod
    def _assert_has_role(user: User, role: Roles) -> None:
        if not any((r.name or "").upper() == role.value for r in (user.roles or [])):
            raise ValidationError(
                f"This user does not hold the {role.value} role.",
                details={"username": user.username},
            )
