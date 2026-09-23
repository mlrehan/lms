"""Mark material whose audience is staff.

The brief asks for video and audio that colleagues can share without it
reaching students, guardians or corporate managers. That is an audience
question, not a permission *level* one: `shared_resources.level` already says
what a recipient may do with a file, and no value of it says "and this person
should never have been offered the file at all".

So one boolean, read alongside the existing level ladder rather than instead of
it. A restricted resource is refused to anyone without `resource.view_restricted`
*before* any share or grant is consulted -- a restriction a share could override
would protect nothing, and sharing is exactly how this material travels between
staff.

Deliberately on the resource and not inherited from a folder: a file dragged
out of a "Staff only" folder would otherwise become visible to a class as a
silent side effect of tidying up.

Revision ID: a93e17c0d5b8
Revises: f2a8d3b61c94
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a93e17c0d5b8"
down_revision = "f2a8d3b61c94"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resources",
        sa.Column(
            "is_restricted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Every existing file stays exactly as visible as it was. Restricting in
    # bulk would hide material a class is already using, and the people who
    # would notice are the ones who cannot fix it.
    op.create_index(
        "ix_resources_is_restricted",
        "resources",
        ["is_restricted"],
        postgresql_where=sa.text("is_restricted"),
    )


def downgrade() -> None:
    op.drop_index("ix_resources_is_restricted", table_name="resources")
    op.drop_column("resources", "is_restricted")
