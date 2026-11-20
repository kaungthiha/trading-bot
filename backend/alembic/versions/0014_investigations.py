"""investigations: one stored result per on-demand pick investigation

Revision ID: 0014_investigations
Revises: 0013_combo_legs
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_investigations"
down_revision: str | None = "0013_combo_legs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investigations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cache_key", sa.String(400), nullable=False, index=True),
        sa.Column("ticker", sa.String(160), nullable=False, index=True),
        sa.Column("side", sa.String(3), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("stale_at", sa.String(32), nullable=True),
        sa.Column("result_json", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("investigations")
