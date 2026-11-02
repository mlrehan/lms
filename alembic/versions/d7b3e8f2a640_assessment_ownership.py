"""Assessment ownership and soft deletion

`assignments`, `quizzes` and `exams` recorded no author, so "a tutor's own
assessment" had nothing to be decided on. Each gains:

* `created_by` -- the author. Backfilled from the append-only audit trail's
  CREATE row for that entity, which every existing assessment has. A row the
  trail cannot attribute stays NULL and is treated as institution-owned.
* `deleted_at` / `deleted_by` -- deletion withdraws an assessment instead of
  removing it, so students' submissions, marks, grade-book entries and
  transcripts are never cascaded away.

Revision ID: d7b3e8f2a640
Revises: c6a9e2d4f1b7
Create Date: 2026-11-02 09:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7b3e8f2a640"
down_revision: Union[str, None] = "c6a9e2d4f1b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = (("assignments", "assignment"), ("quizzes", "quiz"), ("exams", "exam"))


def upgrade() -> None:
    for table, entity in _TABLES:
        for column in ("created_by", "deleted_by"):
            op.add_column(table, sa.Column(column, sa.Integer(), nullable=True))
            op.create_foreign_key(
                f"fk_{table}_{column}", table, "users", [column], ["id"], ondelete="SET NULL"
            )
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index(f"ix_{table}_created_by", table, ["created_by"])
        # Almost every read filters on "not deleted"; the partial index keeps
        # that filter free on tables that will mostly hold live rows.
        op.create_index(
            f"ix_{table}_live", table, ["id"], postgresql_where=sa.text("deleted_at IS NULL")
        )
        op.execute(
            sa.text(
                f"""
                UPDATE {table} t SET created_by = src.actor
                FROM (
                    SELECT DISTINCT ON (l.entity_id) l.entity_id, l.actor_user_id AS actor
                    FROM audit_logs l
                    WHERE l.entity_type = :entity AND l.action = 'CREATE'
                      AND l.actor_user_id IS NOT NULL
                    ORDER BY l.entity_id, l.id
                ) src
                WHERE src.entity_id = t.id
                  AND EXISTS (SELECT 1 FROM users u WHERE u.id = src.actor)
                """
            ).bindparams(entity=entity)
        )


def downgrade() -> None:
    for table, _entity in _TABLES:
        op.drop_index(f"ix_{table}_live", table_name=table)
        op.drop_index(f"ix_{table}_created_by", table_name=table)
        for column in ("created_by", "deleted_by"):
            op.drop_constraint(f"fk_{table}_{column}", table, type_="foreignkey")
            op.drop_column(table, column)
        op.drop_column(table, "deleted_at")
