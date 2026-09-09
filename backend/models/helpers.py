from typing import Optional

from sqlalchemy import Date, DateTime, Time, text, Boolean, func
from sqlalchemy.orm import mapped_column
from datetime import datetime


# =====================================================
# 1. UTC DATETIME COLUMN
# =====================================================
def utc_datetime_column(
    default: bool = True,
    onupdate: bool = False,
    nullable: bool = True,
    index:bool = False
):
    """
    Cross-database UTC-aware datetime column.

    On PostgreSQL:
        CURRENT_TIMESTAMP is ALWAYS UTC internally for timestamptz.
    """

    expr = text("CURRENT_TIMESTAMP")  

    kwargs = {
        "type_": DateTime(timezone=True),
        "nullable": nullable
    }

    kwargs["index"] = index
    # Add default
    if default:
        kwargs["server_default"] = expr

    # ⚠ Onupdate must be client-side for cross-database compatibility
    # server_onupdate does NOT work on SQLite/MySQL/Alembic.
    if onupdate:
        kwargs["onupdate"] = func.now()

    return mapped_column(**kwargs)


# =====================================================
# 2. UTC DATE COLUMN
# =====================================================
def utc_date_column(
    default: bool = True,
    onupdate: bool = False,
    nullable: bool = True,
    index: Optional[bool] = None
):
    """UTC-normalized DATE() column for all DBs."""

    expr = text("CURRENT_DATE")

    kwargs = {
        "type_": Date(),
        "nullable": nullable,
        "index":index
    }

    if default:
        kwargs["server_default"] = expr

    if onupdate:
        kwargs["onupdate"] = func.current_date()

    return mapped_column(**kwargs)


# =====================================================
# 3. TIME-ONLY (UTC) COLUMN
# =====================================================
def utc_time_column(
    default: bool = True,
    onupdate: bool = False,
    nullable: bool = False,
):
    """Time-only (UTC) column."""

    expr = text("CURRENT_TIME")

    kwargs = {
        "type_": Time(timezone=False),  # TIME never stores TZ
        "nullable": nullable,
    }

    if default:
        kwargs["server_default"] = expr

    if onupdate:
        kwargs["onupdate"] = func.time(func.now())

    return mapped_column(**kwargs)


# =====================================================
# 4. BOOLEAN COLUMN
# =====================================================
def bool_column(default: bool = True, nullable: bool = False, index: Optional[bool] = None, comment: Optional[str] = None):
    """Boolean with correct server_default for each DB."""

    expr = text("true" if default else "false")

    return mapped_column(
        Boolean,
        server_default=expr,
        nullable=nullable,
        index=index,
        comment=comment
    )

