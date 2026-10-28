"""Immutable audit log ORM model (spec §19).

The previous version of this model was a database-query-tool's audit trail --
`connection_id`, `session_id`, `engine`, `statement`, `destructive`,
`rows_affected` -- logging raw SQL execution against arbitrary "target
databases". None of that is this product. Spec §19 asks for exactly: Login,
Logout, Create, Update, Delete, Permission changes, Downloads, Uploads, Failed
login -- entity-scoped actions, not SQL statements.

Identity is intentionally denormalized (`actor_email` alongside
`actor_user_id`, no hard FK) so an audit record survives deletion of the user
it describes -- an audit trail must outlive the account, and a plain FK with
`ON DELETE CASCADE` (or a `NOT NULL` FK at all) would let deleting a user
quietly erase the record of what that user did. Writing rows is a
service-layer concern for a later pass; this model only needs to be able to
hold them correctly.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, PublicIdMixin


class AuditLog(Base, PublicIdMixin):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Identity -- denormalized, no FK (see module docstring).
    actor_user_id: Mapped[int | None] = mapped_column(index=True, nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    # What happened. Spec §19's exact tracked-event list, plus room for
    # future entity-specific actions (e.g. "ENROLLMENT_TRANSFER").
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False,
                                         comment="LOGIN, LOGOUT, LOGIN_FAILED, CREATE, UPDATE, DELETE, "
                                                 "PERMISSION_CHANGE, DOWNLOAD, UPLOAD, ...")
    entity_type: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True,
                                                      comment="e.g. 'course', 'enrollment', 'role'")
    entity_id: Mapped[int | None] = mapped_column(nullable=True)

    # Context -- before/after values or any other non-secret detail.
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Client IP that initiated the request, resolved by `core/client_ip.py`
    # (forwarding headers believed only from a trusted proxy). NULL when the
    # client could not be identified, or when no request caused the event.
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # PUBLIC / PRIVATE / LOOPBACK / RESERVED / UNAVAILABLE; NULL when no
    # request caused the event (a scheduled sync) and for rows written before
    # this column existed -- which are deliberately not backfilled.
    ip_scope: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Approximate location of `ip_address`, from a local GeoLite2 lookup made
    # when the row was written (the table is append-only, so it can only ever
    # describe the address at that moment). An estimate of where the network
    # is, never a person's physical location.
    geo_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    geo_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    geo_country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    geo_country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    geo_region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    geo_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    geo_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    geo_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    geo_accuracy_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )

    # No `ForeignKey` exists on `actor_user_id` (see module docstring), so
    # SQLAlchemy has no constraint to infer the join from -- `primaryjoin`
    # spells it out explicitly. `viewonly=True` because writes to this table
    # go through the service layer, keyed on whatever `actor_user_id` was at
    # the moment of the action, not through mutating this relationship.
    actor: Mapped["User | None"] = relationship(
        "User",
        primaryjoin="foreign(AuditLog.actor_user_id) == User.id",
        back_populates="audit_logs",
        viewonly=True,
        # `lazy="raise"`, not `selectin`. `User` carries twenty eager
        # relationships of its own, so loading the actor for a page of fifty
        # audit rows would fan out into hundreds of queries -- on the one
        # endpoint whose whole job is to page through a large table. The row
        # already denormalizes `actor_email` precisely so the join is not
        # needed; the read path resolves actor public ids in a single batch
        # query instead (see `repositories/audit.py`).
        lazy="raise",
    )

    # The three questions this table is actually asked, and none of them are
    # served by the single-column indexes alone: "what did this person do",
    # "what happened to this record", "what happened in this window".
    # `entity_id` had no index at all, so the per-entity trail was a full scan.
    __table_args__ = (
        Index("ix_audit_logs_actor_created", "actor_user_id", "created_at"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id", "created_at"),
        Index("ix_audit_logs_action_created", "action", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AuditLog id={self.id} actor={self.actor_email!r} action={self.action}>"
