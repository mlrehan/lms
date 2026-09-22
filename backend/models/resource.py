from datetime import datetime

from sqlalchemy import (Integer, String, ForeignKey, Index,
                        Enum as SQLEnum, UniqueConstraint, text, CheckConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from backend.models.base import Base, PublicIdMixin
from .helpers import utc_datetime_column, bool_column
from backend.utils.enums import ResourceType, ResourceScopeType, ResourcePermissionLevel


class ResourceFolder(Base, PublicIdMixin):
    """Spec §10's folder hierarchy. Self-referential so a folder tree can be
    built under a course or batch."""
    __tablename__ = "resource_folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_folder_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("resource_folders.id", ondelete="CASCADE"), nullable=True, index=True
    )
    course_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=True)
    batch_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("batches.id", ondelete="CASCADE"), nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = utc_datetime_column(nullable=False)

    parent: Mapped[Optional["ResourceFolder"]] = relationship("ResourceFolder", remote_side=[id], back_populates="children")
    children: Mapped[List["ResourceFolder"]] = relationship("ResourceFolder", back_populates="parent", lazy="selectin")
    resources: Mapped[List["Resource"]] = relationship("Resource", back_populates="folder", lazy="selectin")
    # The anchor columns existed but had no relationships, so a folder could
    # not report which course or batch it belonged to -- the API returned
    # null for both even when they were set.
    course: Mapped[Optional["Course"]] = relationship("Course", foreign_keys=[course_id], lazy="selectin")
    batch: Mapped[Optional["Batch"]] = relationship("Batch", foreign_keys=[batch_id], lazy="selectin")
    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by], lazy="selectin")

    __table_args__ = (
        Index("idx_resource_folders_parent", "parent_folder_id"),
        Index("idx_resource_folders_course", "course_id"),
        Index("idx_resource_folders_batch", "batch_id"),
    )


class Resource(Base, PublicIdMixin):
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    resource_type: Mapped[ResourceType] = mapped_column(
        SQLEnum(ResourceType, name="resource_type", native_enum=False),
        server_default=text(f"'{ResourceType.lecture_sheet.name}'"),
        nullable=False,
        comment="Enum: lecture_sheet, lesson, document, video, audio, presentation, quiz, assignment, certificate, progress_report, announcement, policy_document, custom_content"
    )
    name: Mapped[Optional[str]] = mapped_column(String)
    course_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("courses.id"))
    batch_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("batches.id"))
    folder_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("resource_folders.id", ondelete="SET NULL"), nullable=True)

    # Denormalized pointer to the *current* version's file metadata, kept in
    # sync by the (future, out of this pass's scope) service layer whenever a
    # new ResourceVersion is added -- lets a caller read "what does this
    # resource point to right now" without a join, while ResourceVersion
    # below carries the full upload history spec §10 calls "Versioning".
    path: Mapped[Optional[str]] = mapped_column(String)
    mime_type: Mapped[Optional[str]] = mapped_column(String)
    size: Mapped[Optional[int]] = mapped_column(Integer)

    uploaded_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"))
    modified_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"))
    is_deleted: Mapped[bool] = bool_column(default=False)
    created_at: Mapped[datetime] = utc_datetime_column(nullable=False)
    updated_at: Mapped[datetime] = utc_datetime_column(onupdate=True)
    deleted_at: Mapped[datetime] = utc_datetime_column(default=False)

    share_token: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    folder: Mapped[Optional["ResourceFolder"]] = relationship("ResourceFolder", back_populates="resources", lazy="selectin")
    uploader: Mapped["User"] = relationship("User", foreign_keys=[uploaded_by], back_populates="my_resources", lazy="selectin")
    course: Mapped["Course"] = relationship("Course", back_populates="resources", foreign_keys=[course_id], lazy="selectin")
    # Same omission the folder above already had: the column was set on upload but nothing could read it back,
    # so a batch-scoped resource reported batch_id null and no client could filter by batch.
    batch: Mapped[Optional["Batch"]] = relationship("Batch", foreign_keys=[batch_id], lazy="selectin")
    versions: Mapped[List["ResourceVersion"]] = relationship(
        "ResourceVersion", back_populates="resource",
        cascade="all, delete-orphan", passive_deletes=True,
        order_by="ResourceVersion.version_number", lazy="selectin",
    )
    shared_resources: Mapped[List["SharedResource"]] = relationship(
        "SharedResource",
        back_populates="resource",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin"
    )

    __table_args__ = (
        Index("ix_resources_course_id", "course_id"),
        Index("ix_resources_uploaded_by", "uploaded_by"),
        Index("ix_resources_created_at", "created_at"),
        Index("ix_resources_folder_id", "folder_id"),
    )


