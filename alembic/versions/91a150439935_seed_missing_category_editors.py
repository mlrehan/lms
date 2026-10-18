"""seed_missing_category_editors

Revision ID: 91a150439935
Revises: b8f3d16c92a4
Create Date: 2026-10-18 20:53:20.263847

Ensures category_editors has mappings for both SQL and Python editors
across relevant existing categories. In environments where categories were
synced or populated after initial migrations, category_editors may be missing
seeds for Database/SQL or Python categories.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '91a150439935'
down_revision: Union[str, Sequence[str], None] = 'b8f3d16c92a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEED_RULES: tuple[tuple[str, str], ...] = (
    ("database and sql", "sql"),
    ("data & ai technologies", "python"),
    ("programming languages", "python"),
)


def upgrade() -> None:
    categories = sa.table(
        "categories",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
    )
    category_editors = sa.table(
        "category_editors",
        sa.column("category_id", sa.Integer),
        sa.column("editor", sa.String),
    )

    connection = op.get_bind()

    # Fetch existing category_editors mappings
    existing_mappings = set(
        connection.execute(
            sa.select(category_editors.c.category_id, category_editors.c.editor)
        ).all()
    )

    # Fetch all categories
    all_categories = connection.execute(
        sa.select(categories.c.id, categories.c.name)
    ).all()

    new_rows: list[dict[str, object]] = []

    for cat_id, cat_name in all_categories:
        normalized = (cat_name or "").lower().strip()
        matched_editors: set[str] = set()

        for rule_name, editor in SEED_RULES:
            if rule_name in normalized:
                matched_editors.add(editor)

        # Keyword checks if not matched by exact rules
        if "sql" in normalized or "database" in normalized:
            matched_editors.add("sql")
        if "python" in normalized or "programming" in normalized or "data & ai" in normalized:
            matched_editors.add("python")

        for editor in matched_editors:
            if (cat_id, editor) not in existing_mappings:
                new_rows.append({"category_id": cat_id, "editor": editor})
                existing_mappings.add((cat_id, editor))

    if new_rows:
        op.bulk_insert(category_editors, new_rows)


def downgrade() -> None:
    pass
