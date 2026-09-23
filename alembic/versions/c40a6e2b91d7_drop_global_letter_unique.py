"""Actually drop the global unique on `grade_bands.letter_grade`.

Migration `b71f2c8ea940` intended to do this and did not. It ran

    ALTER TABLE grade_bands DROP CONSTRAINT IF EXISTS grade_bands_letter_grade_key

guessing Postgres's default constraint name, but the column was declared with
`unique=True` inside a named-convention model, so the real name is
`uq_grade_bands_letter_grade`. `IF EXISTS` then made the miss **silent**: the
migration reported success, the replacement per-scheme constraint was added
alongside the old one, and the global unique stayed in force.

The symptom is exactly what the original migration's own comment said it was
avoiding: two schemes cannot both define an "A" or an "F", so the second scheme
an institution creates cannot be given a grade ladder at all.

No `IF EXISTS` here. If this constraint is not present the migration should
fail loudly rather than quietly leave the database in the state this one exists
to correct.

Revision ID: c40a6e2b91d7
Revises: b71f2c8ea940
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c40a6e2b91d7"
down_revision = "b71f2c8ea940"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_grade_bands_letter_grade", "grade_bands", type_="unique")


def downgrade() -> None:
    # Restoring it can fail on data the new rule legitimately permits (two
    # schemes each with an "A"), which is correct: the downgrade should refuse
    # rather than silently delete somebody's grade ladder to fit.
    op.create_unique_constraint(
        "uq_grade_bands_letter_grade", "grade_bands", ["letter_grade"]
    )
