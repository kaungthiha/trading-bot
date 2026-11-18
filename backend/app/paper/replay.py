"""Point-in-time strategy replay of stored research signals (no persistence).

For each stored CANDIDATE signal, in creation order: simulate an IOC BUY of the signal's
side at the signal's quantity, limited at entry + one slippage allowance, against the SAME
quote snapshot the signal used (never a later one). Outcomes count only for markets the
exchange has FINALIZED; others are marked at the latest quote at or before ``as_of``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Market, QuoteSnapshot, Signal
from app.domain.models import PriceRange
from app.domain.pricing import is_on_price_grid
from app.paper.simulator import Scenario, simulate
from app.research.metrics import brier
from app.signals.engine import Level
from app.signals.fees import FeeSchedule, select_schedule, taker_buy_cost


@dataclass
class ReplayTrade:
    signal_id: str
    market_ticker: str
    side: str
    requested: Decimal
    filled: Decimal
    avg_price: Decimal | None
    cost: Decimal
    status: str  # FILLED | PARTIAL | CANCELLED | SKIPPED
    outcome: str | None  # yes | no | None (unresolved)
    payout: Decimal
    p_side: float | None
    note: str | None = None


@dataclass
class ReplayReport:
    as_of: datetime
    scenario: str
    trades: list[ReplayTrade] = field(default_factory=list)
    n_signals: int = 0
    total_cost: Decimal = Decimal(0)
    realized_pnl: Decimal = Decimal(0)  # resolved trades only
    unresolved_cost: Decimal = Decimal(0)
    resolved_brier: float | None = None
    n_resolved: int = 0


def _levels(raw: list[dict]) -> list[Level]:
    return [Level(Decimal(lv["price"]), Decimal(lv["quantity"])) for lv in raw]


def replay(s: Session, scenario: Scenario, as_of: datetime,
           schedules: list[FeeSchedule]) -> ReplayReport:
    rep = ReplayReport(as_of=as_of, scenario=scenario.name)
    sigs = s.scalars(select(Signal).where(Signal.decision != "ABSTAIN",
                                          Signal.created_at <= as_of)
                     .order_by(Signal.created_at)).all()
    rep.n_signals = len(sigs)
    ps, ys = [], []
    for g in sigs:
        m = s.get(Market, g.market_id)
        q = s.get(QuoteSnapshot, g.quote_id) if g.quote_id else None
        side = "YES" if g.decision == "CANDIDATE_YES" else "NO"
        p_side = (g.p_yes if side == "YES" else 1 - g.p_yes) if g.p_yes is not None else None

        schedule = select_schedule(schedules, m.fee_type) if m.fee_type else None
        if q is None or g.entry is None or g.quantity is None or schedule is None:
            rep.trades.append(ReplayTrade(
                g.id, m.external_ticker, side, g.quantity or Decimal(0), Decimal(0), None,
                Decimal(0), "SKIPPED", None, Decimal(0), p_side,
                "missing quote, entry, quantity or fee schedule"))
            continue
        ranges = [PriceRange.model_validate(r) for r in json.loads(m.price_ranges_json)]
        limit = g.entry + (g.slippage or Decimal(0))
        # Snap the limit DOWN onto the grid so we never pay more than entry + slippage.
        while limit > 0 and not is_on_price_grid(limit, ranges):
            limit -= Decimal("0.0001")
        depth = json.loads(q.depth_json)
        fills = simulate(action="BUY", side=side, quantity=g.quantity, limit_price=limit,
                         yes_bids=_levels(depth.get("yes_bids", [])),
                         no_bids=_levels(depth.get("no_bids", [])), notional=m.notional_value,
                         price_ranges=ranges, scenario=scenario)
        if not fills:
            rep.trades.append(ReplayTrade(g.id, m.external_ticker, side, g.quantity, Decimal(0),
                                          None, Decimal(0), "CANCELLED", None, Decimal(0),
                                          p_side))
            continue
        qty = sum((f.quantity for f in fills), Decimal(0))
        cost = taker_buy_cost(schedule, [(f.quantity, f.price) for f in fills]).total_debit
        avg = sum((f.quantity * f.price for f in fills), Decimal(0)) / qty
        outcome = m.result if (m.status == "finalized" and m.result in ("yes", "no")) else None
        payout = Decimal(0)
        if outcome is not None:
            won = (outcome == "yes") == (side == "YES")
            payout = qty * m.notional_value if won else Decimal(0)
            rep.realized_pnl += payout - cost
            rep.n_resolved += 1
            if p_side is not None:
                ps.append(p_side)
                ys.append(int(won))
        else:
            rep.unresolved_cost += cost
        rep.total_cost += cost
        rep.trades.append(ReplayTrade(g.id, m.external_ticker, side, g.quantity, qty,
                                      avg.quantize(Decimal("0.000001")), cost,
                                      "FILLED" if qty == g.quantity else "PARTIAL", outcome,
                                      payout, p_side))
    rep.resolved_brier = brier(ps, ys) if ps else None
    return rep
