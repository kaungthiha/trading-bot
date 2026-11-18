"""SQLAlchemy ORM models for the milestone-01 schema.

Snapshot tables (rule versions, quotes, audit events) are append-only by convention:
repositories only insert into them. Later milestones add evidence, model runs, signals
and paper trading tables via new Alembic revisions.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.db.types import DecimalString, UTCDateTime


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    exchange: Mapped[str] = mapped_column(String(32))
    external_ticker: Mapped[str] = mapped_column(String(128), unique=True)
    event_ticker: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(Text)
    series_ticker: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32))  # normalized MarketStatus value
    status_raw: Mapped[str | None] = mapped_column(String(32), nullable=True)  # as received
    market_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    open_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    close_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    notional_value: Mapped[Decimal] = mapped_column(DecimalString())
    price_ranges_json: Mapped[str] = mapped_column(Text)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    fee_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fee_multiplier: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())

    rule_versions: Mapped[list[MarketRuleVersion]] = relationship(back_populates="market")
    quotes: Mapped[list[QuoteSnapshot]] = relationship(back_populates="market")


class MarketRuleVersion(Base):
    __tablename__ = "market_rule_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id", ondelete="RESTRICT"))
    rules_text: Mapped[str] = mapped_column(Text)
    official_source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    hash: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)

    market: Mapped[Market] = relationship(back_populates="rule_versions")

    # Not unique: rules can revert to an earlier text (A -> B -> A), which is a new version.
    __table_args__ = (Index("ix_rule_versions_market_hash", "market_id", "hash"),)


class QuoteSnapshot(Base):
    __tablename__ = "quote_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id", ondelete="RESTRICT"))
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    received_at: Mapped[datetime] = mapped_column(UTCDateTime())
    yes_bid: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    no_bid: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    yes_ask_derived: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    no_ask_derived: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    depth_json: Mapped[str] = mapped_column(Text)
    raw_ref: Mapped[str | None] = mapped_column(Text, nullable=True)

    market: Mapped[Market] = relationship(back_populates="quotes")

    __table_args__ = (
        Index("ix_quotes_market_observed", "market_id", "observed_at", unique=True),
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    adapter: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    status: Mapped[str] = mapped_column(String(16))  # running|success|partial|failed
    count: Mapped[int] = mapped_column(default=0)
    errors_json: Mapped[str] = mapped_column(Text, default="[]")


class EvidenceRecord(Base):
    """Immutable: one value of one series for one period as published in one vintage."""

    __tablename__ = "evidence_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(String(64))
    series_id: Mapped[str] = mapped_column(String(64))
    observation_date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD period
    vintage_date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD published/revised
    value: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    quality: Mapped[str] = mapped_column(String(16))
    available_at: Mapped[datetime] = mapped_column(UTCDateTime())
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime())
    units: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text)
    license_notes: Mapped[str] = mapped_column(Text)
    hash: Mapped[str] = mapped_column(String(64))

    __table_args__ = (
        Index(
            "ux_evidence_identity",
            "source_id",
            "observation_date",
            "vintage_date",
            unique=True,
        ),
        Index("ix_evidence_source_available", "source_id", "available_at"),
    )


class CollectionGap(Base):
    """A period when a scheduled job did not run (e.g. laptop asleep). Never back-filled
    with invented data; ``backfillable`` says whether the source can recover it."""

    __tablename__ = "collection_gaps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job: Mapped[str] = mapped_column(String(64), index=True)
    gap_start: Mapped[datetime] = mapped_column(UTCDateTime())
    gap_end: Mapped[datetime] = mapped_column(UTCDateTime())
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    backfillable: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text)


class ModelRun(Base):
    """Immutable record of one forecast (or abstention) with its exact inputs."""

    __tablename__ = "model_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    contract_key: Mapped[str] = mapped_column(String(128), index=True)
    market_id: Mapped[str | None] = mapped_column(
        ForeignKey("markets.id", ondelete="RESTRICT"), nullable=True
    )
    model: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    feature_version: Mapped[str] = mapped_column(String(64))
    as_of: Mapped[datetime] = mapped_column(UTCDateTime())
    decision: Mapped[str] = mapped_column(String(16))
    p_yes: Mapped[float | None] = mapped_column(nullable=True)
    lower: Mapped[float | None] = mapped_column(nullable=True)
    upper: Mapped[float | None] = mapped_column(nullable=True)
    uncertainty_method: Mapped[str] = mapped_column(Text)
    reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    inputs_json: Mapped[str] = mapped_column(Text, default="{}")


class ModelEvaluation(Base):
    """Immutable walk-forward evaluation report for one model version on one dataset."""

    __tablename__ = "model_evaluations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    model: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(32))
    feature_version: Mapped[str] = mapped_column(String(64))
    dataset_hash: Mapped[str] = mapped_column(String(64))
    config_json: Mapped[str] = mapped_column(Text)
    dev_json: Mapped[str] = mapped_column(Text)
    holdout_json: Mapped[str] = mapped_column(Text)
    data_notes_json: Mapped[str] = mapped_column(Text)


class MarketMapping(Base):
    """Append-only log linking a market to a model contract definition.

    The latest row per market is in effect. A mapping is pinned to the rules-text hash it
    was reviewed against; if the market's rules change, the mapping stops applying.
    Status: proposed (auto-parsed) | confirmed (human) | rejected (human or parser).
    """

    __tablename__ = "market_mappings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id", ondelete="RESTRICT"),
                                           index=True)
    contract_type: Mapped[str] = mapped_column(String(64))
    reference_month: Mapped[str | None] = mapped_column(String(10), nullable=True)
    threshold: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    rules_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    actor: Mapped[str] = mapped_column(String(64))  # "parser" or "user"
    notes_json: Mapped[str] = mapped_column(Text, default="[]")


class Signal(Base):
    """Immutable research signal: a hypothesis, NOT an order or an authorization."""

    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id", ondelete="RESTRICT"),
                                           index=True)
    quote_id: Mapped[str | None] = mapped_column(
        ForeignKey("quote_snapshots.id", ondelete="RESTRICT"), nullable=True)
    model_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="RESTRICT"), nullable=True)
    mapping_id: Mapped[str | None] = mapped_column(
        ForeignKey("market_mappings.id", ondelete="RESTRICT"), nullable=True)
    rules_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fee_schedule_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision: Mapped[str] = mapped_column(String(24))  # CANDIDATE_YES|CANDIDATE_NO|ABSTAIN
    side: Mapped[str | None] = mapped_column(String(8), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    p_yes: Mapped[float | None] = mapped_column(nullable=True)
    entry: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    fee: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    slippage: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    ev: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    lower_edge: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    caveats_json: Mapped[str] = mapped_column(Text, default="[]")
    details_json: Mapped[str] = mapped_column(Text, default="{}")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    object_type: Mapped[str] = mapped_column(String(64))
    object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
