"""Unit and Integration tests for Direct Database Query & Real-Time Grounding Tools."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from backend.ai.tools.database_tools import (
    clean_sql,
    handle_execute_database_query,
    handle_inspect_database_schema,
    validate_sql_safety,
)
from backend.ai.tools.registry import ToolExecutionContext
from backend.models.identity.user import User
from backend.utils.enums import Roles


def make_test_user(*, user_id: int = 1, role_name: str = Roles.SUPER_ADMIN.value) -> User:
    """Helper to mock an authenticated LMS user with specified role."""
    user = MagicMock(spec=User)
    user.id = user_id
    user.public_id = "00000000-0000-0000-0000-000000000001"
    user.username = "test_user"
    user.email = "test@lms.example.com"
    user.first_name = "Test"
    user.last_name = "User"
    user.timezone = "UTC"

    role = MagicMock()
    role.name = role_name
    role.permissions = []
    user.roles = [role]
    return user


# =============================================================================
# 1. SQL SAFETY VALIDATOR TESTS
# =============================================================================


def test_clean_sql_strips_comments_and_whitespace():
    """clean_sql must strip both single-line and multi-line comments."""
    raw = """
    -- Count all active tutors
    SELECT count(*) 
    /* multi line
       comment */
    FROM users;
    """
    cleaned = clean_sql(raw)
    assert "-- Count" not in cleaned
    assert "/* multi line" not in cleaned
    assert "SELECT count(*)" in cleaned
    assert "FROM users;" in cleaned


def test_validate_sql_accepts_valid_select_and_cte():
    """Standard SELECT and WITH CTE queries must be accepted."""
    superadmin_roles = {Roles.SUPER_ADMIN.value}

    # Standard SELECT
    ok, err, final_sql = validate_sql_safety(
        "SELECT id, username FROM users WHERE status = 'ACTIVE'",
        superadmin_roles,
    )
    assert ok is True
    assert err is None
    assert "LIMIT 100" in final_sql

    # WITH CTE
    ok_cte, err_cte, final_cte = validate_sql_safety(
        "WITH tutor_list AS (SELECT id FROM users) SELECT count(*) FROM tutor_list",
        superadmin_roles,
    )
    assert ok_cte is True
    assert err_cte is None


def test_validate_sql_blocks_forbidden_mutations_and_ddl():
    """Destructive keywords like DROP, DELETE, UPDATE, INSERT, ALTER must be strictly rejected."""
    roles = {Roles.SUPER_ADMIN.value}

    forbidden = [
        "DROP TABLE users",
        "DELETE FROM users WHERE id = 1",
        "UPDATE users SET status = 'DELETED'",
        "INSERT INTO users (username) VALUES ('hacker')",
        "ALTER TABLE courses ADD COLUMN secret text",
        "TRUNCATE audit_logs",
        "GRANT ALL PRIVILEGES ON ALL TABLES TO public",
        "EXEC sp_executesql 'SELECT 1'",
    ]

    for sql in forbidden:
        ok, err, _ = validate_sql_safety(sql, roles)
        assert ok is False, f"Expected {sql} to be blocked"
        assert "strictly prohibited" in err or "Only read-only" in err


def test_validate_sql_blocks_multi_statements():
    """Multiple statements separated by semicolons must be rejected."""
    roles = {Roles.SUPER_ADMIN.value}
    malicious = "SELECT 1; DROP TABLE users; SELECT 2"
    ok, err, _ = validate_sql_safety(malicious, roles)
    assert ok is False
    assert "Multiple SQL statements are strictly forbidden" in err


def test_validate_sql_blocks_sensitive_columns_for_non_superadmin():
    """Non-SuperAdmins must never query password or credential columns."""
    tutor_roles = {Roles.TUTOR.value}
    ok, err, _ = validate_sql_safety(
        "SELECT id, username, hashed_password FROM users",
        tutor_roles,
    )
    assert ok is False
    assert "sensitive credential column" in err


def test_validate_sql_blocks_admin_tables_for_students():
    """Students and Guardians must not access administrative tables."""
    student_roles = {Roles.STUDENT.value}
    ok, err, _ = validate_sql_safety(
        "SELECT * FROM audit_logs",
        student_roles,
    )
    assert ok is False
    assert "Access to operational table" in err or "restricted" in err


# =============================================================================
# 2. SCHEMA INSPECTION HANDLER TESTS
# =============================================================================


def make_mock_session():
    """Create a mock AsyncSession that properly supports `async with session.begin_nested()`."""
    session = AsyncMock()
    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=None)
    session.begin_nested = MagicMock(return_value=nested_cm)
    session.is_active = True
    session.in_transaction = MagicMock(return_value=False)
    return session


def test_handle_inspect_database_schema_all_tables():
    """Calling schema inspection with empty table name returns primary tables list."""
    async def run():
        user = make_test_user(role_name=Roles.SUPER_ADMIN.value)
        session = make_mock_session()
        ctx = ToolExecutionContext(user=user, session=session)

        res = await handle_inspect_database_schema({}, ctx)
        assert res["success"] is True
        assert "tables" in res
        assert "users" in res["tables"]
        assert "courses" in res["tables"]
        assert "batches" in res["tables"]

    asyncio.run(run())


def test_handle_inspect_database_schema_specific_table():
    """Inspecting a specific table queries information_schema and returns columns."""
    async def run():
        user = make_test_user(role_name=Roles.SUPER_ADMIN.value)
        session = make_mock_session()

        # Mock column inspection result
        mock_columns_result = MagicMock()
        mock_columns_result.mappings.return_value.all.return_value = [
            {"column_name": "id", "data_type": "integer", "is_nullable": "NO", "column_default": None},
            {"column_name": "title", "data_type": "character varying", "is_nullable": "NO", "column_default": None},
            {"column_name": "code", "data_type": "character varying", "is_nullable": "YES", "column_default": None},
        ]

        mock_fks_result = MagicMock()
        mock_fks_result.mappings.return_value.all.return_value = []

        session.execute.side_effect = [None, mock_columns_result, mock_fks_result]
        ctx = ToolExecutionContext(user=user, session=session)

        res = await handle_inspect_database_schema({"table_name": "courses"}, ctx)
        assert res["success"] is True
        assert res["table_name"] == "courses"
        assert res["columns_count"] == 3
        assert res["columns"][0]["column_name"] == "id"

    asyncio.run(run())


def test_handle_inspect_database_schema_invalid_table_name():
    """Invalid table names containing punctuation or spaces must be rejected."""
    async def run():
        user = make_test_user()
        session = make_mock_session()
        ctx = ToolExecutionContext(user=user, session=session)

        res = await handle_inspect_database_schema({"table_name": "users; DROP TABLE"}, ctx)
        assert res["success"] is False
        assert "Invalid table name" in res["error"]

    asyncio.run(run())


# =============================================================================
# 3. QUERY EXECUTION HANDLER TESTS
# =============================================================================


def test_handle_execute_database_query_success():
    """Executing a valid read-only query returns formatted rows and row_count."""
    async def run():
        user = make_test_user(role_name=Roles.SUPER_ADMIN.value)
        session = make_mock_session()

        mock_exec_result = MagicMock()
        mock_exec_result.mappings.return_value.all.return_value = [
            {"tutor_count": 29},
        ]
        session.execute.side_effect = [None, None, mock_exec_result]  # SELECT 1, SET timeout, SELECT
        ctx = ToolExecutionContext(user=user, session=session)

        query = (
            "SELECT count(DISTINCT u.id) as tutor_count FROM users u "
            "JOIN user_roles ur ON ur.user_id = u.id "
            "JOIN roles r ON r.id = ur.role_id WHERE r.name = 'TUTOR' AND u.status != 'DELETED'"
        )
        res = await handle_execute_database_query({"query": query, "purpose": "count tutors"}, ctx)
        assert res["success"] is True
        assert res["row_count"] == 1
        assert res["rows"][0]["tutor_count"] == 29

    asyncio.run(run())


def test_handle_execute_database_query_catches_sql_error():
    """Query syntax errors or unknown columns must return a clean error with hint."""
    from sqlalchemy.exc import ProgrammingError

    async def run():
        user = make_test_user()
        session = make_mock_session()
        session.execute.side_effect = ProgrammingError("SELECT unknown_col FROM users", {}, orig=Exception('column "unknown_col" does not exist'))
        ctx = ToolExecutionContext(user=user, session=session)

        res = await handle_execute_database_query({"query": "SELECT unknown_col FROM users"}, ctx)
        assert res["success"] is False
        assert "unknown_col" in res["error"]
        assert "inspect_database_schema" in res["hint"]

    asyncio.run(run())
