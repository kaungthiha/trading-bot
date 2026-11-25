"""The day-by-day review: what you bet on a given day (US Eastern, the day you first bought),
what you paid, how each bet and each leg ended, what the players actually did, and your top
winners and losers. Built from the synced Kalshi history plus your bet journal."""

from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BetJournal, CatalogMarket
from app.history.combo_legs import is_combo
from app.history.journal import _buys
from app.history.legs import LegRow, category, leg_rows, outcome_text, outcomes, subject
from app.sportsdata.espn import ET


def et_day(dt: Any) -> str:
    return dt.astimezone(ET).date().isoformat()


def _rows_by_ticker(rep: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out = {r["ticker"]: r for r in rep["markets"]}
    out.update({r["ticker"]: r for r in rep["open_positions"]})
    return out


def days(s: Session, rep: dict[str, Any], limit: int = 30) -> list[dict[str, Any]]:
    """Days you placed bets, newest first, with the realized P&L of those bets so far."""
    rows = _rows_by_ticker(rep)
    by: dict[str, dict[str, Any]] = {}
    for t, b in _buys(s).items():
        d = et_day(b["first_at"])
        e = by.setdefault(d, {"date": d, "bets": 0, "settled": 0, "won": 0, "pnl": Decimal(0),
                              "staked": Decimal(0)})
        e["bets"] += 1
        e["staked"] += b["cost"] + b["fees"]
        r = rows.get(t)
        if r and r.get("pnl") is not None:
            e["settled"] += 1
            e["won"] += int(Decimal(r["pnl"]) > 0)
            e["pnl"] += Decimal(r["pnl"])
    out = sorted(by.values(), key=lambda x: x["date"], reverse=True)[:limit]
    return [{**x, "pnl": f"{x['pnl']:.2f}", "staked": f"{x['staked']:.2f}"} for x in out]


def _leg_json(r: LegRow, outs: dict[str, Any]) -> dict[str, Any]:
    p = r.parsed
    return {"ticker": r.ticker, "side": r.side, "title": r.title,
            "status": "won" if r.won else "lost" if r.won is False else "open",
            "subject": subject(p), "category": category(p, r.side), "kind": p["kind"],
            "line": p.get("line"), "stat": p.get("stat"), "teams": p.get("teams"),
            "prefix": p.get("prefix"),
            "date": p.get("date"), "what_happened": outcome_text(p, r.side, outs.get(r.ticker))}


def bet_json(t: str, b: dict[str, Any] | None, r: dict[str, Any] | None,
             legs: list[dict[str, Any]], titles: dict[str, str],
             journal: dict[str, BetJournal]) -> dict[str, Any]:
    j = journal.get(t)
    lost = [lg for lg in legs if lg["status"] == "lost"]
    status = r["status"] if r else "open"
    pnl = r.get("pnl") if r else None
    return {
        "ticker": t, "combo": is_combo(t),
        "title": f"{len(legs)}-leg combo" if is_combo(t) else titles.get(t, t),
        "placed_at": None if not b else b["first_at"].isoformat(),
        "side": None if not b else b["side"],
        "contracts": None if not b else str(b["contracts"]),
        "avg_price": None if not b or b["avg_price"] is None
        else str(b["avg_price"].quantize(Decimal("0.0001"))),
        "cost": None if not b else f"{b['cost'] + b['fees']:.2f}",
        "max_payout": None if not b else f"{b['contracts']:.2f}",
        "status": status, "pnl": pnl, "sold_early": bool(r and r.get("sold_early")),
        "legs": legs, "legs_lost": len(lost),
        "sunk_by_one": bool(is_combo(t) and len(lost) == 1
                            and (pnl is None or Decimal(pnl) < 0)),
        "journal": None if j is None else {"note": j.note, "source": j.source,
                                           "my_price": None if j.my_price is None
                                           else str(j.my_price),
                                           "market_price": None if j.market_price is None
                                           else str(j.market_price)},
    }


def day_detail(s: Session, rep: dict[str, Any], day: str) -> dict[str, Any]:
    rows = _rows_by_ticker(rep)
    buys = {t: b for t, b in _buys(s).items() if et_day(b["first_at"]) == day}
    combos = {t for t in buys if is_combo(t)}
    lrows = leg_rows(s, combos)
    outs = outcomes(s, [r.ticker for r in lrows])
    by_combo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in lrows:
        js = _leg_json(r, outs)
        for c in r.combos:
            by_combo[c].append(js)
    singles = [t for t in buys if t not in combos]
    titles = dict(s.execute(select(CatalogMarket.ticker, CatalogMarket.title)
                            .where(CatalogMarket.ticker.in_(singles))).all())
    journal = {e.kalshi_ticker: e for e in s.scalars(
        select(BetJournal).where(BetJournal.kalshi_ticker.in_(list(buys))))}
    bets = [bet_json(t, b, rows.get(t), sorted(by_combo.get(t, []), key=lambda x: x["status"]),
                     titles, journal) for t, b in buys.items()]
    bets.sort(key=lambda x: x["placed_at"] or "")
    done = [b for b in bets if b["pnl"] is not None]
    pnl = sum((Decimal(b["pnl"]) for b in done), Decimal(0))
    staked = sum((Decimal(b["cost"]) for b in bets if b["cost"]), Decimal(0))
    # Legs that sank a combo: grouped, so one player missing in three combos reads once.
    breakers: dict[tuple[str, str], dict[str, Any]] = {}
    for b in bets:
        for lg in b["legs"]:
            if lg["status"] == "lost":
                e = breakers.setdefault((lg["ticker"], lg["side"]),
                                        {**lg, "combos": 0, "sunk_alone": 0})
                e["combos"] += 1
                e["sunk_alone"] += int(b["sunk_by_one"])
    skipped = [e for e in s.scalars(select(BetJournal).where(BetJournal.status == "skipped"))
               if et_day(e.created_at) == day]
    return {
        "date": day, "bets": bets,
        "totals": {"bets": len(bets), "settled": len(done),
                   "won": sum(1 for b in done if Decimal(b["pnl"]) > 0),
                   "pnl": f"{pnl:.2f}", "staked": f"{staked:.2f}",
                   "open": len(bets) - len(done),
                   "combos_sunk_by_one": sum(1 for b in bets if b["sunk_by_one"]
                                             and b["status"] != "open")},
        "breakers": sorted(breakers.values(), key=lambda x: (-x["combos"], x["title"])),
        "winners": sorted((b for b in done if Decimal(b["pnl"]) > 0),
                          key=lambda b: -Decimal(b["pnl"]))[:3],
        "losers": sorted((b for b in done if Decimal(b["pnl"]) < 0),
                         key=lambda b: Decimal(b["pnl"]))[:3],
        "skipped": [{"id": e.id, "legs": json.loads(e.legs_json), "note": e.note}
                    for e in skipped],
    }


def top_bets(s: Session, rep: dict[str, Any], n: int = 5) -> dict[str, list[dict[str, Any]]]:
    """Your biggest winners and losers, all time, with their legs."""
    done = [r for r in rep["markets"] if r.get("pnl") is not None]
    win = sorted((r for r in done if Decimal(r["pnl"]) > 0), key=lambda r: -Decimal(r["pnl"]))
    lose = sorted((r for r in done if Decimal(r["pnl"]) < 0), key=lambda r: Decimal(r["pnl"]))
    pick = [r["ticker"] for r in win[:n] + lose[:n]]
    buys = _buys(s)
    lrows = leg_rows(s, {t for t in pick if is_combo(t)})
    outs = outcomes(s, [r.ticker for r in lrows])
    by_combo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in lrows:
        for c in r.combos:
            by_combo[c].append(_leg_json(r, outs))
    titles = dict(s.execute(select(CatalogMarket.ticker, CatalogMarket.title)
                            .where(CatalogMarket.ticker.in_(pick))).all())
    rows = _rows_by_ticker(rep)
    journal = {e.kalshi_ticker: e for e in s.scalars(
        select(BetJournal).where(BetJournal.kalshi_ticker.in_(pick)))}

    def one(t: str) -> dict[str, Any]:
        return bet_json(t, buys.get(t), rows.get(t), by_combo.get(t, []),
                        {**titles, t: titles.get(t) or rows[t].get("series_title") or t},
                        journal)
    return {"winners": [one(r["ticker"]) for r in win[:n]],
            "losers": [one(r["ticker"]) for r in lose[:n]]}
