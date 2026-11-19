"""Fetch every open Kalshi event with nested markets (public, read-only) and convert to the
detector inputs. ~200 events per call, so a full scan is a few dozen requests. Candidates
are then re-confirmed against each leg's full orderbook before being shown."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from decimal import Decimal, InvalidOperation
from typing import Any

from app.adapters.base import AdapterError
from app.adapters.kalshi_public import KalshiPublicClient
from app.scanner.detectors import EventBook, LegQuote, Opportunity, TopOfBook


def _dec(v: Any) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _price(v: Any) -> Decimal | None:
    d = _dec(v)
    # 0 or 1 means "no order on that side" in top-of-book fields
    return d if d is not None and Decimal(0) < d < Decimal(1) else None


def parse_event(e: dict[str, Any]) -> EventBook:
    markets = []
    for m in e.get("markets") or []:
        markets.append(TopOfBook(
            ticker=str(m.get("ticker")), title=str(m.get("yes_sub_title") or m.get("title")
                                                   or m.get("ticker")),
            status=str(m.get("status")), yes_bid=_price(m.get("yes_bid_dollars")),
            yes_ask=_price(m.get("yes_ask_dollars")),
            yes_bid_size=_dec(m.get("yes_bid_size_fp")) or Decimal(0),
            yes_ask_size=_dec(m.get("yes_ask_size_fp")) or Decimal(0),
            strike_type=m.get("strike_type"), floor_strike=_dec(m.get("floor_strike")),
            rules=m.get("rules_primary"),
        ))
    return EventBook(str(e.get("event_ticker")), str(e.get("title") or e.get("event_ticker")),
                     bool(e.get("mutually_exclusive")), markets,
                     category=str(e.get("category") or "Uncategorized"))


def fetch_open_events(client: KalshiPublicClient, max_pages: int = 300,
                      on_page: Callable[[list[dict[str, Any]]], None] | None = None
                      ) -> tuple[list[EventBook], bool]:
    """All open events. Returns (events, truncated) -- truncated means the page limit was
    hit with more results remaining, which the caller must report, not hide. `on_page`
    receives each raw page (the market catalog is written from it)."""
    events: list[EventBook] = []
    cursor = None
    for _ in range(max_pages):
        params: dict[str, Any] = {"status": "open", "with_nested_markets": "true", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        body = client.get("/events", params)
        page = body.get("events")
        if not isinstance(page, list):
            raise AdapterError("Missing 'events' array")
        if on_page is not None:
            on_page(page)
        events.extend(parse_event(e) for e in page if isinstance(e, dict))
        cursor = body.get("cursor") or None
        if not cursor:
            return events, False
    return events, True


def iter_open_events(client: KalshiPublicClient, max_pages: int = 300) -> Iterator[EventBook]:
    cursor = None
    for _ in range(max_pages):
        params: dict[str, Any] = {"status": "open", "with_nested_markets": "true", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        body = client.get("/events", params)
        events = body.get("events")
        if not isinstance(events, list):
            raise AdapterError("Missing 'events' array")
        for e in events:
            if isinstance(e, dict):
                yield parse_event(e)
        cursor = body.get("cursor") or None
        if not cursor:
            return


def confirm_legs(client: KalshiPublicClient, opp: Opportunity) -> list[LegQuote] | None:
    """Re-read each leg's live orderbook. Returns refreshed leg quotes (best level only) or
    None if any leg vanished."""
    out: list[LegQuote] = []
    for leg in opp.legs:
        book = client.get_orderbook(leg.ticker, depth=1).get("orderbook_fp") or {}
        # Buying YES lifts the best NO bid (ask = 1 - bid); buying NO lifts the best YES bid.
        side_key = "no_dollars" if leg.side == "YES" else "yes_dollars"
        levels = [(Decimal(p), Decimal(c)) for p, c in book.get(side_key) or []]
        if not levels:
            return None
        bid, size = max(levels)
        out.append(LegQuote(leg.ticker, leg.title, leg.side, Decimal(1) - bid, size))
    return out
