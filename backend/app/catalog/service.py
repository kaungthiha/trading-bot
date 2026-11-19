"""Catalog queries for the Markets page: categories, series, events, event detail with
statistics, expected value, and combo pricing."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.catalog.combos import combo_collections, history_for, latest_study
from app.catalog.games import game_ref
from app.catalog.stats import (
    Quote,
    combo_stats,
    exclusive_stats,
    expected_value,
    implied,
    ladder_groups,
    ladder_stats,
    merge_margin_ladders,
    scaled_schedule,
    spread,
)
from app.core.config import Settings
from app.db.models import CatalogEvent, CatalogMarket, CatalogSeries
from app.signals.fees import FeeSchedule, load_schedules, select_schedule

SORTS = {
    "volume_24h": CatalogEvent.volume_24h.desc(),
    "open_interest": CatalogEvent.open_interest.desc(),
    "volume": CatalogEvent.volume.desc(),
    "closing": CatalogEvent.close_at.asc(),
}


def _s(d: Decimal | None) -> str | None:
    return None if d is None else str(d)


def status(s: Session) -> dict[str, Any]:
    return {
        "refreshed_at": s.scalar(select(func.max(CatalogEvent.refreshed_at))),
        "events": s.scalar(select(func.count()).select_from(CatalogEvent)) or 0,
        "markets": s.scalar(select(func.count()).select_from(CatalogMarket)) or 0,
        "series": s.scalar(select(func.count()).select_from(CatalogSeries)) or 0,
    }


def categories(s: Session) -> list[dict[str, Any]]:
    rows = s.execute(select(CatalogEvent.category, func.count(),
                            func.sum(CatalogEvent.market_count),
                            func.sum(CatalogEvent.volume_24h))
                     .group_by(CatalogEvent.category)
                     .order_by(func.sum(CatalogEvent.volume_24h).desc())).all()
    return [{"name": c, "events": n, "markets": int(m or 0), "volume_24h": round(v or 0)}
            for c, n, m, v in rows]


def series_list(s: Session, category: str | None, q: str | None,
                limit: int = 300) -> list[dict[str, Any]]:
    stmt = select(CatalogEvent.series_ticker, func.count(), func.sum(CatalogEvent.market_count),
                  func.sum(CatalogEvent.volume_24h)).group_by(CatalogEvent.series_ticker)
    if category:
        stmt = stmt.where(CatalogEvent.category == category)
    if q:
        like = f"%{q}%"
        titled = select(CatalogSeries.ticker).where(CatalogSeries.title.ilike(like))
        stmt = stmt.where(or_(CatalogEvent.series_ticker.ilike(like),
                              CatalogEvent.series_ticker.in_(titled)))
    rows = s.execute(stmt.order_by(func.sum(CatalogEvent.volume_24h).desc()).limit(limit)).all()
    titles = dict(s.execute(select(CatalogSeries.ticker, CatalogSeries.title).where(
        CatalogSeries.ticker.in_([r[0] for r in rows]))).all())
    return [{"ticker": t, "title": titles.get(t, t), "events": n, "markets": int(m or 0),
             "volume_24h": round(v or 0)} for t, n, m, v in rows]


def _event_out(e: CatalogEvent) -> dict[str, Any]:
    return {"event_ticker": e.event_ticker, "series_ticker": e.series_ticker,
            "category": e.category, "title": e.title, "sub_title": e.sub_title,
            "competition": e.competition, "mutually_exclusive": e.mutually_exclusive,
            "market_count": e.market_count, "volume_24h": round(e.volume_24h),
            "open_interest": round(e.open_interest), "close_at": e.close_at,
            "occurs_at": e.occurs_at, "refreshed_at": e.refreshed_at}


def events(s: Session, *, category: str | None, series: str | None, q: str | None,
           sort: str, limit: int, offset: int) -> dict[str, Any]:
    stmt = select(CatalogEvent)
    if category:
        stmt = stmt.where(CatalogEvent.category == category)
    if series:
        stmt = stmt.where(CatalogEvent.series_ticker == series)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(CatalogEvent.title.ilike(like), CatalogEvent.sub_title.ilike(like),
                              CatalogEvent.event_ticker.ilike(like),
                              CatalogEvent.competition.ilike(like)))
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order = SORTS.get(sort, SORTS["volume_24h"])
    rows = s.scalars(stmt.order_by(order, CatalogEvent.event_ticker)
                     .limit(limit).offset(offset)).all()
    return {"items": [_event_out(e) for e in rows], "total": total, "limit": limit,
            "offset": offset}


def _quote(m: CatalogMarket) -> Quote:
    return Quote(m.ticker, m.yes_sub_title or m.title, m.yes_bid, m.yes_ask, m.strike_type,
                 m.floor_strike, m.group_key, m.title)


def _fee_schedule(s: Session, series_ticker: str) -> tuple[FeeSchedule | None, Decimal | None]:
    ser = s.get(CatalogSeries, series_ticker)
    fee_type = (ser.fee_type if ser and ser.fee_type else "quadratic_with_maker_fees")
    sched = select_schedule(load_schedules(), fee_type) or select_schedule(
        load_schedules(), "quadratic_with_maker_fees")
    if sched is None or not sched.verified:
        return None, None
    mult = ser.fee_multiplier if ser else None
    return scaled_schedule(sched, mult), mult


def event_detail(s: Session, event_ticker: str) -> dict[str, Any] | None:
    e = s.get(CatalogEvent, event_ticker)
    if e is None:
        return None
    ms = list(s.scalars(select(CatalogMarket).where(CatalogMarket.event_ticker == event_ticker)))
    ms.sort(key=lambda m: (m.group_key, m.floor_strike if m.floor_strike is not None
                           else Decimal(0), -(m.volume_24h or 0), m.ticker))
    ser = s.get(CatalogSeries, e.series_ticker)
    sched, mult = _fee_schedule(s, e.series_ticker)
    markets = []
    for m in ms:
        q = _quote(m)
        p, quality = implied(q)
        sp = spread(q)
        markets.append({
            "ticker": m.ticker, "title": m.title, "yes_sub_title": m.yes_sub_title,
            "no_sub_title": m.no_sub_title, "status": m.status,
            "yes_bid": _s(m.yes_bid), "yes_ask": _s(m.yes_ask), "no_bid": _s(m.no_bid),
            "no_ask": _s(m.no_ask), "yes_bid_size": _s(m.yes_bid_size),
            "yes_ask_size": _s(m.yes_ask_size), "last_price": _s(m.last_price),
            "change_24h": _s(m.last_price - m.previous_price)
            if m.last_price is not None and m.previous_price is not None else None,
            "volume_24h": _s(m.volume_24h), "open_interest": _s(m.open_interest),
            "implied": None if p is None else round(p, 4), "implied_quality": quality,
            "spread": None if sp is None else round(sp, 4),
            "floor_strike": _s(m.floor_strike), "strike_type": m.strike_type,
            "close_at": m.close_at,
        })
    quotes = [_quote(m) for m in ms]
    groups = merge_margin_ladders(ladder_groups(quotes))
    ladders = [st for g in groups.values() if (st := ladder_stats(g))]
    ladders.sort(key=lambda x: x["label"])
    return {
        **_event_out(e),
        "series_title": ser.title if ser else e.series_ticker,
        "combo_collections": combo_collections(s, [e.event_ticker]).get(e.event_ticker, []),
        "game": game_ref(s, e),
        "rules_sample": e.rules_sample,
        "fee": {"schedule": sched.version if sched else None,
                "multiplier": _s(mult) if mult is not None else "1",
                "fee_type": ser.fee_type if ser else None},
        "markets": markets,
        "stats": {
            "exclusive": exclusive_stats(quotes) if e.mutually_exclusive else None,
            "ladders": ladders,
        },
    }


class CatalogError(ValueError):
    pass


def market_ev(s: Session, settings: Settings, ticker: str, side: str, contracts: int,
              prob: Decimal, price: Decimal | None) -> dict[str, Any]:
    m = s.get(CatalogMarket, ticker)
    if m is None:
        raise CatalogError("Market not in the catalog; run a scan first")
    e = s.get(CatalogEvent, m.event_ticker)
    sched, _ = _fee_schedule(s, e.series_ticker if e else ticker.split("-")[0])
    if sched is None:
        raise CatalogError("No verified fee schedule")
    ask = m.yes_ask if side == "yes" else m.no_ask
    use = price if price is not None else ask
    if use is None:
        raise CatalogError(f"No {side.upper()} ask right now; enter a limit price")
    # Depth at the best YES ask is known; the NO ask's depth is the YES-bid size.
    depth = (m.yes_ask_size if side == "yes" else m.yes_bid_size) if price is None else None
    out = expected_value(sched, use, contracts, prob, settings.experiment_budget_dollars,
                         settings.scanner_conditional_fraction, depth)
    out.update({"ticker": ticker, "side": side, "price_source": "limit" if price is not None
                else "snapshot ask", "snapshot_at": m.refreshed_at})
    return out


def combo(s: Session, legs: list[tuple[str, str]]) -> dict[str, Any]:
    rows = []
    for ticker, side in legs:
        m = s.get(CatalogMarket, ticker)
        if m is None:
            raise CatalogError(f"{ticker} is not in the catalog")
        e = s.get(CatalogEvent, m.event_ticker)
        rows.append((_quote(m), side, m.event_ticker, bool(e and e.mutually_exclusive)))
    out = combo_stats(rows)
    events = sorted({r[2] for r in rows})
    cols = combo_collections(s, events)
    common = set.intersection(*(set(cols.get(e, [])) for e in events)) if events else set()
    out["kalshi"] = {
        "eligible": bool(common) and len(rows) >= 2,
        "collections": sorted(common),
        "ineligible_events": [e for e in events if e not in cols],
        "history": history_for(latest_study(s), len(rows)),
    }
    return out
