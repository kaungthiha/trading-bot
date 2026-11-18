"""Versioned exchange fee model (Decimal throughout).

Cost of BUYING C contracts at price P as a taker (conservative assumption: we cross the
spread, so taker fees apply):

    model_fee   = taker_rate * C * P * (1 - P)                    (per fill)
    trade_fee   = ceil(model_fee, trade_fee_rounding_step)         (docs: fee_rounding)
    total_debit = ceil(sum(C_i * P_i) + sum(trade_fee_i), balance_precision)

The last step models the exchange's balance-precision "rounding fee" for non-direct
members conservatively (ignores later rebates from the per-order accumulator), so the
effective fee can only be overstated, never understated.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

DEFAULT_FILE = Path(__file__).parent / "fee_schedules.json"


@dataclass(frozen=True)
class FeeSchedule:
    version: str
    fee_types: tuple[str, ...]
    taker_rate: Decimal
    maker_multiplier: dict[str, Decimal]
    trade_fee_rounding_step: Decimal
    balance_precision: Decimal
    source_url: str
    verified: bool
    verified_by: str | None
    verified_at: str | None
    provenance: dict = field(default_factory=dict)


def load_schedules(path: Path = DEFAULT_FILE) -> list[FeeSchedule]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = []
    seen: set[str] = set()
    for s in raw["schedules"]:
        if s["version"] in seen:
            raise ValueError(f"Duplicate fee schedule version {s['version']!r}")
        seen.add(s["version"])
        sched = FeeSchedule(
            version=s["version"],
            fee_types=tuple(s["fee_types"]),
            taker_rate=Decimal(s["taker_rate"]),
            maker_multiplier={k: Decimal(v) for k, v in s.get("maker_multiplier", {}).items()},
            trade_fee_rounding_step=Decimal(s["trade_fee_rounding_step"]),
            balance_precision=Decimal(s["balance_precision"]),
            source_url=s["source_url"],
            verified=bool(s.get("verified")),
            verified_by=s.get("verified_by"),
            verified_at=s.get("verified_at"),
            provenance=s.get("provenance", {}),
        )
        if sched.verified and not (sched.verified_by and sched.verified_at):
            raise ValueError(f"{sched.version}: verified=true requires verified_by/verified_at")
        if not (Decimal(0) <= sched.taker_rate < 1):
            raise ValueError(f"{sched.version}: taker_rate out of range")
        out.append(sched)
    return out


def select_schedule(schedules: Sequence[FeeSchedule], fee_type: str) -> FeeSchedule | None:
    """Prefer the last VERIFIED schedule covering fee_type; else the last candidate."""
    covering = [s for s in schedules if fee_type in s.fee_types]
    verified = [s for s in covering if s.verified]
    if verified:
        return verified[-1]
    return covering[-1] if covering else None


def _ceil(x: Decimal, step: Decimal) -> Decimal:
    return (x / step).to_integral_value(rounding=ROUND_CEILING) * step


@dataclass(frozen=True)
class FillCost:
    notional: Decimal  # sum C_i * P_i
    trade_fees: Decimal  # sum of per-fill rounded model fees
    total_debit: Decimal  # after balance-precision rounding
    effective_fee: Decimal  # total_debit - notional


def taker_buy_cost(schedule: FeeSchedule, fills: Sequence[tuple[Decimal, Decimal]]) -> FillCost:
    """fills: [(contracts, price)] at the levels actually crossed."""
    if not fills:
        raise ValueError("no fills")
    notional = Decimal(0)
    fees = Decimal(0)
    for c, p in fills:
        if c <= 0 or not (Decimal(0) <= p <= Decimal(1)):
            raise ValueError(f"invalid fill ({c}, {p})")
        notional += c * p
        fees += _ceil(schedule.taker_rate * c * p * (1 - p), schedule.trade_fee_rounding_step)
    total = _ceil(notional + fees, schedule.balance_precision)
    return FillCost(notional, fees, total, total - notional)
