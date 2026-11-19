"""Research statistics from market prices. Pure functions, no I/O.

Everything here reads the crowd's prices back as probabilities. It describes what the
market implies; it does not claim the market is wrong. Floats are fine for statistics;
money (costs, fees, EV) uses Decimal and the verified fee schedule.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from app.signals.fees import FeeSchedule, taker_buy_cost

TAIL = Decimal("0.05")
LADDER_TYPES = ("greater", "greater_or_equal")
_NUM = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True)
class Quote:
    ticker: str
    label: str
    yes_bid: Decimal | None
    yes_ask: Decimal | None
    strike_type: str | None = None
    floor_strike: Decimal | None = None
    group_key: str = ""
    title: str = ""


def implied(q: Quote) -> tuple[float | None, str]:
    """(probability of YES, quality). Two-sided -> mid. Deep tails with only one side
    quoted get half-way to the bound (e.g. ask 2c, no bid -> 1c) and are labelled."""
    b, a = q.yes_bid, q.yes_ask
    if b is not None and a is not None:
        return float((b + a) / 2), "mid"
    if a is not None and a <= TAIL:
        return float(a / 2), "tail"
    if b is not None and b >= 1 - TAIL:
        return float((1 + b) / 2), "tail"
    return None, "none"


def spread(q: Quote) -> float | None:
    return float(q.yes_ask - q.yes_bid) if q.yes_bid is not None and q.yes_ask is not None else None


# --- Mutually exclusive sets ---------------------------------------------------------------


def exclusive_stats(quotes: Sequence[Quote]) -> dict[str, Any] | None:
    """For 'exactly one outcome wins' events: how much the listed prices add up to."""
    if len(quotes) < 2:
        return None
    probs = {q.ticker: implied(q)[0] for q in quotes}
    known = {t: p for t, p in probs.items() if p is not None}
    asks = [q.yes_ask for q in quotes]
    bids = [q.yes_bid for q in quotes]
    total_mid = sum(known.values())
    return {
        "outcomes": len(quotes),
        "priced": len(known),
        "sum_yes_ask": str(sum(asks)) if all(a is not None for a in asks) else None,  # type: ignore[arg-type]
        "sum_yes_bid": str(sum(b for b in bids if b is not None)),
        "sum_implied": round(total_mid, 4),
        "overround": round(total_mid - 1, 4) if len(known) == len(quotes) else None,
        # Rescale so the listed outcomes sum to 100%. Only meaningful if the list is
        # exhaustive -- the UI says so.
        "normalized": {t: round(p / total_mid, 4) for t, p in known.items()}
        if total_mid > 0 and len(known) == len(quotes) else {},
    }


# --- Ladders (implied distributions) -------------------------------------------------------


def _pav_decreasing(ys: list[float], ws: list[float]) -> list[float]:
    """Weighted isotonic regression, non-increasing (pool adjacent violators)."""
    blocks: list[list[float]] = []  # [value, weight, count]
    for y, w in zip(ys, ws, strict=True):
        blocks.append([y, w, 1])
        while len(blocks) > 1 and blocks[-2][0] < blocks[-1][0]:
            v2, w2, c2 = blocks.pop()
            v1, w1, c1 = blocks.pop()
            blocks.append([(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2, c1 + c2])
    out: list[float] = []
    for v, _, c in blocks:
        out.extend([v] * int(c))
    return out


def group_label(title: str) -> str:
    return _NUM.sub("X", title).strip()


def ladder_groups(quotes: Sequence[Quote]) -> dict[str, list[Quote]]:
    """'Over k' markets grouped by what they measure (game total; a team's margin; one
    player's points). Needs 3+ strikes to say anything about a distribution."""
    groups: dict[str, list[Quote]] = defaultdict(list)
    for q in quotes:
        if q.strike_type in LADDER_TYPES and q.floor_strike is not None:
            groups[q.group_key + "|" + group_label(q.title)].append(q)
    return {k: sorted(v, key=lambda q: q.floor_strike or 0) for k, v in groups.items()
            if len({q.floor_strike for q in v}) >= 3}


_WINS_BY = re.compile(r"^(.+?) wins by over X", re.I)


def merge_margin_ladders(groups: dict[str, list[Quote]]) -> dict[str, list[Quote]]:
    """A spread event lists 'A wins by over k' and 'B wins by over k' as two ladders. Merge
    them into ONE distribution of A's margin: P(margin > -k) = 1 - P(B wins by over k)
    (exact for half-point strikes, since a margin can't equal -k)."""
    teams = {}
    for key, qs in groups.items():
        m = _WINS_BY.match(group_label(qs[0].title))
        if m:
            teams[key] = m.group(1)
    if len(teams) != 2 or len(groups) != 2:
        return groups
    (ka, a), (kb, b) = teams.items()
    flipped = [Quote(q.ticker, q.label, None if q.yes_ask is None else 1 - q.yes_ask,
                     None if q.yes_bid is None else 1 - q.yes_bid, "greater",
                     -q.floor_strike if q.floor_strike is not None else None, "",
                     f"{a} margin over X (negative = {b} wins)") for q in groups[kb]]
    same = [replace(q, group_key="", title=f"{a} margin over X (negative = {b} wins)")
            for q in groups[ka]]
    merged = sorted(same + flipped, key=lambda q: q.floor_strike or 0)
    return {f"margin|{a}": merged}


def _quantile(ks: list[float], s: list[float], q: float) -> float | None:
    """x where P(X > x) = 1 - q, linear between strikes; None if beyond listed strikes."""
    target = 1 - q
    for i in range(len(ks) - 1):
        a, b = s[i], s[i + 1]
        if a >= target >= b:
            return ks[i] if a == b else ks[i] + (a - target) / (a - b) * (ks[i + 1] - ks[i])
    return None


def ladder_stats(quotes: Sequence[Quote]) -> dict[str, Any] | None:
    pts = []
    for q in quotes:
        p, quality = implied(q)
        if p is None or q.floor_strike is None:
            continue
        pts.append((float(q.floor_strike), p, spread(q), quality, q))
    if len({k for k, *_ in pts}) < 3:
        return None
    pts.sort(key=lambda x: x[0])
    ks = [k for k, *_ in pts]
    raw = [p for _, p, *_ in pts]
    ws = [1 / max(sp if sp is not None else 0.05, 0.01) for _, _, sp, _, _ in pts]
    fit = _pav_decreasing(raw, ws)
    violations = sum(1 for i in range(len(raw) - 1) if raw[i + 1] > raw[i] + 0.005)

    gaps = sorted(ks[i + 1] - ks[i] for i in range(len(ks) - 1))
    step = gaps[len(gaps) // 2] if gaps else 1.0
    buckets = [{"label": f"≤ {ks[0]:g}", "lo": None, "hi": ks[0], "p": round(1 - fit[0], 4)}]
    for i in range(len(ks) - 1):
        buckets.append({"label": f"{ks[i]:g}–{ks[i + 1]:g}", "lo": ks[i], "hi": ks[i + 1],
                        "p": round(max(fit[i] - fit[i + 1], 0.0), 4)})
    buckets.append({"label": f"> {ks[-1]:g}", "lo": ks[-1], "hi": None, "p": round(fit[-1], 4)})
    reps = [ks[0] - step / 2] + [(ks[i] + ks[i + 1]) / 2 for i in range(len(ks) - 1)] \
        + [ks[-1] + step / 2]
    mass = [b["p"] for b in buckets]
    tot = sum(mass) or 1.0
    mean = sum(r * m for r, m in zip(reps, mass, strict=True)) / tot
    var = sum(m * (r - mean) ** 2 for r, m in zip(reps, mass, strict=True)) / tot
    tails = mass[0] + mass[-1]

    points = []
    for (k, p, sp, quality, q), f in zip(pts, fit, strict=True):
        resid = p - f
        tol = max(0.02, (sp or 0) / 2)
        points.append({"ticker": q.ticker, "strike": k, "label": q.label, "implied": round(p, 4),
                       "fitted": round(f, 4), "residual": round(resid, 4), "quality": quality,
                       "spread": None if sp is None else round(sp, 4),
                       "off_curve": abs(resid) > tol})
    return {
        "label": group_label(quotes[0].title),
        "strikes": len(ks),
        "median": _round(_quantile(ks, fit, 0.5)),
        "p10": _round(_quantile(ks, fit, 0.1)), "p25": _round(_quantile(ks, fit, 0.25)),
        "p75": _round(_quantile(ks, fit, 0.75)), "p90": _round(_quantile(ks, fit, 0.9)),
        "mean": round(mean, 2), "sd": round(math.sqrt(var), 2),
        "tail_mass": round(tails, 4),
        "mean_reliable": tails < 0.1,
        "monotonicity_violations": violations,
        "buckets": buckets,
        "points": points,
    }


def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 2)


# --- Expected value & sizing ---------------------------------------------------------------


def scaled_schedule(schedule: FeeSchedule, multiplier: Decimal | None) -> FeeSchedule:
    """Series can carry a fee multiplier (e.g. 0.5); the formula's rate scales with it."""
    if multiplier is None or multiplier == 1:
        return schedule
    return replace(schedule, taker_rate=schedule.taker_rate * multiplier)


def expected_value(schedule: FeeSchedule, price: Decimal, contracts: int, prob: Decimal,
                   budget: Decimal | None, cap_fraction: Decimal,
                   depth: Decimal | None = None) -> dict[str, Any]:
    """Buy `contracts` at `price` as a taker, believing the side wins with `prob`."""
    cost = taker_buy_cost(schedule, [(Decimal(contracts), price)])
    total = cost.total_debit
    payout = prob * contracts
    ev = payout - total
    per = total / contracts  # all-in price per contract = break-even probability
    edge = prob - per
    kelly = edge / (1 - per) if edge > 0 and per < 1 else Decimal(0)
    out: dict[str, Any] = {
        "price": str(price), "contracts": contracts, "probability": str(prob),
        "notional": str(cost.notional), "fee": str(cost.effective_fee),
        "total_cost": str(total), "max_payout": str(Decimal(contracts)),
        "expected_payout": str(payout.quantize(Decimal("0.0001"))),
        "expected_value": str(ev.quantize(Decimal("0.0001"))),
        "ev_per_dollar": str((ev / total).quantize(Decimal("0.0001"))) if total else None,
        "breakeven_probability": str(per.quantize(Decimal("0.0001"))),
        "kelly_fraction": str(kelly.quantize(Decimal("0.0001"))),
        "depth_at_price": None if depth is None else str(depth),
        "depth_warning": depth is not None and Decimal(contracts) > depth,
        "fee_schedule_version": schedule.version,
    }
    if budget is not None and kelly > 0:
        quarter = budget * kelly / 4
        cap = budget * cap_fraction
        stake = min(quarter, cap)
        out["budget"] = str(budget)
        out["quarter_kelly_stake"] = str(quarter.quantize(Decimal("0.01")))
        out["cap_stake"] = str(cap.quantize(Decimal("0.01")))
        out["suggested_contracts"] = int((stake / per).to_integral_value(rounding=ROUND_FLOOR))
    return out


# --- Combos (parlays) ----------------------------------------------------------------------


def game_key(event_ticker: str) -> str:
    """KXNBATOTAL-26NOV18BOSDEN and KXNBAPTS-26NOV18BOSDEN share the game key."""
    parts = event_ticker.split("-", 1)
    return parts[1] if len(parts) == 2 else event_ticker


def combo_stats(legs: Sequence[tuple[Quote, str, str, bool]]) -> dict[str, Any]:
    """legs: (quote, side 'yes'|'no', event_ticker, event_is_mutually_exclusive).
    Joint probability ASSUMING INDEPENDENCE, plus warnings where that is false."""
    warnings: list[str] = []
    out_legs = []
    joint: float | None = 1.0
    impossible = False
    seen_events: dict[str, list[tuple[Quote, str]]] = defaultdict(list)
    for q, side, ev, me in legs:
        p, quality = implied(q)
        ps = None if p is None else (p if side == "yes" else 1 - p)
        out_legs.append({"ticker": q.ticker, "label": q.label, "side": side, "event": ev,
                         "probability": None if ps is None else round(ps, 4),
                         "quality": quality})
        joint = None if joint is None or ps is None else joint * ps
        seen_events[ev].append((q, side))
        if me and side == "yes" and sum(1 for _, s in seen_events[ev] if s == "yes") > 1:
            impossible = True
    if impossible:
        warnings.append("Two YES legs in the same mutually exclusive event can't both win.")
    for ev, items in seen_events.items():
        if len(items) > 1 and not impossible:
            warnings.append(f"{len(items)} legs from {ev}: strongly related, so independence "
                            "is wrong (e.g. two strikes of one ladder).")
    games: dict[str, set[str]] = defaultdict(set)
    for _, _, ev, _ in legs:
        games[game_key(ev)].add(ev)
    for g, evs in games.items():
        if len(evs) > 1:
            warnings.append(f"Same game ({g}) across {len(evs)} markets: outcomes are "
                            "correlated (e.g. a team winning and its star scoring a lot). "
                            "The independent price below is only a rough guide.")
    if any(lg["probability"] is None for lg in out_legs):
        warnings.append("Some legs have no two-sided quote, so no joint probability.")
    if impossible:
        joint = 0.0
    return {
        "legs": out_legs,
        "independent_probability": None if joint is None else round(joint, 6),
        "fair_price": None if joint is None else round(joint, 4),
        "fair_multiple": None if not joint else round(1 / joint, 2),
        "warnings": warnings,
    }
