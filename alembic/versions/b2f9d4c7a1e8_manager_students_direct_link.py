"""Link a Corporate Manager to their students directly, not through the company.

Revision ID: b2f9d4c7a1e8
Revises: f17c4a9b0e23

A manager's roster was derived: manager -> `organization_managers` ->
`organization_memberships` -> every employee of that company. So a company
with four managers and two hundred employees gave each manager all two
hundred, and "these thirty are yours" was not expressible. Visibility was a
side effect of the org chart.

`manager_students` is the same shape as `student_guardians`, and for the same
reason: many managers per student, many students per manager, with its own
history. It is now the **only** thing that decides which students a manager
can read -- `ScopeResolver` asks it, and everything student-scoped asks
`ScopeResolver`.

**The backfill is the important half.** Every (active manager, visible
member) pair in the same organization becomes a row, so the day this ships
every manager sees exactly the students they saw yesterday and nothing
changes under them. Without it, every corporate manager would open the
console to an empty roster. Administrators can then narrow the rosters
deliberately, which is the point of the change.

`relationship_type` is left null by the backfill rather than invented: the
link is real, the description of it is not something this migration knows.

What the company keeps: who employs whom (`organization_memberships`, with
its employee code and department), which company a manager works for
(`organization_managers`), and which company sponsored an enrollment
(`enrollments.organization_id` -- deliberately historical, and the one thing
here that could not be reconstructed if it were dropped).

Downgrade drops the table. The derived rosters are reconstructible from the
org graph, which is untouched, so nothing is lost that cannot be rebuilt.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b2f9d4c7a1e8"
down_revision = "f17c4a9b0e23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manager_students",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("manager_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("relationship_type", sa.String(length=50), nullable=True),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["manager_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "manager_id", "student_id", name="uq_manager_students_manager_student"
        ),
    )
    op.create_index("idx_manager_students_manager", "manager_students", ["manager_id"])
    op.create_index("idx_manager_students_student", "manager_students", ["student_id"])
    op.create_index(
        "ix_manager_students_public_id", "manager_students", ["public_id"], unique=True
    )

    # Preserve exactly today's visibility. The statuses mirror
    # `_VISIBLE_MEMBERSHIP_STATUSES` in `services/scope.py`: an employee who
    # has been REMOVED was already invisible and must not become visible now.
    op.execute(
        """
        INSERT INTO manager_students (public_id, manager_id, student_id)
        SELECT DISTINCT gen_random_uuid(), om.user_id, mem.user_id
        FROM organization_managers om
        JOIN organization_memberships mem
          ON mem.organization_id = om.organization_id
        WHERE om.is_active
          AND mem.status IN ('INVITED', 'ACTIVE', 'SUSPENDED')
          AND om.user_id <> mem.user_id
        ON CONFLICT ON CONSTRAINT uq_manager_students_manager_student DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_manager_students_public_id", table_name="manager_students")
    op.drop_index("idx_manager_students_student", table_name="manager_students")
    op.drop_index("idx_manager_students_manager", table_name="manager_students")
    op.drop_table("manager_students")
