"""Approval-gated execution service (milestone 09). Mock / Kalshi-demo only.

Flow (each step persisted before the next):
  1. create_intent   -> exact exchange payload + SHA-256 fixed; caps, fees, quote checked
  2. approve_and_submit(payload_hash, PIN)
       PIN (scrypt, lockout) -> hash must match -> single-use, unexpired
       -> PROPOSED->APPROVED (conditional UPDATE + unique approval row)
       -> PREFLIGHT against the gateway: kill switch, env, market status, rules hash,
          fresh executable ask (any worsening blocks), caps, balance, fee schedule
       -> APPROVED->SUBMITTING committed BEFORE sending
       -> create_order exactly once
            accepted  -> FILLED / PARTIAL / NOT_FILLED
            definite  -> REJECTED
            unknown   -> UNKNOWN, then a read-only lookup by client_order_id;
                         NEVER resubmitted
  3. reconcile (UNKNOWN only) -> read-only lookup
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    ExchangeOrder,
    ExecutionApproval,
    ExecutionControl,
    ExecutionEvent,
    ExecutionIntent,
    Market,
    QuoteSnapshot,
)
from app.domain.models import PriceRange
from app.domain.pricing import is_on_price_grid
from app.execution.gateway import (
    DefinitiveReject,
    ExecutionGateway,
    GatewayError,
    UnknownOutcome,
    rules_hash_from_market,
)
from app.signals.fees import FeeSchedule, load_schedules, select_schedule, taker_buy_cost
from app.signals.mapping import current_rules

PIN_MAX_FAILURES = 5
PIN_LOCKOUT = timedelta(minutes=15)
COMMITTED = ("APPROVED", "SUBMITTING", "FILLED", "PARTIAL", "UNKNOWN")


class ExecutionError(Exception):
    def __init__(self, code: str, message: str = "", status: int = 409) -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code, self.message, self.status = code, message or code, status


# --- PIN ---------------------------------------------------------------------------------


def hash_pin(pin: str) -> str:
    if len(pin) < 6:
        raise ValueError("PIN must be at least 6 characters")
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pin.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + base64.b64encode(salt).decode() + "$" + \
        base64.b64encode(dk).decode()


def verify_pin(pin: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(pin.encode(), salt=base64.b64decode(salt_b64), n=int(n), r=int(r),
                            p=int(p), dklen=32)
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except (ValueError, TypeError):
        return False


# --- Kill switch & events ------------------------------------------------------------------


def _event(s: Session, now: datetime, kind: str, intent_id: str | None = None,
           **detail: object) -> None:
    s.add(ExecutionEvent(at=now, intent_id=intent_id, kind=kind,
                         detail_json=json.dumps(detail, default=str)))
    s.flush()


def kill_switch_engaged(s: Session) -> bool:
    last = s.scalar(select(ExecutionControl.action)
                    .order_by(ExecutionControl.at.desc()).limit(1))
    return last != "RELEASE"  # no rows -> engaged (fail closed)


def set_kill_switch(s: Session, now: datetime, engage: bool, actor: str, reason: str) -> None:
    s.add(ExecutionControl(at=now, action="ENGAGE" if engage else "RELEASE", actor=actor,
                           reason=reason))
    _event(s, now, "KILL_SWITCH_ENGAGED" if engage else "KILL_SWITCH_RELEASED",
           actor=actor, reason=reason)


# --- Payload -------------------------------------------------------------------------------


def build_payload(ticker: str, side: str, quantity: Decimal, limit_price: Decimal,
                  client_order_id: str) -> dict:
    """Kalshi CreateOrderV2 quotes the YES leg only: buying YES at p = bid at p;
    buying NO at p = ask (sell YES) at 1 - p."""
    yes_price = limit_price if side == "YES" else Decimal(1) - limit_price
    return {
        "ticker": ticker,
        "client_order_id": client_order_id,
        "side": "bid" if side == "YES" else "ask",
        "count": f"{quantity:.2f}",
        "price": f"{yes_price:.4f}",
        "time_in_force": "immediate_or_cancel",
        "self_trade_prevention_type": "taker_at_cross",
        "reduce_only": False,
    }


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def executable_ask(book: dict, side: str) -> Decimal | None:
    """Best price to BUY `side`, derived from the opposite side's best bid."""
    levels = book.get("orderbook_fp", book)
    opposite = levels.get("no_dollars" if side == "YES" else "yes_dollars") or []
    bids = [Decimal(str(p)) for p, c in opposite if Decimal(str(c)) > 0]
    return (Decimal(1) - max(bids)) if bids else None


