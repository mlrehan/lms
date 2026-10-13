"""Corporate manager ↔ student links.

Creating a link is an administrative act, never self-service -- the same rule
as guardianship, for the same reason. "These thirty are mine" is a claim
about who may read thirty people's attendance, marks and results, and the
institution has to be the one asserting it. The CORPORATE_MANAGER role holds
`managed_student.read` only; see `core/permissions.py`.

Employment is a separate fact and is not checked here. A student may be
linked to a manager without an `organization_memberships` row, and two
colleagues at the same company are not linked to each other's manager by
being colleagues. That separation is the whole point of the table.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.core.notification_types import NotificationType
from backend.models.identity.user import User
from backend.models.organization import ManagedStudent
from backend.repositories.managed_student import ManagedStudentRepository
from backend.schemas.base import PageParams
from backend.schemas.managed_student import (
    CreateManagedStudentRequest,
    UpdateManagedStudentRequest,
)
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.notification_service import NotificationService
from backend.services.scope import ScopeResolver
from backend.utils.enums import Roles


class ManagedStudentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.links = ManagedStudentRepository(session)
        self.scopes = ScopeResolver(session)

    # -- reads ---------------------------------------------------------------

    async def list_links(
        self,
        params: PageParams,
        *,
        actor: User,
        manager_public_id: uuid.UUID | None = None,
        student_public_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[ManagedStudent], int]:
        manager_id = None
        if manager_public_id is not None:
            manager_id = (await self._load_user(manager_public_id)).id

        student_id = None
        if student_public_id is not None:
            student_id = (await self._load_user(student_public_id)).id

        return await self.links.search(
            params,
            unrestricted=ScopeResolver.is_unrestricted(actor),
            own_user_id=actor.id,
            manager_id=manager_id,
            student_id=student_id,
        )

    async def get(self, public_id: uuid.UUID, *, actor: User) -> ManagedStudent:
        link = await self.links.get_by_public_id_full(public_id)
        if link is None:
            raise NotFoundError("Manager link not found.")

        if not ScopeResolver.is_unrestricted(actor):
            if actor.id not in (link.manager_id, link.student_id):
                # 404 rather than 403: whether a particular person has a
                # manager on file is not a fact to confirm to a stranger.
                raise NotFoundError("Manager link not found.")
        return link

    # -- writes --------------------------------------------------------------

    async def create(
        self, payload: CreateManagedStudentRequest, *, actor: User
    ) -> ManagedStudent:
        manager = await self._load_user(payload.manager_id)
        student = await self._load_user(payload.student_id)

        if manager.id == student.id:
            raise ValidationError("A user cannot manage themselves.")

        self._assert_has_role(manager, Roles.CORPORATE_MANAGER)
        self._assert_has_role(student, Roles.STUDENT)

        if await self.links.get_link(manager_id=manager.id, student_id=student.id):
            raise ConflictError("This manager is already linked to this student.")

        if payload.is_primary:
            await self._clear_primary(student.id)

        link = ManagedStudent(
            manager_id=manager.id,
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
            entity_type="managed_student",
            entity_id=link.id,
            details={
                "manager": manager.username,
                "student": student.username,
                "relationship": payload.relationship_type,
            },
        )

        # Both sides, for the reason the guardian path gives: this link
        # decides who may read somebody's academic record, it is created by
        # an administrator, and neither party is in the room when it happens.
        # The student finding out is the point -- it is the only moment they
        # could object.
        notifications = NotificationService(self.session)
        await notifications.notify(
            user_id=student.id,
            type_=NotificationType.MANAGER_LINKED,
            title="A manager was linked to your account",
            body=f"{manager.full_name or manager.username} can now see your academic record.",
            meta={"link_id": str(link.public_id)},
        )
        await notifications.notify(
            user_id=manager.id,
            type_=NotificationType.MANAGER_LINKED,
            title="You were linked to a student",
            body=f"You can now see {student.full_name or student.username}'s academic record.",
            meta={"link_id": str(link.public_id)},
        )

        return await self.links.get_by_public_id_full(link.public_id)  # type: ignore[return-value]

    async def update(
        self, public_id: uuid.UUID, payload: UpdateManagedStudentRequest, *, actor: User
    ) -> ManagedStudent:
        link = await self.get(public_id, actor=actor)
        changes = payload.model_dump(exclude_unset=True)

        if changes.get("is_primary"):
            # One first point of contact per student; promoting this manager
            # demotes whichever one previously held it.
            await self._clear_primary(link.student_id, except_link_id=link.id)

        for field, value in changes.items():
            setattr(link, field, value)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="managed_student",
            entity_id=link.id,
            details={"fields": sorted(changes)},
        )
        return link

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        link = await self.links.get_by_public_id_full(public_id)
        if link is None:
            raise NotFoundError("Manager link not found.")

        manager_name = link.manager.username
        student_name = link.student.username
        entity_id = link.id

        # A hard delete, like a guardianship ending: keeping a record of who
        # used to be able to read somebody's results, indefinitely, is data
        # nobody asked us to hold. The audit entry below keeps the act.
        await self.session.delete(link)

        audit_service.record(
            self.session,
            action=AuditAction.PERMISSION_CHANGE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="managed_student",
            entity_id=entity_id,
            details={"unlinked_manager": manager_name, "student": student_name},
        )

    # -- helpers -------------------------------------------------------------

    async def _clear_primary(self, student_id: int, *, except_link_id: int | None = None) -> None:
        stmt = (
            update(ManagedStudent)
            .where(
                ManagedStudent.student_id == student_id,
                ManagedStudent.is_primary.is_(True),
            )
            .values(is_primary=False)
        )
        if except_link_id is not None:
            stmt = stmt.where(ManagedStudent.id != except_link_id)
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
