"""Corporate organizations, and who a Corporate Manager may actually see.

**Two different questions, and they used to share one answer.** Employment --
which company someone works for, their employee code, their department, which
company sponsored an enrollment -- is recorded here on `Organization`,
`OrganizationManager` and `OrganizationMembership`. *Visibility* -- which
students a particular manager may read -- is a direct manager-to-student link
(`ManagedStudent`), exactly as a guardian is linked to a ward.

They were the same thing until now: a manager saw every employee of their
company, derived by joining manager -> organization -> membership. That made
the roster a side effect of the org chart. A company with four managers and
two hundred employees gave each of those managers all two hundred, and there
was no way to say "these thirty are yours".

An earlier version of this docstring argued against a direct link, on the
grounds that `corporate_manager_id` on Student is a one-column answer to a
many-row question. That argument was right about a **column** and does not
apply to a join table: `ManagedStudent` carries many rows per student and
many per manager, keeps its own history, and is the same shape as
`student_guardians`, which has answered the identical question for guardians
since the beginning.

What did not change: one manager still belongs to exactly one organization at
a time, and one student to exactly one organization at a time, both enforced
by a partial unique index on the "currently active" row so a reassignment
leaves history intact. Those constraints are about *employment*, which is
still one company per person. They no longer decide who can see whom.
"""

from datetime import datetime

from sqlalchemy import (Integer, String, ForeignKey, Index, text,
                        Enum as SQLEnum, Boolean, UniqueConstraint)
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


class ManagedStudent(Base, PublicIdMixin):
    """A Corporate Manager and one of their students, linked directly.

    The same shape as `StudentGuardian`, for the same reason: a student may
    have more than one manager (a line manager and an L&D lead), and a
    manager has many students. Neither is expressible as a column, and
    neither is a fact about the company.

    **This table, and nothing else, decides what a manager can see.** It
    feeds `ScopeResolver`, which feeds enrollment, attendance, submissions,
    quiz attempts, exam results, the grade book, performance, transcripts and
    the dashboards. A student with no row here is invisible to every manager,
    whatever company they both belong to.

    A hard delete when a link ends, like a guardianship: keeping a record of
    who used to be able to read somebody's results, indefinitely, is data
    nobody asked us to hold. The audit log keeps the act.
    """

    __tablename__ = "manager_students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manager_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, comment="e.g. 'Line manager', 'L&D sponsor'"
    )
    #: The manager to contact first when a student has several. Mirrors
    #: `student_guardians.is_primary`, and is kept to one per student the
    #: same way -- by demoting the previous holder, not by a constraint,
    #: because "nobody is primary yet" has to stay expressible.
    is_primary: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    created_at: Mapped[datetime] = utc_datetime_column(nullable=False)

    manager: Mapped["User"] = relationship(
        "User", foreign_keys=[manager_id], lazy="selectin"
    )
    student: Mapped["User"] = relationship(
        "User", foreign_keys=[student_id], lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("manager_id", "student_id", name="uq_manager_students_manager_student"),
        # The scope resolver asks "which students does this manager have?"
        # on every request a manager makes.
        Index("idx_manager_students_manager", "manager_id"),
        Index("idx_manager_students_student", "student_id"),
    )
