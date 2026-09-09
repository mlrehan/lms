from sqlalchemy import Integer, ForeignKey, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from backend.models.base import Base, utc_now
from datetime import datetime

class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True
    )
    permission_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True
    )

    # `server_default` must be a live SQL clause (`func.now()`), never a bare
    # Python callable or a pre-called value -- either of those bakes a single
    # frozen timestamp (the moment this module was first imported) into the
    # DDL as a literal default for every future row.
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
