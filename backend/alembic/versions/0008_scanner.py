"""inefficiency scanner: opportunities (thesis cards) and the trade journal

Revision ID: 0008_scanner
Revises: 0007_execution
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_scanner"
down_revision: str | None = "0007_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = sa.String


def upgrade() -> None:
    op.create_table(
        "opportunities",
        sa.Column("id", S(36), primary_key=True),
        sa.Column("detected_at", S(32), nullable=False),
        sa.Column("expires_at", S(32), nullable=False),
        sa.Column("kind", S(16), nullable=False),
        sa.Column("guaranteed", sa.Boolean(), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("event_ticker", S(128), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("legs_json", sa.Text(), nullable=False),
        sa.Column("quantity", S(40), nullable=False),
        sa.Column("cost", S(40), nullable=False),
        sa.Column("fees", S(40), nullable=False),
        sa.Column("min_payoff", S(40), nullable=False),
        sa.Column("profit", S(40), nullable=False),
        sa.Column("return_pct", S(40), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("checklist_json", sa.Text(), nullable=False),
        sa.Column("budget_cap", S(40), nullable=True),
        sa.Column("fee_schedule_version", S(64), nullable=False),
        sa.Column("fingerprint", S(64), nullable=False),
        sa.CheckConstraint("kind IN ('LADDER','EXCL_NO','EXCL_YES')", name="ck_opp_kind"),
    )
    op.create_index("ix_opportunities_detected_at", "opportunities", ["detected_at"])
    op.create_index("ix_opportunities_event_ticker", "opportunities", ["event_ticker"])
    op.create_index("ix_opportunities_fingerprint", "opportunities", ["fingerprint"])
    op.create_table(
        "journal_entries",
        sa.Column("id", S(36), primary_key=True),
        sa.Column("at", S(32), nullable=False),
        sa.Column("opportunity_id", S(36),
                  sa.ForeignKey("opportunities.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("action", S(12), nullable=False),
        sa.Column("legs_json", sa.Text(), nullable=False),
        sa.Column("cost", S(40), nullable=True),
        sa.Column("payoff", S(40), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.CheckConstraint("action IN ('EXECUTED','SKIPPED','SETTLED','NOTE')",
                           name="ck_journal_action"),
    )
    op.create_index("ix_journal_entries_at", "journal_entries", ["at"])
    op.create_index("ix_journal_entries_opportunity_id", "journal_entries", ["opportunity_id"])
    for table in ("opportunities", "journal_entries"):
        op.execute(f"CREATE TRIGGER trg_{table}_no_update BEFORE UPDATE ON {table} "
                   f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;")
        op.execute(f"CREATE TRIGGER trg_{table}_no_delete BEFORE DELETE ON {table} "
                   f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;")


def downgrade() -> None:
    for table in ("opportunities", "journal_entries"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete")
    op.drop_index("ix_journal_entries_opportunity_id", table_name="journal_entries")
    op.drop_index("ix_journal_entries_at", table_name="journal_entries")
    op.drop_table("journal_entries")
    op.drop_index("ix_opportunities_fingerprint", table_name="opportunities")
    op.drop_index("ix_opportunities_event_ticker", table_name="opportunities")
    op.drop_index("ix_opportunities_detected_at", table_name="opportunities")
    op.drop_table("opportunities")
