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


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    object_type: Mapped[str] = mapped_column(String(64))
    object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
