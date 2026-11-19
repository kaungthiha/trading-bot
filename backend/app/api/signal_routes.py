from __future__ import annotations

import json
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query
from pydantic import AwareDatetime, BaseModel
from sqlalchemy import select

from app.api.errors import ApiError, ErrorCode
from app.api.routes import ClockDep, SessionDep
from app.db.models import Market, MarketMapping, QuoteSnapshot, Signal
from app.signals.fees import load_schedules
from app.signals.mapping import current_rules, latest_mapping
from app.signals.service import validity

router = APIRouter(prefix="/api")


class SignalOut(BaseModel):
    id: str
    created_at: AwareDatetime
    expires_at: AwareDatetime
    validity: str
    market_id: str
    market_ticker: str
    market_title: str
    market_event_ticker: str | None = None
    rules_source_url: str | None
    decision: str
    side: str | None
    quantity: Decimal | None
    p_yes: float | None
    p_lower: float | None
    p_upper: float | None
    entry: Decimal | None
    fee: Decimal | None
    slippage: Decimal | None
    ev: Decimal | None
    lower_edge: Decimal | None
    reasons: list[str]
    caveats: list[str]
    quote_id: str | None
    quote_observed_at: AwareDatetime | None
    model_run_id: str | None
    model: str | None
    contract_key: str | None
    mapping_id: str | None
    mapping_status: str | None
    fee_schedule_version: str | None
    details: dict[str, Any]


class MappingOut(BaseModel):
    id: str
    created_at: AwareDatetime
    market_id: str
    market_ticker: str
    contract_type: str
    reference_month: str | None
    threshold: Decimal | None
    status: str
    actor: str
    rules_current: bool
    notes: list[str]


class FeeScheduleOut(BaseModel):
    version: str
    fee_types: list[str]
    taker_rate: Decimal
    maker_multiplier: dict[str, Decimal]
    verified: bool
    verified_by: str | None
    verified_at: str | None
    source_url: str
    provenance: dict[str, Any]


def _signal_out(session, s: Signal, now) -> SignalOut:  # type: ignore[no-untyped-def]
    m = session.get(Market, s.market_id)
    rules = current_rules(session, s.market_id)
    q = session.get(QuoteSnapshot, s.quote_id) if s.quote_id else None
    mp = session.get(MarketMapping, s.mapping_id) if s.mapping_id else None
    details = json.loads(s.details_json)
    return SignalOut(
        id=s.id, created_at=s.created_at, expires_at=s.expires_at,
        validity=validity(s, rules.hash if rules else None, now),
        market_id=s.market_id, market_ticker=m.external_ticker, market_title=m.title,
        market_event_ticker=m.event_ticker,
        rules_source_url=rules.official_source_url if rules else None,
        decision=s.decision, side=s.side, quantity=s.quantity, p_yes=s.p_yes,
        p_lower=details.get("p_lower"), p_upper=details.get("p_upper"),
        entry=s.entry, fee=s.fee, slippage=s.slippage, ev=s.ev, lower_edge=s.lower_edge,
        reasons=json.loads(s.reasons_json), caveats=json.loads(s.caveats_json),
        quote_id=s.quote_id, quote_observed_at=q.observed_at if q else None,
        model_run_id=s.model_run_id, model=details.get("model"),
        contract_key=details.get("contract_key"), mapping_id=s.mapping_id,
        mapping_status=mp.status if mp else None,
        fee_schedule_version=s.fee_schedule_version, details=details,
    )


@router.get("/signals", response_model=list[SignalOut])
def list_signals(session: SessionDep, clock: ClockDep,
                 limit: Annotated[int, Query(ge=1, le=200)] = 50,
                 latest_only: bool = True) -> list[SignalOut]:
    rows = session.scalars(select(Signal).order_by(Signal.created_at.desc())).all()
    if latest_only:
        seen: set[str] = set()
        rows = [r for r in rows if not (r.market_id in seen or seen.add(r.market_id))]
    now = clock.now()
    return [_signal_out(session, s, now) for s in rows[:limit]]


@router.get("/signals/{signal_id}", response_model=SignalOut)
def get_signal(signal_id: Annotated[str, Path(min_length=1, max_length=36)],
               session: SessionDep, clock: ClockDep) -> SignalOut:
    """One signal by id (deep links from the research workspace)."""
    s = session.get(Signal, signal_id)
    if s is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Signal not found")
    return _signal_out(session, s, clock.now())


@router.get("/markets/{market_id}/signals", response_model=list[SignalOut])
def market_signals(market_id: Annotated[str, Path(min_length=1, max_length=36)],
                   session: SessionDep, clock: ClockDep,
                   limit: Annotated[int, Query(ge=1, le=200)] = 20) -> list[SignalOut]:
    if session.get(Market, market_id) is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Market not found")
    rows = session.scalars(select(Signal).where(Signal.market_id == market_id)
                           .order_by(Signal.created_at.desc()).limit(limit)).all()
    now = clock.now()
    return [_signal_out(session, s, now) for s in rows]


@router.get("/mappings", response_model=list[MappingOut])
def list_mappings(session: SessionDep) -> list[MappingOut]:
    out = []
    for mid in session.scalars(select(MarketMapping.market_id).distinct()).all():
        mp = latest_mapping(session, mid)
        m = session.get(Market, mid)
        rules = current_rules(session, mid)
        out.append(MappingOut(
            id=mp.id, created_at=mp.created_at, market_id=mid, market_ticker=m.external_ticker,
            contract_type=mp.contract_type, reference_month=mp.reference_month,
            threshold=mp.threshold, status=mp.status, actor=mp.actor,
            rules_current=bool(rules and rules.hash == mp.rules_hash),
            notes=json.loads(mp.notes_json),
        ))
    return sorted(out, key=lambda x: x.market_ticker)


@router.get("/fee-schedules", response_model=list[FeeScheduleOut])
def fee_schedules() -> list[FeeScheduleOut]:
    return [FeeScheduleOut(version=s.version, fee_types=list(s.fee_types),
                           taker_rate=s.taker_rate, maker_multiplier=s.maker_multiplier,
                           verified=s.verified, verified_by=s.verified_by,
                           verified_at=s.verified_at, source_url=s.source_url,
                           provenance=s.provenance) for s in load_schedules()]
