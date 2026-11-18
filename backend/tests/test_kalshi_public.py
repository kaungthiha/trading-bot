from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest

from app.adapters.base import AdapterError, AdapterErrorCode
from app.adapters.kalshi_public import (
    KalshiPublicClient,
    KalshiPublicMarketAdapter,
    category_slug,
    parse_market,
    parse_orderbook,
)
from app.core.clock import FrozenClock
from app.core.config import KALSHI_REST_BASES, KalshiEnv
from app.domain.models import MarketStatus, MarketType
from app.domain.pricing import derive_quote
from tests.conftest import FROZEN_NOW
from tests.kalshi_payloads import DEFAULT_BOOK, EVENT, SERIES, market, orderbook

BASE = KALSHI_REST_BASES[KalshiEnv.PRODUCTION]
D = Decimal

Handler = Callable[[httpx.Request], httpx.Response]


class Recorder:
    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


def make_client(handler: Handler, **kw) -> tuple[KalshiPublicClient, Recorder, list[float]]:  # type: ignore[no-untyped-def]
    rec = Recorder(handler)
    sleeps: list[float] = []
    client = KalshiPublicClient(
        BASE,
        transport=httpx.MockTransport(rec),
        sleep=sleeps.append,
        monotonic=lambda: 0.0,
        min_interval=0.0,
        **kw,
    )
    return client, rec, sleeps


def router(routes: dict[str, object]) -> Handler:
    def handle(req: httpx.Request) -> httpx.Response:
        path = req.url.path.removeprefix("/trade-api/v2")
        body = routes.get(path)
        if body is None:
            return httpx.Response(404, json={"code": "not_found", "message": "not found"})
        if callable(body):
            return body(req)
        return httpx.Response(200, json=body)

    return handle


# --- Parsing -------------------------------------------------------------------------


def test_orderbook_best_bid_is_last_and_asks_derive() -> None:
    book = parse_orderbook(DEFAULT_BOOK, FROZEN_NOW)
    assert book.yes_bids[0].price == D("0.4300")  # stored best-first
    q = derive_quote(book, D("1.0000"))
    assert q.yes_bid == D("0.4300") and q.no_bid == D("0.5500")
    assert q.yes_ask == D("0.4500") and q.no_ask == D("0.5700")
    assert str(q.yes_ask) == "0.4500"  # precision preserved


def test_orderbook_missing_and_empty_sides() -> None:
    book = parse_orderbook(orderbook(yes=[["0.2000", "40.00"]], no=[]), FROZEN_NOW)
    q = derive_quote(book)
    assert q.yes_ask is None and q.no_ask == D("0.8000")
    empty = parse_orderbook({"orderbook_fp": {"yes_dollars": [], "no_dollars": []}}, FROZEN_NOW)
    assert empty.yes_bids == () and empty.no_bids == ()


def test_orderbook_sub_cent_and_fractional_counts() -> None:
    book = parse_orderbook(orderbook(yes=[["0.0450", "0.50"]], no=[["0.9400", "2.25"]]), FROZEN_NOW)
    assert book.yes_bids[0].quantity == D("0.50")
    assert derive_quote(book).yes_ask == D("0.0600")


def test_zero_quantity_levels_are_dropped() -> None:
    book = parse_orderbook(orderbook(yes=[["0.4000", "0.00"]], no=[]), FROZEN_NOW)
    assert book.yes_bids == ()


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"orderbook_fp": {"yes_dollars": "nope"}},
        {"orderbook_fp": {"yes_dollars": [["0.40"]]}},
        {"orderbook_fp": {"yes_dollars": [[0.40, "1.00"]]}},  # float, not string
        {"orderbook_fp": {"yes_dollars": [["abc", "1.00"]]}},
        {"orderbook_fp": {"yes_dollars": [["NaN", "1.00"]]}},
    ],
)
def test_malformed_orderbook_rejected(bad: dict) -> None:
    with pytest.raises(AdapterError) as ei:
        parse_orderbook(bad, FROZEN_NOW)
    assert ei.value.code is AdapterErrorCode.BAD_RESPONSE


