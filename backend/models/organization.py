"""Corporate organizations. A corporate client enrolls its employees in
platform courses through a Corporate_Manager; the relationships below are
deliberately real tables, not columns on `User`:

* A `corporate_manager_id` (or `guardian_id`) directly on Student can express
  exactly one manager per student and forgets history the instant someone is
  reassigned -- both are one-column answers to a many-row question.
* Every actual requirement here (add/invite employees, view enrollments,
  view progress "where permitted") is answered by joining through
  `OrganizationManager`/`OrganizationMembership`, not by a direct link
  between a manager and a student.

Confirmed cardinality: one manager belongs to exactly one organization (an
organization may have many managers); one student belongs to exactly one
organization at a time. Both constraints are enforced with a partial unique
index on `user_id`, scoped to the "currently active" row -- the same
technique already used on `enrollments` for re-enrollment -- so a manager or
employee who is reassigned or removed leaves their history intact rather
than being deleted or overwritten.
"""

from datetime import datetime

from sqlalchemy import (Integer, String, ForeignKey, Index, text,
                        Enum as SQLEnum, Boolean)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from backend.models.base import Base, PublicIdMixin, SoftDeleteMixin
from .helpers import utc_datetime_column
from backend.utils.enums import OrganizationMembershipStatus


class Organization(Base, PublicIdMixin, SoftDeleteMixin):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(30), unique=True, nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(75), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"), nullable=False)
    created_at: Mapped[datetime] = utc_datetime_column(nullable=False)
    updated_at: Mapped[Optional[datetime]] = utc_datetime_column(onupdate=True)

    managers: Mapped[List["OrganizationManager"]] = relationship(back_populates="organization", lazy="selectin")
    memberships: Mapped[List["OrganizationMembership"]] = relationship(back_populates="organization", lazy="selectin")


class OrganizationManager(Base, PublicIdMixin):
    """One manager belongs to exactly one organization at a time; an
    organization may have many managers. `is_active` + the partial unique
    index below is what makes "at a time" mean something -- a reassigned
    manager's earlier row is kept, not deleted."""
    __tablename__ = "organization_managers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="e.g. 'L&D Manager'")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"), nullable=False)
    invited_at: Mapped[datetime] = utc_datetime_column(nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="managers")
    user: Mapped["User"] = relationship("User", lazy="selectin")

    __table_args__ = (
        # "One manager, one organization, at a time" -- a reassignment inserts
        # a new row rather than overwriting the old one, so history survives.
        Index(
            "uq_organization_managers_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index("idx_organization_managers_org", "organization_id"),
    )


class OrganizationMembership(Base, PublicIdMixin):
    """One student belongs to exactly one organization at a time -- same
    partial-unique-index technique as `OrganizationManager` above, and as
    `enrollments`' own re-enrollment handling."""
    __tablename__ = "organization_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    employee_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    department: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[OrganizationMembershipStatus] = mapped_column(
        SQLEnum(OrganizationMembershipStatus, name="organization_membership_status", native_enum=False),
        server_default=text(f"'{OrganizationMembershipStatus.INVITED.value}'"),
        nullable=False,
    )
    invited_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    invited_at: Mapped[datetime] = utc_datetime_column(nullable=False)
    joined_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False, nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="memberships")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id], lazy="selectin")
    invited_by_user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[invited_by], lazy="selectin")

    __table_args__ = (
        Index(
            "uq_organization_memberships_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('INVITED', 'ACTIVE', 'SUSPENDED')"),
        ),
        Index("idx_organization_memberships_org", "organization_id"),
    )
