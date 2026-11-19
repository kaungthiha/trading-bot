"""The legs inside the combos you traded: live value for open combos, and which legs sank
the settled ones. Leg lists come from Kalshi's PUBLIC market data (mve_selected_legs); leg
results are fetched once and kept, since a settled leg never changes."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.base import AdapterError
from app.adapters.kalshi_public import KalshiPublicClient
from app.catalog.stats import Quote, implied
from app.db.models import (
    AccountFill,
    AccountPosition,
    AccountSettlement,
    CatalogMarket,
    ComboLeg,
)
from app.history.analysis import market_type, series_of

log = logging.getLogger(__name__)


def is_combo(ticker: str) -> bool:
    return ticker.startswith("KXMVE")


def refresh_combo_legs(factory: sessionmaker[Session], client: KalshiPublicClient,
                       now: datetime, max_calls: int = 400) -> int:
    """Store legs for every combo you traded; resolve legs whose market has finished.
    Returns API calls made. Stops at max_calls (the rest fill in on the next sync)."""
    calls = 0
    with factory() as s:
        combos = sorted({t for (t,) in s.execute(select(AccountFill.ticker)) if is_combo(t)}
                        | {t for (t,) in s.execute(select(AccountSettlement.ticker))
                           if is_combo(t)}
                        | {p.ticker for p in s.scalars(select(AccountPosition))
                           if is_combo(p.ticker)})
        have: dict[str, list[ComboLeg]] = defaultdict(list)
        for lg in s.scalars(select(ComboLeg).where(ComboLeg.combo_ticker.in_(combos))):
            have[lg.combo_ticker].append(lg)
        catalog = {m.ticker: m for m in s.scalars(select(CatalogMarket).where(
            CatalogMarket.ticker.in_({lg.leg_ticker for ls in have.values() for lg in ls})))}
    rows: list[dict[str, Any]] = []
    for c in combos:
        legs = have.get(c)
        if not legs:
            if calls >= max_calls:
                break
            try:
                m = client.get_market(c)
                calls += 1
            except AdapterError as e:
                log.info("combo %s: %s", c, e)
                continue
            legs_raw = m.get("mve_selected_legs") or []
            legs = [ComboLeg(combo_ticker=c, leg_ticker=str(x.get("market_ticker") or ""),
                             event_ticker=str(x.get("event_ticker") or ""),
                             side=str(x.get("side") or "yes")[:3], title="", result=None,
                             refreshed_at=now) for x in legs_raw if x.get("market_ticker")]
        for lg in legs:
            if lg.result in ("yes", "no") and lg.title:
                continue
            cm = catalog.get(lg.leg_ticker)
            title, result = lg.title or (cm.title if cm else ""), lg.result
            if cm is None and calls < max_calls:  # not open any more: look up how it ended
                try:
                    lm = client.get_market(lg.leg_ticker)
                    calls += 1
                    title = title or str(lm.get("title") or "")
                    r = str(lm.get("result") or "")
                    result = r if r in ("yes", "no") else None
                except AdapterError:
                    pass
            rows.append({"combo_ticker": c, "leg_ticker": lg.leg_ticker,
                         "event_ticker": lg.event_ticker, "side": lg.side,
                         "title": (title or lg.leg_ticker)[:300], "result": result,
                         "refreshed_at": now})
    if rows:
        with factory() as s:
            stmt = sqlite_insert(ComboLeg.__table__).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["combo_ticker", "leg_ticker"],
                set_={k: stmt.excluded[k] for k in ("title", "result", "refreshed_at")})
            s.execute(stmt)
            s.commit()
    return calls


def _leg_state(lg: ComboLeg, cm: CatalogMarket | None) -> dict[str, Any]:
    won = None if lg.result is None else lg.result == lg.side
    p = None
    if won is None and cm is not None:
        y, _ = implied(Quote(cm.ticker, cm.ticker, cm.yes_bid, cm.yes_ask))
        p = None if y is None else (y if lg.side == "yes" else 1 - y)
    return {"ticker": lg.leg_ticker, "title": lg.title, "side": lg.side,
            "type": market_type(series_of(lg.leg_ticker)),
            "status": "won" if won else "lost" if won is False else "open",
            "probability": None if p is None else round(p, 4)}


def open_combo(s: Session, ticker: str) -> dict[str, Any] | None:
    legs = list(s.scalars(select(ComboLeg).where(ComboLeg.combo_ticker == ticker)))
    if not legs:
        return None
    cms = {m.ticker: m for m in s.scalars(select(CatalogMarket).where(
        CatalogMarket.ticker.in_([lg.leg_ticker for lg in legs])))}
    states = [_leg_state(lg, cms.get(lg.leg_ticker)) for lg in legs]
    if any(x["status"] == "lost" for x in states):
        fair: float | None = 0.0
    elif any(x["status"] == "open" and x["probability"] is None for x in states):
        fair = None
    else:
        fair = 1.0
        for x in states:
            if x["status"] == "open":
                fair *= x["probability"]
    return {"legs": states, "fair": None if fair is None else round(fair, 4),
            "won": sum(1 for x in states if x["status"] == "won"),
            "lost": sum(1 for x in states if x["status"] == "lost"),
            "open": sum(1 for x in states if x["status"] == "open")}


def combo_breakdown(s: Session, settled: dict[str, Decimal]) -> dict[str, Any] | None:
    """settled: combo ticker -> realized P&L. How your settled combos lived and died."""
    if not settled:
        return None
    legs: dict[str, list[ComboLeg]] = defaultdict(list)
    for lg in s.scalars(select(ComboLeg).where(ComboLeg.combo_ticker.in_(list(settled)))):
        legs[lg.combo_ticker].append(lg)
    known = {c: ls for c, ls in legs.items() if ls}
    if not known:
        return {"combos": len(settled), "with_legs": 0}
    by_size: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    lost_by_one = lost = 0
    breakers: dict[str, int] = defaultdict(int)
    leg_counts = []
    for ls in known.values():
        n = len(ls)
        leg_counts.append(n)
        bucket = "2" if n == 2 else "3" if n == 3 else "4-5" if n <= 5 else "6+"
        misses = [lg for lg in ls if lg.result is not None and lg.result != lg.side]
        resolved = all(lg.result is not None for lg in ls)
        win = resolved and not misses
        by_size[bucket][0] += 1
        by_size[bucket][1] += int(win)
        if misses:
            lost += 1
            lost_by_one += int(len(misses) == 1)
            for lg in misses:
                breakers[market_type(series_of(lg.leg_ticker))] += 1
    order = ["2", "3", "4-5", "6+"]
    return {
        "combos": len(settled), "with_legs": len(known),
        "avg_legs": round(sum(leg_counts) / len(leg_counts), 1),
        "by_size": [{"legs": k, "n": by_size[k][0], "won": by_size[k][1]}
                    for k in order if by_size[k][0]],
        "lost": lost, "lost_by_one": lost_by_one,
        "breakers": sorted(({"type": k, "legs": v} for k, v in breakers.items()),
                           key=lambda x: -x["legs"]),
    }
