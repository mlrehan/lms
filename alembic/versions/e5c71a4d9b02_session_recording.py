"""Point a session at its recording, stored in the LMS.

`batch_sessions.recording_link` holds a provider's URL -- a Zoom or Meet page
that is reachable by anyone who has the string, whether or not they were ever
in the class. It stays, because staff use it, but it can never be the answer to
"let the students watch the class back": handing it over is handing over a link
that works outside the LMS and past every check in it.

So a recording uploaded here becomes an ordinary `resources` row (inheriting the
permission ladder, versioning and soft-delete that module already has) and the
session points at it. Playback is then a stream through this API, permission
checked on every request, with no URL to copy.

`ON DELETE SET NULL` rather than CASCADE: deleting the recording file must not
delete the record that the class happened.

Revision ID: e5c71a4d9b02
Revises: d8b1f4e07a23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e5c71a4d9b02"
down_revision = "d8b1f4e07a23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "batch_sessions",
        sa.Column("recording_resource_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_batch_sessions_recording_resource",
        "batch_sessions",
        "resources",
        ["recording_resource_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_batch_sessions_recording_resource",
        "batch_sessions",
        ["recording_resource_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_batch_sessions_recording_resource", table_name="batch_sessions")
    op.drop_constraint(
        "fk_batch_sessions_recording_resource", "batch_sessions", type_="foreignkey"
    )
    op.drop_column("batch_sessions", "recording_resource_id")
