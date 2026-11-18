"""Pure, deterministic fill simulation for paper orders.

Model (simulation_version "paper-sim-v1"): an immediate-or-cancel LIMIT order is matched
against ONE stored orderbook snapshot (the latest at or before submission, which must be
fresh). Scenario knobs make fills conservative:

  depth_fraction  share of displayed size we assume we can take at each level, modelling
                  queue position and competing traders (floor to whole contracts);
  latency_ticks   each fill is priced this many grid steps WORSE than displayed, modelling
                  the book moving between snapshot and arrival.

Never fills at midpoint, never beyond (scaled) displayed depth, never through the limit.
Unfilled quantity is cancelled -- it is never treated as purchased.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from app.domain.models import PriceRange
from app.domain.pricing import is_on_price_grid
from app.signals.engine import Level

SIMULATION_VERSION = "paper-sim-v1"


@dataclass(frozen=True)
class Scenario:
    name: str
    depth_fraction: Decimal
    latency_ticks: int

    @property
    def code(self) -> str:
        return f"IOC_DEPTH{int(self.depth_fraction * 100)}_TICK{self.latency_ticks}"


SCENARIOS: dict[str, Scenario] = {
    "conservative": Scenario("conservative", Decimal("0.5"), 1),
    "baseline": Scenario("baseline", Decimal("1"), 0),
    "harsh": Scenario("harsh", Decimal("0.25"), 2),
}


@dataclass(frozen=True)
class SimFill:
    quantity: Decimal
    price: Decimal  # price we assume we paid/received (after latency penalty)
    displayed_price: Decimal  # price shown in the snapshot


def step_at(price: Decimal, ranges: Sequence[PriceRange]) -> Decimal | None:
    for r in ranges:
        if r.start <= price <= r.end:
            return r.step
    return None


def simulate(
    *,
    action: str,
    side: str,
    quantity: Decimal,
    limit_price: Decimal,
    yes_bids: Sequence[Level],
    no_bids: Sequence[Level],
    notional: Decimal,
    price_ranges: Sequence[PriceRange],
    scenario: Scenario,
) -> list[SimFill]:
    """Return fills (possibly empty). Caller validates inputs/grid before calling."""
    if action == "BUY":
        # Buying `side` lifts derived asks = notional - opposite-side bids, cheapest first.
        opposite = no_bids if side == "YES" else yes_bids
        levels = sorted((Level(notional - b.price, b.quantity) for b in opposite),
                        key=lambda lv: lv.price)
        sign = Decimal(1)
    else:
        # Selling `side` hits that side's own bids, best (highest) first.
        own = yes_bids if side == "YES" else no_bids
        levels = sorted(own, key=lambda lv: lv.price, reverse=True)
        sign = Decimal(-1)

    fills: list[SimFill] = []
    remaining = quantity
    for lv in levels:
        if remaining <= 0:
            break
        step = step_at(lv.price, price_ranges)
        if step is None:
            continue  # level outside the market's grid: ignore rather than guess
        px = lv.price + sign * step * scenario.latency_ticks
        if not (Decimal(0) < px < notional) or not is_on_price_grid(px, price_ranges):
            continue
        if (action == "BUY" and px > limit_price) or (action == "SELL" and px < limit_price):
            break  # levels are ordered; nothing further can satisfy the limit
        available = (lv.quantity * scenario.depth_fraction).to_integral_value(
            rounding=ROUND_FLOOR)
        take = min(remaining, available)
        if take > 0:
            fills.append(SimFill(take, px, lv.price))
            remaining -= take
    return fills
