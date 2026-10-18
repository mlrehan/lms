"""Unit tests for single, bulk, and all-resource purging logic.

Ensures that:
1. Super Admin can delete any resource permanently at a time (even without soft-deleting first).
2. Regular users cannot purge active resources directly (must be soft-deleted first and requires MANAGE).
3. Super Admin can delete all resources permanently at a time, or all selected resources.
4. Non-super admin cannot call purge_all with in_bin_only=False.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.errors import AuthorizationError, ConflictError, NotFoundError
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.resource import Resource, ResourceVersion
from backend.services.resource_service import ResourceService
from backend.utils.enums import ResourcePermissionLevel, ResourceScopeType, ResourceType, Roles



def make_user(*, is_super: bool = False, user_id: int = 1) -> User:
    u = MagicMock(spec=User)
    u.id = user_id
    u.email = "admin@example.com" if is_super else "tutor@example.com"
    u.username = "admin" if is_super else "tutor"
    u.first_name = "Admin" if is_super else "Jane"
    u.last_name = "User" if is_super else "Doe"
    u.is_super_admin = is_super
    if is_super:
        super_role = MagicMock(spec=Role)
        super_role.name = Roles.SUPER_ADMIN.value
        u.roles = [super_role]
    else:
        tutor_role = MagicMock(spec=Role)
        tutor_role.name = Roles.TUTOR.value
        u.roles = [tutor_role]
    return u



def make_resource(*, is_deleted: bool = False, public_id: uuid.UUID | None = None) -> Resource:
    r = MagicMock(spec=Resource)
    r.id = 10
    r.public_id = public_id or uuid.uuid4()
    r.name = "syllabus.pdf"
    r.path = "resources/syllabus.pdf"
    r.mime_type = "application/pdf"
    r.resource_type = ResourceType.document
    r.is_deleted = is_deleted
    r.course_id = 1
    r.batch_id = None
    r.course = None
    r.batch = None
    r.uploader = None
    v = MagicMock(spec=ResourceVersion)
    v.path = "resources/syllabus.pdf"
    r.versions = [v]
    return r



@pytest.mark.asyncio
async def test_super_admin_can_purge_live_resource_directly() -> None:
    session = AsyncMock()
    service = ResourceService(session)

    res = make_resource(is_deleted=False)
    service.resources.get_by_public_id_full = AsyncMock(return_value=res)
    service._resource_reachable = AsyncMock(return_value=True)
    service.require_level = AsyncMock()
    service.resources.versions_for = AsyncMock(return_value=res.versions)
    service.storage.delete = AsyncMock()

    super_admin = make_user(is_super=True)
    await service.purge(res.public_id, actor=super_admin)

    session.delete.assert_called_once_with(res)
    service.storage.delete.assert_called_once_with(res.versions[0].path)


@pytest.mark.asyncio
async def test_regular_user_cannot_purge_live_resource_without_force() -> None:
    session = AsyncMock()
    service = ResourceService(session)

    res = make_resource(is_deleted=False)
    service.resources.get_by_public_id_full = AsyncMock(return_value=res)
    service._resource_reachable = AsyncMock(return_value=True)
    service.require_level = AsyncMock()

    regular_user = make_user(is_super=False)
    with pytest.raises(ConflictError, match="Delete the resource before purging it"):
        await service.purge(res.public_id, actor=regular_user)


@pytest.mark.asyncio
async def test_regular_user_can_purge_soft_deleted_resource() -> None:
    session = AsyncMock()
    service = ResourceService(session)

    res = make_resource(is_deleted=True)
    service.resources.get_by_public_id_full = AsyncMock(return_value=res)
    service._resource_reachable = AsyncMock(return_value=True)
    service.require_level = AsyncMock()
    service.resources.versions_for = AsyncMock(return_value=res.versions)
    service.storage.delete = AsyncMock()

    regular_user = make_user(is_super=False)
    await service.purge(res.public_id, actor=regular_user)

    session.delete.assert_called_once_with(res)


@pytest.mark.asyncio
async def test_purge_many_deletes_multiple_resources_at_once() -> None:
    session = AsyncMock()
    service = ResourceService(session)

    res1 = make_resource(is_deleted=False, public_id=uuid.uuid4())
    res2 = make_resource(is_deleted=True, public_id=uuid.uuid4())

    async def get_by_pid(pid: uuid.UUID) -> Resource | None:
        if pid == res1.public_id:
            return res1
        if pid == res2.public_id:
            return res2
        return None

    service.resources.get_by_public_id_full = AsyncMock(side_effect=get_by_pid)
    service._resource_reachable = AsyncMock(return_value=True)
    service.effective_level = AsyncMock(return_value=ResourcePermissionLevel.MANAGE)
    service.resources.versions_for = AsyncMock(return_value=[])
    service.storage.delete = AsyncMock()

    super_admin = make_user(is_super=True)
    count = await service.purge_many([res1.public_id, res2.public_id], actor=super_admin)

    assert count == 2
    assert session.delete.call_count == 2


@pytest.mark.asyncio
async def test_purge_all_non_bin_rejected_for_non_super_admin() -> None:
    session = AsyncMock()
    service = ResourceService(session)

    regular_user = make_user(is_super=False)
    with pytest.raises(AuthorizationError, match="Only super administrators"):
        await service.purge_all(actor=regular_user, in_bin_only=False)


@pytest.mark.asyncio
async def test_purge_all_permitted_for_super_admin() -> None:
    session = AsyncMock()
    service = ResourceService(session)

    res1 = make_resource(is_deleted=False)
    res2 = make_resource(is_deleted=True)

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [res1, res2]
    session.execute.return_value = result_mock

    service.resources.versions_for = AsyncMock(return_value=[])
    service.storage.delete = AsyncMock()

    super_admin = make_user(is_super=True)
    count = await service.purge_all(actor=super_admin, in_bin_only=False)

    assert count == 2
    assert session.delete.call_count == 2


@pytest.mark.asyncio
async def test_soft_delete_many_and_restore_many() -> None:
    session = AsyncMock()
    service = ResourceService(session)

    res1 = make_resource(is_deleted=False, public_id=uuid.uuid4())
    res2 = make_resource(is_deleted=False, public_id=uuid.uuid4())

    async def get_res(pid: uuid.UUID, actor: User) -> Resource:
        return res1 if pid == res1.public_id else res2

    async def get_by_pid_full(pid: uuid.UUID) -> Resource:
        return res1 if pid == res1.public_id else res2

    service.get = AsyncMock(side_effect=get_res)
    service.resources.get_by_public_id_full = AsyncMock(side_effect=get_by_pid_full)
    service._resource_reachable = AsyncMock(return_value=True)
    service.effective_level = AsyncMock(return_value=ResourcePermissionLevel.MANAGE)

    user = make_user(is_super=False)

    # Soft delete many
    deleted_count = await service.soft_delete_many([res1.public_id, res2.public_id], actor=user)
    assert deleted_count == 2
    assert res1.is_deleted is True
    assert res2.is_deleted is True

    # Restore many
    restored_count = await service.restore_many([res1.public_id, res2.public_id], actor=user)
    assert restored_count == 2
    assert res1.is_deleted is False
    assert res2.is_deleted is False


@pytest.mark.asyncio
async def test_get_deletion_impact_and_superadmin_purge_shared_resource() -> None:
    session = AsyncMock()
    service = ResourceService(session)

    res = make_resource(is_deleted=False)
    service.resources.get_by_public_id_full = AsyncMock(return_value=res)
    service._resource_reachable = AsyncMock(return_value=True)
    service.require_level = AsyncMock()
    service.resources.versions_for = AsyncMock(return_value=res.versions)
    service.storage.delete = AsyncMock()

    # Mock share
    shared_user = make_user(is_super=False, user_id=99)
    shared_user.public_id = uuid.uuid4()
    mock_share = MagicMock()
    mock_share.shared_with_user = shared_user
    mock_share.shared_by_user = make_user(is_super=True)
    mock_share.level = ResourcePermissionLevel.DOWNLOAD
    mock_share.created_at = res.created_at
    service.shares.for_resource = AsyncMock(return_value=[mock_share])

    # Mock permission grant
    mock_perm = MagicMock()
    mock_perm.scope_type = ResourceScopeType.COURSE
    mock_perm.scope_id = 1
    mock_perm.level = ResourcePermissionLevel.VIEW
    mock_perm.created_at = res.created_at
    service.permissions.for_resource = AsyncMock(return_value=[mock_perm])

    admin = make_user(is_super=True)

    impact = await service.get_deletion_impact([res.public_id], actor=admin)
    assert impact.total_resources == 1
    assert impact.total_direct_shares == 1
    assert impact.total_grants == 1
    assert impact.total_affected_users == 1
    assert impact.resources[0].direct_shares[0].user_id == shared_user.public_id

    # Test that superadmin can purge even when shared
    await service.purge(res.public_id, actor=admin)
    session.delete.assert_called_once_with(res)
    assert session.execute.call_count >= 2  # perms and shares delete statements


