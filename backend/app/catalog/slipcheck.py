"""Does this combo make sense for the money you plan to put on it? And what's the cheaper way?

Deterministic: verified fee schedule, market prices, box-score estimates (when available),
the settled-combo study and your budget. No AI. The verdict is a summary of the numbers
below it, never a pick.

Conventions
- Prices are for the side you'd buy (YES ask, or NO ask = 1 - YES bid).
- p_est for a leg = box-score estimate if there is one, else the market mid.
- Combo quotes on Kalshi are take-it-or-leave-it (request for quote), so the advice for
  the combo is a walk-away price; limit orders are advice for single legs.
- Fees: taker = rate x C x P(1-P); maker = taker rate x maker multiplier for the series'
  fee type (0 for plain 'quadratic' series).
"""

from __future__ import annotations

import math
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.combos import history_for, latest_study
from app.catalog.stats import Quote, implied
from app.db.models import AccountPosition, AccountSync, CatalogEvent, CatalogMarket, CatalogSeries
from app.signals.fees import load_schedules, select_schedule

CENT = Decimal("0.01")
MARGIN = Decimal("0.03")      # leave 3 pts of edge before calling a limit "fair"
VALUE_EDGE = Decimal("0.02")  # a single is "value" if history beats the all-in price by 2 pts
REL_EDGE = Decimal("1.10")    # walk-away keeps a 10% edge over the all-in price
COMBO_TYPE = "quadratic_with_combo_maker_fees"


def _d(x: float | Decimal | None) -> Decimal | None:
    return None if x is None else Decimal(str(round(float(x), 4)))


def _money(d: Decimal | None) -> str | None:
    return None if d is None else str(d.quantize(CENT))


class Fees:
    def __init__(self, s: Session) -> None:
        self.s = s
        sched = select_schedule(load_schedules(), "quadratic_with_maker_fees")
        self.verified = bool(sched and sched.verified)
        self.rate = sched.taker_rate if sched else Decimal("0.07")
        self.maker = sched.maker_multiplier if sched else {}
        self._series: dict[str, tuple[str, Decimal]] = {}

    def _info(self, series: str) -> tuple[str, Decimal]:
        if series not in self._series:
            ser = self.s.get(CatalogSeries, series)
            fee_type = (ser.fee_type if ser and ser.fee_type else
                        COMBO_TYPE if series.startswith("KXMVE") else "quadratic")
            mult = ser.fee_multiplier if ser and ser.fee_multiplier is not None else Decimal(1)
            self._series[series] = (fee_type, mult)
        return self._series[series]

    def taker(self, series: str, contracts: Decimal, price: Decimal) -> Decimal:
        _, mult = self._info(series)
        return (self.rate * mult * contracts * price * (1 - price)).quantize(
            CENT, rounding=ROUND_CEILING)

    def maker_fee(self, series: str, contracts: Decimal, price: Decimal) -> Decimal:
        fee_type, mult = self._info(series)
        m = self.maker.get(fee_type, Decimal(0))
        return (self.rate * m * mult * contracts * price * (1 - price)).quantize(
            CENT, rounding=ROUND_CEILING)


def _side_prices(m: CatalogMarket, side: str) -> tuple[Decimal | None, Decimal | None]:
    """(best ask, best bid) for buying `side`."""
    if side == "yes":
        return m.yes_ask, m.yes_bid
    ask = m.no_ask if m.no_ask is not None else (1 - m.yes_bid if m.yes_bid is not None else None)
    bid = m.no_bid if m.no_bid is not None else (1 - m.yes_ask if m.yes_ask is not None else None)
    return ask, bid


def walk_away(p: Decimal, fees: Fees, series: str) -> Decimal | None:
    """Highest price per contract that still leaves a 10% edge after the taker fee:
    (price + fee) x 1.10 <= p. Relative, so it works for 3% combos and 60% singles alike."""
    best = None
    q = CENT
    mult = fees._info(series)[1]
    while q < 1:
        all_in = q + fees.rate * mult * q * (1 - q)
        if all_in * REL_EDGE <= p:
            best = q
        q += CENT
    return best


