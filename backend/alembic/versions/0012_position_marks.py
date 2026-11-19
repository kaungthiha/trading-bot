"""position marks: each open position's market price at every sync and scan

Revision ID: 0012_position_marks
Revises: 0011_combo_eligibility
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_position_marks"
down_revision: str | None = "0011_combo_eligibility"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "position_marks",
        sa.Column("ticker", sa.String(160), primary_key=True),
        sa.Column("at", sa.String(32), primary_key=True),
        sa.Column("side", sa.String(3), nullable=False),
        sa.Column("contracts", sa.String(40), nullable=False),
        sa.Column("cost", sa.String(40), nullable=False),
        sa.Column("yes_bid", sa.String(40), nullable=True),
        sa.Column("yes_ask", sa.String(40), nullable=True),
        sa.Column("mid", sa.String(40), nullable=True),  # of the side held
        sa.Column("source", sa.String(8), nullable=False),  # sync | scan
    )
    op.create_index("ix_position_marks_at", "position_marks", ["at"])


def downgrade() -> None:
    op.drop_table("position_marks")