def _local_book(depth_json: str) -> dict:
    d = json.loads(depth_json)
    return {"yes_dollars": [[lv["price"], lv["quantity"]] for lv in d.get("yes_bids", [])],
            "no_dollars": [[lv["price"], lv["quantity"]] for lv in d.get("no_bids", [])]}


# --- Caps ----------------------------------------------------------------------------------


def _day_start(now: datetime) -> datetime:
    return datetime(now.year, now.month, now.day, tzinfo=UTC)


def committed_cost_today(s: Session, now: datetime, exclude_id: str | None = None) -> Decimal:
    rows = s.scalars(select(ExecutionIntent).where(
        ExecutionIntent.created_at >= _day_start(now),
        ExecutionIntent.status.in_(COMMITTED))).all()
    return sum((r.max_cost for r in rows if r.id != exclude_id), Decimal(0))


def held_contracts(s: Session, market_id: str, side: str) -> Decimal:
    rows = s.execute(select(ExchangeOrder.fill_count).join(
        ExecutionIntent, ExecutionIntent.id == ExchangeOrder.intent_id).where(
        ExecutionIntent.market_id == market_id, ExecutionIntent.side == side)).scalars().all()
    pending = s.scalars(select(ExecutionIntent.quantity).where(
        ExecutionIntent.market_id == market_id, ExecutionIntent.side == side,
        ExecutionIntent.status.in_(("SUBMITTING", "UNKNOWN")))).all()
    # Unknown outcomes count as fully filled (conservative).
    return sum(rows, Decimal(0)) + sum(pending, Decimal(0))


def _check_caps(s: Session, settings: Settings, market_id: str, side: str, qty: Decimal,
                max_cost: Decimal, now: datetime, exclude_id: str | None = None) -> str | None:
    if qty > settings.execution_max_contracts_per_order:
        return "CAP_CONTRACTS_PER_ORDER"
    if max_cost > settings.execution_max_cost_per_order:
        return "CAP_COST_PER_ORDER"
    if held_contracts(s, market_id, side) + qty > settings.execution_max_position_contracts:
        return "CAP_POSITION"
    if committed_cost_today(s, now, exclude_id) + max_cost > settings.execution_max_daily_cost:
        return "CAP_DAILY_COST"
    return None


# --- Intents -------------------------------------------------------------------------------


@dataclass(frozen=True)
class IntentRequest:
    market_id: str
    side: str
    quantity: Decimal
    limit_price: Decimal
    signal_id: str | None = None


def _verified_schedule(market: Market, schedules: list[FeeSchedule]) -> FeeSchedule:
    sched = select_schedule(schedules, market.fee_type) if market.fee_type else None
    if sched is None or not sched.verified:
        raise ExecutionError("FEES_UNVERIFIED", "No verified fee schedule for this market")
    if market.fee_multiplier != Decimal(1):
        raise ExecutionError("FEE_MULTIPLIER_UNSUPPORTED")
    return sched


