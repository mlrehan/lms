"""Which code editor a course needs.

Revision ID: a7e4b2c91d35
Revises: f2a9c31e6b84
Create Date: 2026-10-14

Two tables and nothing else, so this is safe against live data and reverses
cleanly.

**Why a mapping and not a keyword match.** Deciding from the course title is
the obvious implementation and is wrong in both directions: "Introduction to
Python for Data Analysis" and "Advanced SQL Window Functions" happen to
contain a usable word, while "Agentic AI & Automation", "Teens Coding" and
"Power BI for Business" do not, and a course called "Python-free Data
Literacy" would be matched exactly backwards. The decision belongs to somebody
who knows the curriculum, so it is stored.

**Two levels, because courses arrive on their own.** The sync pipeline creates
courses from LAIT on a schedule, and a mapping that had to be set per course by
hand would be permanently out of date. So the rule lives on the *category* --
structured metadata an administrator already maintains -- and new courses
inherit it. `course_editors` is the exception for a course whose category is
absent (eleven of them today) or whose category is right about most of its
courses and wrong about this one.

The seeded category rules below are the three that are unambiguous in this
institution's own category list. Everything else is left unset deliberately:
an editor offered on a course that does not use one is a support question, and
silence is the safer default.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a7e4b2c91d35"
down_revision = "f2a9c31e6b84"
branch_labels = None
depends_on = None

#: Category name -> editors its courses need, applied once at upgrade.
#: Matched on the name because that is what exists to match on now; from here
#: the rows are the record and nothing re-derives them.
SEED: dict[str, tuple[str, ...]] = {
    "Database and SQL": ("sql",),
    "Data & AI Technologies": ("python",),
    "Programming Languages": ("python",),
}


def upgrade() -> None:
    for table, owner, fk_table in (
        ("category_editors", "category_id", "categories"),
        ("course_editors", "course_id", "courses"),
    ):
        op.create_table(
            table,
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(owner, sa.Integer(), nullable=False),
            sa.Column("editor", sa.String(length=20), nullable=False),
            sa.ForeignKeyConstraint(
                [owner], [f"{fk_table}.id"],
                name=f"fk_{table}_{owner}_{fk_table}", ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
            # One row per (owner, editor): ticking a box twice is not two facts.
            sa.UniqueConstraint(owner, "editor", name=f"uq_{table}_{owner}_editor"),
            # Only editors this build knows how to open. A typo here would be a
            # menu item pointing nowhere, which no amount of application code
            # can detect after the fact.
            sa.CheckConstraint("editor IN ('sql', 'python')", name=f"ck_{table}_editor"),
        )
        op.create_index(f"ix_{table}_{owner}", table, [owner], unique=False)

    categories = sa.table(
        "categories", sa.column("id", sa.Integer), sa.column("name", sa.String)
    )
    connection = op.get_bind()
    rows = []
    for name, editors in SEED.items():
        found = connection.execute(
            sa.select(categories.c.id).where(categories.c.name == name)
        ).scalars().all()
        for category_id in found:
            rows.extend({"category_id": category_id, "editor": e} for e in editors)
    if rows:
        op.bulk_insert(
            sa.table(
                "category_editors",
                sa.column("category_id", sa.Integer),
                sa.column("editor", sa.String),
            ),
            rows,
        )


def downgrade() -> None:
    op.drop_index("ix_course_editors_course_id", table_name="course_editors")
    op.drop_table("course_editors")
    op.drop_index("ix_category_editors_category_id", table_name="category_editors")
    op.drop_table("category_editors")
