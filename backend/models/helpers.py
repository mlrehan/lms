from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Time, text, Boolean, func
from sqlalchemy.orm import Mapped, declared_attr, mapped_column
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



class AssessmentOwnershipMixin:
    """Who wrote an assessment, and whether it was withdrawn.

    Shared by `Assignment`, `Quiz` and `Exam` so the three keep one shape (§3).
    `created_by` is what tutor isolation is decided on: a tutor sees and manages
    their own assessments, never a colleague's. NULL means the author is unknown
    (written before the column existed and not in the audit trail) and is treated
    as institution-owned. `deleted_at` withdraws the assessment without removing
    the students' work and marks that hang off it.
    """

    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    deleted_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False)
    deleted_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    @declared_attr
    def copied_from_id(cls) -> Mapped[Optional[int]]:  # noqa: N805
        """The assessment this one was reused from, if any.

        A reuse is a new row -- its own recipients, deadline, state,
        submissions and marks -- that points back at its source. Each copy owns
        its content on purpose: editing one batch's paper after its students sat
        it must not change what another batch is about to sit.
        """
        return mapped_column(
            Integer,
            ForeignKey(f"{cls.__tablename__}.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        )
