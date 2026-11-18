"""kalshi read-only: market lifecycle/type columns, ingestion_runs

Revision ID: 0002_kalshi_read_only
Revises: 0001_initial
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_kalshi_read_only"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("markets") as b:
        b.add_column(sa.Column("series_ticker", sa.String(128), nullable=True))
        b.add_column(sa.Column("status_raw", sa.String(32), nullable=True))
        b.add_column(sa.Column("market_type", sa.String(16), nullable=True))
        b.add_column(sa.Column("open_at", sa.String(32), nullable=True))
        b.create_index("ix_markets_series_ticker", ["series_ticker"])

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("adapter", sa.String(64), nullable=False),
        sa.Column("started_at", sa.String(32), nullable=False),
        sa.Column("finished_at", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.create_index("ix_ingestion_runs_adapter", "ingestion_runs", ["adapter"])
    op.create_index("ix_ingestion_runs_started_at", "ingestion_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_runs_started_at", table_name="ingestion_runs")
    op.drop_index("ix_ingestion_runs_adapter", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
    with op.batch_alter_table("markets") as b:
        b.drop_index("ix_markets_series_ticker")
        b.drop_column("open_at")
        b.drop_column("market_type")
        b.drop_column("status_raw")
        b.drop_column("series_ticker")
