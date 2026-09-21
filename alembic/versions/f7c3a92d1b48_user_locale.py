"""Where a person was last seen from, and whether their time zone came from that.

Revision ID: f7c3a92d1b48
Revises: e6b2d84a1c39
Create Date: 2026-09-21 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7c3a92d1b48"
down_revision: Union[str, Sequence[str], None] = "e6b2d84a1c39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `false` for every existing row: a time zone somebody already has is treated as chosen by them, so the
    # first address change never overwrites it.
    op.add_column("users", sa.Column("timezone_is_auto", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("users", sa.Column("locale_ip", sa.String(length=45), nullable=True))
    op.add_column("users", sa.Column("locale_info", sa.JSON(), nullable=True))
    op.add_column("users", sa.Column("locale_checked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "locale_checked_at")
    op.drop_column("users", "locale_info")
    op.drop_column("users", "locale_ip")
    op.drop_column("users", "timezone_is_auto")
