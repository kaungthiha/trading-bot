"""combo legs: the legs inside each combo you traded, and how each leg resolved

Revision ID: 0013_combo_legs
Revises: 0012_position_marks
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_combo_legs"
down_revision: str | None = "0012_position_marks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "combo_legs",
        sa.Column("combo_ticker", sa.String(160), primary_key=True),
        sa.Column("leg_ticker", sa.String(160), primary_key=True),
        sa.Column("event_ticker", sa.String(128), nullable=False),
        sa.Column("side", sa.String(3), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("result", sa.String(8), nullable=True),  # yes | no | None (unresolved)
        sa.Column("refreshed_at", sa.String(32), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("combo_legs")
