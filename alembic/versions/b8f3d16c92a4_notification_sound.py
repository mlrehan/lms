"""How loudly, if at all, to announce a notification.

Revision ID: b8f3d16c92a4
Revises: a7e4b2c91d35
Create Date: 2026-10-14

One column with a default, so existing rows need no backfill and the migration
reverses cleanly.

**A column on `users`, like `timezone`.** This is a per-person preference about
the interface, not a per-notification-type opt-out -- `notification_preferences`
already holds those, as rows recording only the exceptions. Somebody who wants
the chime off entirely but still wants the notifications is expressing
something that table cannot say.

**`subtle` is the default, not `prominent`.** A new account should not start by
making a noise in a shared office, and the person who needs to be interrupted
knows they need it and will go and say so.

What this cannot promise is written down where it is used: a browser will not
let a page play sound before the person has interacted with it, and the volume
belongs to the device. `prominent` is a longer, more insistent tone -- not a
louder one, because that is not ours to decide.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8f3d16c92a4"
down_revision = "a7e4b2c91d35"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "notification_sound",
            sa.String(length=12),
            nullable=False,
            server_default="subtle",
        ),
    )
    op.create_check_constraint(
        "ck_users_notification_sound",
        "users",
        "notification_sound IN ('off', 'subtle', 'prominent')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_notification_sound", "users", type_="check")
    op.drop_column("users", "notification_sound")
