"""Read-only adapter for Kalshi's PUBLIC (unauthenticated) market-data REST endpoints.

Schema verified against official docs on 2026-11-18:
  - getting_started/quick_start_market_data, orderbook_responses, fixed_point_migration,
    rate_limits, market_lifecycle
  - api-reference/market/get-markets, get-market, get-market-orderbook, get-series

Safety properties (enforced here and tested):
  - GET only; never sends Authorization / KALSHI-ACCESS-* headers.
  - Base URL must be one of the documented hosts; path must match a read-only allowlist
    (/markets, /markets/{ticker}, /markets/{ticker}/orderbook, /events/..., /series/...).
  - Redirects are not followed.
  - 429 and 5xx/timeouts retry with bounded exponential backoff (docs: no Retry-After).
  - Requests are spaced by a minimum interval (unauthenticated limits are unpublished).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.adapters.base import AdapterError, AdapterErrorCode, FetchError, FetchResult
from app.adapters.http import RetryingJsonClient
from app.core.clock import Clock
from app.core.config import KALSHI_REST_BASES, Settings
from app.domain.models import (
    BookLevel,
    MarketSnapshot,
    MarketStatus,
    MarketType,
    OrderBook,
    PriceRange,
)

_TICKER = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
_ALLOWED_PATHS = re.compile(
    rf"^/(?:markets(?:/{_TICKER}(?:/orderbook)?)?|events(?:/{_TICKER})?|series(?:/{_TICKER})?"
    r"|multivariate_event_collections)$"
)
_FORBIDDEN_HEADERS = {"authorization", "kalshi-access-key", "kalshi-access-signature",
                      "kalshi-access-timestamp", "cookie"}
USER_AGENT = "krt-local-research/0.1 (read-only)"


class KalshiPublicClient(RetryingJsonClient):
    def __init__(self, base_url: str, **kw: Any) -> None:
        super().__init__(
            base_url,
            allowed_bases=KALSHI_REST_BASES.values(),
            path_pattern=_ALLOWED_PATHS,
            user_agent=USER_AGENT,
            **kw,
        )

    @classmethod
    def from_settings(cls, s: Settings, **kw: Any) -> KalshiPublicClient:
        return cls(
            s.kalshi_rest_base,
            timeout=s.http_timeout_seconds,
            max_retries=s.kalshi_max_retries,
            min_interval=s.kalshi_min_request_interval_seconds,
            **kw,
        )

    def _check_request(self, request: httpx.Request) -> None:
        if _FORBIDDEN_HEADERS & {h.lower() for h in request.headers}:
            raise RuntimeError("Refusing to send credentials from the public client")

    # --- Endpoints -----------------------------------------------------------------
    def get_series(self, series_ticker: str) -> dict[str, Any]:
        return _require_dict(self.get(f"/series/{series_ticker}"), "series")

    def get_market(self, ticker: str) -> dict[str, Any]:
        return _require_dict(self.get(f"/markets/{ticker}"), "market")

    def get_event(self, event_ticker: str) -> dict[str, Any]:
        return _require_dict(
            self.get(f"/events/{event_ticker}", {"exclude_markets": "true"}), "event"
        )

    def get_orderbook(self, ticker: str, depth: int = 0) -> dict[str, Any]:
        return self.get(f"/markets/{ticker}/orderbook", {"depth": depth})

    def iter_markets(
        self, *, series_ticker: str, status: str | None, limit: int, max_pages: int
    ) -> Iterator[dict[str, Any]]:
        """Cursor pagination. Docs: stop on empty cursor; markets may repeat across pages
        if close times change mid-pagination, so dedupe by ticker."""
        seen: set[str] = set()
        cursor: str | None = None
        for _ in range(max_pages):
            params: dict[str, Any] = {"series_ticker": series_ticker, "limit": limit}
            if status:
                params["status"] = status
            if cursor:
                params["cursor"] = cursor
            body = self.get("/markets", params)
            markets = body.get("markets")
            if not isinstance(markets, list):
                raise AdapterError("Missing 'markets' array", AdapterErrorCode.BAD_RESPONSE)
            for m in markets:
                t = m.get("ticker") if isinstance(m, dict) else None
                if isinstance(t, str) and t not in seen:
                    seen.add(t)
                    yield m
            cursor = body.get("cursor") or None
            if not cursor:
                return
        # Hit max_pages with a non-empty cursor: results are truncated, say so.
        raise TruncatedPagination(series_ticker, max_pages)


class TruncatedPagination(AdapterError):
    def __init__(self, series: str, pages: int) -> None:
        super().__init__(
            f"Stopped after {pages} pages for series {series}; more results exist",
            AdapterErrorCode.TRUNCATED,
        )


# --- Parsing -------------------------------------------------------------------------


def _require_dict(body: dict[str, Any], key: str) -> dict[str, Any]:
    v = body.get(key)
    if not isinstance(v, dict):
        raise AdapterError(f"Missing '{key}' object", AdapterErrorCode.BAD_RESPONSE)
    return v


def _dec(v: Any, field: str) -> Decimal:
    if not isinstance(v, str):
        raise AdapterError(f"{field}: expected decimal string", AdapterErrorCode.BAD_RESPONSE)
    try:
        d = Decimal(v)
    except InvalidOperation as exc:
        raise AdapterError(f"{field}: invalid decimal", AdapterErrorCode.BAD_RESPONSE) from exc
    if not d.is_finite():
        raise AdapterError(f"{field}: non-finite decimal", AdapterErrorCode.BAD_RESPONSE)
    return d


def _dt(v: Any, field: str) -> datetime | None:
    if v in (None, ""):
        return None
    if not isinstance(v, str):
        raise AdapterError(f"{field}: expected date-time string", AdapterErrorCode.BAD_RESPONSE)
    try:
        d = datetime.fromisoformat(v)
    except ValueError as exc:
        raise AdapterError(f"{field}: invalid date-time", AdapterErrorCode.BAD_RESPONSE) from exc
    if d.tzinfo is None:
        raise AdapterError(f"{field}: naive date-time", AdapterErrorCode.BAD_RESPONSE)
    return d


def category_slug(raw: str | None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (raw or "").lower()).strip("-")
    return slug[:64] or "uncategorized"


def parse_orderbook(body: dict[str, Any], observed_at: datetime) -> OrderBook:
    """Docs: {"orderbook_fp": {"yes_dollars": [[price, count], ...], "no_dollars": [...]}},
    each side ascending by price (best bid LAST). Bids only; no asks."""
    ob = _require_dict(body, "orderbook_fp")

    def side(key: str) -> tuple[BookLevel, ...]:
        raw = ob.get(key)
        if raw is None:
            return ()
        if not isinstance(raw, list):
            raise AdapterError(f"{key}: expected array", AdapterErrorCode.BAD_RESPONSE)
        levels = []
        for lvl in raw:
            if not (isinstance(lvl, list) and len(lvl) == 2):
                raise AdapterError(f"{key}: malformed level", AdapterErrorCode.BAD_RESPONSE)
            price, qty = _dec(lvl[0], f"{key}.price"), _dec(lvl[1], f"{key}.count")
            if qty > 0:
                levels.append(BookLevel(price=price, quantity=qty))
        # Store best-first for display; derivation uses max() so order doesn't matter.
        return tuple(sorted(levels, key=lambda lv: lv.price, reverse=True))

    return OrderBook(yes_bids=side("yes_dollars"), no_bids=side("no_dollars"),
                     observed_at=observed_at)


def parse_market(
    m: dict[str, Any],
    *,
    series: dict[str, Any] | None,
    orderbook: OrderBook,
    event: dict[str, Any] | None = None,
) -> MarketSnapshot:
    try:
        ticker = m["ticker"]
        event_ticker = m["event_ticker"]
        status_raw = m["status"]
    except KeyError as exc:
        raise AdapterError(f"Market missing field {exc}", AdapterErrorCode.BAD_RESPONSE) from exc

    # `title` is deprecated in the reference schema; fall back to yes_sub_title.
    title = m.get("title") or m.get("yes_sub_title") or ticker
    rules = "\n\n".join(r for r in (m.get("rules_primary"), m.get("rules_secondary")) if r)
    ranges_raw = m.get("price_ranges") or []
    if not isinstance(ranges_raw, list) or not ranges_raw:
        raise AdapterError(f"{ticker}: missing price_ranges", AdapterErrorCode.BAD_RESPONSE)
    ranges = tuple(
        PriceRange(
            start=_dec(r.get("start"), "price_ranges.start"),
            end=_dec(r.get("end"), "price_ranges.end"),
            step=_dec(r.get("step"), "price_ranges.step"),
        )
        for r in ranges_raw
    )
    source_url = None
    if series:
        source_url = series.get("contract_url") or series.get("contract_terms_url") or None
    fee_type, fee_multiplier = effective_fee(series, event)

    return MarketSnapshot(
        exchange="kalshi",
        external_ticker=ticker,
        event_ticker=event_ticker,
        series_ticker=(series or {}).get("ticker"),
        title=title,
        category=category_slug((series or {}).get("category")),
        status=MarketStatus.parse(status_raw),
        status_raw=str(status_raw),
        market_type=MarketType.parse(m.get("market_type")),
        open_at=_dt(m.get("open_time"), "open_time"),
        close_at=_dt(m.get("close_time"), "close_time"),
        rules_text=rules,
        official_source_url=source_url,
        notional_value=_dec(m.get("notional_value_dollars"), "notional_value_dollars"),
        price_ranges=ranges,
        orderbook=orderbook,
        is_mock=False,
        fee_type=fee_type,
        fee_multiplier=fee_multiplier,
        result=m.get("result") if m.get("result") in ("yes", "no", "scalar") else None,
    )


def _num(v: Any) -> Decimal | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float, str)):
        try:
            d = Decimal(str(v))
        except InvalidOperation:
            return None
        return d if d.is_finite() else None
    return None


def effective_fee(
    series: dict[str, Any] | None, event: dict[str, Any] | None
) -> tuple[str | None, Decimal | None]:
    """Event-level overrides win when set (docs: get-event-fee-changes); else series.
    If the event could not be fetched (``event is None``), the override is unknown, so the
    fee is reported as unknown rather than silently assuming the series default."""
    if series is None or event is None:
        return None, None
    fee_type = event.get("fee_type_override") or series.get("fee_type")
    mult = event.get("fee_multiplier_override")
    multiplier = _num(mult) if mult is not None else _num(series.get("fee_multiplier"))
    return (fee_type if isinstance(fee_type, str) else None), multiplier


class KalshiPublicMarketAdapter:
    name = "kalshi_public"

    def __init__(
        self,
        client: KalshiPublicClient,
        clock: Clock,
        *,
        series_watchlist: list[str],
        status: str | None = "open",
        page_limit: int = 200,
        max_pages: int = 10,
        orderbook_depth: int = 10,
    ) -> None:
        self.client = client
        self.clock = clock
        self.series_watchlist = series_watchlist
        self.status = status
        self.page_limit = page_limit
        self.max_pages = max_pages
        self.depth = orderbook_depth

    @classmethod
    def from_settings(
        cls, s: Settings, clock: Clock, client: KalshiPublicClient | None = None
    ) -> KalshiPublicMarketAdapter:
        return cls(
            client or KalshiPublicClient.from_settings(s),
            clock,
            series_watchlist=s.kalshi_series_watchlist,
            status=s.kalshi_market_status,
            page_limit=s.kalshi_page_limit,
            max_pages=s.kalshi_max_pages,
            orderbook_depth=s.kalshi_orderbook_depth,
        )

    def refresh_tickers(self, tickers: list[str]) -> FetchResult:
        """Re-fetch specific markets regardless of status (e.g. held paper positions after
        close, to pick up the exchange result)."""
        snapshots: list[MarketSnapshot] = []
        errors: list[FetchError] = []
        for i in range(0, len(tickers), 50):
            chunk = tickers[i:i + 50]
            try:
                body = self.client.get("/markets", {"tickers": ",".join(chunk)})
            except AdapterError as e:
                errors.append(FetchError(f"tickers:{chunk[0]}..", e.code, str(e)))
                continue
            series_cache: dict[str, dict[str, Any] | None] = {}
            events: dict[str, dict[str, Any] | None] = {}
            for m in body.get("markets") or []:
                scope = f"market:{m.get('ticker')}"
                try:
                    st = str(m.get("event_ticker", "")).split("-")[0]
                    if st not in series_cache:
                        try:
                            series_cache[st] = self.client.get_series(st)
                        except AdapterError:
                            series_cache[st] = None
                    et = m.get("event_ticker")
                    if et not in events:
                        try:
                            events[et] = self.client.get_event(et)
                        except AdapterError:
                            events[et] = None
                    book = parse_orderbook(self.client.get_orderbook(m["ticker"], self.depth),
                                           self.clock.now())
                    snapshots.append(parse_market(m, series=series_cache[st], orderbook=book,
                                                  event=events[et]))
                except AdapterError as e:
                    errors.append(FetchError(scope, e.code, str(e)))
        return FetchResult(snapshots=snapshots, errors=errors)

    def fetch_markets(self) -> FetchResult:
        if not self.series_watchlist:
            raise AdapterError(
                "No series configured (set KRT_KALSHI_SERIES_WATCHLIST)",
                AdapterErrorCode.SOURCE_UNAVAILABLE,
            )
        snapshots: list[MarketSnapshot] = []
        errors: list[FetchError] = []
        for series_ticker in self.series_watchlist:
            try:
                series = self.client.get_series(series_ticker)
                markets = self.client.iter_markets(
                    series_ticker=series_ticker,
                    status=self.status,
                    limit=self.page_limit,
                    max_pages=self.max_pages,
                )
                events: dict[str, dict[str, Any] | None] = {}
                for m in markets:
                    scope = f"market:{m.get('ticker')}"
                    et = m.get("event_ticker")
                    if isinstance(et, str) and et not in events:
                        try:
                            events[et] = self.client.get_event(et)
                        except AdapterError as e:
                            events[et] = None  # fee override unknown -> fee unknown
                            errors.append(FetchError(f"event:{et}", e.code, str(e)))
                    try:
                        body = self.client.get_orderbook(m["ticker"], self.depth)
                        book = parse_orderbook(body, self.clock.now())
                        snapshots.append(parse_market(
                            m, series=series, orderbook=book, event=events.get(et)))
                    except AdapterError as e:
                        errors.append(FetchError(scope, e.code, str(e)))
            except AdapterError as e:
                errors.append(FetchError(f"series:{series_ticker}", e.code, str(e)))
        if not snapshots and errors and len(errors) >= len(self.series_watchlist):
            # Every series failed outright: total failure, never pretend success.
            if all(e.scope.startswith("series:") for e in errors):
                raise AdapterError(
                    "All configured series failed: " + "; ".join(e.message for e in errors),
                    AdapterErrorCode.SOURCE_UNAVAILABLE,
                )
        return FetchResult(snapshots=snapshots, errors=errors)
