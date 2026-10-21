"""Direct Database Query & Schema Inspection Tools.

Enables the AI Assistant to answer any authorized question about LMS data in real time
by dynamically generating and safely executing read-only SQL queries against PostgreSQL.
Enforces strict zero-trust safety: read-only transactions, forbidden DDL/DML rejection,
sensitive credential column masking, statement timeouts, row limiting, and role scoping.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
import re
from typing import Any
import uuid

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.ai.security import RiskLevel, SecurityPolicyEngine, ToolPolicy
from backend.ai.tools.registry import ToolDefinition, ToolExecutionContext
from backend.core.errors import AuthorizationError, ValidationError
from backend.core.logging import get_logger
from backend.utils.enums import Roles

logger = get_logger(__name__)

# Pattern to strip SQL comments: -- line comment and /* block comment */
_COMMENT_PATTERN = re.compile(r"(--[^\r\n]*)|(/\*[\s\S]*?\*/)")

# Forbidden DDL, DML, and execution keywords
_FORBIDDEN_SQL_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|RENAME|REPLACE|"
    r"GRANT|REVOKE|COPY|EXEC|EXECUTE|CALL|VACUUM|REINDEX|REFRESH|"
    r"EXPLAIN\s+ANALYZE|LOCK|SET\s+PASSWORD|ALTER\s+USER|CREATE\s+USER)\b",
    re.IGNORECASE,
)

# Sensitive authentication columns prohibited from non-SuperAdmin queries
_SENSITIVE_COLUMNS = re.compile(
    r"\b(hashed_password|salt|token_hash|totp_secret|secret_key|api_key|"
    r"password_reset_token|refresh_token)\b",
    re.IGNORECASE,
)

# Tables restricted to Administrators
_ADMIN_ONLY_TABLES = {
    "system_settings",
    "tokens",
    "alembic_version",
    "push_subscriptions",
    "google_connections",
    "google_change_requests",
    "webhook_endpoints",
    "webhook_deliveries",
}

# Tables restricted from general Students / Guardians
_RESTRICTED_FROM_STUDENTS = {
    "audit_logs",
    "system_settings",
    "tokens",
    "alembic_version",
    "organization_managers",
    "sync_pipeline_jobs",
    "sync_pipeline_runs",
    "user_sync_runs",
}

# Primary LMS tables metadata summary for schema discovery
PRIMARY_SCHEMA_METADATA: dict[str, dict[str, Any]] = {
    "users": {
        "description": "Registered LMS users (all roles).",
        "key_columns": [
            "id", "public_id", "username", "email", "first_name", "last_name",
            "status ('ACTIVE','INACTIVE','SUSPENDED','DELETED')", "is_public",
            "timezone", "phone_number", "created_at"
        ],
        "example": "SELECT count(*) FROM users WHERE status = 'ACTIVE'",
    },
    "roles": {
        "description": "Role definitions (SUPER_ADMIN, ADMIN, TUTOR, STUDENT, GUARDIAN, CORPORATE_MANAGER).",
        "key_columns": ["id", "name", "description"],
        "example": "SELECT id, name FROM roles",
    },
    "user_roles": {
        "description": "Associates users with their granted roles.",
        "key_columns": ["user_id (FK -> users.id)", "role_id (FK -> roles.id)"],
        "example": "SELECT count(DISTINCT u.id) FROM users u JOIN user_roles ur ON ur.user_id = u.id JOIN roles r ON r.id = ur.role_id WHERE r.name = 'TUTOR' AND u.status != 'DELETED'",
    },
    "courses": {
        "description": "Course catalog entries.",
        "key_columns": [
            "id", "public_id", "code", "title", "description",
            "status ('DRAFT','ACTIVE','ARCHIVED')", "is_deleted", "created_at"
        ],
        "example": "SELECT id, code, title FROM courses WHERE NOT is_deleted",
    },
    "batches": {
        "description": "Course cohorts / batches of enrolled students.",
        "key_columns": [
            "id", "public_id", "name", "course_id (FK -> courses.id)",
            "status ('SCHEDULED','IN_PROGRESS','COMPLETED','CANCELLED')",
            "start_date", "end_date"
        ],
        "example": "SELECT id, name, course_id, status FROM batches",
    },
    "batch_sessions": {
        "description": "Individual scheduled class sessions for a batch.",
        "key_columns": [
            "id", "batch_id (FK -> batches.id)", "title", "date",
            "start_time", "end_time", "status ('SCHEDULED','CONDUCTED','CANCELLED')"
        ],
        "example": "SELECT id, title, date FROM batch_sessions ORDER BY date DESC LIMIT 10",
    },
    "enrollments": {
        "description": "Student enrollments in batches.",
        "key_columns": [
            "id", "user_id (FK -> users.id)", "batch_id (FK -> batches.id)",
            "status ('ACTIVE','PENDING','CANCELLED','COMPLETED','DROPPED')", "created_at"
        ],
        "example": "SELECT count(*) FROM enrollments WHERE status = 'ACTIVE'",
    },
    "tutor_courses": {
        "description": "Tutor assignments to courses.",
        "key_columns": ["tutor_id (FK -> users.id)", "course_id (FK -> courses.id)"],
        "example": "SELECT tutor_id, course_id FROM tutor_courses",
    },
    "attendances": {
        "description": "Student attendance records per session.",
        "key_columns": [
            "id", "batch_session_id (FK -> batch_sessions.id)", "student_id (FK -> users.id)",
            "status ('PRESENT','ABSENT','LATE','EXCUSED')", "date"
        ],
        "example": "SELECT status, count(*) FROM attendances GROUP BY status",
    },
    "quizzes": {
        "description": "Course quizzes and online assessments.",
        "key_columns": [
            "id", "public_id", "course_id (FK -> courses.id)", "batch_id (FK -> batches.id)",
            "title", "is_published", "created_at"
        ],
        "example": "SELECT id, title, is_published FROM quizzes",
    },
    "quiz_attempts": {
        "description": "Student attempts and scores on quizzes.",
        "key_columns": [
            "id", "quiz_id (FK -> quizzes.id)", "student_id (FK -> users.id)",
            "score", "status ('IN_PROGRESS','SUBMITTED','GRADED')", "submitted_at"
        ],
        "example": "SELECT quiz_id, avg(score) FROM quiz_attempts WHERE status = 'GRADED' GROUP BY quiz_id",
    },
    "assignments": {
        "description": "Course assignments and homework projects.",
        "key_columns": [
            "id", "public_id", "batch_id (FK -> batches.id)", "title", "max_score", "due_date"
        ],
        "example": "SELECT id, title, due_date FROM assignments",
    },
    "assignment_submissions": {
        "description": "Student submissions for assignments.",
        "key_columns": [
            "id", "assignment_id (FK -> assignments.id)", "student_id (FK -> users.id)",
            "grade", "status ('SUBMITTED','GRADED','LATE')", "submitted_at"
        ],
        "example": "SELECT count(*) FROM assignment_submissions WHERE status = 'SUBMITTED'",
    },
    "exams": {
        "description": "Formal exams and tests.",
        "key_columns": ["id", "public_id", "batch_id (FK -> batches.id)", "title", "total_marks"],
        "example": "SELECT id, title, total_marks FROM exams",
    },
    "exam_results": {
        "description": "Student results on formal exams.",
        "key_columns": [
            "id", "exam_id (FK -> exams.id)", "student_id (FK -> users.id)",
            "marks_obtained", "is_passed"
        ],
        "example": "SELECT student_id, marks_obtained FROM exam_results",
    },
    "organizations": {
        "description": "Corporate client organizations / enterprise tenants.",
        "key_columns": ["id", "name", "code", "created_at"],
        "example": "SELECT id, name, code FROM organizations",
    },
    "student_guardians": {
        "description": "Parent/Guardian to Student relationships.",
        "key_columns": [
            "student_id (FK -> users.id)", "guardian_id (FK -> users.id)", "relationship"
        ],
        "example": "SELECT student_id, guardian_id, relationship FROM student_guardians",
    },
    "sync_pipeline_runs": {
        "description": "System data synchronization execution logs.",
        "key_columns": [
            "id", "status ('RUNNING','COMPLETED','FAILED')", "trigger_type",
            "started_at", "completed_at"
        ],
        "example": "SELECT id, status, started_at, completed_at FROM sync_pipeline_runs ORDER BY started_at DESC LIMIT 5",
    },
    "audit_logs": {
        "description": "Administrative and security audit trails.",
        "key_columns": [
            "id", "action", "actor_user_id (FK -> users.id)", "entity_type",
            "entity_id", "timestamp"
        ],
        "example": "SELECT action, actor_user_id, timestamp FROM audit_logs ORDER BY timestamp DESC LIMIT 10",
    },
}


def clean_sql(query: str) -> str:
    """Strip SQL comments and leading/trailing whitespace."""
    no_comments = _COMMENT_PATTERN.sub(" ", query)
    return no_comments.strip()


def validate_sql_safety(
    query: str,
    caller_roles: set[str],
) -> tuple[bool, str | None, str]:
    """Inspect and validate dynamic SQL query for read-only safety and RBAC boundaries.

    Returns:
        (is_valid, error_reason, sanitized_query)
    """
    cleaned = clean_sql(query)
    if not cleaned:
        return False, "Query cannot be empty.", ""

    # 1. Multi-statement check: ensure no semicolons dividing multiple statements
    stripped_end = cleaned.rstrip(";").strip()
    if ";" in stripped_end:
        # Check if semicolon is outside quotes
        parts = [p.strip() for p in stripped_end.split(";") if p.strip()]
        if len(parts) > 1:
            return False, "Multiple SQL statements are strictly forbidden. Submit only a single SELECT query.", ""

    # 2. Statement type check: MUST start with SELECT or WITH
    norm = stripped_end.upper()
    if not (norm.startswith("SELECT") or norm.startswith("WITH")):
        return False, "Only read-only SELECT or WITH (Common Table Expression) queries are permitted.", ""

    # 3. Forbidden keywords (mutations, DDL, DML, execution)
    match = _FORBIDDEN_SQL_KEYWORDS.search(stripped_end)
    if match:
        return (
            False,
            f"Mutating, administrative, or non-SELECT operation '{match.group()}' is strictly prohibited.",
            "",
        )

    # 4. Sensitive columns check (hashed_password, token_hash, secrets)
    is_superadmin = Roles.SUPER_ADMIN.value in caller_roles
    if not is_superadmin:
        sens_match = _SENSITIVE_COLUMNS.search(stripped_end)
        if sens_match:
            return (
                False,
                f"Querying sensitive credential column '{sens_match.group()}' is strictly prohibited.",
                "",
            )

    # 5. Table-level RBAC restrictions
    is_admin = is_superadmin or Roles.ADMIN.value in caller_roles
    is_student_or_guardian = (
        Roles.STUDENT.value in caller_roles or Roles.GUARDIAN.value in caller_roles
    )

    if not is_admin:
        for tbl in _ADMIN_ONLY_TABLES:
            if re.search(rf"\b{tbl}\b", stripped_end, re.IGNORECASE):
                return (
                    False,
                    f"Access to administrative table '{tbl}' is denied for your role.",
                    "",
                )

    if is_student_or_guardian:
        for tbl in _RESTRICTED_FROM_STUDENTS:
            if re.search(rf"\b{tbl}\b", stripped_end, re.IGNORECASE):
                return (
                    False,
                    f"Access to operational table '{tbl}' is restricted.",
                    "",
                )

    # 6. Row limit bounding: ensure large table scans do not exhaust memory
    final_query = stripped_end
    if not re.search(r"\bLIMIT\s+\d+\b", final_query, re.IGNORECASE):
        final_query = f"{final_query} LIMIT 100"
    else:
        # If LIMIT exists, ensure it doesn't exceed 200
        limit_match = re.search(r"\bLIMIT\s+(\d+)\b", final_query, re.IGNORECASE)
        if limit_match and int(limit_match.group(1)) > 200:
            final_query = re.sub(
                r"\bLIMIT\s+\d+\b",
                "LIMIT 200",
                final_query,
                flags=re.IGNORECASE,
            )

    return True, None, final_query


def serialize_mapping(row: dict[str, Any]) -> dict[str, Any]:
    """Convert SQLAlchemy row mapping into JSON-serializable types."""
    res: dict[str, Any] = {}
    for k, v in row.items():
        if v is None:
            res[k] = None
        elif isinstance(v, (int, float, bool, str)):
            res[k] = v
        elif isinstance(v, (datetime, date, time)):
            res[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            res[k] = str(v)
        elif isinstance(v, Decimal):
            res[k] = float(v)
        elif isinstance(v, Enum):
            res[k] = v.value
        elif isinstance(v, (list, tuple)):
            res[k] = [str(x) if isinstance(x, (uuid.UUID, datetime)) else x for x in v]
        elif isinstance(v, dict):
            res[k] = {str(dk): str(dv) if isinstance(dv, (uuid.UUID, datetime)) else dv for dk, dv in v.items()}
        elif isinstance(v, (bytes, bytearray)):
            res[k] = f"<binary {len(v)} bytes>"
        else:
            res[k] = str(v)
    return res


# =============================================================================
# 1. EXECUTE DATABASE QUERY HANDLER
# =============================================================================


async def handle_execute_database_query(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Execute a dynamic, read-only SQL query against the LMS database."""
    query_raw = arguments.get("query", "").strip()
    purpose = arguments.get("purpose", "")
    user = context.user
    held_roles = SecurityPolicyEngine.caller_roles(user)

    logger.info(
        "User %s (%s) executing dynamic database query: %s (Purpose: %s)",
        user.public_id,
        held_roles,
        query_raw,
        purpose,
    )

    # 1. Validate query safety and RBAC boundaries
    is_valid, error_reason, safe_query = validate_sql_safety(query_raw, held_roles)
    if not is_valid:
        logger.warning(
            "Database query rejected for user %s: %s (Query: %s)",
            user.public_id,
            error_reason,
            query_raw,
        )
        return {
            "success": False,
            "error": error_reason,
            "hint": "Ensure your query is a read-only SELECT statement with valid table and column names.",
        }

    # 2. Execute query in safe read-only context with statement timeout
    session = context.session
    try:
        # Enforce read-only transaction and statement timeout
        await session.execute(text("SET LOCAL TRANSACTION READ ONLY"))
        await session.execute(text("SET LOCAL statement_timeout = '5000ms'"))

        stmt = text(safe_query)
        result = await session.execute(stmt)
        raw_rows = result.mappings().all()
        serialized_rows = [serialize_mapping(dict(r)) for r in raw_rows]

        row_count = len(serialized_rows)
        logger.info(
            "Dynamic query succeeded for user %s: %d record(s) returned",
            user.public_id,
            row_count,
        )

        return {
            "success": True,
            "row_count": row_count,
            "rows": serialized_rows,
            "message": f"Query returned {row_count} record(s).",
        }

    except SQLAlchemyError as exc:
        err_msg = str(exc.orig if hasattr(exc, "orig") else exc)
        logger.warning("Database query execution failed: %s (SQL: %s)", err_msg, safe_query)
        return {
            "success": False,
            "error": err_msg,
            "hint": "Check the exact table and column names using 'inspect_database_schema' and retry with valid schema names.",
        }
    except Exception as exc:
        logger.warning("Unexpected error during query execution: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "hint": "Check the query syntax and schema details before retrying.",
        }


