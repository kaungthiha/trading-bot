"""bet journal (your queue of bets), leg outcomes (actual stat vs line), lessons

Revision ID: 0016_bet_journal
Revises: 0015_search_ledger
Create Date: 2026-11-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_bet_journal"
down_revision: str | None = "0015_search_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bet_journal",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False, index=True),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),  # queued | placed | skipped
        sa.Column("legs_json", sa.Text(), nullable=False),
        sa.Column("leg_key", sa.String(2000), nullable=False, index=True),
        sa.Column("market_price", sa.String(40), nullable=True),  # fair when logged (0-1)
        sa.Column("my_price", sa.String(40), nullable=True),      # what you paid (0-1)
        sa.Column("stake", sa.String(40), nullable=True),         # dollars
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("kalshi_ticker", sa.String(160), nullable=True),
        sa.CheckConstraint("status IN ('queued','placed','skipped')", name="ck_journal_status"),
    )
    op.create_table(
        "leg_outcomes",
        sa.Column("leg_ticker", sa.String(160), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("subject", sa.String(120), nullable=False),
        sa.Column("stat", sa.String(12), nullable=True),
        sa.Column("line", sa.Float(), nullable=True),
        sa.Column("actual", sa.Float(), nullable=True),
        sa.Column("minutes", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.String(32), nullable=False),
    )
    op.create_table(
        "lessons",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("day", sa.String(10), nullable=False, index=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("player", sa.String(120), nullable=True),
        sa.Column("stat", sa.String(12), nullable=True),
        sa.Column("side", sa.String(3), nullable=True),
        sa.Column("author", sa.String(8), nullable=False),  # model | you
        sa.Column("active", sa.Boolean(), nullable=False),
    )


def downgrade() -> None:
    for t in ("lessons", "leg_outcomes", "bet_journal"):
        op.drop_table(t)
