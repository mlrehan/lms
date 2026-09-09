from sqlalchemy import Integer, String, ForeignKey, Boolean, DateTime, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from backend.models.base import Base, PublicIdMixin, TimestampMixin, utc_now
from backend.utils.enums import TokenType
from datetime import datetime

class Token(Base, TimestampMixin, PublicIdMixin):
    """A refresh-token session.

    Carries `public_id` because sessions are addressable over the API -- a
    user listing their active devices and revoking one needs an identifier
    for each, and the integer PK is sequential and therefore enumerable.
    """

    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # A hash of the token, never the raw value -- a leaked `tokens` table row
    # (a backup, a stray log line, a compromised replica) must not itself be a
    # usable credential. Hashing happens in the auth service layer, out of
    # scope for this model, but the column name documents the contract so a
    # future caller can't accidentally write the plaintext token here.
    token_hash: Mapped[str] = mapped_column(String(500), unique=True, index=True, nullable=False)

    token_type: Mapped[TokenType] = mapped_column(
        SQLEnum(TokenType, name="token_type", native_enum=False),
        nullable=False,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    revoked: Mapped[bool] = mapped_column(
            Boolean,
            default=False,
            nullable=False,
        )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Session visibility (spec §3's "Session management") -- enough to let a
    # user see and revoke "which devices am I logged in on?" without needing
    # a separate sessions table for this pass.
    user_agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="tokens", lazy="selectin")
