"""model runs and model evaluations

Revision ID: 0004_models
Revises: 0003_evidence
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_models"
down_revision: str | None = "0003_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("contract_key", sa.String(128), nullable=False),
        sa.Column(
            "market_id",
            sa.String(36),
            sa.ForeignKey("markets.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("feature_version", sa.String(64), nullable=False),
        sa.Column("as_of", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("p_yes", sa.Float(), nullable=True),
        sa.Column("lower", sa.Float(), nullable=True),
        sa.Column("upper", sa.Float(), nullable=True),
        sa.Column("uncertainty_method", sa.Text(), nullable=False),
        sa.Column("reasons_json", sa.Text(), nullable=False),
        sa.Column("inputs_json", sa.Text(), nullable=False),
        sa.CheckConstraint("p_yes IS NULL OR (p_yes >= 0 AND p_yes <= 1)", name="ck_p_yes"),
        sa.CheckConstraint("lower IS NULL OR (lower >= 0 AND lower <= 1)", name="ck_lower"),
        sa.CheckConstraint("upper IS NULL OR (upper >= 0 AND upper <= 1)", name="ck_upper"),
    )
    op.create_index("ix_model_runs_created_at", "model_runs", ["created_at"])
    op.create_index("ix_model_runs_contract_key", "model_runs", ["contract_key"])

    op.create_table(
        "model_evaluations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("feature_version", sa.String(64), nullable=False),
        sa.Column("dataset_hash", sa.String(64), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("dev_json", sa.Text(), nullable=False),
        sa.Column("holdout_json", sa.Text(), nullable=False),
        sa.Column("data_notes_json", sa.Text(), nullable=False),
    )
    op.create_index("ix_model_evaluations_created_at", "model_evaluations", ["created_at"])
    op.create_index("ix_model_evaluations_model", "model_evaluations", ["model"])


def downgrade() -> None:
    op.drop_index("ix_model_evaluations_model", table_name="model_evaluations")
    op.drop_index("ix_model_evaluations_created_at", table_name="model_evaluations")
    op.drop_table("model_evaluations")
    op.drop_index("ix_model_runs_contract_key", table_name="model_runs")
    op.drop_index("ix_model_runs_created_at", table_name="model_runs")
    op.drop_table("model_runs")
