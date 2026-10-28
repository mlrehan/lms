"""The Super Admin's guarded SQL change: one INSERT, UPDATE or DELETE, confirmed.

Nothing here executes SQL because a model wrote it. A change passes, in order:

1. **A real parser** (sqlglot, PostgreSQL dialect), never a pattern match. Exactly
   one statement; INSERT, UPDATE or DELETE only; no CTE (a data-modifying CTE
   hides a second write inside a first); no RETURNING; UPDATE and DELETE must
   have a WHERE; only allowlisted functions -- an unknown function is refused,
   so `pg_read_file` and friends never reach the server.
2. **A table and column policy** (`sql_access.py`): the audit trail, the
   permission tables and credential tables can never be written; withheld
   tables and columns may not even be referenced, so a change cannot copy a
   password hash into a readable column.
3. **An exact dry run.** The statement is executed inside a savepoint and
   rolled back, so the preview states how many rows *would* change, measured
   rather than estimated. A change touching nothing, or more than
   `AI_SQL_MAX_WRITE_ROWS`, is refused before anyone is asked.
4. **A recent backup**, by the same rule the system reset uses.
5. **Typed confirmation.** The person types a phrase naming the operation, the
   row count and the table -- a button can be clicked by habit; typing
   "DELETE 40 ROWS IN enrollments" cannot be done without reading it.
6. **A row ceiling at execution.** The confirmed statement runs in a savepoint;
   if it affects a different number of rows than the preview showed, the
   data changed in between and it is rolled back rather than applied to rows
   nobody was shown.

Every executed change is audited with its full text and a SHA-256 of it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from backend.ai.config import get_ai_settings
from backend.ai.security import RiskLevel, SecurityPolicyEngine, ToolPolicy
from backend.ai.sql_access import WITHHELD_COLUMNS, WITHHELD_TABLES, WRITE_PROTECTED_TABLES
from backend.ai.tools.registry import BOUND_PREFIX, ConfirmationPreview, ToolDefinition, ToolExecutionContext
from backend.core.backups import backup_blockers
from backend.core.config import get_settings
from backend.core.errors import AuthorizationError, ConflictError, ValidationError
from backend.services import audit_service
from backend.utils.enums import Roles

# Functions a change may call: pure value functions only. Anything else --
# including every function sqlglot does not recognise, which it reports as
# Anonymous -- is refused.
_ALLOWED_FUNCTIONS = frozenset({
    "LOWER", "UPPER", "TRIM", "LENGTH", "SUBSTRING", "CONCAT", "REPLACE",
    "COALESCE", "NULLIF", "GREATEST", "LEAST", "ABS", "ROUND", "CEIL", "FLOOR",
    "CAST", "TRY_CAST", "CURRENT_TIMESTAMP", "CURRENT_DATE", "IF", "CASE",
})

_KINDS = {exp.Insert: "INSERT", exp.Update: "UPDATE", exp.Delete: "DELETE"}

# Accounts are created, deleted and re-keyed through UserService, which owns
# password hashing, token revocation and the guards on the last Super Admin.
_USERS_UPDATE_ONLY = "users"

_WITHHELD_COLUMN_NAMES = frozenset(column for _, column in WITHHELD_COLUMNS)

_STATEMENT_TIMEOUT_MS = 10_000


@dataclass(frozen=True)
class SqlChange:
    kind: str
    table: str
    sql: str
    digest: str


def validate_sql_change(raw: str) -> SqlChange:
    """Parse and check a proposed change. Raises ValidationError naming the reason."""
    sql = (raw or "").strip().rstrip(";").strip()
    if not sql:
        raise ValidationError("No SQL statement was given.")
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except ParseError as exc:
        raise ValidationError(f"The statement could not be parsed: {str(exc).splitlines()[0]}") from None
    if len(statements) != 1:
        raise ValidationError("Exactly one statement may be run at a time.")
    stmt = statements[0]

    kind = next((name for cls, name in _KINDS.items() if isinstance(stmt, cls)), None)
    if kind is None:
        raise ValidationError(
            f"Only INSERT, UPDATE or DELETE may be run this way (got {type(stmt).__name__.upper()}). "
            "Reads use the query tool; schema changes are made by migrations."
        )
    if stmt.args.get("with"):
        raise ValidationError("WITH clauses are not allowed in a change.")
    if stmt.args.get("returning"):
        raise ValidationError("RETURNING is not allowed in a change.")
    if kind in ("UPDATE", "DELETE") and not stmt.args.get("where"):
        raise ValidationError(f"An {kind} must have a WHERE clause.")

    target = stmt.this.this if isinstance(stmt.this, exp.Schema) else stmt.this
    if not isinstance(target, exp.Table):
        raise ValidationError("The statement's target table could not be determined.")
    if target.db and target.db.lower() != "public":
        raise ValidationError("Only tables in the public schema may be changed.")
    table = target.name.lower()
    if table in WRITE_PROTECTED_TABLES:
        raise ValidationError(f"The table '{table}' can never be changed this way.")
    if table == _USERS_UPDATE_ONLY and kind != "UPDATE":
        raise ValidationError("Accounts are created and deleted on the Users screen, not with SQL.")

    for referenced in stmt.find_all(exp.Table):
        if referenced.name.lower() in WITHHELD_TABLES:
            raise ValidationError(f"The table '{referenced.name}' may not be referenced.")
    for column in stmt.find_all(exp.Column):
        if column.name.lower() in _WITHHELD_COLUMN_NAMES:
            raise ValidationError(f"The column '{column.name}' may not be read or written.")
    for func in stmt.find_all(exp.Func):
        name = "ANONYMOUS" if isinstance(func, exp.Anonymous) else func.sql_name()
        if name not in _ALLOWED_FUNCTIONS:
            shown = func.name if isinstance(func, exp.Anonymous) else name
            raise ValidationError(f"The function '{shown}' is not allowed in a change.")

    canonical = stmt.sql(dialect="postgres")
    return SqlChange(kind=kind, table=table, sql=canonical, digest=hashlib.sha256(canonical.encode()).hexdigest())


def _phrase(change: SqlChange, rows: int) -> str:
    return f"{change.kind} {rows} ROWS IN {change.table}"


def _require_super_admin(context: ToolExecutionContext) -> None:
    if Roles.SUPER_ADMIN.value not in SecurityPolicyEngine.caller_roles(context.user):
        raise AuthorizationError("Only the Super Admin may change data with SQL.")


def _backup_problems() -> list[str]:
    app = get_settings().app
    return backup_blockers(
        app.system_reset_backup_path,
        max_age_hours=app.system_reset_backup_max_age_hours,
        action="This change",
    )


async def _affected_rows(
    context: ToolExecutionContext, change: SqlChange, *, keep: bool, expected: int | None = None
) -> int:
    """Run the statement once in a savepoint and report the rows it changed.

    Rolled back unless `keep`; also rolled back, and refused, if `expected` is
    given and the count differs -- the data moved since the preview. Executed
    as raw driver SQL with no parameters, so nothing in the statement is
    reinterpreted as a bind placeholder.
    """
    session = context.session
    savepoint = await session.begin_nested()
    try:
        conn = await session.connection()
        await conn.exec_driver_sql(f"SET LOCAL statement_timeout = {_STATEMENT_TIMEOUT_MS}")
        # The driver still applies %-formatting to a statement executed with an
        # empty parameter set, so a literal % (LIKE 'x%') must be doubled to
        # arrive unchanged. Nothing is substituted: there are no parameters.
        result = await conn.exec_driver_sql(change.sql.replace("%", "%%"))
        rows = int(result.rowcount)
    except Exception:
        await savepoint.rollback()
        raise
    if expected is not None and rows != expected:
        await savepoint.rollback()
        raise ConflictError(
            f"The data changed since the preview ({rows} rows would now change, not {expected}). "
            "Nothing was changed; ask for a new preview."
        )
    if keep:
        await savepoint.commit()
    else:
        await savepoint.rollback()
    return rows


async def preview_sql_change(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    _require_super_admin(context)
    change = validate_sql_change(str(arguments.get("sql") or ""))

    problems = _backup_problems()
    if problems:
        raise ConflictError(problems[0])

    try:
        rows = await _affected_rows(context, change, keep=False)
    except Exception as exc:
        reason = str(getattr(exc, "orig", exc)).splitlines()[0]
        raise ValidationError(f"The statement failed when tried: {reason}") from None
    if rows <= 0:
        raise ConflictError("The statement would change no rows, so there is nothing to confirm.")
    ceiling = get_ai_settings().sql_max_write_rows
    if rows > ceiling:
        raise ConflictError(
            f"The statement would change {rows} rows; the assistant changes at most {ceiling} at once."
        )

    phrase = _phrase(change, rows)
    return ConfirmationPreview(
        summary=f"{change.kind} {rows} row(s) in {change.table}: {change.sql}",
        affected_records_count=rows,
        bound_parameters={"digest": change.digest, "rows": rows, "phrase": phrase},
        typed_confirmation=phrase,
    )


async def handle_sql_change(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    """Execute a confirmed change, or refuse it. Runs only from a confirmed ticket."""
    _require_super_admin(context)
    change = validate_sql_change(str(arguments.get("sql") or ""))
    expected_rows = arguments.get(f"{BOUND_PREFIX}rows")
    phrase = arguments.get(f"{BOUND_PREFIX}phrase")
    if change.digest != arguments.get(f"{BOUND_PREFIX}digest") or not isinstance(expected_rows, int):
        raise ConflictError("The statement no longer matches the one previewed; ask for it again.")

    typed = (context.confirmation_text or "").strip()
    if typed != phrase:
        raise ConflictError(
            f"To run this change, type exactly: {phrase}. Nothing was changed."
        )

    problems = _backup_problems()
    if problems:
        raise ConflictError(problems[0])

    applied = await _affected_rows(context, change, keep=True, expected=expected_rows)

    audit_service.record(
        context.session,
        action=audit_service.AuditAction.UPDATE if change.kind == "UPDATE" else (
            audit_service.AuditAction.CREATE if change.kind == "INSERT" else audit_service.AuditAction.DELETE
        ),
        actor_user_id=context.user.id,
        actor_email=context.user.email,
        entity_type=change.table,
        details={
            "operation": "AI_SQL_CHANGE",
            "statement": change.sql,
            "sha256": change.digest,
            "rows": applied,
            "client_ip": context.client_ip,
        },
    )
    return {
        "success": True,
        "status": "APPLIED",
        "rows": applied,
        "table": change.table,
        "message": f"{change.kind} applied: {applied} row(s) in {change.table}.",
    }


sql_change_tool = ToolDefinition(
    name="execute_sql_change",
    description=(
        "Propose a single INSERT, UPDATE or DELETE. It is checked, dry-run to count the rows it would "
        "change, and runs only after the Super Admin types the confirmation phrase. Prefer the dedicated "
        "tools for anything they cover."
    ),
    policy=ToolPolicy(
        name="execute_sql_change",
        description="Guarded SQL change",
        required_permissions=("institution.view_all",),
        allowed_roles=(Roles.SUPER_ADMIN.value,),
        risk_level=RiskLevel.CRITICAL,
        requires_confirmation=True,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "One INSERT, UPDATE or DELETE statement"},
            "purpose": {"type": "string", "description": "Why the change is being made"},
        },
        "required": ["sql"],
    },
    handler=handle_sql_change,
    preview=preview_sql_change,
)
