"""approval-gated execution: intents, approvals, events, exchange orders, kill switch

Revision ID: 0007_execution
Revises: 0006_paper
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_execution"
down_revision: str | None = "0006_paper"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = sa.String
T = sa.Text


def _fk(col: str, table: str, nullable: bool = False, unique: bool = False) -> sa.Column:
    return sa.Column(col, S(36), sa.ForeignKey(f"{table}.id", ondelete="RESTRICT"),
                     nullable=nullable, unique=unique)


def upgrade() -> None:
    op.create_table(
        "execution_intents",
        sa.Column("id", S(36), primary_key=True),
        sa.Column("created_at", S(32), nullable=False),
        sa.Column("expires_at", S(32), nullable=False),
        sa.Column("env", S(8), nullable=False),
        _fk("market_id", "markets"),
        _fk("signal_id", "signals", nullable=True),
        _fk("quote_id", "quote_snapshots"),
        sa.Column("side", S(3), nullable=False),
        sa.Column("quantity", S(40), nullable=False),
        sa.Column("limit_price", S(40), nullable=False),
        sa.Column("approved_ask", S(40), nullable=False),
        sa.Column("est_fee", S(40), nullable=False),
        sa.Column("max_cost", S(40), nullable=False),
        sa.Column("fee_schedule_version", S(64), nullable=False),
        sa.Column("rules_hash", S(64), nullable=False),
        sa.Column("client_order_id", S(64), nullable=False, unique=True),
        sa.Column("payload_json", T(), nullable=False),
        sa.Column("payload_hash", S(64), nullable=False, unique=True),
        sa.Column("status", S(12), nullable=False),
        sa.Column("block_reason", S(64), nullable=True),
        sa.CheckConstraint("env IN ('mock','demo')", name="ck_intent_env"),
        sa.CheckConstraint("side IN ('YES','NO')", name="ck_intent_side"),
        sa.CheckConstraint(
            "status IN ('PROPOSED','APPROVED','SUBMITTING','FILLED','PARTIAL','NOT_FILLED',"
            "'REJECTED','UNKNOWN','BLOCKED','EXPIRED')", name="ck_intent_status"),
    )
    op.create_index("ix_execution_intents_created_at", "execution_intents", ["created_at"])

    op.create_table(
        "execution_approvals",
        sa.Column("id", S(36), primary_key=True),
        _fk("intent_id", "execution_intents", unique=True),
        sa.Column("at", S(32), nullable=False),
        sa.Column("payload_hash", S(64), nullable=False),
        sa.Column("actor", S(32), nullable=False),
    )
    op.create_table(
        "execution_events",
        sa.Column("id", S(36), primary_key=True),
        sa.Column("at", S(32), nullable=False),
        _fk("intent_id", "execution_intents", nullable=True),
        sa.Column("kind", S(32), nullable=False),
        sa.Column("detail_json", T(), nullable=False),
    )
    op.create_index("ix_execution_events_at", "execution_events", ["at"])
    op.create_index("ix_execution_events_intent_id", "execution_events", ["intent_id"])
    op.create_table(
        "exchange_orders",
        sa.Column("id", S(36), primary_key=True),
        _fk("intent_id", "execution_intents", unique=True),
        sa.Column("recorded_at", S(32), nullable=False),
        sa.Column("source", S(16), nullable=False),
        sa.Column("exchange_order_id", S(64), nullable=True),
        sa.Column("client_order_id", S(64), nullable=False),
        sa.Column("fill_count", S(40), nullable=False),
        sa.Column("remaining_count", S(40), nullable=True),
        sa.Column("average_fill_price", S(40), nullable=True),
        sa.Column("average_fee_paid", S(40), nullable=True),
        sa.Column("raw_json", T(), nullable=False),
    )
    op.create_table(
        "execution_controls",
        sa.Column("id", S(36), primary_key=True),
        sa.Column("at", S(32), nullable=False),
        sa.Column("action", S(8), nullable=False),
        sa.Column("actor", S(32), nullable=False),
        sa.Column("reason", T(), nullable=False),
        sa.CheckConstraint("action IN ('ENGAGE','RELEASE')", name="ck_control_action"),
    )
    op.create_index("ix_execution_controls_at", "execution_controls", ["at"])
    for table in ("execution_events", "execution_approvals", "execution_controls",
                  "exchange_orders"):
        op.execute(f"CREATE TRIGGER trg_{table}_no_update BEFORE UPDATE ON {table} "
                   f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;")
        op.execute(f"CREATE TRIGGER trg_{table}_no_delete BEFORE DELETE ON {table} "
                   f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;")
    # Intents: the order terms are immutable; only status/block_reason may change.
    op.execute("""
        CREATE TRIGGER trg_execution_intents_terms_immutable BEFORE UPDATE ON execution_intents
        WHEN NEW.payload_json IS NOT OLD.payload_json OR NEW.payload_hash IS NOT OLD.payload_hash
          OR NEW.client_order_id IS NOT OLD.client_order_id OR NEW.quantity IS NOT OLD.quantity
          OR NEW.limit_price IS NOT OLD.limit_price OR NEW.max_cost IS NOT OLD.max_cost
          OR NEW.side IS NOT OLD.side OR NEW.market_id IS NOT OLD.market_id
          OR NEW.env IS NOT OLD.env OR NEW.expires_at IS NOT OLD.expires_at
        BEGIN SELECT RAISE(ABORT, 'execution intent terms are immutable'); END;
    """)
    op.execute("CREATE TRIGGER trg_execution_intents_no_delete BEFORE DELETE ON "
               "execution_intents BEGIN SELECT RAISE(ABORT, 'intents are append-only'); END;")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_execution_intents_terms_immutable")
    op.execute("DROP TRIGGER IF EXISTS trg_execution_intents_no_delete")
    for table in ("execution_events", "execution_approvals", "execution_controls",
                  "exchange_orders"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete")
    op.drop_index("ix_execution_controls_at", table_name="execution_controls")
    op.drop_table("execution_controls")
    op.drop_table("exchange_orders")
    op.drop_index("ix_execution_events_intent_id", table_name="execution_events")
    op.drop_index("ix_execution_events_at", table_name="execution_events")
    op.drop_table("execution_events")
    op.drop_table("execution_approvals")
    op.drop_index("ix_execution_intents_created_at", table_name="execution_intents")
    op.drop_table("execution_intents")
