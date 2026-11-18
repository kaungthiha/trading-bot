"""Offline fixture adapter returning clearly-labeled synthetic markets.

These are NOT real Kalshi markets. Tickers are prefixed ``MOCK-`` and every snapshot has
``is_mock=True`` so the UI can label them.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.adapters.base import AdapterError, AdapterErrorCode, FetchResult
from app.domain.models import MarketSnapshot

DEFAULT_FIXTURE = Path(__file__).parent / "fixtures" / "mock_markets.json"


class FixtureMarketAdapter:
    name = "fixture"

    def __init__(self, path: Path = DEFAULT_FIXTURE) -> None:
        self._path = path

    def list_markets(self) -> list[MarketSnapshot]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AdapterError(
                f"Could not read market fixture {self._path.name}", AdapterErrorCode.BAD_RESPONSE
            ) from exc
        markets = [MarketSnapshot.model_validate({**m, "is_mock": True}) for m in raw["markets"]]
        for m in markets:
            if not m.external_ticker.startswith("MOCK-"):
                raise AdapterError("Fixture tickers must start with MOCK-")
        return markets

    def fetch_markets(self) -> FetchResult:
        return FetchResult(snapshots=self.list_markets())