def create_intent(s: Session, settings: Settings, req: IntentRequest, now: datetime,
                  schedules: list[FeeSchedule] | None = None) -> ExecutionIntent:
    if not settings.execution_enabled:
        raise ExecutionError("EXECUTION_DISABLED", "Set KRT_EXECUTION_ENABLED=true (mock/demo)")
    if kill_switch_engaged(s):
        raise ExecutionError("KILL_SWITCH_ENGAGED", "Release it with the CLI first")
    schedules = schedules if schedules is not None else load_schedules()
    market = s.get(Market, req.market_id)
    if market is None:
        raise ExecutionError("MARKET_NOT_FOUND", status=404)
    if req.side not in ("YES", "NO"):
        raise ExecutionError("INVALID_SIDE", status=422)
    if req.quantity <= 0 or req.quantity != req.quantity.to_integral_value():
        raise ExecutionError("INVALID_QUANTITY", status=422)
    ranges = [PriceRange.model_validate(r) for r in json.loads(market.price_ranges_json)]
    if not (Decimal(0) < req.limit_price < Decimal(1)) or not is_on_price_grid(req.limit_price,
                                                                               ranges):
        raise ExecutionError("LIMIT_OFF_GRID", status=422)
    if market.status != "active" or market.market_type != "binary":
        raise ExecutionError("MARKET_NOT_TRADABLE")
    if settings.execution_env.value == "demo" and market.is_mock:
        raise ExecutionError("MOCK_MARKET_IN_DEMO", "Ingest markets with --demo for demo trading")
    sched = _verified_schedule(market, schedules)
    rules = current_rules(s, market.id)
    if rules is None:
        raise ExecutionError("RULES_MISSING")
    quote = s.scalar(select(QuoteSnapshot).where(QuoteSnapshot.market_id == market.id)
                     .order_by(QuoteSnapshot.observed_at.desc()).limit(1))
    if quote is None or now - quote.observed_at > timedelta(
            seconds=settings.execution_quote_max_age_seconds):
        raise ExecutionError("QUOTE_STALE", "Refresh market data, then propose again")
    ask = executable_ask(_local_book(quote.depth_json), req.side)
    if ask is None:
        raise ExecutionError("NO_EXECUTABLE_ASK")
    cost = taker_buy_cost(sched, [(req.quantity, req.limit_price)])
    reason = _check_caps(s, settings, market.id, req.side, req.quantity, cost.total_debit, now)
    if reason:
        raise ExecutionError(reason)

    coid = f"krt-{uuid.uuid4().hex}"
    payload = build_payload(market.external_ticker, req.side, req.quantity, req.limit_price,
                            coid)
    intent = ExecutionIntent(
        created_at=now, expires_at=now + timedelta(seconds=settings.execution_intent_ttl_seconds),
        env=settings.execution_env.value, market_id=market.id, signal_id=req.signal_id,
        quote_id=quote.id, side=req.side, quantity=req.quantity, limit_price=req.limit_price,
        approved_ask=ask, est_fee=cost.effective_fee, max_cost=cost.total_debit,
        fee_schedule_version=sched.version, rules_hash=rules.hash, client_order_id=coid,
        payload_json=json.dumps(payload, sort_keys=True), payload_hash=payload_hash(payload),
        status="PROPOSED",
    )
    s.add(intent)
    s.flush()
    _event(s, now, "INTENT_CREATED", intent.id, summary=summary(intent, market),
           payload_hash=intent.payload_hash)
    return intent


def summary(i: ExecutionIntent, m: Market) -> str:
    return (f"BUY {i.quantity} {i.side} {m.external_ticker} at limit ${i.limit_price} "
            f"(max cost ${i.max_cost} incl. est. fee ${i.est_fee}) [{i.env.upper()}]")


def _transition(s: Session, intent_id: str, old: str, new: str) -> bool:
    res = s.execute(update(ExecutionIntent).where(
        ExecutionIntent.id == intent_id, ExecutionIntent.status == old).values(status=new))
    return res.rowcount == 1


def _block(s: Session, i: ExecutionIntent, now: datetime, reason: str, **detail: object) -> None:
    s.execute(update(ExecutionIntent).where(ExecutionIntent.id == i.id)
              .values(status="BLOCKED", block_reason=reason))
    _event(s, now, "PREFLIGHT_BLOCKED", i.id, reason=reason, **detail)
    s.commit()
    s.refresh(i)


def _pin_locked(s: Session, now: datetime) -> bool:
    n = s.scalar(select(func.count()).select_from(ExecutionEvent).where(
        ExecutionEvent.kind == "PIN_FAILED", ExecutionEvent.at >= now - PIN_LOCKOUT))
    return n >= PIN_MAX_FAILURES


