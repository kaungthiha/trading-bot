"""SYNTHETIC payloads shaped like Kalshi's documented public responses (2026-11-18 docs).

Values are invented for tests; tickers use a TEST prefix so they cannot be mistaken for
real markets.
"""

from __future__ import annotations

from typing import Any

SERIES = {
    "series": {
        "ticker": "TESTCPI",
        "frequency": "monthly",
        "title": "Test CPI series",
        "category": "Economics",
        "categories": ["Economics"],
        "tags": [],
        "settlement_sources": [{"name": "Source agency", "url": "https://example.gov/cpi"}],
        "contract_url": "https://example.com/contract.pdf",
        "contract_terms_url": "https://example.com/terms.pdf",
        "fee_type": "quadratic",
        "fee_multiplier": 1,
        "additional_prohibitions": [],
    }
}


def market(ticker: str, **over: Any) -> dict[str, Any]:
    m = {
        "ticker": ticker,
        "event_ticker": "TESTCPI-26DEC",
        "market_type": "binary",
        "yes_sub_title": f"Above threshold ({ticker})",
        "no_sub_title": f"Above threshold ({ticker})",
        "created_time": "2026-11-01T00:00:00Z",
        "updated_time": "2026-11-17T00:00:00Z",
        "open_time": "2026-11-02T14:00:00Z",
        "close_time": "2026-12-10T13:25:00Z",
        "latest_expiration_time": "2026-12-17T15:00:00Z",
        "settlement_timer_seconds": 3600,
        "status": "active",
        "notional_value_dollars": "1.0000",
        "yes_bid_dollars": "0.4300",
        "yes_ask_dollars": "0.4500",
        "no_bid_dollars": "0.5500",
        "no_ask_dollars": "0.5700",
        "last_price_dollars": "0.4400",
        "volume_fp": "100.00",
        "result": "",
        "rules_primary": "If the test statistic is above 3.0%, the market resolves to Yes.",
        "rules_secondary": "Revisions after first publication are not considered.",
        "price_level_structure": "linear_cent",
        "price_ranges": [{"start": "0.0000", "end": "1.0000", "step": "0.0100"}],
    }
    m.update(over)
    return m


def orderbook(yes: list[list[str]], no: list[list[str]]) -> dict[str, Any]:
    # Documented: each side ascending by price; best bid is the LAST element.
    return {"orderbook_fp": {"yes_dollars": yes, "no_dollars": no}}


DEFAULT_BOOK = orderbook(
    yes=[["0.4100", "50.00"], ["0.4200", "13.00"], ["0.4300", "120.00"]],
    no=[["0.5300", "10.00"], ["0.5500", "80.00"]],
)


EVENT = {
    "event": {
        "event_ticker": "TESTCPI-26DEC",
        "series_ticker": "TESTCPI",
        "title": "Test CPI December",
        "sub_title": "",
        "collateral_return_type": "",
        "mutually_exclusive": False,
        "settlement_sources": [],
        "fee_type_override": None,
        "fee_multiplier_override": None,
    }
}
