"""The Super Admin's guarded SQL change, and SQL reads through the read-only role,
against a real database.

What only a real database proves: that the dry run measures and changes
nothing, that the confirmed statement affects exactly the rows previewed, that
a change in the data between preview and confirmation is caught and rolled
back, and that the read-only role -- not a regex -- is what keeps a password
hash out of a query result.

Rows are created under a per-run tag in `tags` and removed in teardown. Each
applied change leaves an audit row; the audit trail is append-only by design,
so those remain.
"""

from __future__ import annotations

import asyncio
import random
import selectors
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import func, select, text

from backend.ai.sql_access import readonly_configured
from backend.ai.tools.registry import ToolExecutionContext, get_tool_registry
from backend.ai.workflows.confirmation_service import ConfirmationExecutionService
from backend.core.config import get_settings
from backend.core.errors import ConflictError, ValidationError
from backend.core.permissions import ROLE_PERMISSIONS
from backend.db.manager import DatabaseManager
from backend.models.administration import Tag
from backend.models.audit import AuditLog
from backend.models.identity.permission import Permission
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.utils.enums import Roles

pytestmark = pytest.mark.skipif(not readonly_configured(), reason="AI read-only role not configured")


def _super_admin() -> User:
    role = Role(id=1, name=Roles.SUPER_ADMIN.value)
    role.permissions = [
        Permission(id=i, name=n) for i, n in enumerate(sorted(ROLE_PERMISSIONS[Roles.SUPER_ADMIN.value]), 1)
    ]
    # Never persisted: tickets are in memory here and audit rows carry no FK.
    user = User(id=random.randint(10_000_000, 20_000_000), public_id=uuid.uuid4(),
                username="sqltest@t.test", email="sqltest@t.test", first_name="Sql", last_name="Test")
    user.roles = [role]
    return user


@pytest.fixture()
def env():  # noqa: ANN201
    tag = f"sqlt{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="ai-sql-change-tests")

    async def seed() -> None:
        async with db.session_factory.begin() as session:
            for i in range(3):
                session.add(Tag(name=f"{tag}-{i}"))

    loop.run_until_complete(seed())

    async def count() -> int:
        async with db.session_factory() as session:
            return int((await session.execute(
                select(func.count()).select_from(Tag).where(Tag.name.like(f"{tag}-%"))
            )).scalar_one())

    ns = type("Env", (), dict(
        tag=tag, db=db, loop=loop, run=staticmethod(loop.run_until_complete),
        count=staticmethod(lambda: loop.run_until_complete(count())),
        sql=f"DELETE FROM tags WHERE name LIKE '{tag}-%'",
    ))
    try:
        with patch("backend.ai.tools.sql_change_tool._backup_problems", return_value=[]):
            yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as session:
                await session.execute(text("DELETE FROM tags WHERE name LIKE :t"), {"t": f"{tag}-%"})

        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


async def _stage(env, user, sql):  # noqa: ANN001, ANN202
    async with env.db.session_factory() as session:
        staged = await get_tool_registry().execute_tool(
            name="execute_sql_change", arguments={"sql": sql}, context=ToolExecutionContext(user=user, session=session)
        )
        await session.commit()
        return staged


async def _confirm(env, user, ticket_id, typed):  # noqa: ANN001, ANN202
    async with env.db.session_factory() as session:
        result = await ConfirmationExecutionService(session).execute_ticket(
            ticket_id=ticket_id, actor=user, confirmation_text=typed
        )
        await session.commit()
        return result


def test_the_preview_measures_the_change_and_changes_nothing(env):  # noqa: ANN001
    staged = env.run(_stage(env, _super_admin(), env.sql))
    assert staged["status"] == "REQUIRES_CONFIRMATION"
    assert staged["affected_records_count"] == 3
    assert staged["typed_confirmation"] == "DELETE 3 ROWS IN tags"
    assert env.count() == 3


