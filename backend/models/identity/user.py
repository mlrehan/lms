from sqlalchemy import (Integer, String, Text, Enum as SQLEnum, text,
                        DateTime, Float, ForeignKey, Index, select)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List, NamedTuple, Set
from backend.models.base import Base, PublicIdMixin, TimestampMixin
from backend.models.helpers import utc_date_column, bool_column
from datetime import datetime, date, timezone
from slugify import slugify
from backend.utils.enums import UserStatus, Genders, Roles

class User(Base, TimestampMixin, PublicIdMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True, nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # `DELETED` is itself the deletion signal (see `deleted_at`/`deleted_by`
    # below) -- there is deliberately no separate `is_deleted` boolean here,
    # unlike every other soft-deletable table. Two independent flags claiming
    # to answer "is this account gone?" is how they drift apart.
    status: Mapped[UserStatus] = mapped_column(
        SQLEnum(UserStatus, name="user_status", native_enum=False),
        server_default=text(f"'{UserStatus.ACTIVE.value}'"),
        nullable=False,
        comment="ACTIVE, INACTIVE, SUSPENDED, DELETED",
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    title: Mapped[Optional[str]] = mapped_column(String(6), nullable=True)
    gender: Mapped[Genders] = mapped_column(
        SQLEnum(Genders, name="genders", native_enum=False),
        server_default=text(f"'{Genders.MALE.value}'"),
        nullable=False,
        comment="MALE, FEMALE, OTHER",
    )
    date_of_birth: Mapped[Optional[date]] = utc_date_column(default=False)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Contact & profile (spec §4) ---------------------------------------
    phone_number: Mapped[Optional[str]] = mapped_column(String(75), nullable=True)
    mobile: Mapped[Optional[str]] = mapped_column(String(75), nullable=True)
    designation: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    web: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    postcode: Mapped[Optional[str]] = mapped_column(String(35), nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    country_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("countries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    city_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("cities.id", ondelete="SET NULL"), nullable=True, index=True)
    profile_picture: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, comment="Free-text profile bio", nullable=True)
    is_public: Mapped[bool] = bool_column(default=True, nullable=False)

    # --- Emergency contact (spec §4 explicitly requires this) --------------
    emergency_contact_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    emergency_contact_phone: Mapped[Optional[str]] = mapped_column(String(75), nullable=True)
    emergency_contact_relationship: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # --- Login security ------------------------------------------------------
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True, comment="Last known login IP")
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    is_locked: Mapped[bool] = bool_column(default=False, nullable=False)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    roles: Mapped[List["Role"]] = relationship(
        "Role",
        secondary="user_roles",
        back_populates="users",
        passive_deletes=True,
        lazy="selectin"
    )

    tokens: Mapped[List["Token"]] = relationship("Token", back_populates="user", passive_deletes=True, lazy="selectin")
    sessions: Mapped[List["BatchSession"]] = relationship("BatchSession", back_populates="tutor", lazy="selectin")
    enrollments: Mapped[List["Enrollments"]] = relationship("Enrollments", back_populates="student", foreign_keys="[Enrollments.student_id]", lazy="selectin")
    given_enrollments: Mapped[List["Enrollments"]] = relationship("Enrollments", back_populates="enrolled_by_user", foreign_keys="[Enrollments.enrolled_by]", lazy="selectin")
    attendances: Mapped[List["Attendance"]] = relationship("Attendance", back_populates="student", foreign_keys="[Attendance.student_id]", lazy="selectin")
    recorded_attendances: Mapped[List["Attendance"]] = relationship("Attendance", back_populates="tutor", foreign_keys="[Attendance.recorded_by]", lazy="selectin")
    current_city: Mapped[Optional["City"]] = relationship("City", back_populates="users", foreign_keys=[city_id], lazy="selectin")
    country: Mapped[Optional["Country"]] = relationship("Country", foreign_keys=[country_id], lazy="selectin")
    my_resources: Mapped[List["Resource"]] = relationship("Resource", back_populates="uploader", foreign_keys="Resource.uploaded_by", lazy="selectin")
    shared_resources: Mapped[List["SharedResource"]] = relationship("SharedResource", back_populates="shared_with_user", foreign_keys="[SharedResource.shared_with_user_id]", lazy="selectin")
    shared_to: Mapped[List["SharedResource"]] = relationship("SharedResource", back_populates="shared_by_user", foreign_keys="[SharedResource.shared_by_user_id]", lazy="selectin")
    # `lazy="raise"` on all five, deliberately. These were `selectin`, which
    # means SQLAlchemy issues an extra SELECT for them every time a User is
    # loaded by a query -- and a User is loaded by a query on *every*
    # authenticated request, to resolve permissions. That silently attached
    # "fetch this person's entire message and review history" to the hot
    # path of the whole API. Nothing needs them as collections: the
    # messaging endpoints query `user_messages` directly, with paging and a
    # scope filter, which is the only shape that stays correct once a
    # mailbox has 10,000 rows in it. Raising is preferred to plain lazy
    # loading because a lazy load under asyncio fails as `MissingGreenlet`,
    # which reads like a driver bug rather than "you asked for too much".
    reviews_written: Mapped[List["TutorReview"]] = relationship("TutorReview", foreign_keys="[TutorReview.student_id]", back_populates="student", lazy="raise")
    reviews_received: Mapped[List["TutorReview"]] = relationship("TutorReview", foreign_keys="[TutorReview.tutor_id]", back_populates="tutor", lazy="raise")
    sent_messages: Mapped[List["UserMessage"]] = relationship("UserMessage", back_populates="sender", foreign_keys="[UserMessage.sender_id]", lazy="raise")
    received_messages: Mapped[List["UserMessage"]] = relationship("UserMessage", back_populates="recipient", foreign_keys="[UserMessage.recipient_id]", lazy="raise")
    # `AuditLog.actor_user_id` deliberately carries no `ForeignKey` (an audit
    # record must outlive the user it describes -- see audit.py's module
    # docstring), so SQLAlchemy has nothing to infer the join from on either
    # side; `primaryjoin`/`viewonly` here must mirror `AuditLog.actor` exactly.
    audit_logs: Mapped[List["AuditLog"]] = relationship(
        "AuditLog",
        primaryjoin="foreign(AuditLog.actor_user_id) == User.id",
        back_populates="actor",
        viewonly=True,
        lazy="selectin",
    )
    shared_links_sent: Mapped[List["SharedLink"]] = relationship("SharedLink", back_populates="shared_by_user", lazy="selectin")
    shared_links_received: Mapped[List["SharedLinkTarget"]] = relationship("SharedLinkTarget", back_populates="shared_with_user", lazy="selectin")
    courses: Mapped[List["Course"]] = relationship(
        "Course",
        secondary="tutor_courses",
        back_populates="tutors",
        lazy="selectin"
    )
    quiz_attempts: Mapped[List["QuizAttempt"]] = relationship(back_populates="student")
    submissions: Mapped[List["AssignmentSubmission"]] = relationship(
        primaryjoin="User.id == AssignmentSubmission.student_id",
        back_populates="student"
    )
    graded_submissions: Mapped[List["AssignmentSubmission"]] = relationship(
        primaryjoin="User.id == AssignmentSubmission.graded_by_id",
        back_populates="grader"
    )
    issued_certificates: Mapped[List["CertificateIssued"]] = relationship(back_populates="student")
    user_badges: Mapped[List["UserBadge"]] = relationship(back_populates="user")
    notifications: Mapped[List["Notification"]] = relationship(back_populates="user", lazy="raise")

    # Corporate organization -- kept as a full history (INVITED/ACTIVE/
    # SUSPENDED/REMOVED rows), not a single current value, since a
    # reassigned manager or removed employee's earlier row is data, not
    # noise. A service layer resolves "the current one" by filtering on
    # is_active / status, exactly as it already must for enrollments.
    organization_manager_memberships: Mapped[List["OrganizationManager"]] = relationship(
        "OrganizationManager", back_populates="user", lazy="selectin"
    )
    organization_memberships: Mapped[List["OrganizationMembership"]] = relationship(
        "OrganizationMembership", foreign_keys="[OrganizationMembership.user_id]", back_populates="user", lazy="selectin"
    )

    # Guardian <-> student, both directions of the same many-to-many table.
    guardians: Mapped[List["StudentGuardian"]] = relationship(
        "StudentGuardian", foreign_keys="[StudentGuardian.student_id]", back_populates="student", lazy="selectin"
    )
    wards: Mapped[List["StudentGuardian"]] = relationship(
        "StudentGuardian", foreign_keys="[StudentGuardian.guardian_id]", back_populates="guardian", lazy="selectin"
    )

    __table_args__ = (
        Index(
            "idx_users_status_locked",
            "status",
            "is_locked",
        ),
        Index(
            "idx_users_id_status",
            "id",
            "status",
        ),
    )

    # Convenience
    @property
    def full_name(self) -> str:
        if not (self.first_name or self.last_name):
            return self.username or ""
        if not self.first_name:
            return self.last_name or ""
        if not self.last_name:
            return self.first_name or ""
        return f"{self.first_name} {self.last_name}"

    @property
    def is_locked_out(self) -> bool:
        """Is this account currently shut out by the failed-login lockout?

        **One rule, one place.** This was written out twice and the two
        disagreed: `auth_service` honoured `locked_until`, so a lapsed lock
        let somebody sign in; `api/deps.get_current_user` read the raw
        `is_locked` flag, so the token that sign-in produced was rejected on
        every subsequent request. Same account, same instant, opposite
        answers, and the 401 said only "Authentication required". A third
        reading then appeared in this phase's `/security/locked-accounts`
        query. The drift was the defect, not any one of the three readings,
        which is why the fix is a shared predicate rather than three edits.

        A lock with **no expiry** counts as locked, and that is the reading
        the other implementation got wrong: the failed-login path always sets
        an expiry, so a NULL `locked_until` can only come from a deliberate
        administrative lock -- and treating that as "already over" makes an
        indefinite lock inexpressible. A security flag fails closed.

        The equivalent SQL lives in `services/security_service.py`; a Python
        property cannot run inside a WHERE clause, so that one is a mirror by
        necessity and a test asserts the two agree on every state.
        """
        if not self.is_locked:
            return False
        if self.locked_until is None:
            return True
        return self.locked_until > datetime.now(timezone.utc)

    def has_roles(self, roles: List[str]) -> bool:
        user_role_names = {r.name.lower() for r in (self.roles or [])}
        return any(role.lower() in user_role_names for role in roles)

    def has_permissions(self, permissions: List[str]) -> bool:
        if not self.roles:
            return False
        user_permissions = {perm.name.lower() for role in self.roles for perm in (role.permissions or [])}
        return any(p.lower() in user_permissions for p in permissions)

    @property
    def is_super_admin(self) -> bool:
        return self.has_roles([Roles.SUPER_ADMIN.name])

    @property
    def is_admin(self) -> bool:
        return self.has_roles([Roles.ADMIN.name])

    @property
    def is_tutor(self) -> bool:
        return self.has_roles([Roles.TUTOR.name])

    @property
    def is_student(self) -> bool:
        return self.has_roles([Roles.STUDENT.name])

    @property
    def is_corporate_manager(self) -> bool:
        return self.has_roles([Roles.CORPORATE_MANAGER.name])

    @property
    def is_guardian(self) -> bool:
        return self.has_roles([Roles.GUARDIAN.name])

    @staticmethod
    async def generate_slug(username: str, db: AsyncSession) -> str:
        """Generate a unique slug for a username.

        Takes a plain `AsyncSession` -- not a FastAPI `Depends()`-wrapped
        type. A domain model must not know that FastAPI, or any particular
        web framework, exists; that's what keeps it usable from a worker,
        a script, or a test with no HTTP server involved.
        """

        base_slug = slugify(username, max_length=80, lowercase=True, separator="-")
        slug = base_slug

        result = await db.execute(
            select(User.slug).where(User.slug.ilike(f"{base_slug}%"))
        )
        existing = {row[0] for row in result.all()}

        if slug not in existing:
            return slug

        counter = 1
        while counter <= 1000:  # safety limit
            candidate = f"{base_slug}-{counter}"
            if candidate not in existing:
                return candidate
            counter += 1

        raise RuntimeError("Too many slug duplicates for username.")


class CurrentUser(NamedTuple):
    user: User
    permissions: Set[str]
