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
    result: Mapped[str | None] = mapped_column(String(16), nullable=True)
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


class PaperOrder(Base):
    """Immutable simulated order. Immediate-or-cancel: its final status is known at
    submission (FILLED | PARTIAL | CANCELLED | REJECTED); unfilled remainder is cancelled."""

    __tablename__ = "paper_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True)
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id", ondelete="RESTRICT"),
                                           index=True)
    signal_id: Mapped[str | None] = mapped_column(
        ForeignKey("signals.id", ondelete="RESTRICT"), nullable=True)
    quote_id: Mapped[str | None] = mapped_column(
        ForeignKey("quote_snapshots.id", ondelete="RESTRICT"), nullable=True)
    side: Mapped[str] = mapped_column(String(3))  # YES | NO
    action: Mapped[str] = mapped_column(String(4))  # BUY | SELL
    quantity: Mapped[Decimal] = mapped_column(DecimalString())
    limit_price: Mapped[Decimal] = mapped_column(DecimalString())
    status: Mapped[str] = mapped_column(String(10))
    filled_quantity: Mapped[Decimal] = mapped_column(DecimalString())
    reject_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scenario: Mapped[str] = mapped_column(String(32))
    simulation_version: Mapped[str] = mapped_column(String(32))
    fee_schedule_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fee_schedule_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | replay


class PaperFill(Base):
    __tablename__ = "paper_fills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_order_id: Mapped[str] = mapped_column(
        ForeignKey("paper_orders.id", ondelete="RESTRICT"), index=True)
    quantity: Mapped[Decimal] = mapped_column(DecimalString())
    price: Mapped[Decimal] = mapped_column(DecimalString())
    displayed_price: Mapped[Decimal] = mapped_column(DecimalString())
    fee: Mapped[Decimal] = mapped_column(DecimalString())  # per-fill trade fee (pre-rounding)
    filled_at: Mapped[datetime] = mapped_column(UTCDateTime())
    assumption_code: Mapped[str] = mapped_column(String(64))


class PaperSettlement(Base):
    """One per market. SETTLED only on a finalized exchange result that our own evidence
    does not contradict; otherwise HELD for human review (no payout)."""

    __tablename__ = "paper_settlements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id", ondelete="RESTRICT"),
                                           unique=True)
    exchange_status: Mapped[str] = mapped_column(String(32))
    exchange_result: Mapped[str] = mapped_column(String(16))
    evidence_check: Mapped[str] = mapped_column(String(16))  # agree|disagree|unavailable
    status: Mapped[str] = mapped_column(String(16))  # SETTLED | HELD
    notes_json: Mapped[str] = mapped_column(Text, default="[]")


class PaperLedgerEntry(Base):
    """Append-only cash ledger. Balance = sum(amount). Never updated or deleted."""

    __tablename__ = "paper_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # DEPOSIT|BUY|SELL|SETTLEMENT_PAYOUT
    amount: Mapped[Decimal] = mapped_column(DecimalString())
    market_id: Mapped[str | None] = mapped_column(
        ForeignKey("markets.id", ondelete="RESTRICT"), nullable=True)
    paper_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("paper_orders.id", ondelete="RESTRICT"), nullable=True)
    settlement_id: Mapped[str | None] = mapped_column(
        ForeignKey("paper_settlements.id", ondelete="RESTRICT"), nullable=True)
    memo: Mapped[str] = mapped_column(Text, default="")


