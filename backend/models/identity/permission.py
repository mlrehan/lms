from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List, Optional
from backend.models.base import Base, TimestampMixin
from datetime import datetime

class Permission(Base, TimestampMixin):
    """Permission model for fine-grained access control."""
    __tablename__ = "permissions"
    id:Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    name:Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    module:Mapped[Optional[str]] = mapped_column(String(50))
    action:Mapped[Optional[str]] = mapped_column(String(50))

    # `Mapped[List["Role"]]`, not `Mapped["Role"]`. SQLAlchemy infers
    # cardinality from this annotation, and the singular form declares a
    # *scalar* attribute -- so with `back_populates`, granting a permission
    # to a second role silently revoked it from the first, and the grants
    # table ended up holding exactly one row per permission no matter how
    # many roles were meant to have it. The `role_permissions` table itself
    # was always a correct many-to-many; only this annotation disagreed.
    roles:Mapped[List["Role"]] = relationship("Role", secondary="role_permissions", back_populates="permissions", passive_deletes=True)
