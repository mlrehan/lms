"""A cancelled session no longer occupies its (batch, start time) slot.

Revision ID: e6b2d84a1c39
Revises: d5a1c93f7e20
Create Date: 2026-09-21 11:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6b2d84a1c39"
down_revision: Union[str, Sequence[str], None] = "d5a1c93f7e20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ux_batch_sessions_batch_start", table_name="batch_sessions")
    # A cancelled class is history; a replacement in the same slot is a new session.
    op.create_index("ux_batch_sessions_batch_start", "batch_sessions", ["batch_id", "session_start_time"], unique=True,
                    postgresql_where=sa.text("cancelled_at IS NULL"))


def downgrade() -> None:
    op.drop_index("ux_batch_sessions_batch_start", table_name="batch_sessions")
    op.create_index("ux_batch_sessions_batch_start", "batch_sessions", ["batch_id", "session_start_time"], unique=True)
