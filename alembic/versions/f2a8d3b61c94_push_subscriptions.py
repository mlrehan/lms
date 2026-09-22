"""Remember which devices have agreed to be interrupted.

Web Push needs somewhere to keep the endpoint a browser was given and the two
public keys it generated, per device. One row per browser profile rather than
per person: a laptop and a phone are two subscriptions, and pushing to one is
not pushing to the other.

`endpoint` is unique table-wide, not per user. A push endpoint identifies a
browser installation, so the same one appearing under two accounts would mean
one person's notifications arriving on another's device -- re-registering moves
it rather than duplicating it.

`ON DELETE CASCADE` from `users`: a deleted account must stop being pushed to
immediately, and there is nothing in this row worth keeping without its owner.

Revision ID: f2a8d3b61c94
Revises: e5c71a4d9b02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f2a8d3b61c94"
down_revision = "e5c71a4d9b02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(length=255), nullable=False),
        sa.Column("auth", sa.String(length=255), nullable=False),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_unique_constraint("uq_push_subscriptions_public_id", "push_subscriptions", ["public_id"])
    op.create_index("ix_push_subscriptions_public_id", "push_subscriptions", ["public_id"])
    op.create_unique_constraint("uq_push_subscriptions_endpoint", "push_subscriptions", ["endpoint"])
    op.create_index("ix_push_subscriptions_user", "push_subscriptions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_push_subscriptions_user", table_name="push_subscriptions")
    op.drop_constraint("uq_push_subscriptions_endpoint", "push_subscriptions", type_="unique")
    op.drop_index("ix_push_subscriptions_public_id", table_name="push_subscriptions")
    op.drop_constraint("uq_push_subscriptions_public_id", "push_subscriptions", type_="unique")
    op.drop_table("push_subscriptions")
