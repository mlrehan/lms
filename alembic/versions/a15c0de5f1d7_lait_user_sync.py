"""LAIT user sync: can_login gate, external ids, wider title, run history

Revision ID: a15c0de5f1d7
Revises: 6612ea1b2250
Create Date: 2026-09-20 10:00:00.000000

`can_login` is added so that every account that exists *today* keeps working
and every account created *after* this starts closed:

    1. add the column with server_default TRUE  -> existing rows become TRUE
    2. flip the server_default to FALSE          -> new rows default to FALSE

Adding it straight away as `DEFAULT false` would silently lock out every
current user, including the only Super Admin, with no way back through the
application.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a15c0de5f1d7"
down_revision: Union[str, Sequence[str], None] = "6612ea1b2250"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- users.can_login: existing accounts stay open, new ones start closed --
    op.add_column(
        "users",
        sa.Column(
            "can_login",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
            comment="False = cannot sign in, whatever the password. Set by a Super Admin.",
        ),
    )
    op.alter_column("users", "can_login", server_default=sa.text("false"))

    # -- external LAIT identities --------------------------------------------
    op.add_column("users", sa.Column("external_student_id", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("external_tutor_id", sa.Integer(), nullable=True))
    op.create_unique_constraint("uq_users_external_student_id", "users", ["external_student_id"])
    op.create_unique_constraint("uq_users_external_tutor_id", "users", ["external_tutor_id"])

    # -- titles longer than 6 characters ("Professor", "Reverend") --------------
    op.alter_column(
        "users",
        "title",
        existing_type=sa.String(length=6),
        type_=sa.String(length=20),
        existing_nullable=True,
    )

    # -- run history, and the one-at-a-time lock -------------------------------
    op.create_table(
        "user_sync_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("trigger_type", sa.String(length=10), nullable=False),
        sa.Column("triggered_by_user_id", sa.Integer(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stats", sa.JSON(), nullable=True),
        sa.Column("errors", sa.JSON(), nullable=True),
        sa.Column("failure_reason", sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(["triggered_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_sync_runs_public_id", "user_sync_runs", ["public_id"], unique=True)
    op.create_index("ix_user_sync_runs_status", "user_sync_runs", ["status"], unique=False)
    op.create_index("ix_user_sync_runs_started_at", "user_sync_runs", ["started_at"], unique=False)
    op.create_index(
        "ux_user_sync_runs_one_running",
        "user_sync_runs",
        [sa.text("(true)")],
        unique=True,
        postgresql_where=sa.text("status = 'RUNNING'"),
    )


def downgrade() -> None:
    op.drop_index("ux_user_sync_runs_one_running", table_name="user_sync_runs")
    op.drop_index("ix_user_sync_runs_started_at", table_name="user_sync_runs")
    op.drop_index("ix_user_sync_runs_status", table_name="user_sync_runs")
    op.drop_index("ix_user_sync_runs_public_id", table_name="user_sync_runs")
    op.drop_table("user_sync_runs")

    # Narrowing can fail if a title longer than 6 characters was stored.
    op.alter_column(
        "users",
        "title",
        existing_type=sa.String(length=20),
        type_=sa.String(length=6),
        existing_nullable=True,
    )

    op.drop_constraint("uq_users_external_tutor_id", "users", type_="unique")
    op.drop_constraint("uq_users_external_student_id", "users", type_="unique")
    op.drop_column("users", "external_tutor_id")
    op.drop_column("users", "external_student_id")
    op.drop_column("users", "can_login")