def approve_and_submit(s: Session, settings: Settings, intent_id: str, quoted_hash: str,
                       pin: str, gateway: ExecutionGateway, now: datetime,
                       schedules: list[FeeSchedule] | None = None) -> ExecutionIntent:
    intent = s.get(ExecutionIntent, intent_id)
    if intent is None:
        raise ExecutionError("INTENT_NOT_FOUND", status=404)
    # --- authentication of the approval ---------------------------------------------------
    if settings.execution_approval_pin_hash is None:
        raise ExecutionError("PIN_NOT_CONFIGURED", "Run: python -m app.cli set-approval-pin",
                             status=403)
    if _pin_locked(s, now):
        raise ExecutionError("PIN_LOCKED_OUT", "Too many wrong PINs; wait 15 minutes",
                             status=429)
    if not verify_pin(pin, settings.execution_approval_pin_hash.get_secret_value()):
        _event(s, now, "PIN_FAILED", intent.id)
        s.commit()
        raise ExecutionError("PIN_INVALID", status=403)
    if not hmac.compare_digest(quoted_hash, intent.payload_hash):
        _event(s, now, "APPROVAL_HASH_MISMATCH", intent.id)
        s.commit()
        raise ExecutionError("HASH_MISMATCH", "Approval does not match the proposed order")
    if intent.status != "PROPOSED":
        _event(s, now, "APPROVAL_REPLAY_REJECTED", intent.id, status=intent.status)
        s.commit()
        raise ExecutionError("ALREADY_USED", f"Intent is {intent.status}; propose a new order")
    if now > intent.expires_at:
        _transition(s, intent.id, "PROPOSED", "EXPIRED")
        _event(s, now, "INTENT_EXPIRED", intent.id)
        s.commit()
        raise ExecutionError("EXPIRED", "Approval window elapsed; propose a new order")
    # --- single-use approval (conditional update + unique row) ----------------------------
    if not _transition(s, intent.id, "PROPOSED", "APPROVED"):
        s.rollback()
        raise ExecutionError("ALREADY_USED")
    try:
        s.add(ExecutionApproval(intent_id=intent.id, at=now, payload_hash=quoted_hash,
                                actor="user-pin"))
        s.flush()
    except IntegrityError:
        s.rollback()
        raise ExecutionError("ALREADY_USED") from None
    _event(s, now, "APPROVED", intent.id)
    s.commit()

    # --- preflight against the gateway ----------------------------------------------------
    s.refresh(intent)
    market = s.get(Market, intent.market_id)
    if not settings.execution_enabled:
        _block(s, intent, now, "EXECUTION_DISABLED")
        return intent
    if kill_switch_engaged(s):
        _block(s, intent, now, "KILL_SWITCH_ENGAGED")
        return intent
    if gateway.env != intent.env or settings.execution_env.value != intent.env:
        _block(s, intent, now, "ENV_MISMATCH", gateway=gateway.env, intent=intent.env)
        return intent
    try:
        remote = gateway.get_market(market.external_ticker)
        book = gateway.get_orderbook(market.external_ticker)
        balance = gateway.get_balance_dollars()
    except GatewayError as e:
        _block(s, intent, now, "PREFLIGHT_READ_FAILED", error=str(e))
        return intent
    if remote.get("status") != "active":
        _block(s, intent, now, "MARKET_NOT_ACTIVE", status=remote.get("status"))
        return intent
    if rules_hash_from_market(remote) != intent.rules_hash:
        _block(s, intent, now, "RULES_CHANGED")
        return intent
    fresh_ask = executable_ask(book, intent.side)
    if fresh_ask is None:
        _block(s, intent, now, "NO_LIQUIDITY")
        return intent
    if fresh_ask > intent.approved_ask:
        _block(s, intent, now, "PRICE_CHANGED", approved=str(intent.approved_ask),
               fresh=str(fresh_ask))
        return intent
    schedules = schedules if schedules is not None else load_schedules()
    try:
        sched = _verified_schedule(market, schedules)
    except ExecutionError as e:
        _block(s, intent, now, e.code)
        return intent
    if sched.version != intent.fee_schedule_version:
        _block(s, intent, now, "FEE_SCHEDULE_CHANGED")
        return intent
    reason = _check_caps(s, settings, intent.market_id, intent.side, intent.quantity,
                         intent.max_cost, now, exclude_id=intent.id)
    if reason:
        _block(s, intent, now, reason)
        return intent
    if balance < intent.max_cost:
        _block(s, intent, now, "INSUFFICIENT_BALANCE", balance=str(balance))
        return intent
    _event(s, now, "PREFLIGHT_PASSED", intent.id, fresh_ask=str(fresh_ask))

    # --- submit exactly once ----------------------------------------------------------------
    if not _transition(s, intent.id, "APPROVED", "SUBMITTING"):
        s.rollback()
        raise ExecutionError("STATE_CONFLICT")
    _event(s, now, "SUBMITTING", intent.id, client_order_id=intent.client_order_id)
    s.commit()  # durable BEFORE the network call
    payload = json.loads(intent.payload_json)
    try:
        resp = gateway.create_order(payload)
    except DefinitiveReject as e:
        s.execute(update(ExecutionIntent).where(ExecutionIntent.id == intent.id)
                  .values(status="REJECTED", block_reason=e.code))
        _event(s, now, "EXCHANGE_REJECTED", intent.id, status=e.status, code=e.code)
        s.commit()
        s.refresh(intent)
        return intent
    except UnknownOutcome as e:
        s.execute(update(ExecutionIntent).where(ExecutionIntent.id == intent.id)
                  .values(status="UNKNOWN", block_reason=e.reason))
        _event(s, now, "OUTCOME_UNKNOWN", intent.id, reason=e.reason)
        s.commit()
        return reconcile(s, intent.id, gateway, now)
    _record(s, intent, resp, "response", now)
    s.refresh(intent)
    return intent


