"""Give an assignment submission somewhere to actually put the files.

Revision ID: d5b8c2e71f43
Revises: c4a7e1f93d20

`assignment_submissions.files` is a JSON column that has always been written
**from the request body** -- `[{"filename": "...", "path": "..."}]`, supplied
by the client. Two things follow from that, and both are bad:

* nothing ever stored a byte, so "file upload" assignments collected text and
  a list of filenames that pointed at nothing;
* `path` was attacker-controlled. The only reason it was not a file-read
  primitive is that no endpoint ever read it back.

An attachment needs identity (to be downloaded), ownership (to be authorised),
and server-owned bytes. A JSON blob can carry none of those, so it gets a
table.

`submission_id` is **nullable**: a student attaches files and then submits, so
the rows exist before the submission does. They are claimed when the
submission is written, which is also what makes an orphan identifiable -- a
row with no submission and nothing claiming it is an abandoned upload a sweep
can reclaim.

The JSON column is left alone. It holds nothing that any code reads now, and
dropping a column whose history we cannot inspect is not worth the risk;
`files` is written from these rows on read instead.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d5b8c2e71f43"
down_revision = "c4a7e1f93d20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assignment_submission_files",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.UUID(), nullable=False),
        sa.Column("assignment_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        # Null until the student submits. See the module docstring.
        sa.Column("submission_id", sa.Integer(), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        # The storage key. Written by the server from `build_key`, never by a
        # client -- which is the whole point of this table.
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=True),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assignment_submission_files")),
        sa.UniqueConstraint("public_id", name=op.f("uq_assignment_submission_files_public_id")),
        sa.ForeignKeyConstraint(
            ["assignment_id"], ["assignments.id"], ondelete="CASCADE",
            name=op.f("fk_assignment_submission_files_assignment_id_assignments"),
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["users.id"],
            name=op.f("fk_assignment_submission_files_student_id_users"),
        ),
        # The submission goes, its attachments go with it. They are that
        # submission's work and have no meaning without it.
        sa.ForeignKeyConstraint(
            ["submission_id"], ["assignment_submissions.id"], ondelete="CASCADE",
            name=op.f("fk_assignment_submission_files_submission_id"),
        ),
        sa.CheckConstraint("size > 0", name=op.f("ck_assignment_submission_files_size")),
    )
    # The lookup every read does: "this student's attachments on this
    # assignment", which is both the pre-submit list and the authorisation.
    op.create_index(
        "idx_submission_files_owner",
        "assignment_submission_files",
        ["assignment_id", "student_id"],
    )
    op.create_index(
        "idx_submission_files_submission",
        "assignment_submission_files",
        ["submission_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_submission_files_submission", table_name="assignment_submission_files")
    op.drop_index("idx_submission_files_owner", table_name="assignment_submission_files")
    op.drop_table("assignment_submission_files")