def test_parse_market_fields() -> None:
    book = parse_orderbook(DEFAULT_BOOK, FROZEN_NOW)
    snap = parse_market(market("TESTCPI-26DEC-T3.0"), series=SERIES["series"], orderbook=book)
    assert snap.title == "Above threshold (TESTCPI-26DEC-T3.0)"  # title deprecated -> sub_title
    assert snap.category == "economics"
    assert snap.series_ticker == "TESTCPI"
    assert snap.status is MarketStatus.ACTIVE and snap.status_raw == "active"
    assert snap.market_type is MarketType.BINARY
    assert snap.notional_value == D("1.0000")
    assert snap.price_ranges[0].step == D("0.0100")
    assert "Revisions after first publication" in snap.rules_text  # secondary included
    assert snap.official_source_url == "https://example.com/contract.pdf"
    assert snap.close_at is not None and snap.close_at.tzinfo is not None
    assert snap.is_mock is False


def test_unknown_status_preserved_raw() -> None:
    book = parse_orderbook(DEFAULT_BOOK, FROZEN_NOW)
    snap = parse_market(market("T1", status="halted_new"), series=None, orderbook=book)
    assert snap.status is MarketStatus.UNKNOWN and snap.status_raw == "halted_new"
    assert snap.category == "uncategorized"


def test_market_missing_price_ranges_rejected() -> None:
    book = parse_orderbook(DEFAULT_BOOK, FROZEN_NOW)
    with pytest.raises(AdapterError):
        parse_market(market("T1", price_ranges=[]), series=None, orderbook=book)


def test_naive_datetime_rejected() -> None:
    book = parse_orderbook(DEFAULT_BOOK, FROZEN_NOW)
    with pytest.raises(AdapterError):
        parse_market(market("T1", close_time="2026-12-10T13:25:00"), series=None, orderbook=book)


def test_category_slug() -> None:
    assert category_slug("Climate and Weather") == "climate-and-weather"
    assert category_slug(None) == "uncategorized"


# --- Client safety and reliability ---------------------------------------------------


def test_only_documented_hosts_allowed() -> None:
    with pytest.raises(ValueError):
        KalshiPublicClient("https://evil.example/trade-api/v2")


@pytest.mark.parametrize(
    "path",
    [
        "/portfolio/orders",
        "/portfolio/events/orders",
        "/portfolio/balance",
        "/markets/../portfolio/orders",
        "/markets/T1/orders",
        "https://evil.example/markets",
    ],
)
def test_non_read_only_paths_refused(path: str) -> None:
    client, rec, _ = make_client(router({}))
    with pytest.raises(ValueError):
        client.get(path)
    assert rec.requests == []


def test_requests_are_get_without_credentials() -> None:
    client, rec, _ = make_client(router({"/markets/T1": {"market": market("T1")}}))
    client.get_market("T1")
    (req,) = rec.requests
    assert req.method == "GET"
    lowered = {h.lower() for h in req.headers}
    assert not lowered & {"authorization", "kalshi-access-key", "kalshi-access-signature", "cookie"}
    assert str(req.url).startswith(BASE)