def _record(s: Session, intent: ExecutionIntent, resp: dict, source: str,
            now: datetime) -> None:
    filled = Decimal(str(resp.get("fill_count") or "0"))
    remaining = resp.get("remaining_count")

    def dec(x: object) -> Decimal | None:
        return None if x in (None, "") else Decimal(str(x))

    s.add(ExchangeOrder(
        intent_id=intent.id, recorded_at=now, source=source,
        exchange_order_id=resp.get("order_id"), client_order_id=intent.client_order_id,
        fill_count=filled, remaining_count=dec(remaining),
        average_fill_price=dec(resp.get("average_fill_price")),
        average_fee_paid=dec(resp.get("average_fee_paid")),
        raw_json=json.dumps(resp, default=str)))
    status = "NOT_FILLED" if filled == 0 else (
        "FILLED" if filled >= intent.quantity else "PARTIAL")
    s.execute(update(ExecutionIntent).where(ExecutionIntent.id == intent.id)
              .values(status=status, block_reason=None))
    _event(s, now, "EXCHANGE_RECORDED", intent.id, source=source, status=status,
           fill_count=str(filled), order_id=resp.get("order_id"))
    s.commit()


def reconcile(s: Session, intent_id: str, gateway: ExecutionGateway,
              now: datetime) -> ExecutionIntent:
    """Read-only lookup for UNKNOWN outcomes. Never submits anything."""
    intent = s.get(ExecutionIntent, intent_id)
    if intent is None:
        raise ExecutionError("INTENT_NOT_FOUND", status=404)
    if intent.status != "UNKNOWN":
        return intent
    market = s.get(Market, intent.market_id)
    created_ms = int(intent.created_at.timestamp() * 1000)
    try:
        found = gateway.find_order(market.external_ticker, intent.client_order_id, created_ms)
    except GatewayError as e:
        _event(s, now, "RECONCILE_FAILED", intent.id, error=str(e))
        s.commit()
        return intent
    if found is None:
        _event(s, now, "RECONCILE_NOT_FOUND", intent.id)
        s.commit()
        return intent
    _record(s, intent, found, "reconciliation", now)
    s.refresh(intent)
    return intent
