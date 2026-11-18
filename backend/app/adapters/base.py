"""Adapter interfaces. Kept separate so research/paper code never depends on execution."""

from __future__ import annotations

from typing import Protocol

from app.domain.models import MarketSnapshot


class AdapterError(Exception):
    """Raised when a source fails; callers must surface it, never invent data."""


class ExchangeMarketDataAdapter(Protocol):
    """Read-only exchange market data. Must never call authenticated or write endpoints."""

    name: str

    def list_markets(self) -> list[MarketSnapshot]: ...
