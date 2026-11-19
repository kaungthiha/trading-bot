"""combo eligibility: which events can be combined on Kalshi (multivariate collections)

Revision ID: 0011_combo_eligibility
Revises: 0010_account_history
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_combo_eligibility"
down_revision: str | None = "0010_account_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_combo_events",
        sa.Column("event_ticker", sa.String(128), primary_key=True),
        sa.Column("collections", sa.Text(), nullable=False),
        sa.Column("refreshed_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_catalog_combo_events_refreshed_at", "catalog_combo_events",
                    ["refreshed_at"])


def downgrade() -> None:
    op.drop_table("catalog_combo_events")
