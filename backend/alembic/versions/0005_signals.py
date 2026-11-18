"""market fee columns, market mappings, signals

Revision ID: 0005_signals
Revises: 0004_models
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_signals"
down_revision: str | None = "0004_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("markets") as b:
        b.add_column(sa.Column("fee_type", sa.String(64), nullable=True))
        b.add_column(sa.Column("fee_multiplier", sa.String(40), nullable=True))

    op.create_table(
        "market_mappings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("market_id", sa.String(36),
                  sa.ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("contract_type", sa.String(64), nullable=False),
        sa.Column("reference_month", sa.String(10), nullable=True),
        sa.Column("threshold", sa.String(40), nullable=True),
        sa.Column("rules_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("notes_json", sa.Text(), nullable=False),
        sa.CheckConstraint("status IN ('proposed','confirmed','rejected')",
                           name="ck_mapping_status"),
    )
    op.create_index("ix_market_mappings_created_at", "market_mappings", ["created_at"])
    op.create_index("ix_market_mappings_market_id", "market_mappings", ["market_id"])

    op.create_table(
        "signals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.String(32), nullable=False),
        sa.Column("market_id", sa.String(36),
                  sa.ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quote_id", sa.String(36),
                  sa.ForeignKey("quote_snapshots.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("model_run_id", sa.String(36),
                  sa.ForeignKey("model_runs.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("mapping_id", sa.String(36),
                  sa.ForeignKey("market_mappings.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("rules_hash", sa.String(64), nullable=True),
        sa.Column("fee_schedule_version", sa.String(64), nullable=True),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("side", sa.String(8), nullable=True),
        sa.Column("quantity", sa.String(40), nullable=True),
        sa.Column("p_yes", sa.Float(), nullable=True),
        sa.Column("entry", sa.String(40), nullable=True),
        sa.Column("fee", sa.String(40), nullable=True),
        sa.Column("slippage", sa.String(40), nullable=True),
        sa.Column("ev", sa.String(40), nullable=True),
        sa.Column("lower_edge", sa.String(40), nullable=True),
        sa.Column("reasons_json", sa.Text(), nullable=False),
        sa.Column("caveats_json", sa.Text(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "decision IN ('CANDIDATE_YES','CANDIDATE_NO','ABSTAIN')", name="ck_signal_decision"
        ),
        sa.CheckConstraint("p_yes IS NULL OR (p_yes >= 0 AND p_yes <= 1)",
                           name="ck_signal_p_yes"),
    )
    op.create_index("ix_signals_created_at", "signals", ["created_at"])
    op.create_index("ix_signals_market_id", "signals", ["market_id"])


def downgrade() -> None:
    op.drop_index("ix_signals_market_id", table_name="signals")
    op.drop_index("ix_signals_created_at", table_name="signals")
    op.drop_table("signals")
    op.drop_index("ix_market_mappings_market_id", table_name="market_mappings")
    op.drop_index("ix_market_mappings_created_at", table_name="market_mappings")
    op.drop_table("market_mappings")
    with op.batch_alter_table("markets") as b:
        b.drop_column("fee_multiplier")
        b.drop_column("fee_type")