def test_429_retries_with_exponential_backoff_then_succeeds() -> None:
    calls = {"n": 0}

    def flaky(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(
                429, json={"error": {"code": "too_many_requests", "message": "too many requests"}}
            )
        return httpx.Response(200, json={"market": market("T1")})

    client, rec, sleeps = make_client(router({"/markets/T1": flaky}), backoff_base=0.5)
    assert client.get_market("T1")["ticker"] == "T1"
    assert len(rec.requests) == 3
    assert sleeps == [0.5, 1.0]


def test_429_exhausted_raises_rate_limited() -> None:
    client, rec, sleeps = make_client(
        lambda _: httpx.Response(429, json={}), max_retries=3, backoff_base=1.0, backoff_cap=3.0
    )
    with pytest.raises(AdapterError) as ei:
        client.get_market("T1")
    assert ei.value.code is AdapterErrorCode.RATE_LIMITED and ei.value.status == 429
    assert len(rec.requests) == 4
    assert sleeps == [1.0, 2.0, 3.0]  # capped


def test_5xx_retried_4xx_not() -> None:
    client, rec, _ = make_client(lambda _: httpx.Response(503), max_retries=1)
    with pytest.raises(AdapterError) as ei:
        client.get_market("T1")
    assert ei.value.code is AdapterErrorCode.UPSTREAM_ERROR and len(rec.requests) == 2

    client, rec, _ = make_client(lambda _: httpx.Response(400, json={}), max_retries=3)
    with pytest.raises(AdapterError) as ei:
        client.get_market("T1")
    assert ei.value.code is AdapterErrorCode.HTTP_ERROR and len(rec.requests) == 1


def test_timeout_retried_then_network_error() -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=req)

    client, rec, sleeps = make_client(boom, max_retries=2)
    with pytest.raises(AdapterError) as ei:
        client.get_market("T1")
    assert ei.value.code is AdapterErrorCode.NETWORK
    assert len(rec.requests) == 3 and len(sleeps) == 2


def test_redirects_not_followed() -> None:
    client, rec, _ = make_client(
        lambda _: httpx.Response(302, headers={"location": "https://evil.example/"})
    )
    with pytest.raises(AdapterError):
        client.get_market("T1")
    assert len(rec.requests) == 1


def test_non_json_response() -> None:
    client, _, _ = make_client(lambda _: httpx.Response(200, text="<html>"))
    with pytest.raises(AdapterError) as ei:
        client.get_market("T1")
    assert ei.value.code is AdapterErrorCode.BAD_RESPONSE


def test_min_interval_throttle() -> None:
    t = {"now": 0.0}
    sleeps: list[float] = []
    client = KalshiPublicClient(
        BASE,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"market": market("T1")})),
        sleep=lambda s: (sleeps.append(s), t.__setitem__("now", t["now"] + s)),
        monotonic=lambda: t["now"],
        min_interval=0.25,
    )
    client.get_market("T1")
    client.get_market("T1")
    assert sleeps == [0.25]


# --- Pagination ----------------------------------------------------------------------


def paged(pages: list[dict]) -> Handler:
    def handle(req: httpx.Request) -> httpx.Response:
        cursor = req.url.params.get("cursor") or ""
        idx = int(cursor) if cursor else 0
        return httpx.Response(200, json=pages[idx])

    return handle


def test_pagination_follows_cursor_and_dedupes() -> None:
    pages = [
        {"markets": [market("A"), market("B")], "cursor": "1"},
        {"markets": [market("B"), market("C")], "cursor": ""},  # B repeated across pages
    ]
    client, rec, _ = make_client(router({"/markets": paged(pages)}))
    tickers = [m["ticker"] for m in client.iter_markets(
        series_ticker="TESTCPI", status="open", limit=2, max_pages=5)]
    assert tickers == ["A", "B", "C"]
    assert len(rec.requests) == 2
    first = rec.requests[0].url.params
    assert first["series_ticker"] == "TESTCPI" and first["status"] == "open"
    assert first["limit"] == "2" and "cursor" not in first
    assert rec.requests[1].url.params["cursor"] == "1"


def test_pagination_truncation_is_reported() -> None:
    pages = [{"markets": [market(f"M{i}")], "cursor": str(i + 1)} for i in range(5)]
    client, _, _ = make_client(router({"/markets": paged(pages)}))
    got: list[str] = []
    with pytest.raises(AdapterError) as ei:
        for m in client.iter_markets(series_ticker="S", status=None, limit=1, max_pages=2):
            got.append(m["ticker"])
    assert got == ["M0", "M1"]
    assert ei.value.code is AdapterErrorCode.TRUNCATED


