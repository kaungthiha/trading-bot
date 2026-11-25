"""Your bet journal: a queue of bets you plan to place (from the Docket or a slate combo),
what you paid, your reason, and the Kalshi market it became once your history syncs.

Local only. The app never places orders: 'placed' is something you mark (or the sync finds)."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AccountFill, BetJournal, CatalogMarket, ComboLeg
from app.history.combo_legs import is_combo

STATUSES = ("queued", "placed", "skipped")
SOURCES = ("docket", "slate", "own")
NOTE_MAX = 500
MAX_LEGS = 12
MATCH_WINDOW = timedelta(days=2)


def leg_key(legs: list[dict[str, Any]]) -> str:
    return ",".join(sorted(f"{lg['ticker']}:{lg['side']}" for lg in legs))


def _dec(x: Any) -> Decimal | None:
    if x is None or x == "":
        return None
    d = Decimal(str(x))
    return d if d.is_finite() else None


def create(s: Session, body: dict[str, Any], now: datetime) -> BetJournal:
    legs = [{"ticker": lg["ticker"], "side": lg["side"], "label": lg["label"][:300],
             "event": lg.get("event") or "", "price": lg.get("price")}
            for lg in body["legs"][:MAX_LEGS]]
    e = BetJournal(created_at=now, updated_at=now, status=body.get("status") or "queued",
                   legs_json=json.dumps(legs), leg_key=leg_key(legs),
                   market_price=_dec(body.get("market_price")),
                   my_price=_dec(body.get("my_price")), stake=_dec(body.get("stake")),
                   source=body.get("source") or "docket",
                   note=(body.get("note") or "").strip()[:NOTE_MAX])
    s.add(e)
    s.commit()
    return e


def update(s: Session, e: BetJournal, body: dict[str, Any], now: datetime) -> BetJournal:
    if body.get("status"):
        e.status = body["status"]
    for k in ("my_price", "stake"):
        if k in body:
            setattr(e, k, _dec(body[k]))
    if "note" in body and body["note"] is not None:
        e.note = body["note"].strip()[:NOTE_MAX]
    e.updated_at = now
    s.commit()
    return e


def _buys(s: Session) -> dict[str, dict[str, Any]]:
    """ticker -> {side, first_at, contracts, cost, avg_price} for markets you bought."""
    out: dict[str, dict[str, Any]] = {}
    for f in s.scalars(select(AccountFill).where(AccountFill.action == "buy")
                       .order_by(AccountFill.created_at)):
        b = out.setdefault(f.ticker, {"side": f.side, "first_at": f.created_at,
                                      "contracts": Decimal(0), "cost": Decimal(0),
                                      "fees": Decimal(0)})
        b["contracts"] += f.count
        b["cost"] += f.count * f.price
        b["fees"] += f.fee
    for b in out.values():
        b["avg_price"] = (b["cost"] / b["contracts"]) if b["contracts"] else None
    return out


def match_all(s: Session, entries: list[BetJournal], now: datetime) -> int:
    """Link unmatched entries to the Kalshi market you bought with the same legs."""
    todo = [e for e in entries if e.kalshi_ticker is None and e.status != "skipped"]
    if not todo:
        return 0
    buys = _buys(s)
    combos: dict[str, str] = {}
    legs_by: dict[str, list[ComboLeg]] = defaultdict(list)
    for lg in s.scalars(select(ComboLeg)):
        legs_by[lg.combo_ticker].append(lg)
    for c, ls in legs_by.items():
        combos[c] = leg_key([{"ticker": lg.leg_ticker, "side": lg.side} for lg in ls])
    taken = {e.kalshi_ticker for e in entries if e.kalshi_ticker}
    n = 0
    for e in todo:
        legs = json.loads(e.legs_json)
        cands: list[tuple[datetime, str]] = []
        if len(legs) == 1:
            t, side = legs[0]["ticker"], legs[0]["side"]
            b = buys.get(t)
            if b and b["side"] == side:
                cands.append((b["first_at"], t))
        else:
            for c, k in combos.items():
                b = buys.get(c)
                if k == e.leg_key and b:
                    cands.append((b["first_at"], c))
        cands = [(at, t) for at, t in cands if t not in taken
                 and e.created_at - MATCH_WINDOW <= at <= e.created_at + MATCH_WINDOW]
        if not cands:
            continue
        at, t = min(cands, key=lambda x: abs((x[0] - e.created_at).total_seconds()))
        e.kalshi_ticker = t
        taken.add(t)
        if e.status == "queued":
            e.status = "placed"
        e.updated_at = now
        n += 1
    if n:
        s.commit()
    return n


def _leg_status(s: Session, legs: list[dict[str, Any]]) -> dict[str, str]:
    """ticker -> won/lost/open for the journal's legs, from what's known locally."""
    tickers = [lg["ticker"] for lg in legs]
    res: dict[str, str | None] = {}
    for lg in s.scalars(select(ComboLeg).where(ComboLeg.leg_ticker.in_(tickers))):
        res[lg.leg_ticker] = res.get(lg.leg_ticker) or lg.result
    open_now = {m.ticker for m in s.scalars(select(CatalogMarket).where(
        CatalogMarket.ticker.in_(tickers)))}
    out = {}
    for lg in legs:
        r = res.get(lg["ticker"])
        out[lg["ticker"]] = ("won" if r == lg["side"] else "lost") if r in ("yes", "no") \
            else "open" if lg["ticker"] in open_now else "unknown"
    return out


def entry_json(s: Session, e: BetJournal, rows: dict[str, dict[str, Any]],
               buys: dict[str, dict[str, Any]]) -> dict[str, Any]:
    legs = json.loads(e.legs_json)
    st = _leg_status(s, legs)
    for lg in legs:
        lg["status"] = st.get(lg["ticker"], "unknown")
    k = None
    if e.kalshi_ticker:
        r, b = rows.get(e.kalshi_ticker), buys.get(e.kalshi_ticker)
        k = {"ticker": e.kalshi_ticker, "combo": is_combo(e.kalshi_ticker),
             "status": r["status"] if r else "open", "pnl": r["pnl"] if r else None,
             "staked": r["staked"] if r else None,
             "avg_price": None if not b or b["avg_price"] is None
             else str(b["avg_price"].quantize(Decimal("0.0001"))),
             "contracts": None if not b else str(b["contracts"]),
             "placed_at": None if not b else b["first_at"].isoformat()}
    lost = sum(1 for lg in legs if lg["status"] == "lost")
    pending = sum(1 for lg in legs if lg["status"] in ("open", "unknown"))
    would = "lost" if lost else "won" if not pending else None
    return {"id": e.id, "created_at": e.created_at.isoformat(), "status": e.status,
            "source": e.source, "note": e.note, "legs": legs,
            "market_price": None if e.market_price is None else str(e.market_price),
            "my_price": None if e.my_price is None else str(e.my_price),
            "stake": None if e.stake is None else str(e.stake), "kalshi": k,
            "legs_outcome": would}


def listing(s: Session, rows: dict[str, dict[str, Any]], now: datetime,
            limit: int = 100) -> list[dict[str, Any]]:
    entries = list(s.scalars(select(BetJournal).order_by(BetJournal.created_at.desc())
                             .limit(limit)))
    match_all(s, entries, now)
    buys = _buys(s)
    return [entry_json(s, e, rows, buys) for e in entries]
