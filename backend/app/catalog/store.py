"""Write the public Kalshi snapshot into the catalog tables, one page at a time.

Used by the scanner, which already downloads every open event with nested markets: the
same pages are upserted here, so browsing costs no extra API calls. Rows not seen in a
COMPLETE pass are deleted afterwards (a truncated pass keeps them rather than guess).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.kalshi_public import KalshiPublicClient
from app.db.models import CatalogEvent, CatalogMarket, CatalogSeries

SERIES_MAX_AGE = timedelta(hours=6)


def _dec(v: Any) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _price(v: Any) -> Decimal | None:
    """Top-of-book field: 0 or 1 means 'no order on that side'."""
    d = _dec(v)
    return d if d is not None and Decimal(0) < d < Decimal(1) else None


def _dt(v: Any) -> datetime | None:
    if not isinstance(v, str) or not v:
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else None


def _f(d: Decimal | None) -> float:
    return float(d) if d is not None else 0.0


def market_row(m: dict[str, Any], event_ticker: str, now: datetime) -> dict[str, Any]:
    custom = m.get("custom_strike")
    return {
        "ticker": str(m.get("ticker")),
        "event_ticker": event_ticker,
        "title": str(m.get("title") or m.get("ticker")),
        "yes_sub_title": str(m.get("yes_sub_title") or ""),
        "no_sub_title": str(m.get("no_sub_title") or ""),
        "status": str(m.get("status") or ""),
        "yes_bid": _price(m.get("yes_bid_dollars")),
        "yes_ask": _price(m.get("yes_ask_dollars")),
        "no_bid": _price(m.get("no_bid_dollars")),
        "no_ask": _price(m.get("no_ask_dollars")),
        "yes_bid_size": _dec(m.get("yes_bid_size_fp")),
        "yes_ask_size": _dec(m.get("yes_ask_size_fp")),
        "last_price": _price(m.get("last_price_dollars")),
        "previous_price": _price(m.get("previous_price_dollars")),
        "volume": _dec(m.get("volume_fp")),
        "volume_24h": _dec(m.get("volume_24h_fp")),
        "open_interest": _dec(m.get("open_interest_fp")),
        "close_at": _dt(m.get("close_time")),
        "strike_type": m.get("strike_type") or None,
        "floor_strike": _dec(m.get("floor_strike")),
        "cap_strike": _dec(m.get("cap_strike")),
        "group_key": json.dumps(custom, sort_keys=True) if isinstance(custom, dict) else "",
        "refreshed_at": now,
    }


def event_row(e: dict[str, Any], markets: list[dict[str, Any]], raw_markets: list[dict],
              now: datetime) -> dict[str, Any]:
    closes = [m["close_at"] for m in markets if m["close_at"]]
    occurs = [d for d in (_dt(m.get("occurrence_datetime")) for m in raw_markets) if d]
    meta = e.get("product_metadata") if isinstance(e.get("product_metadata"), dict) else {}
    ticker = str(e.get("event_ticker"))
    return {
        "event_ticker": ticker,
        "series_ticker": str(e.get("series_ticker") or ticker.split("-")[0]),
        "category": str(e.get("category") or "Uncategorized"),
        "title": str(e.get("title") or ticker),
        "sub_title": str(e.get("sub_title") or ""),
        "competition": str(meta.get("competition"))[:128] if meta.get("competition") else None,
        "mutually_exclusive": bool(e.get("mutually_exclusive")),
        "market_count": len(markets),
        "volume": sum(_f(m["volume"]) for m in markets),
        "volume_24h": sum(_f(m["volume_24h"]) for m in markets),
        "open_interest": sum(_f(m["open_interest"]) for m in markets),
        "close_at": min(closes) if closes else None,
        "occurs_at": min(occurs) if occurs else None,
        "rules_sample": str((raw_markets[0].get("rules_primary") if raw_markets else "") or ""),
        "refreshed_at": now,
    }


def _upsert(s: Session, table: Any, rows: list[dict[str, Any]], key: str) -> None:
    if not rows:
        return
    # SQLite caps bound parameters per statement; keep batches well under it.
    cols = len(rows[0])
    step = max(1, 30000 // cols)
    for i in range(0, len(rows), step):
        stmt = insert(table).values(rows[i:i + step])
        stmt = stmt.on_conflict_do_update(
            index_elements=[key],
            set_={c: stmt.excluded[c] for c in rows[0] if c != key})
        s.execute(stmt)


class CatalogWriter:
    """Pass `write_page` as the scanner's page callback, then call `finish`."""

    def __init__(self, factory: sessionmaker[Session], now: datetime) -> None:
        self.factory, self.now = factory, now
        self.events = 0
        self.markets = 0

    def write_page(self, page: list[dict[str, Any]]) -> None:
        ev_rows, mk_rows = [], []
        for e in page:
            if not isinstance(e, dict) or not e.get("event_ticker"):
                continue
            raw = [m for m in (e.get("markets") or []) if isinstance(m, dict) and m.get("ticker")]
            rows = [market_row(m, str(e["event_ticker"]), self.now) for m in raw]
            mk_rows.extend(rows)
            ev_rows.append(event_row(e, rows, raw, self.now))
        with self.factory() as s:
            _upsert(s, CatalogEvent.__table__, ev_rows, "event_ticker")
            _upsert(s, CatalogMarket.__table__, mk_rows, "ticker")
            s.commit()
        self.events += len(ev_rows)
        self.markets += len(mk_rows)

    def finish(self, complete: bool) -> None:
        """Drop events/markets that a complete pass did not see (closed or settled)."""
        if not complete:
            return
        with self.factory() as s:
            s.execute(delete(CatalogMarket).where(CatalogMarket.refreshed_at < self.now))
            s.execute(delete(CatalogEvent).where(CatalogEvent.refreshed_at < self.now))
            s.commit()


def refresh_series(factory: sessionmaker[Session], client: KalshiPublicClient,
                   now: datetime, force: bool = False) -> int:
    """Series titles + fee multipliers (one request). Skipped if refreshed recently."""
    with factory() as s:
        last = s.scalar(select(func.max(CatalogSeries.refreshed_at)))
    if last and not force and now - last < SERIES_MAX_AGE:
        return 0
    body = client.get("/series", {})
    rows = []
    for x in body.get("series") or []:
        if not isinstance(x, dict) or not x.get("ticker"):
            continue
        rows.append({"ticker": str(x["ticker"]), "title": str(x.get("title") or x["ticker"]),
                     "category": str(x.get("category") or "Uncategorized"),
                     "frequency": (str(x["frequency"])[:32] if x.get("frequency") else None),
                     "fee_type": (str(x["fee_type"])[:64] if x.get("fee_type") else None),
                     "fee_multiplier": _dec(x.get("fee_multiplier")),
                     "refreshed_at": now})
    with factory() as s:
        _upsert(s, CatalogSeries.__table__, rows, "ticker")
        s.commit()
    return len(rows)