# --- Adapter -------------------------------------------------------------------------


def adapter_for(routes: dict[str, object], series: list[str] | None = None):  # type: ignore[no-untyped-def]
    client, rec, _ = make_client(router(routes), max_retries=0)
    return (
        KalshiPublicMarketAdapter(
            client, FrozenClock(FROZEN_NOW), series_watchlist=series or ["TESTCPI"]
        ),
        rec,
    )


def test_adapter_fetches_series_markets_and_books() -> None:
    adapter, rec = adapter_for({
        "/series/TESTCPI": SERIES,
        "/events/TESTCPI-26DEC": EVENT,
        "/markets": {"markets": [market("TESTCPI-26DEC-T3.0"), market("TESTCPI-26DEC-T3.5")],
                     "cursor": ""},
        "/markets/TESTCPI-26DEC-T3.0/orderbook": DEFAULT_BOOK,
        "/markets/TESTCPI-26DEC-T3.5/orderbook": orderbook(yes=[], no=[]),
    })
    result = adapter.fetch_markets()
    assert result.errors == []
    assert [s.external_ticker for s in result.snapshots] == [
        "TESTCPI-26DEC-T3.0", "TESTCPI-26DEC-T3.5"]
    assert result.snapshots[0].orderbook.observed_at == FROZEN_NOW
    assert all(r.method == "GET" for r in rec.requests)
    assert rec.requests[-1].url.params["depth"] == "10"


def test_adapter_partial_failure_recorded() -> None:
    adapter, _ = adapter_for({
        "/series/TESTCPI": SERIES,
        "/events/TESTCPI-26DEC": EVENT,
        "/markets": {"markets": [market("OK"), market("BROKEN")], "cursor": ""},
        "/markets/OK/orderbook": DEFAULT_BOOK,
        "/markets/BROKEN/orderbook": {"unexpected": True},
    })
    result = adapter.fetch_markets()
    assert [s.external_ticker for s in result.snapshots] == ["OK"]
    assert len(result.errors) == 1
    assert result.errors[0].scope == "market:BROKEN"
    assert result.errors[0].code == "BAD_RESPONSE"


def test_adapter_total_failure_raises() -> None:
    adapter, _ = adapter_for({}, series=["NOPE1", "NOPE2"])
    with pytest.raises(AdapterError) as ei:
        adapter.fetch_markets()
    assert ei.value.code is AdapterErrorCode.SOURCE_UNAVAILABLE


def test_adapter_requires_watchlist() -> None:
    adapter, rec = adapter_for({}, series=[])
    adapter.series_watchlist = []
    with pytest.raises(AdapterError):
        adapter.fetch_markets()
    assert rec.requests == []


# --- Fees ------------------------------------------------------------------------------


def test_effective_fee_series_and_event_override() -> None:
    from app.adapters.kalshi_public import effective_fee

    s = {**SERIES["series"], "fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1}
    assert effective_fee(s, EVENT["event"]) == ("quadratic_with_maker_fees", D("1"))
    ov = {**EVENT["event"], "fee_type_override": "flat", "fee_multiplier_override": 0.5}
    assert effective_fee(s, ov) == ("flat", D("0.5"))
    assert effective_fee(s, None) == (None, None)  # override unknown -> fee unknown


def test_adapter_event_failure_recorded_and_fee_unknown() -> None:
    adapter, _ = adapter_for({
        "/series/TESTCPI": SERIES,
        "/markets": {"markets": [market("OK")], "cursor": ""},
        "/markets/OK/orderbook": DEFAULT_BOOK,
    })
    result = adapter.fetch_markets()
    assert [e.scope for e in result.errors] == ["event:TESTCPI-26DEC"]
    assert result.snapshots[0].fee_type is None and result.snapshots[0].fee_multiplier is None