class ExecutionIntent(Base):
    """A proposed order. The exact exchange payload and its SHA-256 are fixed at creation;
    an approval must quote that hash. ``status`` moves forward only (every transition is
    also written to execution_events): PROPOSED -> APPROVED -> SUBMITTING -> FILLED |
    PARTIAL | NOT_FILLED | REJECTED | UNKNOWN; or PROPOSED -> BLOCKED / EXPIRED."""

    __tablename__ = "execution_intents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    env: Mapped[str] = mapped_column(String(8))
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id", ondelete="RESTRICT"))
    signal_id: Mapped[str | None] = mapped_column(
        ForeignKey("signals.id", ondelete="RESTRICT"), nullable=True)
    quote_id: Mapped[str] = mapped_column(ForeignKey("quote_snapshots.id", ondelete="RESTRICT"))
    side: Mapped[str] = mapped_column(String(3))  # YES | NO (what we BUY)
    quantity: Mapped[Decimal] = mapped_column(DecimalString())
    limit_price: Mapped[Decimal] = mapped_column(DecimalString())  # price of OUR side
    approved_ask: Mapped[Decimal] = mapped_column(DecimalString())  # snapshot executable ask
    est_fee: Mapped[Decimal] = mapped_column(DecimalString())
    max_cost: Mapped[Decimal] = mapped_column(DecimalString())  # worst case incl. fees
    fee_schedule_version: Mapped[str] = mapped_column(String(64))
    rules_hash: Mapped[str] = mapped_column(String(64))
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True)
    payload_json: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(12))
    block_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ExecutionApproval(Base):
    """Single use: at most one approval per intent (unique constraint)."""

    __tablename__ = "execution_approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    intent_id: Mapped[str] = mapped_column(
        ForeignKey("execution_intents.id", ondelete="RESTRICT"), unique=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime())
    payload_hash: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(32))


class ExecutionEvent(Base):
    """Append-only audit trail of everything that happened to an intent."""

    __tablename__ = "execution_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    intent_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_intents.id", ondelete="RESTRICT"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    detail_json: Mapped[str] = mapped_column(Text, default="{}")


class ExchangeOrder(Base):
    """What the exchange reported for an intent's single submission."""

    __tablename__ = "exchange_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    intent_id: Mapped[str] = mapped_column(
        ForeignKey("execution_intents.id", ondelete="RESTRICT"), unique=True)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime())
    source: Mapped[str] = mapped_column(String(16))  # response | reconciliation
    exchange_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_order_id: Mapped[str] = mapped_column(String(64))
    fill_count: Mapped[Decimal] = mapped_column(DecimalString())
    remaining_count: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    average_fill_price: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    average_fee_paid: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    raw_json: Mapped[str] = mapped_column(Text)


class ExecutionControl(Base):
    """Kill-switch log (append-only). Latest row wins; NO rows means ENGAGED."""

    __tablename__ = "execution_controls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    action: Mapped[str] = mapped_column(String(8))  # ENGAGE | RELEASE
    actor: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text, default="")


class Opportunity(Base):
    """Immutable thesis card produced by the scanner (a suggestion, never an order)."""

    __tablename__ = "opportunities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    kind: Mapped[str] = mapped_column(String(16))
    guaranteed: Mapped[bool] = mapped_column(Boolean)
    confirmed: Mapped[bool] = mapped_column(Boolean)  # re-checked against live orderbooks
    event_ticker: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(Text)
    legs_json: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(DecimalString())
    cost: Mapped[Decimal] = mapped_column(DecimalString())
    fees: Mapped[Decimal] = mapped_column(DecimalString())
    min_payoff: Mapped[Decimal] = mapped_column(DecimalString())
    profit: Mapped[Decimal] = mapped_column(DecimalString())
    return_pct: Mapped[Decimal] = mapped_column(DecimalString())
    claim: Mapped[str] = mapped_column(Text)
    checklist_json: Mapped[str] = mapped_column(Text)
    budget_cap: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    fee_schedule_version: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)


class JournalEntry(Base):
    """Append-only record of what YOU did with a card (executed on Kalshi yourself, skipped,
    or settled), used for the real-money scorecard."""

    __tablename__ = "journal_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    opportunity_id: Mapped[str | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="RESTRICT"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(12))  # EXECUTED | SKIPPED | SETTLED | NOTE
    legs_json: Mapped[str] = mapped_column(Text, default="[]")
    cost: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    payoff: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    object_type: Mapped[str] = mapped_column(String(64))
    object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")


# --- Market catalog (milestone: browse every open Kalshi market) ---------------------------
# A refreshable CACHE of the latest public snapshot, not a record: rows are upserted on each
# full scan and rows not seen in a complete scan are deleted. Nothing here is append-only.


class CatalogSeries(Base):
    __tablename__ = "catalog_series"

    ticker: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64), index=True)
    frequency: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fee_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fee_multiplier: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    refreshed_at: Mapped[datetime] = mapped_column(UTCDateTime())


