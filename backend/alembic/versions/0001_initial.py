"""initial schema: markets, rule versions, quote snapshots, audit events

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "markets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("external_ticker", sa.String(128), nullable=False, unique=True),
        sa.Column("event_ticker", sa.String(128), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("close_at", sa.String(32), nullable=True),
        sa.Column("notional_value", sa.String(40), nullable=False),
        sa.Column("price_ranges_json", sa.Text(), nullable=False),
        sa.Column("is_mock", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_markets_event_ticker", "markets", ["event_ticker"])
    op.create_index("ix_markets_category", "markets", ["category"])

    op.create_table(
        "market_rule_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "market_id",
            sa.String(36),
            sa.ForeignKey("markets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("rules_text", sa.Text(), nullable=False),
        sa.Column("official_source_url", sa.Text(), nullable=True),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.String(32), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "ix_rule_versions_market_hash", "market_rule_versions", ["market_id", "hash"]
    )

    op.create_table(
        "quote_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "market_id",
            sa.String(36),
            sa.ForeignKey("markets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.String(32), nullable=False),
        sa.Column("received_at", sa.String(32), nullable=False),
        sa.Column("yes_bid", sa.String(40), nullable=True),
        sa.Column("no_bid", sa.String(40), nullable=True),
        sa.Column("yes_ask_derived", sa.String(40), nullable=True),
        sa.Column("no_ask_derived", sa.String(40), nullable=True),
        sa.Column("depth_json", sa.Text(), nullable=False),
        sa.Column("raw_ref", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_quotes_market_observed",
        "quote_snapshots",
        ["market_id", "observed_at"],
        unique=True,
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("at", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("object_type", sa.String(64), nullable=False),
        sa.Column("object_id", sa.String(64), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
    )
    op.create_index("ix_audit_events_at", "audit_events", ["at"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_quotes_market_observed", table_name="quote_snapshots")
    op.drop_table("quote_snapshots")
    op.drop_index("ix_rule_versions_market_hash", table_name="market_rule_versions")
    op.drop_table("market_rule_versions")
    op.drop_index("ix_markets_category", table_name="markets")
    op.drop_index("ix_markets_event_ticker", table_name="markets")
    op.drop_table("markets")