def price_single(fees: Fees, r: dict[str, Any]) -> dict[str, Any]:
    """All-in price, edge vs history and a limit-order suggestion for buying one side.
    r: {ticker, side, label, series, mid, ask, bid, history, p_est} (Decimals or None)."""
    ask, bid, p = r["ask"], r["bid"], r["p_est"]
    one = Decimal(1)
    item: dict[str, Any] = {"ticker": r["ticker"], "side": r["side"], "label": r["label"],
                            "ask": str(ask) if ask is not None else None,
                            "bid": str(bid) if bid is not None else None,
                            "history": None if r["history"] is None else str(r["history"]),
                            "mid": None if r["mid"] is None else str(r["mid"])}
    if ask is not None:
        all_in = ask + fees.taker(r["series"], one * 100, ask) / 100
        item["all_in"] = str(all_in.quantize(Decimal("0.001")))
        if p is not None:
            edge = p - all_in
            item["edge_pts"] = round(float(edge) * 100, 1)
            item["value"] = r["history"] is not None and edge >= VALUE_EDGE
    if bid is not None and ask is not None and ask > bid:
        # Improve the bid by 1c when there's room; with a 1c spread, join the bid.
        limit = bid + CENT if ask - bid > CENT else bid
        if r["history"] is not None:
            ceiling = (r["history"] - MARGIN).quantize(CENT, rounding=ROUND_FLOOR)
            limit = min(limit, ceiling)
        if limit > 0:
            saved = (ask - limit) * 100 + fees.taker(r["series"], one * 100, ask) \
                - fees.maker_fee(r["series"], one * 100, limit)
            item["limit"] = {"price": str(limit),
                             "saves_per_100": _money(saved),
                             "maker_fee_per_100": _money(fees.maker_fee(r["series"],
                                                                        one * 100, limit)),
                             "behind_bid": limit <= bid}
    return item