class CatalogEvent(Base):
    __tablename__ = "catalog_events"

    event_ticker: Mapped[str] = mapped_column(String(128), primary_key=True)
    series_ticker: Mapped[str] = mapped_column(String(128), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(Text)
    sub_title: Mapped[str] = mapped_column(Text, default="")
    competition: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mutually_exclusive: Mapped[bool] = mapped_column(Boolean)
    market_count: Mapped[int] = mapped_column()
    # Floats are for RANKING only (sorting by activity); prices stay exact decimals.
    volume: Mapped[float] = mapped_column()
    volume_24h: Mapped[float] = mapped_column(index=True)
    open_interest: Mapped[float] = mapped_column()
    close_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    occurs_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    rules_sample: Mapped[str] = mapped_column(Text, default="")
    refreshed_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)


class CatalogMarket(Base):
    __tablename__ = "catalog_markets"

    ticker: Mapped[str] = mapped_column(String(160), primary_key=True)
    event_ticker: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(Text)
    yes_sub_title: Mapped[str] = mapped_column(Text, default="")
    no_sub_title: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32))
    yes_bid: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    yes_ask: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    no_bid: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    no_ask: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    yes_bid_size: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    yes_ask_size: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    last_price: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    previous_price: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    volume_24h: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    open_interest: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    close_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    strike_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    floor_strike: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    cap_strike: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    group_key: Mapped[str] = mapped_column(Text, default="")  # custom_strike (team/player)
    refreshed_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)


# --- Your Kalshi account history (read-only sync) ------------------------------------------
# Synced from Kalshi's authenticated READ endpoints and upserted by Kalshi's own ids.
# Personal financial data: it stays in the local database (and its backups) only.


class AccountFill(Base):
    __tablename__ = "account_fills"

    fill_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(160), index=True)
    order_id: Mapped[str] = mapped_column(String(64), default="")
    side: Mapped[str] = mapped_column(String(4))  # contract traded: yes | no
    action: Mapped[str] = mapped_column(String(4))  # buy | sell
    is_taker: Mapped[bool] = mapped_column(Boolean)
    count: Mapped[Decimal] = mapped_column(DecimalString())
    price: Mapped[Decimal] = mapped_column(DecimalString())  # per contract, for `side`
    yes_price: Mapped[Decimal] = mapped_column(DecimalString())
    fee: Mapped[Decimal] = mapped_column(DecimalString())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    source: Mapped[str] = mapped_column(String(16))  # live | historical


class AccountSettlement(Base):
    __tablename__ = "account_settlements"

    ticker: Mapped[str] = mapped_column(String(160), primary_key=True)
    event_ticker: Mapped[str] = mapped_column(String(128), index=True)
    market_result: Mapped[str] = mapped_column(String(8))  # yes | no | scalar | ''
    yes_count: Mapped[Decimal] = mapped_column(DecimalString())
    yes_cost: Mapped[Decimal] = mapped_column(DecimalString())
    no_count: Mapped[Decimal] = mapped_column(DecimalString())
    no_cost: Mapped[Decimal] = mapped_column(DecimalString())
    revenue: Mapped[Decimal] = mapped_column(DecimalString())  # dollars (API sends cents)
    fee: Mapped[Decimal] = mapped_column(DecimalString())
    settled_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)


class AccountPosition(Base):
    __tablename__ = "account_positions"

    ticker: Mapped[str] = mapped_column(String(160), primary_key=True)
    position: Mapped[Decimal] = mapped_column(DecimalString())  # + YES, - NO
    exposure: Mapped[Decimal] = mapped_column(DecimalString())
    realized_pnl: Mapped[Decimal] = mapped_column(DecimalString())
    fees_paid: Mapped[Decimal] = mapped_column(DecimalString())
    total_traded: Mapped[Decimal] = mapped_column(DecimalString())
    last_updated: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    source: Mapped[str] = mapped_column(String(16))  # live | historical


class AccountSync(Base):
    __tablename__ = "account_syncs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    status: Mapped[str] = mapped_column(String(16))
    fills: Mapped[int] = mapped_column(default=0)
    settlements: Mapped[int] = mapped_column(default=0)
    positions: Mapped[int] = mapped_column(default=0)
    balance: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    portfolio_value: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")


