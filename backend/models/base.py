import uuid
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Uuid,
    false,
    func,
    true,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": (
        "fk_%(table_name)s_"
        "%(column_0_name)s_"
        "%(referred_table_name)s"
    ),
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    metadata = metadata


class TimestampMixin:

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ActiveMixin:

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=true(),
        nullable=False,
    )


class PublicIdMixin:
    """Opaque, unique identifier safe to expose in URLs and API responses.

    Every entity keeps a fast auto-increment integer as its real primary key
    for internal joins/indexes; ``public_id`` is the only identifier that
    should ever leave the process. Sequential integer PKs are trivially
    enumerable (``GET /courses/1``, ``/courses/2`` ...) — this column exists
    so the API layer never has to expose one.
    """

    public_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        unique=True,
        index=True,
        default=uuid.uuid4,
        nullable=False,
    )


class SoftDeleteMixin:
    """Shared soft-delete columns, so ``is_deleted``/``deleted_at``/``deleted_by``
    aren't redeclared with slightly different types in every model file.

    ``deleted_by`` references ``users.id`` — the actor who performed the
    deletion is always a user, including for ``User`` rows themselves
    (an admin soft-deleting another account is a self-referencing FK, which
    Postgres handles fine).
    """

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
        nullable=False,
    )

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    deleted_by: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
