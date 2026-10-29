"""Phase 5: what the guarded SQL change refuses before any database is touched.

The dry run, the row ceiling at execution and the read-only role are proven
against Postgres in tests/integration/test_ai_sql_change.py.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from backend.ai.sql_access import WITHHELD_COLUMNS, WITHHELD_TABLES, WRITE_PROTECTED_TABLES
from backend.ai.tools.registry import BOUND_PREFIX, ToolExecutionContext, get_tool_registry
from backend.ai.tools.sql_change_tool import handle_sql_change, validate_sql_change
from backend.core.errors import AuthorizationError, ConflictError, ValidationError
from backend.core.permissions import ROLE_PERMISSIONS
from backend.models.identity.permission import Permission
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.utils.enums import Roles


def make_user(role_name: str) -> User:
    role = Role(id=1, name=role_name)
    role.permissions = [Permission(id=i, name=n) for i, n in enumerate(sorted(ROLE_PERMISSIONS[role_name]), 1)]
    user = User(id=99, public_id=uuid.uuid4(), username="u@x.test", email="u@x.test")
    user.roles = [role]
    return user


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE courses SET title = lower(title) WHERE id = 1",
        "update courses set price = coalesce(price, 0) + 1 where code in (select code from courses where id < 5);",
        "INSERT INTO tags (name) VALUES ('new tag')",
        "DELETE FROM tags WHERE name LIKE 'old-%'",
        "UPDATE courses SET updated_at = CURRENT_TIMESTAMP WHERE id = 3",
        "UPDATE users SET first_name = 'Ana' WHERE id = 7",
    ],
)
def test_ordinary_changes_pass(sql):
    change = validate_sql_change(sql)
    assert change.kind in {"INSERT", "UPDATE", "DELETE"}
    assert len(change.digest) == 64


@pytest.mark.parametrize(
    "sql, reason",
    [
        ("", "No SQL"),
        ("SELECT * FROM courses", "Only INSERT, UPDATE or DELETE"),
        ("TRUNCATE tags", "Only INSERT, UPDATE or DELETE"),
        ("DROP TABLE tags", "Only INSERT, UPDATE or DELETE"),
        ("COPY tags TO '/tmp/x'", "Only INSERT, UPDATE or DELETE"),
        ("UPDATE tags SET name = 'x' WHERE id = 1; DELETE FROM tags WHERE id = 2", "Exactly one statement"),
        ("UPDATE courses SET title = 'x'", "must have a WHERE"),
        ("DELETE FROM tags", "must have a WHERE"),
        ("WITH gone AS (DELETE FROM tags WHERE id = 1 RETURNING *) INSERT INTO tags (name) SELECT name FROM gone",
         "WITH clauses"),
        ("DELETE FROM tags WHERE id = 1 RETURNING name", "RETURNING"),
        ("DELETE FROM audit_logs WHERE id = 1", "can never be changed"),
        ("UPDATE role_permissions SET role_id = 1 WHERE role_id = 2", "can never be changed"),
        ("INSERT INTO user_roles (user_id, role_id) VALUES (5, 1)", "can never be changed"),
        ("INSERT INTO users (username) VALUES ('x')", "Users screen"),
        ("DELETE FROM users WHERE id = 5", "Users screen"),
        ("UPDATE users SET hashed_password = 'x' WHERE id = 5", "hashed_password"),
        # Acts with consequences a service carries out have dedicated tools.
        ("UPDATE users SET status = 'ACTIVE' WHERE id = 5", "manage_user"),
        ("UPDATE users SET locked_until = NULL WHERE id = 5", "unlock_account"),
        ("INSERT INTO enrollments (batch_id, student_id) VALUES (1, 2)", "manage_enrollment"),
        ("UPDATE enrollments SET status = 'DROPPED' WHERE id = 1", "manage_enrollment"),
        ("UPDATE system_settings SET value = '1' WHERE key = 'x'", "update_system_setting"),
        ("UPDATE courses SET title = (SELECT token FROM tokens LIMIT 1) WHERE id = 1", "tokens"),
        ("UPDATE courses SET title = (SELECT hashed_password FROM users LIMIT 1) WHERE id = 1", "hashed_password"),
        ("UPDATE courses SET title = pg_read_file('/etc/passwd') WHERE id = 1", "pg_read_file"),
        ("UPDATE courses SET title = 'x' WHERE pg_terminate_backend(1)", "pg_terminate_backend"),
        ("UPDATE other_schema.courses SET title = 'x' WHERE id = 1", "public schema"),
        ("UPDATE courses SET WHERE", "could not be parsed"),
    ],
)
def test_dangerous_or_ambiguous_changes_are_refused(sql, reason):
    with pytest.raises(ValidationError, match=reason):
        validate_sql_change(sql)


def test_every_withheld_table_and_column_is_refused():
    for table in WITHHELD_TABLES:
        with pytest.raises(ValidationError):
            validate_sql_change(f"UPDATE courses SET title = 'x' WHERE id IN (SELECT 1 FROM {table})")
    for table, column in WITHHELD_COLUMNS:
        with pytest.raises(ValidationError):
            validate_sql_change(f"UPDATE courses SET title = 'x' WHERE id IN (SELECT {column} FROM {table})")
    assert WITHHELD_TABLES <= WRITE_PROTECTED_TABLES


@pytest.mark.parametrize("role", [Roles.ADMIN.value, Roles.TUTOR.value, Roles.STUDENT.value])
def test_only_the_super_admin_is_offered_or_allowed_the_tool(role):
    user = make_user(role)
    assert "execute_sql_change" not in {t.name for t in get_tool_registry().list_tools_for_caller(user)}
    with pytest.raises(AuthorizationError):
        asyncio.run(handle_sql_change({"sql": "DELETE FROM tags WHERE id = 1"}, ToolExecutionContext(user=user, session=AsyncMock())))


def test_the_model_cannot_supply_the_typed_phrase_or_the_bound_count():
    """The phrase arrives only via the confirm endpoint (context.confirmation_text)."""
    sql = "DELETE FROM tags WHERE id = 1"
    change = validate_sql_change(sql)
    args = {
        "sql": sql,
        "confirmation_text": "DELETE 1 ROWS IN tags",  # model-written: ignored
        f"{BOUND_PREFIX}digest": change.digest,
        f"{BOUND_PREFIX}rows": 1,
        f"{BOUND_PREFIX}phrase": "DELETE 1 ROWS IN tags",
    }
    ctx = ToolExecutionContext(user=make_user(Roles.SUPER_ADMIN.value), session=AsyncMock())
    with patch("backend.ai.tools.sql_change_tool._affected_rows", new_callable=AsyncMock) as run:
        with pytest.raises(ConflictError, match="type exactly"):
            asyncio.run(handle_sql_change(args, ctx))
        run.assert_not_awaited()


def test_a_statement_altered_after_preview_is_refused():
    previewed = validate_sql_change("DELETE FROM tags WHERE id = 1")
    ctx = ToolExecutionContext(
        user=make_user(Roles.SUPER_ADMIN.value), session=AsyncMock(), confirmation_text="DELETE 1 ROWS IN tags"
    )
    with patch("backend.ai.tools.sql_change_tool._affected_rows", new_callable=AsyncMock) as run:
        with pytest.raises(ConflictError, match="no longer matches"):
            asyncio.run(handle_sql_change(
                {
                    "sql": "DELETE FROM tags WHERE id > 0",
                    f"{BOUND_PREFIX}digest": previewed.digest,
                    f"{BOUND_PREFIX}rows": 1,
                    f"{BOUND_PREFIX}phrase": "DELETE 1 ROWS IN tags",
                },
                ctx,
            ))
        run.assert_not_awaited()


def test_the_tool_is_critical_and_requires_confirmation():
    tool = get_tool_registry().get("execute_sql_change")
    assert tool.policy.requires_confirmation
    assert tool.policy.allowed_roles == (Roles.SUPER_ADMIN.value,)
