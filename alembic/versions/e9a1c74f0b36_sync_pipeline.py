"""Background synchronisation pipeline: one press, six ordered jobs.

Revision ID: e9a1c74f0b36
Revises: d5b8c2e71f43
Create Date: 2026-10-12

Two new tables and nothing else -- no existing column is altered, so this is
safe to run against live data and reverses cleanly.

The partial unique index on `status = 'RUNNING'` is the duplicate-run guard,
and it is deliberately in the schema rather than in the service: two API
processes, or a press racing the scheduler, both reach the same database, and
only the database can settle which one wins.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e9a1c74f0b36"
down_revision = "d5b8c2e71f43"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_pipeline_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("trigger_type", sa.String(length=10), nullable=False),
        sa.Column("triggered_by_user_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(
            ["triggered_by_user_id"], ["users.id"],
            name="fk_sync_pipeline_runs_triggered_by_user_id_users", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sync_pipeline_runs"),
    )
    op.create_index("ix_sync_pipeline_runs_public_id", "sync_pipeline_runs", ["public_id"], unique=True)
    op.create_index("ix_sync_pipeline_runs_status", "sync_pipeline_runs", ["status"])
    op.create_index("ix_sync_pipeline_runs_started_at", "sync_pipeline_runs", ["started_at"])
    # At most one RUNNING pipeline across the whole deployment.
    op.create_index(
        "ux_sync_pipeline_runs_one_running",
        "sync_pipeline_runs",
        [sa.text("(true)")],
        unique=True,
        postgresql_where=sa.text("status = 'RUNNING'"),
    )

    op.create_table(
        "sync_pipeline_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_run_id", sa.Integer(), nullable=False),
        sa.Column("step", sa.String(length=20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("succeeded", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("sync_run_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["pipeline_run_id"], ["sync_pipeline_runs.id"],
            name="fk_sync_pipeline_jobs_pipeline_run_id_sync_pipeline_runs", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"], ["user_sync_runs.id"],
            name="fk_sync_pipeline_jobs_sync_run_id_user_sync_runs", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sync_pipeline_jobs"),
        sa.UniqueConstraint("pipeline_run_id", "step", name="uq_sync_pipeline_jobs_run_step"),
    )
    op.create_index("ix_sync_pipeline_jobs_public_id", "sync_pipeline_jobs", ["public_id"], unique=True)
    op.create_index("ix_sync_pipeline_jobs_pipeline_run_id", "sync_pipeline_jobs", ["pipeline_run_id"])


def downgrade() -> None:
    op.drop_index("ix_sync_pipeline_jobs_pipeline_run_id", table_name="sync_pipeline_jobs")
    op.drop_index("ix_sync_pipeline_jobs_public_id", table_name="sync_pipeline_jobs")
    op.drop_table("sync_pipeline_jobs")
    op.drop_index("ux_sync_pipeline_runs_one_running", table_name="sync_pipeline_runs")
    op.drop_index("ix_sync_pipeline_runs_started_at", table_name="sync_pipeline_runs")
    op.drop_index("ix_sync_pipeline_runs_status", table_name="sync_pipeline_runs")
    op.drop_index("ix_sync_pipeline_runs_public_id", table_name="sync_pipeline_runs")
    op.drop_table("sync_pipeline_runs")
