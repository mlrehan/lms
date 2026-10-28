"""audit_logs: client IP scope and approximate geolocation.

The audit trail recorded the console server's address (127.0.0.1, or the
frontend container's) as the client for every signed-in action, because the
Next.js proxy never passed the browser's address on and the API trusted any
`X-Forwarded-For`. The resolution is fixed in code; these columns record what
it found: the address's scope, and where a local GeoLite2 lookup places it.

Additive and nullable. Existing rows are **not** backfilled: the table is
append-only (a trigger refuses UPDATE), and more to the point a location
computed today for an address recorded last month would be a fabrication --
addresses move between networks. Old rows keep exactly the IP they had.

Adding columns is DDL, which the append-only trigger does not fire on.

Revision ID: f3c9a1d47e85
Revises: e8b3f52a6d71
Create Date: 2026-10-28 22:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3c9a1d47e85"
down_revision: Union[str, None] = "e8b3f52a6d71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    ("ip_scope", sa.String(16)),
    ("geo_status", sa.String(16)),
    ("geo_source", sa.String(64)),
    ("geo_country_code", sa.String(2)),
    ("geo_country", sa.String(100)),
    ("geo_region", sa.String(100)),
    ("geo_city", sa.String(100)),
    ("geo_latitude", sa.Float()),
    ("geo_longitude", sa.Float()),
    ("geo_accuracy_km", sa.Integer()),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column("audit_logs", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("audit_logs", name)
