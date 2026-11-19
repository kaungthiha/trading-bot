"""your Kalshi account history: fills, settlements, positions, sync runs (read-only sync)

Revision ID: 0010_account_history
Revises: 0009_catalog
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_account_history"
down_revision: str | None = "0009_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = sa.String
D = sa.String(40)


def upgrade() -> None:
    op.create_table(
        "account_fills",
        sa.Column("fill_id", S(64), primary_key=True),
        sa.Column("ticker", S(160), nullable=False),
        sa.Column("order_id", S(64), nullable=False),
        sa.Column("side", S(4), nullable=False),
        sa.Column("action", S(4), nullable=False),
        sa.Column("is_taker", sa.Boolean(), nullable=False),
        sa.Column("count", D, nullable=False),
        sa.Column("price", D, nullable=False),
        sa.Column("yes_price", D, nullable=False),
        sa.Column("fee", D, nullable=False),
        sa.Column("created_at", S(32), nullable=False),
        sa.Column("source", S(16), nullable=False),
        sa.CheckConstraint("side IN ('yes','no')", name="ck_fill_side"),
        sa.CheckConstraint("action IN ('buy','sell')", name="ck_fill_action"),
    )
    op.create_index("ix_account_fills_ticker", "account_fills", ["ticker"])
    op.create_index("ix_account_fills_created_at", "account_fills", ["created_at"])
    op.create_table(
        "account_settlements",
        sa.Column("ticker", S(160), primary_key=True),
        sa.Column("event_ticker", S(128), nullable=False),
        sa.Column("market_result", S(8), nullable=False),
        *[sa.Column(c, D, nullable=False) for c in (
            "yes_count", "yes_cost", "no_count", "no_cost", "revenue", "fee")],
        sa.Column("settled_at", S(32), nullable=False),
    )
    op.create_index("ix_account_settlements_event_ticker", "account_settlements",
                    ["event_ticker"])
    op.create_index("ix_account_settlements_settled_at", "account_settlements", ["settled_at"])
    op.create_table(
        "account_positions",
        sa.Column("ticker", S(160), primary_key=True),
        *[sa.Column(c, D, nullable=False) for c in (
            "position", "exposure", "realized_pnl", "fees_paid", "total_traded")],
        sa.Column("last_updated", S(32), nullable=True),
        sa.Column("source", S(16), nullable=False),
    )
    op.create_table(
        "account_syncs",
        sa.Column("id", S(36), primary_key=True),
        sa.Column("at", S(32), nullable=False),
        sa.Column("status", S(16), nullable=False),
        sa.Column("fills", sa.Integer(), nullable=False),
        sa.Column("settlements", sa.Integer(), nullable=False),
        sa.Column("positions", sa.Integer(), nullable=False),
        sa.Column("balance", D, nullable=True),
        sa.Column("portfolio_value", D, nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
    )
    op.create_index("ix_account_syncs_at", "account_syncs", ["at"])


def downgrade() -> None:
    for t in ("account_syncs", "account_positions", "account_settlements", "account_fills"):
        op.drop_table(t)
