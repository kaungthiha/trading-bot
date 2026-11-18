"""paper trading: orders, fills, settlements, ledger; market result

Revision ID: 0006_paper
Revises: 0005_signals
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_paper"
down_revision: str | None = "0005_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("markets") as b:
        b.add_column(sa.Column("result", sa.String(16), nullable=True))

    op.create_table(
        "paper_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_order_id", sa.String(64), nullable=False, unique=True),
        sa.Column("submitted_at", sa.String(32), nullable=False),
        sa.Column("market_id", sa.String(36),
                  sa.ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("signal_id", sa.String(36),
                  sa.ForeignKey("signals.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("quote_id", sa.String(36),
                  sa.ForeignKey("quote_snapshots.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("side", sa.String(3), nullable=False),
        sa.Column("action", sa.String(4), nullable=False),
        sa.Column("quantity", sa.String(40), nullable=False),
        sa.Column("limit_price", sa.String(40), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("filled_quantity", sa.String(40), nullable=False),
        sa.Column("reject_reason", sa.String(64), nullable=True),
        sa.Column("scenario", sa.String(32), nullable=False),
        sa.Column("simulation_version", sa.String(32), nullable=False),
        sa.Column("fee_schedule_version", sa.String(64), nullable=True),
        sa.Column("fee_schedule_verified", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.CheckConstraint("side IN ('YES','NO')", name="ck_paper_side"),
        sa.CheckConstraint("action IN ('BUY','SELL')", name="ck_paper_action"),
        sa.CheckConstraint("status IN ('FILLED','PARTIAL','CANCELLED','REJECTED')",
                           name="ck_paper_status"),
    )
    op.create_index("ix_paper_orders_submitted_at", "paper_orders", ["submitted_at"])
    op.create_index("ix_paper_orders_market_id", "paper_orders", ["market_id"])

    op.create_table(
        "paper_fills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("paper_order_id", sa.String(36),
                  sa.ForeignKey("paper_orders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity", sa.String(40), nullable=False),
        sa.Column("price", sa.String(40), nullable=False),
        sa.Column("displayed_price", sa.String(40), nullable=False),
        sa.Column("fee", sa.String(40), nullable=False),
        sa.Column("filled_at", sa.String(32), nullable=False),
        sa.Column("assumption_code", sa.String(64), nullable=False),
    )
    op.create_index("ix_paper_fills_paper_order_id", "paper_fills", ["paper_order_id"])

    op.create_table(
        "paper_settlements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("market_id", sa.String(36),
                  sa.ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False,
                  unique=True),
        sa.Column("exchange_status", sa.String(32), nullable=False),
        sa.Column("exchange_result", sa.String(16), nullable=False),
        sa.Column("evidence_check", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("notes_json", sa.Text(), nullable=False),
        sa.CheckConstraint("status IN ('SETTLED','HELD')", name="ck_settlement_status"),
    )

    op.create_table(
        "paper_ledger",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("at", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("amount", sa.String(40), nullable=False),
        sa.Column("market_id", sa.String(36),
                  sa.ForeignKey("markets.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("paper_order_id", sa.String(36),
                  sa.ForeignKey("paper_orders.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("settlement_id", sa.String(36),
                  sa.ForeignKey("paper_settlements.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("memo", sa.Text(), nullable=False),
        sa.CheckConstraint("kind IN ('DEPOSIT','BUY','SELL','SETTLEMENT_PAYOUT')",
                           name="ck_ledger_kind"),
    )
    op.create_index("ix_paper_ledger_at", "paper_ledger", ["at"])

    # Append-only enforcement at the database level.
    for table in ("paper_ledger", "paper_fills", "paper_orders"):
        op.execute(f"""
            CREATE TRIGGER trg_{table}_no_update BEFORE UPDATE ON {table}
            BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;
        """)
        op.execute(f"""
            CREATE TRIGGER trg_{table}_no_delete BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;
        """)


def downgrade() -> None:
    for table in ("paper_ledger", "paper_fills", "paper_orders"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete")
    op.drop_index("ix_paper_ledger_at", table_name="paper_ledger")
    op.drop_table("paper_ledger")
    op.drop_table("paper_settlements")
    op.drop_index("ix_paper_fills_paper_order_id", table_name="paper_fills")
    op.drop_table("paper_fills")
    op.drop_index("ix_paper_orders_market_id", table_name="paper_orders")
    op.drop_index("ix_paper_orders_submitted_at", table_name="paper_orders")
    op.drop_table("paper_orders")
    with op.batch_alter_table("markets") as b:
        b.drop_column("result")
