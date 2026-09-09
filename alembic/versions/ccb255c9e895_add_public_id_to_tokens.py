"""add public_id to tokens

Sessions became addressable over the API (list your devices, revoke one), so
`tokens` needs an identifier that is safe to expose. The integer primary key
is sequential and therefore enumerable, which is the same reason every other
table in this schema carries `public_id`.

Also picks up a named CHECK constraint on `tutor_reviews.rating` that the
model declared but the initial migration created anonymously -- unrelated to
the tokens change, but leaving model/database drift in place is worse than
carrying it along.

Revision ID: ccb255c9e895
Revises: ec8f0a2fc9dd
Create Date: 2026-08-26 16:54:48.939915

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ccb255c9e895'
down_revision: Union[str, Sequence[str], None] = 'ec8f0a2fc9dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Adds `public_id` in the three steps required for a NOT NULL column on a
    populated table. Autogenerate emitted this as a single
    `add_column(..., nullable=False)`, which succeeds only while `tokens` is
    empty and fails outright against any environment where somebody has
    already signed in -- i.e. it would pass in development and break the
    production deploy.
    """
    # 1. Add nullable, so existing rows are accepted.
    op.add_column('tokens', sa.Column('public_id', sa.Uuid(), nullable=True))

    # 2. Backfill. `gen_random_uuid()` is built into PostgreSQL 13+, so no
    #    pgcrypto extension is needed.
    op.execute('UPDATE tokens SET public_id = gen_random_uuid() WHERE public_id IS NULL')

    # 3. Now that every row has a value, enforce it.
    op.alter_column('tokens', 'public_id', nullable=False)

    op.create_index(op.f('ix_tokens_public_id'), 'tokens', ['public_id'], unique=True)
    op.create_check_constraint(op.f('ck_tutor_reviews_rating_range'), 'tutor_reviews', 'rating >= 0 AND rating <= 5')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('ck_tutor_reviews_rating_range'), 'tutor_reviews', type_='check')
    op.drop_index(op.f('ix_tokens_public_id'), table_name='tokens')
    op.drop_column('tokens', 'public_id')
