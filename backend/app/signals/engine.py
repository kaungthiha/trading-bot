"""Signal engine: (market, quote, mapping, forecast, fees) -> research signal.

Pure and deterministic. Money math in Decimal. Per $1-notional contract:

    EV_yes     = p_yes        - yes_entry - fee - slippage
    EV_no      = (1 - p_yes)  - no_entry  - fee - slippage
    lower_yes  = p_lower      - yes_entry - fee - slippage
    lower_no   = (1 - p_upper)- no_entry  - fee - slippage

Entries are depth-aware VWAPs over DERIVED asks (from the opposite side's bids) for the
configured quantity -- never last price or midpoint. A CANDIDATE requires every gate to
pass, the lower-bound edge to exceed the margin, and the edge to survive doubled fees and
slippage. Anything else is ABSTAIN with enumerated reasons. A signal is a research
hypothesis: it is never an order and never authorizes one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from app.domain.models import PriceRange
from app.domain.pricing import is_on_price_grid
from app.signals.fees import FeeSchedule, taker_buy_cost

Q6 = Decimal("0.000001")


class SignalDecision(StrEnum):
    CANDIDATE_YES = "CANDIDATE_YES"
    CANDIDATE_NO = "CANDIDATE_NO"
    ABSTAIN = "ABSTAIN"


class Reason(StrEnum):
    MARKET_NOT_OPEN = "MARKET_NOT_OPEN"
    NOT_BINARY = "NOT_BINARY"
    NO_MAPPING = "NO_MAPPING"
    MAPPING_NOT_CONFIRMED = "MAPPING_NOT_CONFIRMED"
    RULES_CHANGED = "RULES_CHANGED"
    QUOTE_MISSING = "QUOTE_MISSING"
    QUOTE_STALE = "QUOTE_STALE"
    MODEL_ABSTAINED = "MODEL_ABSTAINED"
    MODEL_NOT_VALIDATED = "MODEL_NOT_VALIDATED"
    FEE_TYPE_UNKNOWN = "FEE_TYPE_UNKNOWN"
    FEE_TYPE_UNSUPPORTED = "FEE_TYPE_UNSUPPORTED"
    FEE_MULTIPLIER_UNVERIFIED = "FEE_MULTIPLIER_UNVERIFIED"
    FEE_SCHEDULE_UNVERIFIED = "FEE_SCHEDULE_UNVERIFIED"
    NO_EXECUTABLE_ASK = "NO_EXECUTABLE_ASK"
    INSUFFICIENT_DEPTH = "INSUFFICIENT_DEPTH"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    ONE_SIDED_BOOK = "ONE_SIDED_BOOK"
    # The model uses only past CPI prints; a liquid market aggregates far more current
    # information. A large disagreement is treated as evidence the MODEL is missing
    # something, not as an opportunity.
    MODEL_MARKET_DIVERGENCE = "MODEL_MARKET_DIVERGENCE"
    PRICE_OFF_GRID = "PRICE_OFF_GRID"
    EDGE_BELOW_MARGIN = "EDGE_BELOW_MARGIN"
    EDGE_NOT_ROBUST_TO_COSTS = "EDGE_NOT_ROBUST_TO_COSTS"


CAVEATS = [
    "Research hypothesis only: not an order, not a recommendation, and nothing is executed.",
    "EV assumes the model probability is right; the model uses only past CPI prints.",
    "The quote is a snapshot; prices available at order time may differ.",
    "Taker fees are assumed (crossing the spread); balance-rounding is charged "
    "conservatively without later rebates.",
    "A large gap between model and market usually means the model lacks information the "
    "market has; such cases abstain (MODEL_MARKET_DIVERGENCE).",
]


@dataclass(frozen=True)
class Level:
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class SignalParams:
    quantity: Decimal
    slippage_per_contract: Decimal
    max_spread: Decimal
    min_edge: Decimal
    quote_max_age: timedelta
    min_holdout_events: int
    max_model_market_divergence: Decimal = Decimal("0.20")


@dataclass(frozen=True)
class SignalInputs:
    now: datetime
    market_status: str
    market_type: str | None
    close_at: datetime | None
    notional: Decimal
    price_ranges: Sequence[PriceRange]
    fee_type: str | None
    fee_multiplier: Decimal | None
    current_rules_hash: str | None
    mapping_status: str | None
    mapping_rules_hash: str | None
    quote_observed_at: datetime | None
    yes_bids: Sequence[Level]  # raw exchange bids
    no_bids: Sequence[Level]
    forecast_decision: str  # FORECAST | ABSTAIN
    forecast_reasons: Sequence[str]
    p_yes: float | None
    p_lower: float | None
    p_upper: float | None
    model_holdout_events: int | None
    model_beats_baseline: bool | None
    fee_schedule: FeeSchedule | None


@dataclass(frozen=True)
class SideEval:
    side: str
    entry: Decimal | None = None  # VWAP per contract
    fee: Decimal | None = None  # effective fee per contract
    slippage: Decimal | None = None
    ev: Decimal | None = None
    lower_edge: Decimal | None = None
    lower_edge_stressed: Decimal | None = None  # doubled fee + slippage
    filled: Decimal | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SignalResult:
    decision: SignalDecision
    side: str | None
    chosen: SideEval | None
    yes: SideEval
    no: SideEval
    reasons: list[str]
    caveats: list[str]
    expires_at: datetime
    spread_yes: Decimal | None
    model_market_divergence: Decimal | None = None


def derived_asks(opposite_bids: Sequence[Level], notional: Decimal) -> list[Level]:
    """A bid for NO at p is an offer of YES at notional - p (and vice versa)."""
    return sorted((Level(notional - b.price, b.quantity) for b in opposite_bids),
                  key=lambda lv: lv.price)


def walk_book(asks: Sequence[Level], qty: Decimal) -> list[tuple[Decimal, Decimal]] | None:
    """Fills for qty against ask levels (cheapest first); None if depth is insufficient."""
    fills, remaining = [], qty
    for lv in asks:
        take = min(remaining, lv.quantity)
        if take > 0:
            fills.append((take, lv.price))
            remaining -= take
        if remaining <= 0:
            return fills
    return None


def _d(x: float) -> Decimal:
    return Decimal(repr(x)).quantize(Q6)


def _side(side: str, prob_mid: float | None, prob_low: float | None, asks: list[Level],
          inp: SignalInputs, params: SignalParams, fees_ok: bool) -> SideEval:
    reasons: list[str] = []
    if not asks:
        return SideEval(side, reasons=[f"{Reason.NO_EXECUTABLE_ASK}:{side}"])
    fills = walk_book(asks, params.quantity)
    if fills is None:
        return SideEval(side, reasons=[f"{Reason.INSUFFICIENT_DEPTH}:{side}"])
    if any(not is_on_price_grid(p, inp.price_ranges) for _, p in fills):
        reasons.append(f"{Reason.PRICE_OFF_GRID}:{side}")
    qty = sum(c for c, _ in fills)
    vwap = (sum(c * p for c, p in fills) / qty).quantize(Q6)
    fee = None
    if fees_ok and inp.fee_schedule is not None:
        fee = (taker_buy_cost(inp.fee_schedule, fills).effective_fee / qty).quantize(Q6)
    slip = params.slippage_per_contract
    if prob_mid is None or fee is None:
        return SideEval(side, vwap, fee, slip, filled=qty, reasons=reasons)
    ev = _d(prob_mid) - vwap - fee - slip
    lower = _d(prob_low) - vwap - fee - slip if prob_low is not None else None
    stressed = (_d(prob_low) - vwap - 2 * fee - 2 * slip) if prob_low is not None else None
    return SideEval(side, vwap, fee, slip, ev, lower, stressed, qty, reasons)


def evaluate(inp: SignalInputs, params: SignalParams) -> SignalResult:
    reasons: list[str] = []
    # --- Market & rules gates ---------------------------------------------------------
    if inp.market_status != "active":
        reasons.append(Reason.MARKET_NOT_OPEN)
    if inp.market_type != "binary":
        reasons.append(Reason.NOT_BINARY)
    if inp.mapping_status is None:
        reasons.append(Reason.NO_MAPPING)
    else:
        if inp.mapping_rules_hash != inp.current_rules_hash:
            reasons.append(Reason.RULES_CHANGED)
        if inp.mapping_status != "confirmed":
            reasons.append(Reason.MAPPING_NOT_CONFIRMED)
    # --- Quote gates ------------------------------------------------------------------
    if inp.quote_observed_at is None:
        reasons.append(Reason.QUOTE_MISSING)
    else:
        age = inp.now - inp.quote_observed_at
        if age > params.quote_max_age or age < timedelta(0):
            reasons.append(Reason.QUOTE_STALE)
    # --- Model gates ------------------------------------------------------------------
    if inp.forecast_decision != "FORECAST":
        reasons.append(Reason.MODEL_ABSTAINED)
        reasons.extend(f"model:{r}" for r in inp.forecast_reasons)
    if (inp.model_holdout_events is None or inp.model_holdout_events < params.min_holdout_events
            or not inp.model_beats_baseline):
        reasons.append(Reason.MODEL_NOT_VALIDATED)
    # --- Fee gates --------------------------------------------------------------------
    fees_ok = True
    if inp.fee_type is None:
        reasons.append(Reason.FEE_TYPE_UNKNOWN)
        fees_ok = False
    elif inp.fee_schedule is None:
        reasons.append(Reason.FEE_TYPE_UNSUPPORTED)
        fees_ok = False
    else:
        if inp.fee_multiplier != Decimal(1):
            reasons.append(Reason.FEE_MULTIPLIER_UNVERIFIED)
            fees_ok = False
        if not inp.fee_schedule.verified:
            reasons.append(Reason.FEE_SCHEDULE_UNVERIFIED)  # still computed, for display

    # --- Prices & EV ------------------------------------------------------------------
    yes_asks = derived_asks(inp.no_bids, inp.notional)
    no_asks = derived_asks(inp.yes_bids, inp.notional)
    best_yes_bid = max((b.price for b in inp.yes_bids), default=None)
    spread = (yes_asks[0].price - best_yes_bid) if (yes_asks and best_yes_bid is not None) \
        else None
    if spread is not None and spread > params.max_spread:
        reasons.append(Reason.SPREAD_TOO_WIDE)
    if inp.quote_observed_at is not None and (best_yes_bid is None or not yes_asks):
        reasons.append(Reason.ONE_SIDED_BOOK)

    usable = inp.forecast_decision == "FORECAST" and inp.p_yes is not None
    divergence = None
    if usable and inp.quote_observed_at is not None:
        # Distance from the model's p to the market's [best YES bid, YES ask] interval.
        lo = best_yes_bid if best_yes_bid is not None else Decimal(0)
        hi = yes_asks[0].price if yes_asks else inp.notional
        p = _d(inp.p_yes)  # type: ignore[arg-type]
        divergence = max(lo - p, p - hi, Decimal(0))
        if divergence > params.max_model_market_divergence:
            reasons.append(Reason.MODEL_MARKET_DIVERGENCE)
    p_no = (1 - inp.p_yes) if usable else None
    p_no_low = (1 - inp.p_upper) if usable and inp.p_upper is not None else None
    yes = _side("YES", inp.p_yes if usable else None, inp.p_lower if usable else None,
                yes_asks, inp, params, fees_ok)
    no = _side("NO", p_no, p_no_low, no_asks, inp, params, fees_ok)

    candidates = [s for s in (yes, no) if s.lower_edge is not None]
    chosen = max(candidates, key=lambda s: s.lower_edge) if candidates else None  # type: ignore[arg-type,return-value]
    if chosen is None:
        # Surface why neither side could be evaluated.
        for s in (yes, no):
            reasons.extend(r for r in s.reasons if r not in reasons)
    else:
        reasons.extend(r for r in chosen.reasons if r not in reasons)
        if chosen.lower_edge <= params.min_edge:  # type: ignore[operator]
            reasons.append(Reason.EDGE_BELOW_MARGIN)
        elif chosen.lower_edge_stressed is None or chosen.lower_edge_stressed <= 0:
            reasons.append(Reason.EDGE_NOT_ROBUST_TO_COSTS)

    expires = inp.now + params.quote_max_age
    if inp.quote_observed_at is not None:
        expires = inp.quote_observed_at + params.quote_max_age
    if inp.close_at is not None:
        expires = min(expires, inp.close_at)

    reasons = list(dict.fromkeys(str(r) for r in reasons))
    if reasons or chosen is None:
        decision = SignalDecision.ABSTAIN
    else:
        decision = SignalDecision.CANDIDATE_YES if chosen.side == "YES" \
            else SignalDecision.CANDIDATE_NO
    caveats = list(CAVEATS)
    if inp.fee_schedule is not None:
        caveats.append(f"Fee schedule {inp.fee_schedule.version} "
                       f"({'verified' if inp.fee_schedule.verified else 'UNVERIFIED'}).")
    return SignalResult(decision, chosen.side if chosen else None, chosen, yes, no, reasons,
                        caveats, expires, spread, divergence)
