"""Paper broker: validate -> simulate -> persist immutable order/fills/ledger rows.

Accounting uses average cost (fees included in cost basis). Realized P&L comes only from
simulated sales and VERIFIED settlements; open positions are marked conservatively at the
price we could sell into right now (own-side bids, full taker fees, credit rounded down),
which is reported separately as unrealized.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    EvidenceRecord,
    Market,
    PaperFill,
    PaperLedgerEntry,
    PaperOrder,
    PaperSettlement,
    QuoteSnapshot,
)
from app.domain.models import PriceRange
from app.domain.pricing import is_on_price_grid
from app.paper.simulator import SCENARIOS, SIMULATION_VERSION, simulate
from app.research.cpi import CpiMomContract, build_first_prints
from app.signals.engine import Level
from app.signals.fees import (
    FeeSchedule,
    _ceil,
    load_schedules,
    select_schedule,
    taker_buy_cost,
    taker_sell_proceeds,
)
from app.signals.mapping import latest_mapping


class Reject:
    INVALID_SIDE = "INVALID_SIDE"
    INVALID_ACTION = "INVALID_ACTION"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    LIMIT_OFF_GRID = "LIMIT_OFF_GRID"
    UNKNOWN_SCENARIO = "UNKNOWN_SCENARIO"
    MARKET_NOT_OPEN = "MARKET_NOT_OPEN"
    NOT_BINARY = "NOT_BINARY"
    FEE_UNKNOWN = "FEE_UNKNOWN"
    FEE_MULTIPLIER_UNVERIFIED = "FEE_MULTIPLIER_UNVERIFIED"
    QUOTE_MISSING = "QUOTE_MISSING"
    QUOTE_STALE = "QUOTE_STALE"
    INSUFFICIENT_POSITION = "INSUFFICIENT_POSITION"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    ALREADY_SETTLED = "ALREADY_SETTLED"


@dataclass(frozen=True)
class OrderRequest:
    client_order_id: str
    market_id: str
    side: str
    action: str
    quantity: Decimal
    limit_price: Decimal
    scenario: str
    signal_id: str | None = None
    source: str = "manual"


@dataclass(frozen=True)
class SubmitResult:
    order: PaperOrder
    duplicate: bool


def cash_balance(s: Session) -> Decimal:
    rows = s.scalars(select(PaperLedgerEntry.amount)).all()
    return sum(rows, Decimal(0))


def ensure_funded(s: Session, settings: Settings, now: datetime) -> None:
    if s.scalar(select(func.count()).select_from(PaperLedgerEntry)) == 0:
        s.add(PaperLedgerEntry(at=now, kind="DEPOSIT", amount=settings.paper_starting_cash,
                               memo="Initial simulated cash (KRT_PAPER_STARTING_CASH)"))
        s.flush()


def _levels(raw: list[dict]) -> list[Level]:
    return [Level(Decimal(lv["price"]), Decimal(lv["quantity"])) for lv in raw]


def latest_quote(s: Session, market_id: str, at: datetime) -> QuoteSnapshot | None:
    return s.scalar(select(QuoteSnapshot).where(QuoteSnapshot.market_id == market_id,
                                                QuoteSnapshot.observed_at <= at)
                    .order_by(QuoteSnapshot.observed_at.desc()).limit(1))


def submit_order(s: Session, settings: Settings, req: OrderRequest, now: datetime,
                 schedules: list[FeeSchedule] | None = None) -> SubmitResult:
    existing = s.scalar(select(PaperOrder).where(
        PaperOrder.client_order_id == req.client_order_id))
    if existing is not None:
        return SubmitResult(existing, duplicate=True)  # idempotent re-submission
    ensure_funded(s, settings, now)
    schedules = schedules if schedules is not None else load_schedules()
    market = s.get(Market, req.market_id)
    if market is None:
        raise ValueError("Unknown market")

    scenario = SCENARIOS.get(req.scenario)
    ranges = [PriceRange.model_validate(r) for r in json.loads(market.price_ranges_json)]
    schedule = select_schedule(schedules, market.fee_type) if market.fee_type else None
    quote = latest_quote(s, market.id, now)
    reason: str | None = None
    if req.side not in ("YES", "NO"):
        reason = Reject.INVALID_SIDE
    elif req.action not in ("BUY", "SELL"):
        reason = Reject.INVALID_ACTION
    elif (req.quantity <= 0 or req.quantity != req.quantity.to_integral_value()
          or req.quantity > settings.paper_max_order_quantity):
        reason = Reject.INVALID_QUANTITY
    elif scenario is None:
        reason = Reject.UNKNOWN_SCENARIO
    elif not (Decimal(0) < req.limit_price < market.notional_value) or not is_on_price_grid(
            req.limit_price, ranges):
        reason = Reject.LIMIT_OFF_GRID
    elif s.scalar(select(PaperSettlement.id).where(PaperSettlement.market_id == market.id)):
        reason = Reject.ALREADY_SETTLED
    elif market.status != "active":
        reason = Reject.MARKET_NOT_OPEN
    elif market.market_type != "binary":
        reason = Reject.NOT_BINARY
    elif schedule is None:
        reason = Reject.FEE_UNKNOWN
    elif market.fee_multiplier != Decimal(1):
        reason = Reject.FEE_MULTIPLIER_UNVERIFIED
    elif quote is None:
        reason = Reject.QUOTE_MISSING
    elif now - quote.observed_at > timedelta(seconds=settings.quote_max_age_seconds):
        reason = Reject.QUOTE_STALE
    elif req.action == "SELL":
        held = positions(s).get((market.id, req.side))
        if held is None or held.open_qty < req.quantity:
            reason = Reject.INSUFFICIENT_POSITION

    def record(status: str, filled: Decimal, rej: str | None) -> PaperOrder:
        o = PaperOrder(
            client_order_id=req.client_order_id, submitted_at=now, market_id=market.id,
            signal_id=req.signal_id, quote_id=quote.id if quote else None, side=req.side,
            action=req.action, quantity=req.quantity, limit_price=req.limit_price,
            status=status, filled_quantity=filled, reject_reason=rej,
            scenario=req.scenario, simulation_version=SIMULATION_VERSION,
            fee_schedule_version=schedule.version if schedule else None,
            fee_schedule_verified=bool(schedule and schedule.verified), source=req.source,
        )
        s.add(o)
        s.flush()
        return o

    if reason is not None:
        return SubmitResult(record("REJECTED", Decimal(0), reason), duplicate=False)

    depth = json.loads(quote.depth_json)  # type: ignore[union-attr]
    fills = simulate(action=req.action, side=req.side, quantity=req.quantity,
                     limit_price=req.limit_price, yes_bids=_levels(depth.get("yes_bids", [])),
                     no_bids=_levels(depth.get("no_bids", [])), notional=market.notional_value,
                     price_ranges=ranges, scenario=scenario)  # type: ignore[arg-type]
    if not fills:
        return SubmitResult(record("CANCELLED", Decimal(0), None), duplicate=False)

    pairs = [(f.quantity, f.price) for f in fills]
    if req.action == "BUY":
        cost = taker_buy_cost(schedule, pairs)  # type: ignore[arg-type]
        if cost.total_debit > cash_balance(s):
            return SubmitResult(record("REJECTED", Decimal(0), Reject.INSUFFICIENT_CASH), False)
        amount = -cost.total_debit
    else:
        amount = taker_sell_proceeds(schedule, pairs).net_credit  # type: ignore[arg-type]

    filled = sum((f.quantity for f in fills), Decimal(0))
    order = record("FILLED" if filled == req.quantity else "PARTIAL", filled, None)
    for f in fills:
        s.add(PaperFill(
            paper_order_id=order.id, quantity=f.quantity, price=f.price,
            displayed_price=f.displayed_price, filled_at=now,
            fee=_ceil(schedule.taker_rate * f.quantity * f.price * (1 - f.price),  # type: ignore[union-attr]
                      schedule.trade_fee_rounding_step),  # type: ignore[union-attr]
            assumption_code=scenario.code,  # type: ignore[union-attr]
        ))
    s.add(PaperLedgerEntry(at=now, kind=req.action, amount=amount, market_id=market.id,
                           paper_order_id=order.id,
                           memo=f"{req.action} {filled} {req.side} @ sim ({scenario.code})"))  # type: ignore[union-attr]
    s.flush()
    return SubmitResult(order, duplicate=False)


# --- Positions & P&L ---------------------------------------------------------------------


@dataclass
class Position:
    market_id: str
    side: str
    bought_qty: Decimal = Decimal(0)
    cost: Decimal = Decimal(0)  # total cash paid incl. fees
    sold_qty: Decimal = Decimal(0)
    proceeds: Decimal = Decimal(0)
    settled: bool = False
    settlement_payout: Decimal = Decimal(0)
    held: bool = False

    @property
    def avg_cost(self) -> Decimal:
        return self.cost / self.bought_qty if self.bought_qty else Decimal(0)

    @property
    def open_qty(self) -> Decimal:
        return Decimal(0) if self.settled else self.bought_qty - self.sold_qty

    @property
    def realized(self) -> Decimal:
        r = self.proceeds - self.avg_cost * self.sold_qty
        if self.settled:
            r += self.settlement_payout - self.avg_cost * (self.bought_qty - self.sold_qty)
        return r


def positions(s: Session) -> dict[tuple[str, str], Position]:
    out: dict[tuple[str, str], Position] = {}
    rows = s.execute(
        select(PaperOrder, PaperLedgerEntry.amount)
        .join(PaperLedgerEntry, PaperLedgerEntry.paper_order_id == PaperOrder.id)
        .where(PaperOrder.status.in_(("FILLED", "PARTIAL")))
    ).all()
    for o, amount in rows:
        p = out.setdefault((o.market_id, o.side), Position(o.market_id, o.side))
        if o.action == "BUY":
            p.bought_qty += o.filled_quantity
            p.cost += -amount
        else:
            p.sold_qty += o.filled_quantity
            p.proceeds += amount
    payouts: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for e in s.scalars(select(PaperLedgerEntry).where(
            PaperLedgerEntry.kind == "SETTLEMENT_PAYOUT")).all():
        side = e.memo.split(" ", 1)[0]  # memo begins with the side
        payouts[(e.market_id, side)] += e.amount  # type: ignore[index]
    for st in s.scalars(select(PaperSettlement)).all():
        for side in ("YES", "NO"):
            p = out.get((st.market_id, side))
            if p is None:
                continue
            if st.status == "SETTLED":
                p.settled = True
                p.settlement_payout = payouts.get((st.market_id, side), Decimal(0))
            else:
                p.held = True
    return out


@dataclass(frozen=True)
class Mark:
    value: Decimal  # conservative liquidation value of the open quantity
    marked_qty: Decimal  # quantity that the current book could absorb
    quote_observed_at: datetime | None
    note: str | None


def mark_position(s: Session, p: Position, now: datetime,
                  schedules: list[FeeSchedule]) -> Mark:
    market = s.get(Market, p.market_id)
    q = latest_quote(s, p.market_id, now)
    if q is None or market is None or p.open_qty <= 0:
        return Mark(Decimal(0), Decimal(0), None, "no quote" if q is None else None)
    schedule = select_schedule(schedules, market.fee_type) if market.fee_type else None
    depth = json.loads(q.depth_json)
    ranges = [PriceRange.model_validate(r) for r in json.loads(market.price_ranges_json)]
    min_px = min((r.start for r in ranges), default=Decimal("0.01"))
    fills = simulate(action="SELL", side=p.side, quantity=p.open_qty,
                     limit_price=max(min_px, Decimal("0.0001")),
                     yes_bids=_levels(depth.get("yes_bids", [])),
                     no_bids=_levels(depth.get("no_bids", [])), notional=market.notional_value,
                     price_ranges=ranges, scenario=SCENARIOS["baseline"])
    if not fills or schedule is None:
        return Mark(Decimal(0), Decimal(0), q.observed_at,
                    "no bids to sell into: marked at 0" if not fills else "fee unknown")
    qty = sum((f.quantity for f in fills), Decimal(0))
    value = taker_sell_proceeds(schedule, [(f.quantity, f.price) for f in fills]).net_credit
    note = None if qty == p.open_qty else f"book absorbs {qty} of {p.open_qty}; rest marked 0"
    return Mark(value, qty, q.observed_at, note)


@dataclass
class AccountSummary:
    cash: Decimal
    deposits: Decimal
    open_value: Decimal
    equity: Decimal
    realized: Decimal
    unrealized: Decimal
    fee_schedule_verified: bool
    notes: list[str] = field(default_factory=list)


def account_summary(s: Session, now: datetime,
                    schedules: list[FeeSchedule] | None = None) -> tuple[AccountSummary, list]:
    schedules = schedules if schedules is not None else load_schedules()
    cash = cash_balance(s)
    deposits = sum(s.scalars(select(PaperLedgerEntry.amount).where(
        PaperLedgerEntry.kind == "DEPOSIT")).all(), Decimal(0))
    rows = []
    open_value = realized = unrealized = Decimal(0)
    for p in positions(s).values():
        mk = mark_position(s, p, now, schedules)
        unr = (mk.value - p.avg_cost * p.open_qty) if p.open_qty > 0 else Decimal(0)
        open_value += mk.value if p.open_qty > 0 else Decimal(0)
        realized += p.realized
        unrealized += unr
        rows.append((p, mk, unr))
    used = s.scalars(select(PaperOrder.fee_schedule_verified).where(
        PaperOrder.status.in_(("FILLED", "PARTIAL")))).all()
    verified = all(used)  # vacuously true with no fills
    notes = [] if verified else ["Some fills used an UNVERIFIED fee schedule; P&L may be "
                                 "misstated."]
    return AccountSummary(cash, deposits, open_value, cash + open_value, realized, unrealized,
                          verified, notes), rows


# --- Settlement ----------------------------------------------------------------------------


def _evidence_check(s: Session, market: Market) -> tuple[str, str | None]:
    """Independent check of a CPI market's outcome from our own vintage evidence."""
    mp = latest_mapping(s, market.id)
    if mp is None or mp.contract_type != "CPI_MOM_SA_FIRST" or not mp.reference_month:
        return "unavailable", "No confirmed contract mapping to check against"
    contract = CpiMomContract(date.fromisoformat(mp.reference_month), mp.threshold)  # type: ignore[arg-type]
    rows = s.scalars(select(EvidenceRecord).where(
        EvidenceRecord.source_id == "fred:CPIAUCSL")).all()
    fp = next((p for p in build_first_prints(rows).prints
               if p.month == contract.reference_month), None)
    if fp is None:
        return "unavailable", "First print not in stored evidence yet"
    ours = "yes" if contract.resolves_yes(fp.mom_rounded) else "no"
    return ours, f"Our first print {fp.mom_rounded}% vs threshold {contract.threshold}%"


