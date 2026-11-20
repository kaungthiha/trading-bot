"""search_ledger: one row per Brave Search network attempt (for app-side spending caps)

Revision ID: 0015_search_ledger
Revises: 0014_investigations
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_search_ledger"
down_revision: str | None = "0014_investigations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "search_ledger",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("at", sa.String(32), nullable=False, index=True),
        sa.Column("purpose", sa.String(16), nullable=False, index=True),
        sa.Column("query_hash", sa.String(64), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("search_ledger")
