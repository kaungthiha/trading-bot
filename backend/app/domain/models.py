"""Immutable, validated domain types shared by adapters, persistence and API."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _to_utc(v: datetime) -> datetime:
    return v.astimezone(UTC)


class PriceRange(Frozen):
    """One segment of a market's allowed price grid: [start, end] in steps of ``step``."""

    start: Decimal
    end: Decimal
    step: Decimal = Field(gt=0)

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, v: Decimal, info) -> Decimal:  # type: ignore[no-untyped-def]
        start = info.data.get("start")
        if start is not None and v < start:
            raise ValueError("price range end must be >= start")
        return v


class BookLevel(Frozen):
    price: Decimal = Field(ge=0)
    quantity: Decimal = Field(gt=0)


class OrderBook(Frozen):
    """Raw bid ladders as the exchange reports them. Asks are NOT stored here.

    ``observed_at`` is when we received the snapshot: Kalshi's REST orderbook response
    carries no exchange timestamp, so receipt time is the best available observation time.
    """

    yes_bids: tuple[BookLevel, ...] = ()
    no_bids: tuple[BookLevel, ...] = ()
    observed_at: AwareDatetime

    @field_validator("observed_at")
    @classmethod
    def normalize_utc(cls, v: datetime) -> datetime:
        return _to_utc(v)


class PriceProvenance(StrEnum):
    EXCHANGE = "exchange"
    DERIVED_FROM_COMPLEMENT = "derived_from_complementary_bid"


class DerivedQuote(Frozen):
    """Best bids (raw) plus complementary-derived asks. ``None`` means no counterparty
    (or, for non-binary markets, that derivation is not supported)."""

    yes_bid: Decimal | None
    no_bid: Decimal | None
    yes_ask: Decimal | None
    no_ask: Decimal | None
    yes_ask_provenance: PriceProvenance | None
    no_ask_provenance: PriceProvenance | None
    spread_yes: Decimal | None


class MarketStatus(StrEnum):
    """Kalshi market lifecycle (docs.kalshi.com/getting_started/market_lifecycle,
    checked 2026-11-18). Unrecognized values map to UNKNOWN; raw value is preserved."""

    INITIALIZED = "initialized"
    INACTIVE = "inactive"
    ACTIVE = "active"
    CLOSED = "closed"
    DETERMINED = "determined"
    DISPUTED = "disputed"
    AMENDED = "amended"
    FINALIZED = "finalized"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, raw: str) -> MarketStatus:
        try:
            return cls(raw)
        except ValueError:
            return cls.UNKNOWN


class MarketType(StrEnum):
    BINARY = "binary"
    SCALAR = "scalar"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, raw: str | None) -> MarketType:
        try:
            return cls(raw or "")
        except ValueError:
            return cls.UNKNOWN


class MarketSnapshot(Frozen):
    """A market as returned by an ExchangeMarketDataAdapter."""

    exchange: str
    external_ticker: str
    event_ticker: str
    series_ticker: str | None = None
    title: str
    category: str
    status: MarketStatus
    status_raw: str
    market_type: MarketType = MarketType.BINARY
    open_at: AwareDatetime | None = None
    close_at: AwareDatetime | None
    rules_text: str
    official_source_url: str | None
    notional_value: Decimal = Field(gt=0)
    price_ranges: tuple[PriceRange, ...]
    orderbook: OrderBook
    is_mock: bool = False

    @field_validator("open_at", "close_at")
    @classmethod
    def normalize_utc(cls, v: datetime | None) -> datetime | None:
        return _to_utc(v) if v is not None else None