def settle(s: Session, now: datetime) -> list[PaperSettlement]:
    """Settle markets with open paper positions whose exchange result is FINALIZED.
    determined/disputed/amended are not final -> wait. Our evidence disagreeing -> HELD."""
    created = []
    open_markets = {p.market_id for p in positions(s).values()
                    if p.open_qty > 0 and not p.held}
    for mid in sorted(open_markets):
        if s.scalar(select(PaperSettlement.id).where(PaperSettlement.market_id == mid)):
            continue
        market = s.get(Market, mid)
        if market is None or market.status != "finalized" or market.result is None:
            continue
        notes: list[str] = []
        ours, why = _evidence_check(s, market)
        if why:
            notes.append(why)
        if market.result not in ("yes", "no"):
            check, status = "unavailable", "HELD"
            notes.append(f"Unsupported result {market.result!r}")
        elif ours == "unavailable":
            check, status = "unavailable", "SETTLED"
            notes.append("Settled on the finalized exchange result without independent check")
        elif ours == market.result:
            check, status = "agree", "SETTLED"
        else:
            check, status = "disagree", "HELD"
            notes.append("Exchange result contradicts our evidence: HELD for human review")
        st = PaperSettlement(created_at=now, market_id=mid, exchange_status=market.status,
                             exchange_result=market.result, evidence_check=check,
                             status=status, notes_json=json.dumps(notes))
        s.add(st)
        s.flush()
        if status == "SETTLED":
            winner = "YES" if market.result == "yes" else "NO"
            for (pm, side), p in positions(s).items():
                if pm != mid or side != winner:
                    continue
                qty = p.bought_qty - p.sold_qty
                if qty > 0:
                    s.add(PaperLedgerEntry(
                        at=now, kind="SETTLEMENT_PAYOUT", amount=qty * market.notional_value,
                        market_id=mid, settlement_id=st.id,
                        memo=f"{side} payout {qty} x {market.notional_value}"))
            s.flush()
        created.append(st)
    return created