class ResourceVersion(Base):
    """Spec §10's "Versioning" -- one row per upload of a resource's file."""
    __tablename__ = "resource_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_id: Mapped[int] = mapped_column(Integer, ForeignKey("resources.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    path: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    uploaded_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    change_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = utc_datetime_column(nullable=False)

    resource: Mapped["Resource"] = relationship("Resource", back_populates="versions", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("resource_id", "version_number", name="uq_resource_versions_resource_version"),
    )


class ResourcePermission(Base):
    """Spec §11's cascade: Course -> Batch -> Session -> Individual. One
    generic table instead of four bespoke permission tables; `scope_type`
    says which level `scope_id` refers to."""
    __tablename__ = "resource_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("resources.id", ondelete="CASCADE"), nullable=True)
    folder_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("resource_folders.id", ondelete="CASCADE"), nullable=True)
    scope_type: Mapped[ResourceScopeType] = mapped_column(
        SQLEnum(ResourceScopeType, name="resource_scope_type", native_enum=False), nullable=False,
    )
    scope_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="course_id/batch_id/session_id/user_id depending on scope_type")
    level: Mapped[ResourcePermissionLevel] = mapped_column(
        SQLEnum(ResourcePermissionLevel, name="resource_permission_level", native_enum=False), nullable=False,
    )
    granted_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = utc_datetime_column(nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(resource_id IS NOT NULL) <> (folder_id IS NOT NULL)",
            name="exactly_one_target",
        ),
        Index("idx_resource_permissions_resource", "resource_id"),
        Index("idx_resource_permissions_folder", "folder_id"),
        Index("idx_resource_permissions_scope", "scope_type", "scope_id"),
    )


class SharedResource(Base):
    """User-to-user resource sharing."""
    __tablename__ = "shared_resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=False
    )
    shared_with_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    shared_by_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    # What the recipient may do with it. A share had no level at all, so every
    # share was implicitly "whatever the recipient's global role allows" -- which
    # is how a read-only audience ended up able to download and, for staff, edit.
    # DOWNLOAD is the default because handing someone a file and forbidding them
    # to keep it is the unusual case, not the common one; VIEW expresses that.
    level: Mapped[ResourcePermissionLevel] = mapped_column(
        SQLEnum(ResourcePermissionLevel, name="resource_permission_level", native_enum=False),
        nullable=False,
        server_default=text(f"'{ResourcePermissionLevel.DOWNLOAD.value}'"),
    )
    created_at: Mapped[datetime] = utc_datetime_column(nullable=False)

    __table_args__ = (UniqueConstraint('resource_id', 'shared_with_user_id', name="uq_shared_resources_resource_user"),)

    resource: Mapped[Resource] = relationship(Resource, back_populates="shared_resources", lazy="selectin")
    shared_with_user: Mapped["User"] = relationship("User", foreign_keys=[shared_with_user_id], back_populates="shared_resources", lazy="selectin")
    shared_by_user: Mapped["User"] = relationship("User", foreign_keys=[shared_by_user_id], back_populates="shared_to", lazy="selectin")
