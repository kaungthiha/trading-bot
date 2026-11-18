"""evidence records (vintage-aware) and collection gaps

Revision ID: 0003_evidence
Revises: 0002_kalshi_read_only
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_evidence"
down_revision: str | None = "0002_kalshi_read_only"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evidence_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("series_id", sa.String(64), nullable=False),
        sa.Column("observation_date", sa.String(10), nullable=False),
        sa.Column("vintage_date", sa.String(10), nullable=False),
        sa.Column("value", sa.String(40), nullable=True),
        sa.Column("quality", sa.String(16), nullable=False),
        sa.Column("available_at", sa.String(32), nullable=False),
        sa.Column("retrieved_at", sa.String(32), nullable=False),
        sa.Column("units", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("license_notes", sa.Text(), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
    )
    op.create_index(
        "ux_evidence_identity",
        "evidence_records",
        ["source_id", "observation_date", "vintage_date"],
        unique=True,
    )
    op.create_index(
        "ix_evidence_source_available", "evidence_records", ["source_id", "available_at"]
    )

    op.create_table(
        "collection_gaps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job", sa.String(64), nullable=False),
        sa.Column("gap_start", sa.String(32), nullable=False),
        sa.Column("gap_end", sa.String(32), nullable=False),
        sa.Column("detected_at", sa.String(32), nullable=False),
        sa.Column("backfillable", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
    )
    op.create_index("ix_collection_gaps_job", "collection_gaps", ["job"])


def downgrade() -> None:
    op.drop_index("ix_collection_gaps_job", table_name="collection_gaps")
    op.drop_table("collection_gaps")
    op.drop_index("ix_evidence_source_available", table_name="evidence_records")
    op.drop_index("ux_evidence_identity", table_name="evidence_records")
    op.drop_table("evidence_records")