def check_slip(s: Session, legs: list[tuple[str, str]], evidence: dict[str, Any] | None,
               stake: Decimal | None, quote: Decimal | None, budget: Decimal | None,
               cap_fraction: Decimal, unset_cap: Decimal) -> dict[str, Any]:
    fees = Fees(s)
    ev_by = {lg["ticker"]: lg for lg in (evidence or {}).get("legs", [])}
    rows = []
    for t, side in legs:
        m = s.get(CatalogMarket, t)
        if m is None:
            continue
        e = s.get(CatalogEvent, m.event_ticker)
        series = e.series_ticker if e else t.split("-")[0]
        y, _ = implied(Quote(t, t, m.yes_bid, m.yes_ask))
        mid = None if y is None else (y if side == "yes" else 1 - y)
        ask, bid = _side_prices(m, side)
        ev = ev_by.get(t) or {}
        hist = ev.get("estimate") if ev.get("supported") else None
        p_est = _d(hist) if hist is not None else _d(mid)
        rows.append({"ticker": t, "side": side, "label": m.title, "series": series,
                     "mid": _d(mid), "ask": ask, "bid": bid, "history": _d(hist),
                     "interval": ev.get("interval"), "verdict": ev.get("verdict"),
                     "p_est": p_est})
    n = len(rows)

    # --- singles and limit buys ------------------------------------------------------------
    singles = [price_single(fees, r) for r in rows]

    # --- the combo -------------------------------------------------------------------------
    fair = math.prod(float(r["mid"]) for r in rows) if n and all(r["mid"] is not None
                                                                   for r in rows) else None
    adj = (evidence or {}).get("adjusted_probability")
    p_combo = _d(adj if adj is not None else fair)
    hist = history_for(latest_study(s), n) if n >= 2 else None
    combo: dict[str, Any] = {"legs": n, "fair": None if fair is None else round(fair, 4),
                             "estimate": None if p_combo is None else float(p_combo),
                             "history": hist, "walk_away": None}
    if p_combo is not None and n >= 2:
        wa = walk_away(p_combo, fees, "KXMVECROSSCATEGORY")
        combo["walk_away"] = None if wa is None else str(wa)

    # --- sizing ----------------------------------------------------------------------------
    cap = (budget * cap_fraction).quantize(CENT) if budget else unset_cap
    open_cost = sum((p.exposure for p in s.scalars(select(AccountPosition)) if p.position != 0),
                    Decimal(0))
    last = s.scalars(select(AccountSync).order_by(AccountSync.at.desc()).limit(1)).first()
    cash = last.balance if last and last.status == "success" else None
    price = quote if quote is not None else None
    sizing: dict[str, Any] = {"cap": _money(cap), "budget": _money(budget),
                              "open_cost": _money(open_cost), "cash": _money(cash),
                              "stake": _money(stake)}
    ev_combo = None
    if n >= 2 and price is not None and p_combo is not None:
        per = price + fees.rate * price * (1 - price)
        k = (p_combo - per) / (1 - per) if per < 1 else Decimal(0)
        if budget:
            sizing["kelly_quarter"] = _money(min(max(Decimal(0), budget * k / 4), cap))
        if stake is not None and stake > 0:
            c = (stake / per).to_integral_value(rounding=ROUND_FLOOR)
            cost = c * price + fees.taker("KXMVECROSSCATEGORY", c, price)
            ev_combo = c * p_combo - cost
            sizing.update({"contracts": str(c), "cost": _money(cost), "pays": _money(c),
                           "expected": _money(ev_combo)})

    # --- trim: drop the weakest leg ----------------------------------------------------------
    trim = None
    if n >= 3:
        def weakness(r: dict[str, Any]) -> float:
            if r["verdict"] == "market_higher":
                return -1.0
            if r["history"] is not None and r["ask"] is not None:
                return float(r["history"] - r["ask"])
            return 0.0
        worst = min(rows, key=weakness)
        rest = [r for r in rows if r is not worst]
        if all(r["mid"] is not None for r in rest):
            f2 = math.prod(float(r["mid"]) for r in rest)
            trim = {"drop": worst["ticker"], "label": worst["label"],
                    "fair_after": round(f2, 4), "legs_after": len(rest),
                    "history_after": history_for(latest_study(s), len(rest))}

    # --- verdict ---------------------------------------------------------------------------
    reasons: list[dict[str, str]] = []
    score = 0
    if n >= 6:
        score += 2
        reasons.append({"level": "warn", "text": f"{n} legs. Past 6+ leg combos returned "
                        f"${(hist or {}).get('return_per_dollar') or 0:.2f} per $1."})
    elif n >= 4:
        score += 1
        reasons.append({"level": "warn", "text": f"{n} legs: each extra leg multiplies the "
                        "maker's margin."})
    if hist and hist.get("return_per_dollar") is not None and n >= 2 and n < 6:
        reasons.append({"level": "info", "text": f"Past {hist['bucket']} combos returned "
                        f"${hist['return_per_dollar']:.2f} per $1."})
    against = [r for r in rows if r["verdict"] == "market_higher"]
    if against:
        score += 1
        reasons.append({"level": "warn", "text": f"{len(against)} leg(s) priced above what box "
                        "scores support."})
    if price is not None and combo["walk_away"] is not None:
        wa = Decimal(combo["walk_away"])
        if price > wa:
            score += 2 if price > wa * Decimal("1.25") else 1
            reasons.append({"level": "warn", "text": f"Quote {int(price * 100)}¢ is above the "
                            f"{int(wa * 100)}¢ walk-away price."})
        else:
            score -= 1
            reasons.append({"level": "good", "text": f"Quote {int(price * 100)}¢ is under the "
                            f"{int(wa * 100)}¢ walk-away price."})
    elif price is None and n >= 2:
        reasons.append({"level": "info", "text": "Enter Kalshi's quote to judge the price."})
    if stake is not None and stake > cap:
        score += 1
        reasons.append({"level": "warn", "text": f"${stake:.2f} is over your ${cap:.2f} "
                        "per-idea cap."})
    if budget and open_cost > budget:
        reasons.append({"level": "warn", "text": f"You already have ${open_cost:.2f} in open "
                        f"positions, over your ${budget:.0f} budget."})
    value = [x for x in singles if x.get("value")]
    if value and n >= 2:
        reasons.append({"level": "good", "text": f"{len(value)} leg(s) look like value on their "
                        "own: consider them as singles (below)."})
    verdict = "avoid" if score >= 3 else "stretch" if score >= 1 else "reasonable"
    if n < 2:
        verdict = "single"
    return {"verdict": verdict, "reasons": reasons, "combo": combo, "sizing": sizing,
            "singles": singles, "trim": trim, "fees_verified": fees.verified,
            "evidence_used": bool(ev_by)}