def test_without_the_typed_phrase_nothing_happens(env):  # noqa: ANN001
    user = _super_admin()
    for typed in (None, "yes", "delete 3 rows in tags"):
        staged = env.run(_stage(env, user, env.sql))
        with pytest.raises(ConflictError, match="type exactly"):
            env.run(_confirm(env, user, staged["ticket_id"], typed))
    assert env.count() == 3


def test_with_the_phrase_exactly_the_previewed_rows_change_and_are_audited(env):  # noqa: ANN001
    user = _super_admin()
    staged = env.run(_stage(env, user, env.sql))
    result = env.run(_confirm(env, user, staged["ticket_id"], "DELETE 3 ROWS IN tags"))
    assert result["rows"] == 3
    assert env.count() == 0

    async def audit():  # noqa: ANN202
        async with env.db.session_factory() as session:
            rows = (await session.execute(
                select(AuditLog).where(AuditLog.actor_user_id == user.id).order_by(AuditLog.id.desc())
            )).scalars().all()
            return rows

    rows = env.run(audit())
    assert rows and rows[0].details["operation"] == "AI_SQL_CHANGE"
    assert rows[0].details["rows"] == 3
    assert len(rows[0].details["sha256"]) == 64


def test_data_that_changed_since_the_preview_is_rolled_back(env):  # noqa: ANN001
    user = _super_admin()
    staged = env.run(_stage(env, user, env.sql))

    async def another_matching_row() -> None:
        async with env.db.session_factory.begin() as session:
            session.add(Tag(name=f"{env.tag}-late"))

    env.run(another_matching_row())
    with pytest.raises(ConflictError, match="changed since the preview"):
        env.run(_confirm(env, user, staged["ticket_id"], "DELETE 3 ROWS IN tags"))
    assert env.count() == 4


def test_a_change_touching_nothing_or_too_much_is_refused_before_confirmation(env):  # noqa: ANN001
    user = _super_admin()
    with pytest.raises(ConflictError, match="no rows"):
        env.run(_stage(env, user, "DELETE FROM tags WHERE name = 'no-such-tag-anywhere'"))
    with patch("backend.ai.tools.sql_change_tool.get_ai_settings") as settings:
        settings.return_value.sql_max_write_rows = 2
        with pytest.raises(ConflictError, match="at most 2"):
            env.run(_stage(env, user, env.sql))
    assert env.count() == 3


def test_without_a_recent_backup_the_change_is_refused(env, tmp_path):  # noqa: ANN001
    """The fixture stubs the backup check out; this test puts the real one back
    and points it at a dump that does not exist."""
    from backend.ai.tools import sql_change_tool

    fake = type("S", (), {"app": type("A", (), {
        "system_reset_backup_path": tmp_path / "missing.dump",
        "system_reset_backup_max_age_hours": 24,
    })()})()
    with patch("backend.ai.tools.sql_change_tool.get_settings", return_value=fake), \
         patch("backend.ai.tools.sql_change_tool._backup_problems", new=_REAL_BACKUP_PROBLEMS):
        with pytest.raises(ConflictError, match="not found"):
            env.run(_stage(env, _super_admin(), env.sql))
    assert env.count() == 3
    assert sql_change_tool  # imported for the patch target's module


from backend.ai.tools.sql_change_tool import _backup_problems as _REAL_BACKUP_PROBLEMS  # noqa: E402


def test_reads_go_through_the_read_only_role_not_a_regex(env):  # noqa: ANN001
    """The validator lets the Super Admin name any column; the role still refuses."""
    user = _super_admin()

    async def query(sql):  # noqa: ANN001, ANN202
        async with env.db.session_factory() as session:
            return await get_tool_registry().execute_tool(
                name="execute_database_query", arguments={"query": sql},
                context=ToolExecutionContext(user=user, session=session),
            )

    ok = env.run(query(f"SELECT count(*) AS n FROM tags WHERE name LIKE '{env.tag}-%'"))
    assert ok["success"] is True and ok["rows"][0]["n"] == 3

    refused = env.run(query("SELECT hashed_password FROM users LIMIT 1"))
    assert refused["success"] is False
    assert "permission denied" in refused["error"]
