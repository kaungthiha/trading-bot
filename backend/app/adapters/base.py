"""Adapter interfaces. Kept separate so research/paper code never depends on execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from app.domain.models import MarketSnapshot


class AdapterErrorCode(StrEnum):
    NETWORK = "NETWORK"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    NOT_FOUND = "NOT_FOUND"
    HTTP_ERROR = "HTTP_ERROR"
    BAD_RESPONSE = "BAD_RESPONSE"
    TRUNCATED = "TRUNCATED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


class AdapterError(Exception):
    """Raised when a source fails; callers must surface it, never invent data."""

    def __init__(
        self,
        message: str,
        code: AdapterErrorCode = AdapterErrorCode.SOURCE_UNAVAILABLE,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class FetchError:
    scope: str  # e.g. "series:KXCPI" or "market:KXCPI-26DEC-T3.0"
    code: str
    message: str


@dataclass(frozen=True)
class FetchResult:
    snapshots: list[MarketSnapshot] = field(default_factory=list)
    errors: list[FetchError] = field(default_factory=list)


class ExchangeMarketDataAdapter(Protocol):
    """Read-only exchange market data. Must never call authenticated or write endpoints.

    Partial failures are reported in ``FetchResult.errors``; a total failure raises
    ``AdapterError``.
    """

    name: str

    def fetch_markets(self) -> FetchResult: ...
