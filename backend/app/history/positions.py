"""Open positions in context, plus the stored trail behind entry-quality stats.

- record_marks: after every account sync and every scan, store each open position's
  market price. Local only; kept forever. This is what lets us ask, later, "did my entry
  beat where the market ended up?" (closing-line value), which says more about skill than
  a small sample of wins and losses.
- open_analysis: each open position with today's price, move since entry, time to close,
  box-score evidence (when it's a game leg), injuries, and plain flags. Plus portfolio
  totals and concentration by game.
- entry_quality: closing-line value and the sell-winners/hold-losers pattern.

Flags are prompts to think, not instructions to trade.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from app.catalog.games import game_ref
from app.catalog.stats import Quote, implied
from app.db.models import AccountPosition, CatalogEvent, CatalogMarket, PositionMark
from app.history.analysis import market_type, series_of
from app.history.combo_legs import is_combo, open_combo
from app.sportsdata.espn import EspnSource
from app.sportsdata.service import evidence_for

log = logging.getLogger(__name__)
ZERO = Decimal(0)
CENT = Decimal("0.01")


def _q(d: Decimal | None) -> str | None:
    return None if d is None else str(d.quantize(CENT))


def _side_mid(m: CatalogMarket | None, side: str) -> Decimal | None:
    if m is None:
        return None
    p, _ = implied(Quote(m.ticker, m.ticker, m.yes_bid, m.yes_ask))
    if p is None:
        return None
    d = Decimal(str(round(p, 4)))
    return d if side == "yes" else 1 - d


def record_marks(factory: sessionmaker[Session], now: datetime, source: str) -> int:
    """One mark per open position at `now`. Returns how many were stored."""
    with factory() as s:
        pos = [p for p in s.scalars(select(AccountPosition)) if p.position != 0]
        if not pos:
            return 0
        mkts = {m.ticker: m for m in s.scalars(select(CatalogMarket).where(
            CatalogMarket.ticker.in_([p.ticker for p in pos])))}
        rows = []
        for p in pos:
            side = "yes" if p.position > 0 else "no"
            m = mkts.get(p.ticker)
            mid = _side_mid(m, side)
            rows.append({"ticker": p.ticker, "at": now, "side": side,
                         "contracts": abs(p.position), "cost": p.exposure,
                         "yes_bid": m.yes_bid if m else None, "yes_ask": m.yes_ask if m else None,
                         "mid": mid, "source": source})
        stmt = sqlite_insert(PositionMark.__table__).values(rows).on_conflict_do_nothing()
        s.execute(stmt)
        s.commit()
        return len(rows)


def safe_record_marks(factory: sessionmaker[Session], now: datetime, source: str) -> None:
    try:
        record_marks(factory, now, source)
    except Exception as e:  # noqa: BLE001 - a missed mark must never fail a sync or scan
        log.warning("recording position marks failed: %s", e)


def _flags(r: dict[str, Any], budget: Decimal | None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    move = r["move_pts"]
    if move is not None and move <= -15:
        out.append({"level": "warn", "text": f"Down {abs(move):.0f} pts since entry. Would "
                    "you buy it at today's price? If not, why hold?"})
    if move is not None and move >= 25:
        out.append({"level": "info", "text": f"Up {move:.0f} pts. Selling locks gains; "
                    "holding is a new bet at today's price."})
    ev = r.get("evidence") or {}
    if ev.get("verdict") == "market_higher":
        out.append({"level": "warn", "text": "Box scores say your side is less likely than "
                    "today's price implies."})
    elif ev.get("verdict") == "market_lower":
        out.append({"level": "good", "text": "Box scores say your side is likelier than "
                    "today's price."})
    if ev.get("injury"):
        out.append({"level": "warn", "text": f"Injury report: {ev['injury']['status']}."})
    h = r["hours_to_close"]
    c = r.get("combo")
    if c and c["lost"]:
        out.append({"level": "warn", "text": f"Dead: {c['lost']} leg(s) already lost."})
    elif c and c["won"] and c["open"]:
        out.append({"level": "info", "text": f"{c['won']} leg(s) won, {c['open']} still "
                    "open."})
    if h is not None and 0 <= h <= 3:
        out.append({"level": "info", "text": "Closes within 3 hours."})
    if budget and Decimal(r["cost"]) > budget * Decimal("0.10"):
        out.append({"level": "warn", "text": "Over 10% of your budget in one market."})
    return out


def open_analysis(s: Session, src: EspnSource | None, budget: Decimal | None,
                  now: datetime) -> dict[str, Any]:
    pos = [p for p in s.scalars(select(AccountPosition)) if p.position != 0]
    tickers = [p.ticker for p in pos]
    mkts = {m.ticker: m for m in s.scalars(select(CatalogMarket).where(
        CatalogMarket.ticker.in_(tickers)))}
    trails: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for mk in s.scalars(select(PositionMark).where(PositionMark.ticker.in_(tickers))
                        .order_by(PositionMark.at)):
        trails[mk.ticker].append({"at": mk.at, "mid": None if mk.mid is None else float(mk.mid)})

    evidence: dict[str, dict[str, Any]] = {}
    correlation: list[dict[str, Any]] = []
    evidence_error = None
    if src is not None and pos:
        parsed = [(p.ticker, "yes" if p.position > 0 else "no") for p in pos
                  if p.ticker in mkts]
        try:
            ev, _, _ = evidence_for(s, src, parsed)
            evidence = {lg["ticker"]: lg for lg in ev["legs"]}
            correlation = ev["correlation"]
        except Exception as e:  # noqa: BLE001 - evidence is optional context
            evidence_error = str(e)[:200]

    rows = []
    for p in pos:
        side = "yes" if p.position > 0 else "no"
        n = abs(p.position)
        m = mkts.get(p.ticker)
        e = s.get(CatalogEvent, m.event_ticker) if m else None
        mid = _side_mid(m, side)
        combo = open_combo(s, p.ticker) if is_combo(p.ticker) else None
        if combo and combo["fair"] is not None and mid is None:
            fair = Decimal(str(combo["fair"]))
            mid = fair if side == "yes" else 1 - fair
        avg = (p.exposure / n) if n else None
        value = None if mid is None else n * mid
        close_at = m.close_at if m else None
        hours = None
        if close_at is not None:
            ca = close_at if close_at.tzinfo else close_at.replace(tzinfo=now.tzinfo)
            hours = round((ca - now).total_seconds() / 3600, 1)
        ev = evidence.get(p.ticker)
        r = {
            "ticker": p.ticker, "title": m.title if m else p.ticker,
            "event_ticker": m.event_ticker if m else None,
            "event_title": e.title if e else None,
            "type": market_type(series_of(p.ticker)), "side": side, "contracts": str(n),
            "avg_cost": None if avg is None else str(avg.quantize(Decimal("0.001"))),
            "cost": _q(p.exposure), "mid": None if mid is None else str(mid),
            "value": _q(value), "unrealized": _q(None if value is None else value - p.exposure),
            "move_pts": None if mid is None or avg is None else round(float(mid - avg) * 100, 1),
            "max_payout": _q(n), "close_at": close_at, "hours_to_close": hours,
            "game": game_ref(s, e) if e else None,
            "evidence": ev if ev and ev.get("supported") else None,
            "evidence_note": None if ev is None or ev.get("supported") else ev.get("reason"),
            "trail": trails.get(p.ticker, [])[-60:],
            "combo": combo,
        }
        if combo:
            r["title"] = f"{len(combo['legs'])}-leg combo"
        r["flags"] = _flags(r, budget)
        rows.append(r)

    cost = sum((p.exposure for p in pos), ZERO)
    value = sum((Decimal(r["value"]) for r in rows if r["value"] is not None), ZERO)
    by_game: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["game"]:
            by_game[r["game"]["game_key"]].append(r)
    groups = []
    for gk, rs in by_game.items():
        gcost = sum((Decimal(r["cost"]) for r in rs), ZERO)
        groups.append({"game_key": gk, "title": rs[0]["event_title"], "tickers":
                       [r["ticker"] for r in rs], "cost": _q(gcost),
                       "share": round(float(gcost / cost), 4) if cost else None})
    groups.sort(key=lambda g: -Decimal(g["cost"]))
    rows.sort(key=lambda r: (r["hours_to_close"] is None, r["hours_to_close"] or 0))
    return {
        "positions": rows,
        "portfolio": {
            "count": len(rows), "cost": _q(cost), "value": _q(value),
            "unrealized": _q(value - cost) if rows else _q(ZERO),
            "max_payout": _q(sum((abs(p.position) for p in pos), ZERO)),
            "budget_share": round(float(cost / budget), 4) if budget and cost else None,
            "games": [g for g in groups if len(g["tickers"]) > 1],
        },
        "correlation": correlation,
        "evidence_enabled": src is not None,
        "evidence_error": evidence_error,
        "as_of": now,
    }


def entry_quality(s: Session, done_rows: list[dict[str, Any]],
                  buy_price: dict[tuple[str, str], Decimal]) -> dict[str, Any]:
    """Closing-line value from stored marks, and the disposition pattern.

    buy_price: (ticker, side) -> average price paid. done_rows: closed/settled rows from
    the report (status, pnl, sold_early)."""
    tickers = list({t for t, _ in buy_price})
    last: dict[str, PositionMark] = {}
    for mk in s.scalars(select(PositionMark).where(PositionMark.ticker.in_(tickers))
                        .order_by(PositionMark.at)):
        if mk.mid is not None:
            last[mk.ticker] = mk
    closed = {r["ticker"] for r in done_rows}
    clv = []
    for (t, side), paid in buy_price.items():
        mk = last.get(t)
        if t in closed and mk is not None and mk.side == side:
            clv.append(float(mk.mid - paid))  # type: ignore[operator]
    early = [r for r in done_rows if r.get("sold_early")]
    held = [r for r in done_rows if r["status"] == "settled" and not r.get("sold_early")]
    return {
        "clv": {"n": len(clv), "avg_pts": round(sum(clv) / len(clv) * 100, 1) if clv else None,
                "beat_share": round(sum(1 for x in clv if x > 0) / len(clv), 4) if clv else None},
        "early_exits": {"n": len(early),
                        "in_profit": sum(1 for r in early if Decimal(r["pnl"]) > 0)},
        "held_to_settlement": {"n": len(held),
                               "lost": sum(1 for r in held if Decimal(r["pnl"]) < 0)},
    }
