"""Model-free mispricing detectors (pure functions, Decimal money).

All prices are EXECUTABLE (buy at the ask: YES ask, or NO ask = 1 - YES bid) and sized only
to the quantity resting at the best level. Each leg is a separate order, so each leg pays its
own taker fee rounded up to the cent (verified Kalshi schedule) -- small orders on cheap
contracts are often killed by that rounding, which sizing accounts for.

Detectors
  LADDER       same event, strike_type "greater" (or "greater_or_equal"), strikes k1 < k2:
               P(>k1) >= P(>k2) must hold. Buy YES(k1) + NO(k2) -> pays >= $1 in every
               outcome (2 if k1 < X <= k2). Profit if ask_yes(k1) + ask_no(k2) + fees < 1.
  EXCL_NO      event marked mutually_exclusive (at most one YES), n outcomes:
               buy NO on all -> pays >= n-1 (n if none wins). Guaranteed by exclusivity alone.
  EXCL_YES     buy YES on all -> pays exactly 1 ONLY IF the outcome list is exhaustive (some
               listed outcome must win). CONDITIONAL: a human must verify exhaustiveness.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from app.signals.fees import FeeSchedule, taker_buy_cost

ONE = Decimal(1)


@dataclass(frozen=True)
class TopOfBook:
    ticker: str
    title: str
    status: str
    yes_bid: Decimal | None
    yes_ask: Decimal | None
    yes_bid_size: Decimal
    yes_ask_size: Decimal
    strike_type: str | None = None
    floor_strike: Decimal | None = None
    rules: str | None = None  # rules_primary text; defines what the market measures

    @property
    def no_ask(self) -> Decimal | None:  # buy NO by hitting the best YES bid
        return None if self.yes_bid is None else ONE - self.yes_bid

    @property
    def no_ask_size(self) -> Decimal:
        return self.yes_bid_size


@dataclass(frozen=True)
class EventBook:
    event_ticker: str
    title: str
    mutually_exclusive: bool
    markets: Sequence[TopOfBook]
    category: str = "Uncategorized"

    @property
    def series(self) -> str:
        return self.event_ticker.split("-", 1)[0]


@dataclass(frozen=True)
class LegQuote:
    ticker: str
    title: str
    side: str  # YES | NO (what we BUY)
    price: Decimal  # executable price per contract
    available: Decimal  # contracts resting at that price


@dataclass(frozen=True)
class SizedLeg:
    ticker: str
    title: str
    side: str
    limit_price: Decimal
    quantity: Decimal
    cost: Decimal  # total debit incl. fee rounding
    fee: Decimal
    available: Decimal


@dataclass(frozen=True)
class Opportunity:
    kind: str  # LADDER | EXCL_NO | EXCL_YES
    guaranteed: bool
    event_ticker: str
    title: str
    legs: list[SizedLeg]
    quantity: Decimal  # sets of the combination
    cost: Decimal
    fees: Decimal
    min_payoff: Decimal  # worst-case payout across outcomes (assuming stated condition)
    profit: Decimal  # min_payoff - cost
    return_pct: Decimal
    claim: str
    checklist: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SizingRules:
    max_cost: Decimal  # per-opportunity spend cap from the budget rules
    min_profit: Decimal = Decimal("0.10")
    min_return: Decimal = Decimal("0.02")
    max_legs: int = 8
    max_quantity: int = 500
    require_catch_all: bool = True  # EXCL_YES only when an "Other/None/Field" outcome exists


def size_combo(legs: Sequence[LegQuote], payoff_per_set: Decimal, schedule: FeeSchedule,
               rules: SizingRules) -> tuple[Decimal, list[SizedLeg], Decimal, Decimal] | None:
    """Choose the integer set count maximising profit after per-leg fee rounding, within
    depth and the spend cap. Returns (qty, legs, total_cost, total_fees) or None."""
    if not legs or len(legs) > rules.max_legs:
        return None
    depth = min(lg.available for lg in legs)
    cap_q = int(min(depth, Decimal(rules.max_quantity)))
    best: tuple[Decimal, Decimal, list[SizedLeg], Decimal, Decimal] | None = None
    for q in range(1, cap_q + 1):
        qd = Decimal(q)
        sized, total, fees = [], Decimal(0), Decimal(0)
        for lg in legs:
            c = taker_buy_cost(schedule, [(qd, lg.price)])
            sized.append(SizedLeg(lg.ticker, lg.title, lg.side, lg.price, qd, c.total_debit,
                                  c.effective_fee, lg.available))
            total += c.total_debit
            fees += c.effective_fee
        if total > rules.max_cost:
            break  # cost grows with q
        profit = qd * payoff_per_set - total
        if best is None or profit > best[0]:
            best = (profit, qd, sized, total, fees)
    if best is None:
        return None
    profit, qd, sized, total, fees = best
    if profit < rules.min_profit or profit < total * rules.min_return:
        return None
    return qd, sized, total, fees


def _make(kind: str, guaranteed: bool, ev: EventBook, legs: list[LegQuote],
          payoff_per_set: Decimal, schedule: FeeSchedule, rules: SizingRules, claim: str,
          checklist: list[str]) -> Opportunity | None:
    sized = size_combo(legs, payoff_per_set, schedule, rules)
    if sized is None:
        return None
    q, sl, cost, fees = sized
    min_payoff = q * payoff_per_set
    profit = min_payoff - cost
    return Opportunity(kind, guaranteed, ev.event_ticker, ev.title, sl, q, cost, fees,
                       min_payoff, profit, (profit / cost * 100).quantize(Decimal("0.01")),
                       claim, checklist)


def _tradable(m: TopOfBook) -> bool:
    return m.status == "active"


CATCH_ALL = re.compile(r"\b(other|others|none|no one|nobody|field|any other|not listed)\b",
                       re.IGNORECASE)
NONE_OUTCOME = re.compile(r"\b(none|no one|nobody|neither|not before|no winner)\b",
                          re.IGNORECASE)
# "before Jan 1, 2027" / "by December 31" etc.: the event may simply not happen in time.
DEADLINE = re.compile(r"\b(before|by)\b[^.]{0,40}\d{4}", re.IGNORECASE)
_NUM = re.compile(r"-?\d+(?:[.,]\d+)*")


def is_game(ev: EventBook) -> bool:
    """Head-to-head game/match series (e.g. KXNBAGAME, KXATPMATCH): one side must win."""
    return ev.series.endswith(("GAME", "MATCH"))


def excl_yes_eligible(ev: EventBook, ms: Sequence[TopOfBook]) -> bool:
    """Can 'buy YES on every listed outcome' plausibly be exhaustive?
    - two-outcome GAMES/MATCHES: yes (postponement rules still need a human check);
    - otherwise an explicit catch-all outcome is required, and when the rules carry a
      deadline only a None-type outcome counts ("Other" doesn't cover "nobody in time").
    Live lessons (2026-11-18): elections listing two candidates are NOT exhaustive; "first
    AI to hit 1550 before Jan 1, 2027" listed "Other" but no "None"."""
    if len(ms) == 2 and is_game(ev):
        return True
    has_deadline = any(m.rules and DEADLINE.search(m.rules) for m in ms)
    pattern = NONE_OUTCOME if has_deadline else CATCH_ALL
    return any(pattern.search(m.title) for m in ms)


def ladder_key(m: TopOfBook) -> str | None:
    """Markets are rungs of ONE ladder only if their rules are identical apart from numbers
    (an event can hold several ladders, e.g. each team's total). No rules -> not laddered."""
    if not m.rules or m.strike_type is None:
        return None
    return m.strike_type + "|" + _NUM.sub("#", " ".join(m.rules.split()).lower())


def detect_ladder(ev: EventBook, schedule: FeeSchedule, rules: SizingRules) -> list[Opportunity]:
    out: list[Opportunity] = []
    groups: dict[str, list[TopOfBook]] = {}
    for m in ev.markets:
        key = ladder_key(m)
        if (key and _tradable(m) and m.floor_strike is not None
                and m.strike_type in ("greater", "greater_or_equal")):
            groups.setdefault(key, []).append(m)
    for key, members in groups.items():
        stype = key.split("|", 1)[0]
        rungs = sorted(members, key=lambda m: m.floor_strike)  # type: ignore[arg-type,return-value]
        for i, lo in enumerate(rungs):
            if lo.yes_ask is None or lo.yes_ask_size <= 0:
                continue
            for hi in rungs[i + 1:]:
                if hi.floor_strike == lo.floor_strike or hi.no_ask is None or hi.no_ask_size <= 0:
                    continue
                if lo.yes_ask + hi.no_ask >= ONE:
                    continue  # consistent (no raw gap); skip before fee math
                legs = [LegQuote(lo.ticker, lo.title, "YES", lo.yes_ask, lo.yes_ask_size),
                        LegQuote(hi.ticker, hi.title, "NO", hi.no_ask, hi.no_ask_size)]
                opp = _make(
                    "LADDER", True, ev, legs, ONE, schedule, rules,
                    f"'{lo.title}' (lower strike {lo.floor_strike}) is priced BELOW "
                    f"'{hi.title}' (higher strike {hi.floor_strike}); YES on the lower + NO on "
                    f"the higher pays at least $1 per set in every outcome.",
                    [f"Both markets are in event {ev.event_ticker} and their rules are identical "
                     "apart from the strike; confirm they settle on the SAME value and source.",
                     f"Strike {lo.floor_strike} < {hi.floor_strike} and both use "
                     f"'{stype}' (strictly comparable).",
                     "Place the THINNER leg first; if the second leg can't fill at its limit, "
                     "sell the first back rather than holding one side."])
                if opp:
                    out.append(opp)
    return out


def detect_exclusive(ev: EventBook, schedule: FeeSchedule,
                     rules: SizingRules) -> list[Opportunity]:
    if not ev.mutually_exclusive or len(ev.markets) < 2:
        return []
    ms = list(ev.markets)
    if not all(_tradable(m) for m in ms):
        return []  # an inactive outcome breaks the "buy every outcome" structure
    out: list[Opportunity] = []
    n = Decimal(len(ms))
    if all(m.no_ask is not None and m.no_ask_size > 0 for m in ms):
        if sum((m.no_ask for m in ms), Decimal(0)) < n - ONE:  # type: ignore[misc]
            legs = [LegQuote(m.ticker, m.title, "NO", m.no_ask, m.no_ask_size)  # type: ignore[arg-type]
                    for m in ms]
            opp = _make(
                "EXCL_NO", True, ev, legs, n - ONE, schedule, rules,
                f"The YES bids across all {len(ms)} mutually exclusive outcomes add up to more "
                f"than $1; buying NO on every outcome pays at least ${n - ONE} per set "
                "(at most one can resolve YES).",
                ["Kalshi marks this event mutually exclusive: confirm in the rules that at "
                 "most ONE outcome can resolve YES (no ties / co-winners / multiple YES).",
                 "Check for outcomes that could resolve at a non-binary value (e.g. voided "
                 "or split settlement).",
                 f"All {len(ms)} legs must be bought; place the thinnest first and stop if "
                 "any leg can't fill at its limit."])
            if opp:
                out.append(opp)
    # Without an explicit catch-all outcome the list is almost never exhaustive: the "gap"
    # is just the probability of the unlisted result (e.g. "no new state"). Skip those.
    if rules.require_catch_all and not excl_yes_eligible(ev, ms):
        return out
    if all(m.yes_ask is not None and m.yes_ask_size > 0 for m in ms):
        if sum((m.yes_ask for m in ms), Decimal(0)) < ONE:  # type: ignore[misc]
            legs = [LegQuote(m.ticker, m.title, "YES", m.yes_ask, m.yes_ask_size)  # type: ignore[arg-type]
                    for m in ms]
            opp = _make(
                "EXCL_YES", False, ev, legs, ONE, schedule, rules,
                f"The YES asks across all {len(ms)} outcomes add up to less than $1; buying "
                "YES on every outcome pays $1 per set IF one listed outcome must win.",
                ["CONDITIONAL: verify the list is EXHAUSTIVE. If no listed outcome could win "
                 "(an 'other' result, cancellation, or a missing candidate), every leg loses.",
                 "For games: read what happens on postponement, cancellation, or a tie.",
                 "Check whether Kalshi could add outcomes later, or settle to an unlisted one.",
                 f"All {len(ms)} legs must be bought; stop if any leg can't fill."])
            if opp:
                out.append(opp)
    return out


def scan_events(events: Sequence[EventBook], schedule: FeeSchedule,
                rules: SizingRules) -> list[Opportunity]:
    found: list[Opportunity] = []
    for ev in events:
        found.extend(detect_ladder(ev, schedule, rules))
        found.extend(detect_exclusive(ev, schedule, rules))
    return sorted(found, key=lambda o: (not o.guaranteed, -o.profit))


# --- Coverage & near misses (for transparency; not opportunities) ---------------------------


@dataclass(frozen=True)
class NearMiss:
    kind: str
    event_ticker: str
    title: str
    category: str
    raw_cost_per_set: Decimal  # before fees, at best prices
    payoff_per_set: Decimal
    gap: Decimal  # payoff - cost (positive = gap before fees; fees decide the rest)
    detail: str


def near_misses(events: Sequence[EventBook], limit: int = 15) -> list[NearMiss]:
    """Structures closest to a mispricing, BEFORE fees, so you can see what the scanner
    evaluated even when nothing qualifies."""
    out: list[NearMiss] = []
    for ev in events:
        ms = [m for m in ev.markets if _tradable(m)]
        groups: dict[str, list[TopOfBook]] = {}
        for m in ms:
            k = ladder_key(m)
            if (k and m.floor_strike is not None
                    and m.strike_type in ("greater", "greater_or_equal")):
                groups.setdefault(k, []).append(m)
        for members in groups.values():
            rungs = sorted(members, key=lambda m: m.floor_strike)  # type: ignore[arg-type,return-value]
            for lo, hi in zip(rungs, rungs[1:], strict=False):  # adjacent rungs only
                if (lo.yes_ask is not None and hi.no_ask is not None
                        and hi.floor_strike != lo.floor_strike):
                    cost = lo.yes_ask + hi.no_ask
                    out.append(NearMiss("LADDER", ev.event_ticker, ev.title, ev.category, cost,
                                        ONE, ONE - cost, f"YES {lo.title} + NO {hi.title}"))
        if ev.mutually_exclusive and len(ms) >= 2 and len(ms) == len(ev.markets):
            n = Decimal(len(ms))
            if all(m.no_ask is not None for m in ms):
                cost = sum((m.no_ask for m in ms), Decimal(0))  # type: ignore[misc]
                out.append(NearMiss("EXCL_NO", ev.event_ticker, ev.title, ev.category, cost,
                                    n - ONE, n - ONE - cost, f"NO on all {len(ms)} outcomes"))
            if all(m.yes_ask is not None for m in ms) and excl_yes_eligible(ev, ms):
                cost = sum((m.yes_ask for m in ms), Decimal(0))  # type: ignore[misc]
                out.append(NearMiss("EXCL_YES", ev.event_ticker, ev.title, ev.category, cost,
                                    ONE, ONE - cost, f"YES on all {len(ms)} outcomes"))
    best: dict[str, NearMiss] = {}  # one entry per event so a single event can't flood it
    for nm in sorted(out, key=lambda x: -x.gap):
        best.setdefault(nm.event_ticker, nm)
    return sorted(best.values(), key=lambda x: -x.gap)[:limit]


def coverage(events: Sequence[EventBook], top_series: int = 12) -> dict:
    by_cat: dict[str, list[int]] = {}
    by_series: dict[str, list[int]] = {}
    for ev in events:
        for bucket, key in ((by_cat, ev.category or "Uncategorized"), (by_series, ev.series)):
            c = bucket.setdefault(key, [0, 0])
            c[0] += 1
            c[1] += len(ev.markets)
    cats = sorted(by_cat.items(), key=lambda kv: -kv[1][1])
    series = sorted(by_series.items(), key=lambda kv: -kv[1][1])[:top_series]
    return {"categories": [{"name": k, "events": v[0], "markets": v[1]} for k, v in cats],
            "top_series": [{"name": k, "events": v[0], "markets": v[1]} for k, v in series]}
