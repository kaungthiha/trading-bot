"""Response schemas. Decimals serialize as exact strings in JSON."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.domain.models import PriceProvenance, PriceRange


class HealthOut(BaseModel):
    status: str
    version: str
    env: str
    trading_mode: str
    live_execution_enabled: bool
    market_data_source: str
    kalshi_env: str
    database: str
    server_time: datetime
    # Booleans only -- credential VALUES are never returned.
    credentials_configured: dict[str, bool]


class QuoteOut(BaseModel):
    observed_at: datetime
    received_at: datetime
    age_seconds: float
    is_stale: bool
    max_age_seconds: int
    yes_bid: Decimal | None
    no_bid: Decimal | None
    yes_ask: Decimal | None
    no_ask: Decimal | None
    yes_ask_provenance: PriceProvenance | None
    no_ask_provenance: PriceProvenance | None
    spread_yes: Decimal | None


class MarketSummaryOut(BaseModel):
    id: str
    exchange: str
    external_ticker: str
    event_ticker: str
    series_ticker: str | None
    title: str
    category: str
    status: str
    status_raw: str | None
    market_type: str | None
    open_at: datetime | None
    close_at: datetime | None
    is_mock: bool
    quote: QuoteOut | None


class QuoteHistoryItemOut(BaseModel):
    id: str
    observed_at: datetime
    received_at: datetime
    yes_bid: Decimal | None
    no_bid: Decimal | None
    yes_ask: Decimal | None
    no_ask: Decimal | None
    raw_ref: str | None


class QuoteHistoryOut(BaseModel):
    market_id: str
    items: list[QuoteHistoryItemOut]


class IngestionErrorOut(BaseModel):
    scope: str
    code: str
    message: str


class IngestionRunOut(BaseModel):
    id: str
    adapter: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    count: int
    errors: list[IngestionErrorOut]


class IngestionRunListOut(BaseModel):
    items: list[IngestionRunOut]


class CategoriesOut(BaseModel):
    items: list[str]


class EvidenceSourceOut(BaseModel):
    id: str
    title: str
    series_id: str
    category: str
    frequency: str
    upstream_agency: str
    source_page_url: str
    license_notes: str
    attribution: str | None
    release_timing_note: str
    configured: bool
    record_count: int
    latest_vintage: str | None
    latest_available_at: datetime | None
    is_fresh: bool
    freshness_max_age_days: int
    last_run: IngestionRunOut | None


class EvidenceSourceListOut(BaseModel):
    items: list[EvidenceSourceOut]


class EvidenceObservationOut(BaseModel):
    observation_date: str
    vintage_date: str
    value: Decimal | None
    quality: str
    available_at: datetime
    retrieved_at: datetime
    units: str | None
    source_url: str


class EvidenceAsOfOut(BaseModel):
    source_id: str
    as_of: datetime
    items: list[EvidenceObservationOut]


class EvidenceVintagesOut(BaseModel):
    source_id: str
    observation_date: str
    items: list[EvidenceObservationOut]


class CollectionGapOut(BaseModel):
    id: str
    job: str
    gap_start: datetime
    gap_end: datetime
    detected_at: datetime
    backfillable: bool
    reason: str


class CollectionGapListOut(BaseModel):
    items: list[CollectionGapOut]


class BookLevelOut(BaseModel):
    price: Decimal
    quantity: Decimal


class RulesOut(BaseModel):
    text: str
    official_source_url: str | None
    hash: str
    observed_at: datetime


class MarketDetailOut(MarketSummaryOut):
    notional_value: Decimal
    price_ranges: list[PriceRange]
    rules: RulesOut | None
    yes_bids: list[BookLevelOut]
    no_bids: list[BookLevelOut]
    updated_at: datetime


class MarketListOut(BaseModel):
    items: list[MarketSummaryOut]
    limit: int
    offset: int
