"""Turn your synced fills/settlements/positions into P&L, behavior stats, calibration and
history-based suggestions. Pure computation over the database; no network.

Conventions
- A "market-side" is one market and one contract side you bought (yes or no). It is the
  sample unit for win rates and calibration (fills within it are not independent).
- Realized P&L is computed from your fills + settlement payout, net of all fees, and
  reconciled against Kalshi's own per-market realized P&L where available.
- Statistics carry their sample size; small samples are labelled, not hidden.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.stats import Quote, implied
from app.db.models import (
    AccountFill,
    AccountPosition,
    AccountSettlement,
    AccountSync,
    CatalogEvent,
    CatalogMarket,
    CatalogSeries,
)

ZERO = Decimal(0)
CENT = Decimal("0.01")
SMALL_SAMPLE = 30
_PROP = re.compile(r"(PTS|REB|AST|3PT|BLK|STL|PRA|YDS|TDS|PASS|RUSH|RSH|REC|SOG|HITS|HR|KS|"
                   r"GOALS|SAVES|ACES|FTM|FIRSTTD|ANYTD|TD$)")


def series_of(ticker: str) -> str:
    return ticker.split("-", 1)[0]


def market_type(series: str) -> str:
    s = series.upper()
    if s.startswith("KXMVE"):
        return "combo"
    if "SPREAD" in s or "MARGIN" in s:
        return "spread"
    if "TOTAL" in s:
        return "total"
    if _PROP.search(s.removeprefix("KX")):
        return "player prop"
    if s.endswith(("GAME", "MATCH")) or "WINNER" in s:
        return "game winner"
    return "other"


@dataclass
class Mkt:
    ticker: str
    bought: dict[str, list[Decimal]] = field(default_factory=lambda: {
        "yes": [ZERO, ZERO], "no": [ZERO, ZERO]})  # side -> [contracts, cost]
    sold: Decimal = ZERO  # proceeds
    fees: Decimal = ZERO
    contracts: Decimal = ZERO
    taker_contracts: Decimal = ZERO
    first_at: datetime | None = None
    last_at: datetime | None = None
    fills: int = 0

    @property
    def buy_cost(self) -> Decimal:
        return self.bought["yes"][1] + self.bought["no"][1]


def _q(d: Decimal) -> str:
    return str(d.quantize(CENT))


def _stat(won: int, n: int, avg_price: float) -> dict[str, Any]:
    rate = won / n if n else 0.0
    se = math.sqrt(max(avg_price * (1 - avg_price), 1e-9) / n) if n else None
    return {"n": n, "won": won, "win_rate": round(rate, 4), "avg_price": round(avg_price, 4),
            "edge": round(rate - avg_price, 4), "se": None if se is None else round(se, 4),
            "small_sample": n < SMALL_SAMPLE}


def report(s: Session, budget: Decimal | None) -> dict[str, Any]:
    fills = list(s.scalars(select(AccountFill).order_by(AccountFill.created_at)))
    settles = {x.ticker: x for x in s.scalars(select(AccountSettlement))}
    positions = {p.ticker: p for p in s.scalars(select(AccountPosition))}
    last_sync = s.scalars(select(AccountSync).order_by(AccountSync.at.desc()).limit(1)).first()

    mk: dict[str, Mkt] = {}
    for f in fills:
        m = mk.setdefault(f.ticker, Mkt(f.ticker))
        m.fills += 1
        m.last_at = f.created_at
        m.fees += f.fee
        m.contracts += f.count
        if f.is_taker:
            m.taker_contracts += f.count
        if f.action == "buy":
            m.bought[f.side][0] += f.count
            m.bought[f.side][1] += f.count * f.price
            m.first_at = m.first_at or f.created_at
        else:
            m.sold += f.count * f.price

    tickers = set(mk) | set(settles) | {t for t, p in positions.items() if p.position != 0}
    series_list = {series_of(t) for t in tickers}
    titles = dict(s.execute(select(CatalogSeries.ticker, CatalogSeries.title)
                            .where(CatalogSeries.ticker.in_(series_list))).all())
    cats = dict(s.execute(select(CatalogSeries.ticker, CatalogSeries.category)
                          .where(CatalogSeries.ticker.in_(series_list))).all())
    quotes = {m.ticker: m for m in s.scalars(select(CatalogMarket).where(
        CatalogMarket.ticker.in_(tickers)))}

    rows: list[dict[str, Any]] = []
    recon = {"checked": 0, "net": 0, "gross": 0}
    calib: list[tuple[float, bool]] = []  # (avg price paid, won) per settled market-side
    lead_hours: dict[str, list[float]] = defaultdict(list)
    for t in sorted(tickers):
        m = mk.get(t, Mkt(t))
        st = settles.get(t)
        pos = positions.get(t)
        ser = series_of(t)
        row: dict[str, Any] = {
            "ticker": t, "series": ser, "series_title": titles.get(ser, ser),
            "category": cats.get(ser, "Unknown"), "type": market_type(ser),
            "fills": m.fills, "staked": _q(m.buy_cost + m.fees), "fees": _q(m.fees),
            "sides": [sd for sd in ("yes", "no") if m.bought[sd][0] > 0],
            "result": st.market_result if st else None, "status": "open",
            "pnl": None, "kalshi_realized": None if pos is None else _q(pos.realized_pnl),
            "position": None if pos is None else str(pos.position),
            "mark": None, "first_trade_at": m.first_at, "sold_early": m.sold > 0,
        }
        if st is not None:
            row["status"] = "settled"
            if m.fills:
                pnl = st.revenue + m.sold - m.buy_cost - m.fees - st.fee
            else:  # fills archived beyond reach: use the settlement's cost basis
                pnl = st.revenue - st.yes_cost - st.no_cost - st.fee
                row["staked"] = _q(st.yes_cost + st.no_cost)
            row["pnl"] = _q(pnl)
            row["closed_at"] = st.settled_at
            if st.market_result in ("yes", "no"):
                for sd in ("yes", "no"):
                    c, cost = m.bought[sd]
                    if c > 0:
                        calib.append((float(cost / c), st.market_result == sd))
            if m.first_at:
                lead_hours[row["type"]].append((st.settled_at - m.first_at).total_seconds() / 3600)
        elif pos is not None and pos.position == 0 and m.fills:
            row["status"] = "closed"
            row["pnl"] = _q(m.sold - m.buy_cost - m.fees)
            row["closed_at"] = m.last_at
        elif pos is not None and pos.position != 0:
            side = "yes" if pos.position > 0 else "no"
            cm = quotes.get(t)
            p_yes = implied(Quote(t, t, cm.yes_bid, cm.yes_ask))[0] if cm else None
            if p_yes is not None:
                mid = Decimal(str(p_yes)) if side == "yes" else 1 - Decimal(str(p_yes))
                value = abs(pos.position) * mid
                row["mark"] = {"side": side, "contracts": str(abs(pos.position)),
                               "mid": str(mid.quantize(Decimal("0.001"))),
                               "value": _q(value), "cost": _q(pos.exposure),
                               "unrealized": _q(value - pos.exposure)}
            else:
                row["mark"] = {"side": side, "contracts": str(abs(pos.position)),
                               "mid": None, "value": None, "cost": _q(pos.exposure),
                               "unrealized": None}
        if row["pnl"] is not None and pos is not None and m.fills:
            recon["checked"] += 1
            pnl_d = Decimal(row["pnl"])
            if abs(pnl_d - pos.realized_pnl) <= CENT:
                recon["net"] += 1
            elif abs(pnl_d - (pos.realized_pnl - pos.fees_paid)) <= CENT:
                recon["gross"] += 1
        rows.append(row)

    done = [r for r in rows if r["pnl"] is not None]
    realized = sum((Decimal(r["pnl"]) for r in done), ZERO)
    staked = sum((Decimal(r["staked"]) for r in done), ZERO)
    fees = sum((m.fees for m in mk.values()), ZERO) + sum((x.fee for x in settles.values()), ZERO)
    open_rows = [r for r in rows if r["status"] == "open"]
    unrealized = sum((Decimal(r["mark"]["unrealized"]) for r in open_rows
                      if r["mark"] and r["mark"]["unrealized"] is not None), ZERO)

    # Timeline: realized P&L on the day each market settled (or was sold out), cumulative.
    daily: dict[str, dict[str, Any]] = {}
    for r in done:
        at = r.get("closed_at")
        if at is None:
            continue
        d = at.date().isoformat()
        e = daily.setdefault(d, {"date": d, "pnl": ZERO, "markets": 0, "wins": 0,
                                 "by_type": defaultdict(lambda: ZERO)})
        pnl_d = Decimal(r["pnl"])
        e["pnl"] += pnl_d
        e["markets"] += 1
        e["wins"] += 1 if pnl_d > 0 else 0
        e["by_type"][r["type"]] += pnl_d
    timeline, run = [], ZERO
    for d in sorted(daily):
        e = daily[d]
        run += e["pnl"]
        timeline.append({"date": d, "pnl": _q(e["pnl"]), "cumulative": _q(run),
                         "markets": e["markets"], "wins": e["wins"],
                         "by_type": {k: _q(v) for k, v in e["by_type"].items()}})

    def group(key: str) -> list[dict[str, Any]]:
        g: dict[str, dict[str, Any]] = {}
        for r in done:
            k = r[key] if key != "series" else f"{r['series_title']} ({r['series']})"
            e = g.setdefault(k, {"name": k, "markets": 0, "staked": ZERO, "pnl": ZERO,
                                 "series": r["series"]})
            e["markets"] += 1
            e["staked"] += Decimal(r["staked"])
            e["pnl"] += Decimal(r["pnl"])
        out = []
        for e in g.values():
            out.append({"name": e["name"], "series": e["series"], "markets": e["markets"],
                        "staked": _q(e["staked"]), "pnl": _q(e["pnl"]),
                        "roi": round(float(e["pnl"] / e["staked"]), 4) if e["staked"] else None})
        return sorted(out, key=lambda x: Decimal(x["pnl"]))

    # Calibration: buckets of the price you paid vs how often that side won.
    buckets = []
    for lo in range(0, 100, 10):
        pts = [(p, w) for p, w in calib if lo / 100 <= p < (lo + 10) / 100 or (lo == 90 and p >= 1)]
        if pts:
            b = _stat(sum(w for _, w in pts), len(pts), sum(p for p, _ in pts) / len(pts))
            buckets.append({"range": f"{lo}–{lo + 10}¢", **b})
    overall = _stat(sum(w for _, w in calib), len(calib),
                    sum(p for p, _ in calib) / len(calib)) if calib else None

    buy_fills = [f for f in fills if f.action == "buy"]
    buy_contracts = sum((f.count for f in buy_fills), ZERO)
    buy_notional = sum((f.count * f.price for f in buy_fills), ZERO)
    long_c = sum((f.count for f in buy_fills if f.price <= Decimal("0.20")), ZERO)
    fav_c = sum((f.count for f in buy_fills if f.price >= Decimal("0.80")), ZERO)
    all_c = sum((f.count for f in fills), ZERO)
    taker_c = sum((f.count for f in fills if f.is_taker), ZERO)
    stakes = [float(m.buy_cost + m.fees) for m in mk.values() if m.buy_cost > 0]
    days = {f.created_at.date() for f in fills}
    behavior = {
        "fills": len(fills), "markets": len(mk), "active_days": len(days),
        "avg_entry_price": None if not buy_contracts
        else str((buy_notional / buy_contracts).quantize(Decimal("0.001"))),
        "longshot_share": None if not buy_contracts else round(float(long_c / buy_contracts), 4),
        "favorite_share": None if not buy_contracts else round(float(fav_c / buy_contracts), 4),
        "taker_share": None if not all_c else round(float(taker_c / all_c), 4),
        "fee_share_of_notional": None if not buy_notional else round(float(fees / buy_notional), 4),
        "median_stake": None if not stakes else round(median(stakes), 2),
        "max_stake": None if not stakes else round(max(stakes), 2),
        "max_stake_share_of_budget": None if not (stakes and budget)
        else round(max(stakes) / float(budget), 4),
        "combo_markets": sum(1 for r in rows if r["type"] == "combo"),
        "median_hours_before_settlement": {k: round(median(v), 1)
                                           for k, v in lead_hours.items() if v},
    }
    by_type = group("type")
    by_series = group("series")
    from app.history.positions import entry_quality  # local: positions imports this module

    buy_price = {(t, sd): m.bought[sd][1] / m.bought[sd][0] for t, m in mk.items()
                 for sd in ("yes", "no") if m.bought[sd][0] > 0}
    quality = entry_quality(s, done, buy_price)
    from app.history.combo_legs import combo_breakdown

    combos = combo_breakdown(s, {r["ticker"]: Decimal(r["pnl"]) for r in done
                                 if r["type"] == "combo" and r["status"] == "settled"})
    summary = {
        "balance": _q(last_sync.balance) if last_sync and last_sync.balance is not None
        else None,
        "portfolio_value": _q(last_sync.portfolio_value)
        if last_sync and last_sync.portfolio_value is not None else None,
        "realized_pnl": _q(realized), "unrealized_pnl": _q(unrealized), "fees": _q(fees),
        "staked_closed": _q(staked), "roi": round(float(realized / staked), 4) if staked else None,
        "settled_markets": sum(1 for r in rows if r["status"] == "settled"),
        "open_markets": len(open_rows), "win_rate": overall,
        "budget": None if budget is None else str(budget),
    }
    return {
        "last_sync": None if last_sync is None else {
            "at": last_sync.at, "status": last_sync.status, "message": last_sync.message},
        "summary": summary,
        "reconciliation": recon,
        "timeline": timeline,
        "behavior": behavior,
        "calibration": buckets,
        "by_type": by_type,
        "by_series": by_series,
        "open_positions": open_rows,
        "markets": sorted(done, key=lambda r: r["first_trade_at"].isoformat()
                          if r["first_trade_at"] else "", reverse=True)[:200],
        "entry_quality": quality,
        "combo_breakdown": combos,
        "playbook": playbook(summary, behavior, buckets, by_type, quality, combos),
        "insights": insights(summary, behavior, buckets, by_type, by_series),
        "suggestions": suggestions(s, by_type, by_series, behavior, buckets),
    }


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def insights(summary: dict, behavior: dict, buckets: list[dict], by_type: list[dict],
             by_series: list[dict]) -> list[dict[str, str]]:
    """Plain-language observations, each with its evidence. Thresholds are deliberately
    modest; small samples are flagged."""
    out: list[dict[str, str]] = []
    wr = summary["win_rate"]
    n = wr["n"] if wr else 0
    if n == 0:
        return [{"level": "info", "text": "No settled trades yet. Insights appear once "
                                          "markets you traded have settled."}]
    if n < SMALL_SAMPLE:
        out.append({"level": "info", "text": f"Only {n} settled market-sides so far. Treat "
                    "every number here as noisy until you have 30+."})
    if wr:
        verdict = "ahead of" if wr["edge"] > 0 else "behind"
        out.append({"level": "good" if wr["edge"] > 0 else "warn",
                    "text": f"Your picks won {_pct(wr['win_rate'])} of the time at an average "
                    f"price of {wr['avg_price'] * 100:.0f}¢: {verdict} the market by "
                    f"{abs(wr['edge']) * 100:.1f} pts (±{(wr['se'] or 0) * 100:.1f} standard "
                    "error), before fees."})
    for b in buckets:
        if b["n"] >= 8 and abs(b["edge"]) > 2 * (b["se"] or 1):
            good = b["edge"] > 0
            out.append({"level": "good" if good else "warn",
                        "text": f"At {b['range']} you won {_pct(b['win_rate'])} vs "
                        f"{b['avg_price'] * 100:.0f}¢ paid over {b['n']} picks: a clear "
                        f"{'edge' if good else 'leak'} beyond noise."})
    ls = behavior.get("longshot_share")
    if ls is not None and ls > 0.4:
        out.append({"level": "warn", "text": f"{_pct(ls)} of your contracts were bought at "
                    "20¢ or less. Longshots on prediction markets tend to be overpriced "
                    "(the favorite–longshot bias), and fees take a bigger bite of cheap "
                    "contracts."})
    ts, fs = behavior.get("taker_share"), behavior.get("fee_share_of_notional")
    if ts is not None and fs is not None and ts > 0.8 and fs > 0.02:
        out.append({"level": "warn", "text": f"{_pct(ts)} of your volume took liquidity, and "
                    f"fees came to {fs * 100:.1f}% of what you spent. Resting limit orders "
                    "(maker) pay far lower fees."})
    ms = behavior.get("max_stake_share_of_budget")
    if ms is not None and ms > 0.2:
        out.append({"level": "warn", "text": f"Your largest single market stake was "
                    f"{_pct(ms)} of your budget. A few bad outcomes can end the experiment; "
                    "5–10% per idea is a common ceiling."})
    worst = [t for t in by_type if Decimal(t["pnl"]) < 0 and t["markets"] >= 5]
    best = [t for t in reversed(by_type) if Decimal(t["pnl"]) > 0 and t["markets"] >= 5]
    if best:
        out.append({"level": "good", "text": f"Best market type: {best[0]['name']} "
                    f"(+${best[0]['pnl']} over {best[0]['markets']} markets)."})
    if worst:
        out.append({"level": "warn", "text": f"Worst market type: {worst[0]['name']} "
                    f"(${worst[0]['pnl']} over {worst[0]['markets']} markets)."})
    if behavior.get("combo_markets"):
        combo = next((t for t in by_type if t["name"] == "combo"), None)
        if combo:
            out.append({"level": "info", "text": f"Combos: {combo['markets']} settled, P&L "
                        f"${combo['pnl']}. Combos multiply every leg's vig, so they need a "
                        "real edge on each leg to pay off."})
    return out


def playbook(summary: dict, behavior: dict, buckets: list[dict], by_type: list[dict],
             quality: dict, combos: dict | None = None) -> list[dict[str, str]]:
    """Short, testable rules drawn from your own record. Each carries its evidence and how
    much to trust it. Rule-based today; a local LLM can add judgment later."""
    out: list[dict[str, str]] = []
    budget = summary.get("budget")
    if budget:
        cap = Decimal(budget) * Decimal("0.05")
        out.append({"rule": f"Cap each idea at ${cap:.2f}", "why": f"5% of your ${budget} "
                    "budget. A losing streak then costs a few dollars, not the experiment.",
                    "confidence": "standard"})
    good = [b for b in buckets if b["n"] >= 8 and b["edge"] > 2 * (b["se"] or 1)]
    bad = [b for b in buckets if b["n"] >= 8 and b["edge"] < -2 * (b["se"] or 1)]
    if good:
        b = max(good, key=lambda x: x["edge"])
        out.append({"rule": f"Lean into {b['range']} prices", "why": f"Won {b['won']}/"
                    f"{b['n']} vs {b['avg_price'] * 100:.0f}¢ paid.", "confidence": "medium"})
    if bad:
        b = min(bad, key=lambda x: x["edge"])
        out.append({"rule": f"Skip {b['range']} prices", "why": f"Won {b['won']}/{b['n']} vs "
                    f"{b['avg_price'] * 100:.0f}¢ paid.", "confidence": "medium"})
    best = [t for t in reversed(by_type) if Decimal(t["pnl"]) > 0 and t["markets"] >= 5]
    worst = [t for t in by_type if Decimal(t["pnl"]) < 0 and t["markets"] >= 5]
    if best:
        out.append({"rule": f"Favor {best[0]['name']} markets", "why": f"+${best[0]['pnl']} "
                    f"over {best[0]['markets']}.", "confidence": "low" if best[0]["markets"]
                    < SMALL_SAMPLE else "medium"})
    if worst:
        out.append({"rule": f"Pause {worst[0]['name']} markets", "why": f"${worst[0]['pnl']} "
                    f"over {worst[0]['markets']}.", "confidence": "low" if worst[0]["markets"]
                    < SMALL_SAMPLE else "medium"})
    ts = behavior.get("taker_share")
    if ts is not None and ts > 0.8:
        out.append({"rule": "Rest limit orders instead of crossing the spread",
                    "why": f"{ts * 100:.0f}% of your volume paid taker fees.",
                    "confidence": "standard"})
    ee, hs = quality["early_exits"], quality["held_to_settlement"]
    sells_winners = ee["n"] >= 5 and ee["in_profit"] / ee["n"] > 0.6
    rides_losers = hs["n"] >= 5 and hs["lost"] / hs["n"] > 0.6
    if sells_winners and rides_losers:
        out.append({"rule": "Set your exit before you enter",
                    "why": f"You sold {ee['in_profit']}/{ee['n']} early exits in profit but "
                    f"{hs['lost']}/{hs['n']} positions held to the end lost: selling winners "
                    "and riding losers.", "confidence": "medium"})
    clv = quality["clv"]
    if clv["n"] >= 10 and clv["avg_pts"] is not None:
        good_clv = clv["avg_pts"] > 0
        out.append({"rule": "Keep your entry process" if good_clv else "Wait for better prices",
                    "why": f"Your entries averaged {clv['avg_pts']:+.1f} pts vs the last price "
                    f"before close ({clv['n']} trades).", "confidence": "medium"})
    if combos and combos.get("lost", 0) >= 5:
        sizes = [b for b in combos["by_size"] if b["n"] >= 3]
        big = [b for b in sizes if b["legs"] in ("4-5", "6+")]
        n, w = sum(b["n"] for b in big), sum(b["won"] for b in big)
        if n >= 5 and w / n < 0.1:
            out.append({"rule": "Keep combos to 2–3 legs", "why": f"{w} win{'s' if w != 1 else ''}"
                        f" in {n} combos of 4+ legs (avg {combos['avg_legs']} legs).",
                        "confidence": "medium" if n >= 10 else "low"})
        total = sum(x["legs"] for x in combos["breakers"])
        top = combos["breakers"][0] if combos["breakers"] else None
        if top and total >= 10 and top["legs"] / total > 0.5:
            out.append({"rule": f"Check {top['type']} legs hardest", "why": f"They were "
                        f"{top['legs']} of the {total} legs that sank your combos.",
                        "confidence": "medium"})
        if combos["lost_by_one"] / combos["lost"] > 0.4:
            out.append({"rule": "'One leg away' is the design, not bad luck",
                        "why": f"{combos['lost_by_one']} of {combos['lost']} lost combos missed "
                        "by a single leg. More legs make near-misses more common, not wins.",
                        "confidence": "standard"})
    if behavior.get("combo_markets"):
        combo = next((t for t in by_type if t["name"] == "combo"), None)
        if combo and Decimal(combo["pnl"]) < 0:
            out.append({"rule": "Only combo legs you'd bet alone",
                        "why": f"Combos: ${combo['pnl']} over {combo['markets']}. Each leg's "
                        "margin multiplies.", "confidence": "standard"})
    return out


def suggestions(s: Session, by_type: list[dict], by_series: list[dict], behavior: dict,
                buckets: list[dict]) -> list[dict[str, Any]]:
    """Research leads grounded in your record. Not picks: each says why it's listed."""
    out: list[dict[str, Any]] = []
    good_series = [x for x in reversed(by_series) if Decimal(x["pnl"]) > 0 and x["markets"] >= 3]
    for g in good_series[:3]:
        evs = s.scalars(select(CatalogEvent).where(CatalogEvent.series_ticker == g["series"])
                        .order_by(CatalogEvent.volume_24h.desc()).limit(3)).all()
        if evs:
            out.append({"kind": "lean_in", "title": f"Open markets in {g['name']}",
                        "why": f"You're +${g['pnl']} over {g['markets']} markets here "
                               f"(ROI {(g['roi'] or 0) * 100:.0f}%). Sample size matters; "
                               "check it's not one lucky hit.",
                        "events": [{"event_ticker": e.event_ticker, "title": e.title,
                                    "sub_title": e.sub_title} for e in evs]})
    bad = [x for x in by_series if Decimal(x["pnl"]) < 0 and x["markets"] >= 3][:3]
    for b in bad:
        out.append({"kind": "caution", "title": f"Go easy on {b['name']}",
                    "why": f"${b['pnl']} over {b['markets']} markets. Before the next one, "
                           "write down why your probability differs from the price.",
                    "events": []})
    cheap = next((b for b in buckets if b["range"].startswith("0–") and b["n"] >= 8), None)
    if cheap and cheap["edge"] < 0:
        out.append({"kind": "caution", "title": "Longshots under 10¢",
                    "why": f"You won {cheap['won']} of {cheap['n']} vs ~"
                           f"{cheap['avg_price'] * 100:.0f}¢ paid. Consider the other side, "
                           "or skipping them.", "events": []})
    out.append({"kind": "method", "title": "Use the ladders before a prop",
                "why": "On the Markets page, compare a player-prop or total strike with its "
                       "neighbours: strikes flagged 'off the smooth curve' are where a price "
                       "disagrees with its own ladder. Then decide your probability and run "
                       "it through EV before trading.", "events": []})
    return out


def fills_page(s: Session, limit: int, offset: int) -> list[dict[str, Any]]:
    rows = s.scalars(select(AccountFill).order_by(AccountFill.created_at.desc())
                     .limit(limit).offset(offset)).all()
    return [{"fill_id": f.fill_id, "ticker": f.ticker, "side": f.side, "action": f.action,
             "count": str(f.count), "price": str(f.price), "fee": str(f.fee),
             "is_taker": f.is_taker, "created_at": f.created_at,
             "type": market_type(series_of(f.ticker))}
            for f in rows]
