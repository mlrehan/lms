"""Corporate organizations, manager appointment and employee membership.

Two invariants are enforced here *and* by partial unique indexes in the
database (`uq_organization_managers_active_user`,
`uq_organization_memberships_active_user`): a user manages at most one
organization at a time, and belongs to at most one at a time. The service
checks so the caller gets a readable 409 rather than an IntegrityError; the
index is what makes the rule actually true under concurrency.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.models.identity.user import User
from backend.models.organization import (
    ManagedStudent,
    Organization,
    OrganizationManager,
    OrganizationMembership,
)
from backend.repositories.organization import (
    OrganizationManagerRepository,
    OrganizationMembershipRepository,
    OrganizationRepository,
)
from backend.schemas.base import PageParams
from backend.schemas.organization import (
    AddMemberRequest,
    AppointManagerRequest,
    OrganizationCreateRequest,
    OrganizationUpdateRequest,
)
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.scope import ScopeResolver
from backend.utils.enums import OrganizationMembershipStatus, Roles

# INVITED/ACTIVE/SUSPENDED are all "currently ours"; REMOVED is terminal.
# Re-hiring creates a fresh row rather than resurrecting the old one, which
# keeps the previous spell of employment intact -- the same shape as
# re-enrolling after DROPPED.
_ALLOWED_MEMBERSHIP_TRANSITIONS: dict[
    OrganizationMembershipStatus, frozenset[OrganizationMembershipStatus]
] = {
    OrganizationMembershipStatus.INVITED: frozenset(
        {OrganizationMembershipStatus.ACTIVE, OrganizationMembershipStatus.REMOVED}
    ),
    OrganizationMembershipStatus.ACTIVE: frozenset(
        {OrganizationMembershipStatus.SUSPENDED, OrganizationMembershipStatus.REMOVED}
    ),
    OrganizationMembershipStatus.SUSPENDED: frozenset(
        {OrganizationMembershipStatus.ACTIVE, OrganizationMembershipStatus.REMOVED}
    ),
    OrganizationMembershipStatus.REMOVED: frozenset(),
}


class OrganizationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.organizations = OrganizationRepository(session)
        self.managers = OrganizationManagerRepository(session)
        self.memberships = OrganizationMembershipRepository(session)
        self.scopes = ScopeResolver(session)

    # -- organizations -------------------------------------------------------

    async def list_organizations(
        self,
        params: PageParams,
        *,
        actor: User,
        query: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[Sequence[Organization], int]:
        """Row-scoped: a Corporate Manager sees only the organization they
        manage. Unlike the course catalogue, there is no browsing case here
        -- one company has no business enumerating the others."""
        scope = await self.scopes.visible_organization_ids(actor)
        return await self.organizations.search(
            params, scope=scope, query=query, is_active=is_active
        )

    async def get(self, public_id: uuid.UUID, *, actor: User) -> Organization:
        org = await self.organizations.get_by_public_id_active(public_id)
        if org is None:
            raise NotFoundError("Organization not found.")

        scope = await self.scopes.visible_organization_ids(actor)
        if not scope.allows(org.id):
            raise NotFoundError("Organization not found.")
        return org

    async def counts(self, org: Organization) -> tuple[int, int]:
        return (
            await self.organizations.count_active_managers(org.id),
            await self.organizations.count_current_members(org.id),
        )

    async def create(self, payload: OrganizationCreateRequest, *, actor: User) -> Organization:
        if await self.organizations.get_by_name(payload.name):
            raise ConflictError("An organization with that name already exists.")
        if payload.code and await self.organizations.get_by_code(payload.code):
            raise ConflictError("An organization with that code already exists.")

        org = Organization(
            name=payload.name,
            code=payload.code,
            contact_email=str(payload.contact_email).lower() if payload.contact_email else None,
            contact_phone=payload.contact_phone,
            is_active=True,
        )
        await self.organizations.add_and_flush(org)

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="organization",
            entity_id=org.id,
            details={"name": org.name},
        )
        return org

    async def update(
        self, public_id: uuid.UUID, payload: OrganizationUpdateRequest, *, actor: User
    ) -> Organization:
        org = await self.get(public_id, actor=actor)
        changes = payload.model_dump(exclude_unset=True)

        if changes.get("name") and changes["name"].lower() != (org.name or "").lower():
            if await self.organizations.get_by_name(changes["name"]):
                raise ConflictError("An organization with that name already exists.")
        if changes.get("code") and (changes["code"] or "").lower() != (org.code or "").lower():
            if await self.organizations.get_by_code(changes["code"]):
                raise ConflictError("An organization with that code already exists.")
        if "contact_email" in changes and changes["contact_email"]:
            changes["contact_email"] = str(changes["contact_email"]).lower()

        for field, value in changes.items():
            setattr(org, field, value)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="organization",
            entity_id=org.id,
            details={"fields": sorted(changes)},
        )
        return org

    async def soft_delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        org = await self.get(public_id, actor=actor)

        members = await self.organizations.count_current_members(org.id)
        if members:
            # Deleting an organization out from under its employees would
            # silently strip their sponsored enrollments' provenance. Remove
            # the members first, or deactivate the organization instead.
            raise ConflictError(
                "This organization still has current members.",
                details={"current_members": members},
            )

        org.is_deleted = True
        org.deleted_at = datetime.now(UTC)
        org.deleted_by = actor.id
        org.is_active = False

        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="organization",
            entity_id=org.id,
        )

    # -- managers ------------------------------------------------------------

    async def list_managers(
        self, public_id: uuid.UUID, *, actor: User, include_inactive: bool = False
    ) -> list[OrganizationManager]:
        org = await self.get(public_id, actor=actor)
        return await self.managers.list_for_organization(
            org.id, include_inactive=include_inactive
        )

    async def appoint_manager(
        self, public_id: uuid.UUID, payload: AppointManagerRequest, *, actor: User
    ) -> OrganizationManager:
        """Appointing a manager grants sight of every employee's records.

        Gated on `organization.appoint`, which Corporate Managers do **not**
        hold: a manager who could appoint co-managers could hand a colleague
        access to their whole roster without the institution's involvement.
        """
        org = await self.get(public_id, actor=actor)
        user = await self._load_user(payload.user_id)
        self._assert_has_role(user, Roles.CORPORATE_MANAGER)

        existing = await self.managers.get_active_for_user(user.id)
        if existing is not None:
            if existing.organization_id == org.id:
                raise ConflictError("This user already manages this organization.")
            raise ConflictError(
                "This user already manages another organization.",
                details={"current_organization": existing.organization.name},
            )

        appointment = OrganizationManager(
            organization_id=org.id,
            user_id=user.id,
            title=payload.title,
            is_active=True,
        )
        await self.managers.add_and_flush(appointment)

        audit_service.record(
            self.session,
            action=AuditAction.PERMISSION_CHANGE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="organization",
            entity_id=org.id,
            details={"appointed_manager": user.username, "organization": org.name},
        )
        return await self.managers.get_by_public_id_full(appointment.public_id)  # type: ignore[return-value]

    async def revoke_manager(
        self, public_id: uuid.UUID, manager_public_id: uuid.UUID, *, actor: User
    ) -> None:
        org = await self.get(public_id, actor=actor)
        appointment = await self.managers.get_by_public_id_full(manager_public_id)

        if appointment is None or appointment.organization_id != org.id:
            # Scoped to this organization, so an appointment id belonging to
            # another company answers 404 rather than confirming it exists.
            raise NotFoundError("Manager appointment not found.")

        if not appointment.is_active:
            raise ConflictError("This appointment has already been revoked.")

        # Deactivated rather than deleted: the appointment is a record of who
        # had access to these employees' data and when, which is exactly the
        # thing an audit would ask about.
        appointment.is_active = False

        # The roster goes with it, and for the same reason the membership
        # case above does: `is_active` used to be read on every resolution,
        # so revoking an appointment ended that manager's access at once.
        # The links are what grant it now, so the links are what have to go.
        # Only the students of *this* company -- a manager who also looks
        # after someone elsewhere keeps that.
        unlinked = await self._unlink_manager_from_org_students(
            manager_id=appointment.user_id, organization_id=org.id
        )

        audit_service.record(
            self.session,
            action=AuditAction.PERMISSION_CHANGE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="organization",
            entity_id=org.id,
            details={
                "revoked_manager": appointment.user.username,
                "manager_links_removed": unlinked,
            },
        )

    # -- memberships ---------------------------------------------------------

    async def list_members(
        self,
        params: PageParams,
        *,
        actor: User,
        organization_public_id: uuid.UUID | None = None,
        status: OrganizationMembershipStatus | None = None,
    ) -> tuple[Sequence[OrganizationMembership], int]:
        organization_id = None
        if organization_public_id is not None:
            org = await self.get(organization_public_id, actor=actor)
            organization_id = org.id

        scope = await self.scopes.visible_organization_ids(actor)
        return await self.memberships.search(
            params, scope=scope, organization_id=organization_id, status=status
        )

    async def add_member(
        self, public_id: uuid.UUID, payload: AddMemberRequest, *, actor: User
    ) -> OrganizationMembership:
        org = await self.get(public_id, actor=actor)

        if not org.is_active:
            raise ConflictError("This organization is not active.")

        user = await self._load_user(payload.user_id)
        self._assert_has_role(user, Roles.STUDENT)

        current = await self.memberships.get_current_for_user(user.id)
        if current is not None:
            if current.organization_id == org.id:
                raise ConflictError("This user is already a member of this organization.")
            raise ConflictError(
                "This user already belongs to another organization.",
                details={"current_organization": current.organization.name},
            )

        status = (
            OrganizationMembershipStatus.ACTIVE
            if payload.activate_immediately
            else OrganizationMembershipStatus.INVITED
        )
        membership = OrganizationMembership(
            organization_id=org.id,
            user_id=user.id,
            employee_code=payload.employee_code,
            department=payload.department,
            status=status,
            invited_by=actor.id,
            joined_at=datetime.now(UTC) if payload.activate_immediately else None,
        )
        await self.memberships.add_and_flush(membership)

        # A manager who brings somebody in gets that one person, and nobody
        # else.
        #
        # Before the roster became a direct link, adding an employee made
        # them visible to *every* manager of the company, immediately,
        # because visibility was derived from the membership row. Dropping
        # that entirely would leave a manager inviting an employee they then
        # cannot see until an administrator intervenes -- a dead end in a
        # workflow `organization.invite` exists to support.
        #
        # So the inviting manager is linked, and only them. The difference
        # from the old behaviour is the one the change is about: a colleague
        # managing the same company still sees nothing until somebody says
        # so. An administrator adding a member links nobody, because they are
        # not the person who will be looking after them.
        linked_to_actor = False
        if await self._is_active_manager_of(user_id=actor.id, organization_id=org.id):
            self.session.add(
                ManagedStudent(manager_id=actor.id, student_id=user.id)
            )
            await self.session.flush()
            linked_to_actor = True

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="organization_membership",
            entity_id=membership.id,
            details={
                "organization": org.name,
                "employee": user.username,
                "status": status.value,
                "assigned_to_inviter": linked_to_actor,
            },
        )
        return await self.memberships.get_by_public_id_full(membership.public_id)  # type: ignore[return-value]

    async def set_member_status(
        self,
        membership_public_id: uuid.UUID,
        new_status: OrganizationMembershipStatus,
        *,
        organization_public_id: uuid.UUID,
        actor: User,
    ) -> OrganizationMembership:
        # Resolves (and scope-checks) the organization first, so a membership
        # id from another company answers 404 rather than being acted on
        # because its own id happened to be known.
        org = await self.get(organization_public_id, actor=actor)

        membership = await self.memberships.get_by_public_id_full(membership_public_id)
        if membership is None or membership.organization_id != org.id:
            raise NotFoundError("Membership not found.")

        current = membership.status
        if new_status == current:
            return membership

        allowed = _ALLOWED_MEMBERSHIP_TRANSITIONS.get(current, frozenset())
        if new_status not in allowed:
            raise ConflictError(
                f"A {current.value} membership cannot become {new_status.value}.",
                details={
                    "current_status": current.value,
                    "allowed_transitions": sorted(s.value for s in allowed),
                },
            )

        membership.status = new_status
        if new_status is OrganizationMembershipStatus.ACTIVE and membership.joined_at is None:
            membership.joined_at = datetime.now(UTC)

        unlinked = 0
        if new_status is OrganizationMembershipStatus.REMOVED:
            # Leaving the company ends the managers' access, and it has to be
            # done explicitly now.
            #
            # It used to happen by itself: visibility was derived from this
            # row, so a REMOVED status stopped resolving. With the roster held
            # in `manager_students`, nothing would notice -- a former employee
            # would keep showing up on their old manager's dashboard, with
            # their current coursework, indefinitely. That is the single
            # safety property most easily lost in a change like this one, so
            # it is enforced here and asserted by a test.
            #
            # Scoped to *this organization's* managers: a link made by another
            # company's manager was never justified by this employment and is
            # not theirs to lose.
            unlinked = await self._unlink_from_org_managers(
                student_id=membership.user_id, organization_id=org.id
            )

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="organization_membership",
            entity_id=membership.id,
            details={
                "status": f"{current.value} -> {new_status.value}",
                **({"manager_links_removed": unlinked} if unlinked else {}),
            },
        )
        return membership

    # -- helpers -------------------------------------------------------------

    async def _is_active_manager_of(self, *, user_id: int, organization_id: int) -> bool:
        stmt = select(OrganizationManager.id).where(
            OrganizationManager.user_id == user_id,
            OrganizationManager.organization_id == organization_id,
            OrganizationManager.is_active.is_(True),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def _unlink_from_org_managers(self, *, student_id: int, organization_id: int) -> int:
        """Drop this student's links to every manager of this organization.

        Returns how many went, for the audit entry -- "the membership was
        removed" and "and four managers lost sight of them" are different
        facts, and the second is the one an access review asks about.
        """
        managers = select(OrganizationManager.user_id).where(
            OrganizationManager.organization_id == organization_id
        )
        result = await self.session.execute(
            delete(ManagedStudent).where(
                ManagedStudent.student_id == student_id,
                ManagedStudent.manager_id.in_(managers),
            )
        )
        return int(result.rowcount or 0)

    async def _unlink_manager_from_org_students(
        self, *, manager_id: int, organization_id: int
    ) -> int:
        """Drop this manager's links to every member of this organization."""
        members = select(OrganizationMembership.user_id).where(
            OrganizationMembership.organization_id == organization_id
        )
        result = await self.session.execute(
            delete(ManagedStudent).where(
                ManagedStudent.manager_id == manager_id,
                ManagedStudent.student_id.in_(members),
            )
        )
        return int(result.rowcount or 0)

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