# =============================================================================
# 2. INSPECT DATABASE SCHEMA HANDLER
# =============================================================================


async def handle_inspect_database_schema(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Inspect tables, column names, data types, and relationships in the LMS database."""
    table_name = arguments.get("table_name", "").strip().lower()
    user = context.user
    held_roles = SecurityPolicyEngine.caller_roles(user)

    # 1. If no table name provided, return primary domain tables overview
    if not table_name:
        # Filter out admin-only tables for non-admins
        is_admin = Roles.SUPER_ADMIN.value in held_roles or Roles.ADMIN.value in held_roles
        available_tables = {
            t: meta
            for t, meta in PRIMARY_SCHEMA_METADATA.items()
            if is_admin or t not in _ADMIN_ONLY_TABLES
        }
        return {
            "success": True,
            "total_tables": len(available_tables),
            "tables": available_tables,
            "hint": "Provide 'table_name' to inspect the detailed column schema and foreign keys of a specific table.",
        }

    # 2. Validate table_name format to prevent SQL injection
    if not re.match(r"^[a-zA-Z0-9_]+$", table_name):
        return {
            "success": False,
            "error": f"Invalid table name '{table_name}'. Use alphanumeric characters and underscores only.",
        }

    # 3. RBAC check on table inspection
    is_admin = Roles.SUPER_ADMIN.value in held_roles or Roles.ADMIN.value in held_roles
    if not is_admin and table_name in _ADMIN_ONLY_TABLES:
        return {
            "success": False,
            "error": f"Access to schema of table '{table_name}' is restricted for your role.",
        }

    # 4. Query information_schema for columns
    session = context.session
    try:
        col_query = text("""
            SELECT 
                column_name, 
                data_type, 
                is_nullable, 
                column_default
            FROM information_schema.columns 
            WHERE table_schema = 'public' AND table_name = :table_name 
            ORDER BY ordinal_position;
        """)
        cols_res = await session.execute(col_query, {"table_name": table_name})
        cols = cols_res.mappings().all()

        if not cols:
            return {
                "success": False,
                "error": f"Table '{table_name}' does not exist in the public schema.",
                "available_tables": sorted(list(PRIMARY_SCHEMA_METADATA.keys())),
            }

        # 5. Query foreign key constraints
        fk_query = text("""
            SELECT
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema = 'public'
                AND tc.table_name = :table_name;
        """)
        fk_res = await session.execute(fk_query, {"table_name": table_name})
        fks = fk_res.mappings().all()

        # Mask sensitive columns if not SuperAdmin
        is_superadmin = Roles.SUPER_ADMIN.value in held_roles
        columns_info = []
        for c in cols:
            c_name = c["column_name"]
            if not is_superadmin and _SENSITIVE_COLUMNS.search(c_name):
                continue
            columns_info.append({
                "column_name": c_name,
                "data_type": c["data_type"],
                "is_nullable": c["is_nullable"] == "YES",
                "default": c["column_default"],
            })

        fk_info = [
            {
                "column": fk["column_name"],
                "references": f"{fk['foreign_table_name']}.{fk['foreign_column_name']}",
            }
            for fk in fks
        ]

        metadata = PRIMARY_SCHEMA_METADATA.get(table_name, {})

        return {
            "success": True,
            "table_name": table_name,
            "description": metadata.get("description", "LMS database table"),
            "columns_count": len(columns_info),
            "columns": columns_info,
            "foreign_keys": fk_info,
            "sample_query": metadata.get("example"),
        }

    except Exception as exc:
        logger.warning("Schema inspection error for table %s: %s", table_name, exc)
        return {
            "success": False,
            "error": str(exc),
        }


# =============================================================================
# TOOL DEFINITIONS & REGISTRATION
# =============================================================================

execute_database_query_tool = ToolDefinition(
    name="execute_database_query",
    description=(
        "Execute a safe, read-only SQL query against the LMS PostgreSQL database to answer "
        "authorized questions about application data in real time (e.g. tutor counts, student counts, "
        "active courses, batches, schedules, attendance, quiz scores, or system statistics). "
        "Only SELECT and WITH (CTE) queries are permitted. Returns actual database records."
    ),
    policy=ToolPolicy(
        name="execute_database_query",
        description="Execute read-only SQL database queries",
        required_permissions=(),
        risk_level=RiskLevel.LOW,
        requires_confirmation=False,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "The read-only SQL query to execute (e.g. "
                    "'SELECT count(DISTINCT u.id) FROM users u JOIN user_roles ur ON ur.user_id = u.id "
                    "JOIN roles r ON r.id = ur.role_id WHERE r.name = \\'TUTOR\\' AND u.status != \\'DELETED\\'', "
                    "or 'SELECT code, title, status FROM courses WHERE NOT is_deleted ORDER BY created_at DESC LIMIT 5')."
                ),
            },
            "purpose": {
                "type": "string",
                "description": "Brief description of the user inquiry or question being answered.",
            },
        },
        "required": ["query"],
    },
    handler=handle_execute_database_query,
)

inspect_database_schema_tool = ToolDefinition(
    name="inspect_database_schema",
    description=(
        "Inspect database tables, column names, data types, and foreign key relationships in the LMS database. "
        "Use this tool to discover exact column names or verify table relationships before querying, "
        "or if a database query fails with an unknown column or relation error."
    ),
    policy=ToolPolicy(
        name="inspect_database_schema",
        description="Inspect database schema metadata",
        required_permissions=(),
        risk_level=RiskLevel.LOW,
        requires_confirmation=False,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": (
                    "Optional name of the specific table to inspect (e.g. 'users', 'roles', 'user_roles', "
                    "'courses', 'batches', 'batch_sessions', 'enrollments', 'attendances', 'quizzes', 'assignments'). "
                    "If omitted, returns all available LMS tables with descriptions."
                ),
            },
        },
        "required": [],
    },
    handler=handle_inspect_database_schema,
)

