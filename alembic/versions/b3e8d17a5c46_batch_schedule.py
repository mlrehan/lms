"""How a batch is scheduled: training days, clock times, duration, method, fee.

Revision ID: b3e8d17a5c46
Revises: a9d4e6b18c02
Create Date: 2026-09-22 09:00:00.000000

All nullable: a batch created by hand has none of this until an administrator generates its sessions, and one
synced before this column existed is filled by the next LAIT sync (or inferred from its existing sessions).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3e8d17a5c46"
down_revision: Union[str, Sequence[str], None] = "a9d4e6b18c02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("batches", sa.Column("training_days", sa.String(100), nullable=True))
    op.add_column("batches", sa.Column("training_start_day", sa.String(12), nullable=True))
    op.add_column("batches", sa.Column("training_end_day", sa.String(12), nullable=True))
    op.add_column("batches", sa.Column("training_start_time", sa.Time(), nullable=True))
    op.add_column("batches", sa.Column("training_end_time", sa.Time(), nullable=True))
    op.add_column("batches", sa.Column("class_duration_minutes", sa.Integer(), nullable=True))
    op.add_column("batches", sa.Column("training_method", sa.String(100), nullable=True))
    op.add_column("batches", sa.Column("batch_fee", sa.Numeric(10, 2), nullable=True))
    op.add_column("batches", sa.Column("schedule_timezone", sa.String(50), nullable=True))


def downgrade() -> None:
    for name in ("schedule_timezone", "batch_fee", "training_method", "class_duration_minutes", "training_end_time",
                 "training_start_time", "training_end_day", "training_start_day", "training_days"):
        op.drop_column("batches", name)
