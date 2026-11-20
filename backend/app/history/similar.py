"""'From your history': how trades like this one went for you, with small-sample guards.

One rule everywhere a past record is summarised, so no screen shows a trend the data can't
support:
- under MIN_SAMPLE closed markets: counts and net P&L only, labelled "too few to say";
  no win rate, no ROI;
- MIN_SAMPLE or more: the return on money staked (total P&L / total staked, i.e. weighted
  by stake) is compared with its standard error (ratio estimator). Weighting by stake keeps
  one tiny long-shot win from masking large losses, or one tiny loss from hiding gains.
  Within LUCK_Z standard errors of zero the record is called noise; only beyond that is it
  described as better or worse than luck. Even then it's a record, not a forecast.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from app.history.analysis import market_type, series_of

MIN_SAMPLE = 10
LUCK_Z = 2.0


def assess(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise closed market rows (from report()['markets'] or the full row list)."""
    closed = [r for r in rows if r.get("pnl") is not None]
    n = len(closed)
    pnl = sum((Decimal(r["pnl"]) for r in closed), Decimal(0))
    staked = sum((Decimal(r["staked"]) for r in closed), Decimal(0))
    won = sum(1 for r in closed if Decimal(r["pnl"]) > 0)
    priced = [(float(r["staked"]), float(r["pnl"])) for r in closed if Decimal(r["staked"]) > 0]
    out: dict[str, Any] = {"n": n, "won": won, "pnl": str(pnl.quantize(Decimal("0.01"))),
                           "staked": str(staked.quantize(Decimal("0.01"))), "roi": None,
                           "mean_return": None, "se": None}
    if n == 0:
        return {**out, "verdict": "none", "text": "No closed trades like this yet."}
    if n < MIN_SAMPLE or len(priced) < MIN_SAMPLE:
        word = "trade" if n == 1 else "trades"
        return {**out, "verdict": "too_few",
                "text": f"{n} closed {word}, net ${pnl:.2f}: too few to say anything about how "
                        f"these go for you (needs {MIN_SAMPLE}+)."}
    m = len(priced)
    w_total = sum(w for w, _ in priced)
    mean = sum(x for _, x in priced) / w_total  # return per dollar staked
    var = sum((x - mean * w) ** 2 for w, x in priced) * m / (m - 1)
    se = math.sqrt(var) / w_total
    roi = float(pnl / staked) if staked else None
    out.update(roi=None if roi is None else round(roi, 4), mean_return=round(mean, 4),
               se=round(se, 4))
    base = f"Won {won} of {n}, net ${pnl:.2f}"
    if abs(mean) <= LUCK_Z * se:
        return {**out, "verdict": "noise",
                "text": f"{base}. That's within what luck alone produces, so it isn't a pattern."}
    if mean > 0:
        return {**out, "verdict": "better",
                "text": f"{base}. Better than luck would usually give over {n} trades. "
                        "A record, not a forecast."}
    return {**out, "verdict": "worse",
            "text": f"{base}. Worse than luck would usually give over {n} trades: "
                    "worth asking what you keep getting wrong here."}


def similar(rows: list[dict[str, Any]], tickers: list[str], extra_series: list[str],
            combo_by_size: list[dict[str, Any]] | None, titles: dict[str, str]) -> dict[str, Any]:
    """Groups of past trades that resemble the given legs (or series)."""
    series = list(dict.fromkeys([series_of(t) for t in tickers] + extra_series))
    groups: list[dict[str, Any]] = []
    for ser in series:
        g = assess([r for r in rows if r["series"] == ser])
        groups.append({"kind": "series", "key": ser, "label": titles.get(ser, ser), **g})
    types = list(dict.fromkeys(market_type(s) for s in series))
    for t in types:
        if t == "other":
            continue  # too broad to mean anything
        g = assess([r for r in rows if r["type"] == t])
        groups.append({"kind": "type", "key": t, "label": f"All your {t} markets", **g})
    if len(tickers) >= 2:
        g = assess([r for r in rows if r["type"] == "combo"])
        groups.append({"kind": "combo", "key": "combo", "label": "All your Kalshi combos", **g})
        n_legs = len(tickers)
        bucket = "2" if n_legs == 2 else "3" if n_legs == 3 else "4-5" if n_legs <= 5 else "6+"
        size = next((b for b in (combo_by_size or []) if b["legs"] == bucket), None)
        if size:
            n, w = size["n"], size["won"]
            text = (f"{n} settled {bucket}-leg combo{'s' if n != 1 else ''}, {w} won: too few to "
                    f"say anything (needs {MIN_SAMPLE}+)." if n < MIN_SAMPLE
                    else f"Won {w} of {n} {bucket}-leg combos. A record, not a forecast.")
            groups.append({"kind": "combo_size", "key": bucket,
                           "label": f"Your {bucket}-leg combos",
                           "n": n, "won": w, "pnl": None, "staked": None, "roi": None,
                           "mean_return": None, "se": None,
                           "verdict": "too_few" if n < MIN_SAMPLE else "record", "text": text})
    return {"groups": groups, "min_sample": MIN_SAMPLE}
