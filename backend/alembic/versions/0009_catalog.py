"""market catalog: refreshable cache of every open Kalshi series/event/market

Revision ID: 0009_catalog
Revises: 0008_scanner
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_catalog"
down_revision: str | None = "0008_scanner"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = sa.String
D = sa.String(40)  # exact decimal as text


def upgrade() -> None:
    op.create_table(
        "catalog_series",
        sa.Column("ticker", S(128), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("category", S(64), nullable=False),
        sa.Column("frequency", S(32), nullable=True),
        sa.Column("fee_type", S(64), nullable=True),
        sa.Column("fee_multiplier", D, nullable=True),
        sa.Column("refreshed_at", S(32), nullable=False),
    )
    op.create_index("ix_catalog_series_category", "catalog_series", ["category"])
    op.create_table(
        "catalog_events",
        sa.Column("event_ticker", S(128), primary_key=True),
        sa.Column("series_ticker", S(128), nullable=False),
        sa.Column("category", S(64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("sub_title", sa.Text(), nullable=False),
        sa.Column("competition", S(128), nullable=True),
        sa.Column("mutually_exclusive", sa.Boolean(), nullable=False),
        sa.Column("market_count", sa.Integer(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("volume_24h", sa.Float(), nullable=False),
        sa.Column("open_interest", sa.Float(), nullable=False),
        sa.Column("close_at", S(32), nullable=True),
        sa.Column("occurs_at", S(32), nullable=True),
        sa.Column("rules_sample", sa.Text(), nullable=False),
        sa.Column("refreshed_at", S(32), nullable=False),
    )
    for col in ("series_ticker", "category", "volume_24h", "close_at", "refreshed_at"):
        op.create_index(f"ix_catalog_events_{col}", "catalog_events", [col])
    op.create_table(
        "catalog_markets",
        sa.Column("ticker", S(160), primary_key=True),
        sa.Column("event_ticker", S(128), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("yes_sub_title", sa.Text(), nullable=False),
        sa.Column("no_sub_title", sa.Text(), nullable=False),
        sa.Column("status", S(32), nullable=False),
        *[sa.Column(c, D, nullable=True) for c in (
            "yes_bid", "yes_ask", "no_bid", "no_ask", "yes_bid_size", "yes_ask_size",
            "last_price", "previous_price", "volume", "volume_24h", "open_interest")],
        sa.Column("close_at", S(32), nullable=True),
        sa.Column("strike_type", S(32), nullable=True),
        sa.Column("floor_strike", D, nullable=True),
        sa.Column("cap_strike", D, nullable=True),
        sa.Column("group_key", sa.Text(), nullable=False),
        sa.Column("refreshed_at", S(32), nullable=False),
    )
    op.create_index("ix_catalog_markets_event_ticker", "catalog_markets", ["event_ticker"])
    op.create_index("ix_catalog_markets_refreshed_at", "catalog_markets", ["refreshed_at"])


def downgrade() -> None:
    op.drop_table("catalog_markets")
    op.drop_table("catalog_events")
    op.drop_table("catalog_series")
