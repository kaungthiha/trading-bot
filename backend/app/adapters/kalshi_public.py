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
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.adapters.base import AdapterError, AdapterErrorCode, FetchError, FetchResult
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
    rf"^/(?:markets(?:/{_TICKER}(?:/orderbook)?)?|events(?:/{_TICKER})?|series(?:/{_TICKER})?)$"
)
_FORBIDDEN_HEADERS = {"authorization", "kalshi-access-key", "kalshi-access-signature",
                      "kalshi-access-timestamp", "cookie"}
USER_AGENT = "krt-local-research/0.1 (read-only)"


class KalshiPublicClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 10.0,
        max_retries: int = 4,
        min_interval: float = 0.25,
        backoff_base: float = 0.5,
        backoff_cap: float = 8.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if base_url not in KALSHI_REST_BASES.values():
            raise ValueError("Base URL is not a documented Kalshi public REST host")
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )
        self._max_retries = max_retries
        self._min_interval = min_interval
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request: float | None = None
        self.request_count = 0

    @classmethod
    def from_settings(cls, s: Settings, **kw: Any) -> KalshiPublicClient:
        return cls(
            s.kalshi_rest_base,
            timeout=s.http_timeout_seconds,
            max_retries=s.kalshi_max_retries,
            min_interval=s.kalshi_min_request_interval_seconds,
            **kw,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> KalshiPublicClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _throttle(self) -> None:
        now = self._monotonic()
        if self._last_request is not None:
            wait = self._min_interval - (now - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._monotonic()

    def _backoff(self, attempt: int) -> None:
        self._sleep(min(self._backoff_base * (2**attempt), self._backoff_cap))

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not _ALLOWED_PATHS.fullmatch(path):
            raise ValueError(f"Path not in read-only allowlist: {path!r}")
        attempt = 0
        while True:
            self._throttle()
            request = self._http.build_request("GET", path, params=params)
            if _FORBIDDEN_HEADERS & {h.lower() for h in request.headers}:
                raise RuntimeError("Refusing to send credentials from the public client")
            self.request_count += 1
            try:
                resp = self._http.send(request)
            except httpx.TimeoutException as exc:
                if attempt >= self._max_retries:
                    raise AdapterError("Request timed out", AdapterErrorCode.NETWORK) from exc
                self._backoff(attempt)
                attempt += 1
                continue
            except httpx.TransportError as exc:
                if attempt >= self._max_retries:
                    raise AdapterError("Network error", AdapterErrorCode.NETWORK) from exc
                self._backoff(attempt)
                attempt += 1
                continue

            status = resp.status_code
            if status == 429 or status >= 500:
                if attempt >= self._max_retries:
                    code = (
                        AdapterErrorCode.RATE_LIMITED
                        if status == 429
                        else AdapterErrorCode.UPSTREAM_ERROR
                    )
                    raise AdapterError(f"Upstream returned {status}", code, status)
                self._backoff(attempt)
                attempt += 1
                continue
            if status == 404:
                raise AdapterError("Not found", AdapterErrorCode.NOT_FOUND, status)
            if status >= 300:
                raise AdapterError(
                    f"Upstream returned {status}", AdapterErrorCode.HTTP_ERROR, status
                )
            try:
                body = resp.json()
            except ValueError as exc:
                raise AdapterError("Response was not JSON", AdapterErrorCode.BAD_RESPONSE) from exc
            if not isinstance(body, dict):
                raise AdapterError("Unexpected response shape", AdapterErrorCode.BAD_RESPONSE)
            return body

    # --- Endpoints -----------------------------------------------------------------
    def get_series(self, series_ticker: str) -> dict[str, Any]:
        return _require_dict(self.get(f"/series/{series_ticker}"), "series")

    def get_market(self, ticker: str) -> dict[str, Any]:
        return _require_dict(self.get(f"/markets/{ticker}"), "market")

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
    )


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
                for m in markets:
                    scope = f"market:{m.get('ticker')}"
                    try:
                        body = self.client.get_orderbook(m["ticker"], self.depth)
                        book = parse_orderbook(body, self.clock.now())
                        snapshots.append(parse_market(m, series=series, orderbook=book))
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