class PositionMark(Base):
    """An open position's market price at one moment (every account sync and every scan).
    Kept forever locally: the trail behind 'did my entries beat the closing price?'."""

    __tablename__ = "position_marks"

    ticker: Mapped[str] = mapped_column(String(160), primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), primary_key=True, index=True)
    side: Mapped[str] = mapped_column(String(3))
    contracts: Mapped[Decimal] = mapped_column(DecimalString())
    cost: Mapped[Decimal] = mapped_column(DecimalString())
    yes_bid: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    yes_ask: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    mid: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    source: Mapped[str] = mapped_column(String(8))


class ComboLeg(Base):
    """One leg of a combo market you traded (from the combo's mve_selected_legs)."""

    __tablename__ = "combo_legs"

    combo_ticker: Mapped[str] = mapped_column(String(160), primary_key=True)
    leg_ticker: Mapped[str] = mapped_column(String(160), primary_key=True)
    event_ticker: Mapped[str] = mapped_column(String(128))
    side: Mapped[str] = mapped_column(String(3))
    title: Mapped[str] = mapped_column(String(300))
    result: Mapped[str | None] = mapped_column(String(8), nullable=True)
    refreshed_at: Mapped[datetime] = mapped_column(UTCDateTime())


class CatalogComboEvent(Base):
    """Events Kalshi lets you combine into a combo (multivariate) market, by collection."""

    __tablename__ = "catalog_combo_events"

    event_ticker: Mapped[str] = mapped_column(String(128), primary_key=True)
    collections: Mapped[str] = mapped_column(Text)  # comma-separated collection tickers
    refreshed_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)


class Investigation(Base):
    """One on-demand pick investigation (research only). result_json is the canonical
    app.investigate.schemas.Result; the summary and the full view both read it."""

    __tablename__ = "investigations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(400), index=True)
    ticker: Mapped[str] = mapped_column(String(160), index=True)
    side: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    stale_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    result_json: Mapped[str] = mapped_column(Text)


class SearchLedgerEntry(Base):
    """One Brave Search network attempt (app-side spending caps; see investigate/ledger.py)."""

    __tablename__ = "search_ledger"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    at: Mapped[str] = mapped_column(String(32), index=True)
    purpose: Mapped[str] = mapped_column(String(16), index=True)
    query_hash: Mapped[str] = mapped_column(String(64))


# --- Your bet journal, leg post-mortems and lessons (local only) ---------------------------


class BetJournal(Base):
    """A bet you queued from the Docket (or a slate combo), then placed or skipped. Matched to
    the Kalshi market you actually bought once your history syncs (kalshi_ticker)."""

    __tablename__ = "bet_journal"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(12))
    legs_json: Mapped[str] = mapped_column(Text)
    leg_key: Mapped[str] = mapped_column(String(2000), index=True)
    market_price: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    my_price: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    stake: Mapped[Decimal | None] = mapped_column(DecimalString(), nullable=True)
    source: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(Text, default="")
    kalshi_ticker: Mapped[str | None] = mapped_column(String(160), nullable=True)


class LegOutcome(Base):
    """What actually happened on a leg you traded: the player's stat line vs the line."""

    __tablename__ = "leg_outcomes"

    leg_ticker: Mapped[str] = mapped_column(String(160), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    subject: Mapped[str] = mapped_column(String(120))
    stat: Mapped[str | None] = mapped_column(String(12), nullable=True)
    line: Mapped[float | None] = mapped_column(nullable=True)
    actual: Mapped[float | None] = mapped_column(nullable=True)
    minutes: Mapped[float | None] = mapped_column(nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime())


class Lesson(Base):
    """A lesson from a day's results (written by the local model or by you). Tagged lessons
    (player/stat/side) warn you when a new bet matches them."""

    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    day: Mapped[str] = mapped_column(String(10), index=True)
    text: Mapped[str] = mapped_column(Text)
    player: Mapped[str | None] = mapped_column(String(120), nullable=True)
    stat: Mapped[str | None] = mapped_column(String(12), nullable=True)
    side: Mapped[str | None] = mapped_column(String(3), nullable=True)
    author: Mapped[str] = mapped_column(String(8))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
