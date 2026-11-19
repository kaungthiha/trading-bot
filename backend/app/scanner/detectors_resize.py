"""Rebuild an opportunity from freshly confirmed leg quotes (same structure, new prices)."""

from __future__ import annotations

from decimal import Decimal

from app.scanner.detectors import LegQuote, Opportunity, SizingRules, size_combo
from app.signals.fees import FeeSchedule


def payoff_per_set(opp: Opportunity) -> Decimal:
    return Decimal(len(opp.legs) - 1) if opp.kind == "EXCL_NO" else Decimal(1)


def resize(opp: Opportunity, fresh: list[LegQuote], schedule: FeeSchedule,
           rules: SizingRules) -> Opportunity | None:
    pps = payoff_per_set(opp)
    sized = size_combo(fresh, pps, schedule, rules)
    if sized is None:
        return None
    q, legs, cost, fees = sized
    min_payoff = q * pps
    profit = min_payoff - cost
    return Opportunity(opp.kind, opp.guaranteed, opp.event_ticker, opp.title, legs, q, cost,
                       fees, min_payoff, profit,
                       (profit / cost * 100).quantize(Decimal("0.01")), opp.claim,
                       opp.checklist)
