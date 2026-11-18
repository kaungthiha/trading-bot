"""Assemble engine inputs from the database, run the engine, persist immutable signals."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Market, MarketMapping, ModelEvaluation, QuoteSnapshot, Signal
from app.domain.models import PriceRange
from app.research.cpi import CpiMomContract, history_as_of
from app.research.models import REGISTRY
from app.research.service import load_first_prints, save_forecast
from app.signals.engine import (
    Level,
    SignalInputs,
    SignalParams,
    SignalResult,
    evaluate,
)
from app.signals.fees import FeeSchedule, load_schedules, select_schedule
from app.signals.mapping import current_rules, latest_mapping


def params_from(settings: Settings) -> SignalParams:
    return SignalParams(
        quantity=settings.signal_quantity,
        slippage_per_contract=settings.signal_slippage_per_contract,
        max_spread=settings.signal_max_spread,
        min_edge=settings.signal_min_edge,
        quote_max_age=timedelta(seconds=settings.quote_max_age_seconds),
        min_holdout_events=settings.signal_min_holdout_events,
        max_model_market_divergence=settings.signal_max_model_market_divergence,
    )


def model_validation(session: Session, model: str) -> tuple[int | None, bool | None, dict]:
    """Holdout months for the model and whether it beats the base-rate baseline on holdout
    Brier (or, for the baseline itself, a constant 0.5 forecast)."""
    def latest(name: str) -> ModelEvaluation | None:
        return session.scalar(select(ModelEvaluation).where(ModelEvaluation.model == name)
                              .order_by(ModelEvaluation.created_at.desc()).limit(1))

    ev = latest(model)
    if ev is None:
        return None, None, {}
    hold = json.loads(ev.holdout_json)
    brier = hold.get("brier")
    if model == "base_rate":
        ref = 0.25
    else:
        base = latest("base_rate")
        ref = json.loads(base.holdout_json).get("brier") if base else None
    beats = brier is not None and ref is not None and brier < ref
    return hold.get("n_events"), beats, {"evaluation_id": ev.id, "holdout_brier": brier,
                                         "reference_brier": ref}


def _levels(raw: list[dict]) -> list[Level]:
    return [Level(Decimal(lv["price"]), Decimal(lv["quantity"])) for lv in raw]


def build_and_evaluate(
    session: Session, market: Market, settings: Settings, schedules: list[FeeSchedule],
    now: datetime,
) -> tuple[SignalResult, dict]:
    rules = current_rules(session, market.id)
    mapping: MarketMapping | None = latest_mapping(session, market.id)
    quote = session.scalar(select(QuoteSnapshot).where(QuoteSnapshot.market_id == market.id)
                           .order_by(QuoteSnapshot.observed_at.desc()).limit(1))
    depth = json.loads(quote.depth_json) if quote else {"yes_bids": [], "no_bids": []}

    forecast = None
    model_run_id = None
    if mapping is not None and mapping.reference_month and mapping.threshold is not None:
        contract = CpiMomContract(date.fromisoformat(mapping.reference_month), mapping.threshold)
        hist = history_as_of(load_first_prints(session).prints, now)
        forecast = REGISTRY[settings.signal_model].predict(contract, hist, now)
        model_run_id = save_forecast(session, forecast, now, market_id=market.id).id

    holdout_events, beats, validation = model_validation(session, settings.signal_model)
    schedule = select_schedule(schedules, market.fee_type) if market.fee_type else None
    inp = SignalInputs(
        now=now,
        market_status=market.status,
        market_type=market.market_type,
        close_at=market.close_at,
        notional=market.notional_value,
        price_ranges=[PriceRange.model_validate(r) for r in json.loads(market.price_ranges_json)],
        fee_type=market.fee_type,
        fee_multiplier=market.fee_multiplier,
        current_rules_hash=rules.hash if rules else None,
        mapping_status=mapping.status if mapping else None,
        mapping_rules_hash=mapping.rules_hash if mapping else None,
        quote_observed_at=quote.observed_at if quote else None,
        yes_bids=_levels(depth.get("yes_bids", [])),
        no_bids=_levels(depth.get("no_bids", [])),
        forecast_decision=forecast.decision.value if forecast else "ABSTAIN",
        forecast_reasons=forecast.reasons if forecast else ["NO_CONTRACT_MAPPING"],
        p_yes=forecast.p_yes if forecast else None,
        p_lower=forecast.lower if forecast else None,
        p_upper=forecast.upper if forecast else None,
        model_holdout_events=holdout_events,
        model_beats_baseline=beats,
        fee_schedule=schedule,
    )
    ids = {
        "quote_id": quote.id if quote else None,
        "model_run_id": model_run_id,
        "mapping_id": mapping.id if mapping else None,
        "rules_hash": rules.hash if rules else None,
        "fee_schedule_version": schedule.version if schedule else None,
        "validation": validation,
        "model": settings.signal_model,
        "p_yes": forecast.p_yes if forecast else None,
        "p_lower": forecast.lower if forecast else None,
        "p_upper": forecast.upper if forecast else None,
        "contract_key": forecast.contract_key if forecast else None,
    }
    return evaluate(inp, params_from(settings)), ids


def _side_dict(s) -> dict:  # type: ignore[no-untyped-def]
    d = asdict(s)
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in d.items()}


def save_signal(session: Session, market: Market, result: SignalResult, ids: dict,
                quantity: Decimal, now: datetime) -> Signal:
    c = result.chosen
    row = Signal(
        created_at=now,
        expires_at=result.expires_at,
        market_id=market.id,
        quote_id=ids["quote_id"],
        model_run_id=ids["model_run_id"],
        mapping_id=ids["mapping_id"],
        rules_hash=ids["rules_hash"],
        fee_schedule_version=ids["fee_schedule_version"],
        decision=result.decision.value,
        side=result.side,
        quantity=quantity,
        p_yes=ids["p_yes"],
        entry=c.entry if c else None,
        fee=c.fee if c else None,
        slippage=c.slippage if c else None,
        ev=c.ev if c else None,
        lower_edge=c.lower_edge if c else None,
        reasons_json=json.dumps(result.reasons),
        caveats_json=json.dumps(result.caveats),
        details_json=json.dumps({
            "yes": _side_dict(result.yes),
            "no": _side_dict(result.no),
            "spread_yes": None if result.spread_yes is None else str(result.spread_yes),
            "model_market_divergence": None if result.model_market_divergence is None
            else str(result.model_market_divergence),
            "model": ids["model"],
            "p_lower": ids["p_lower"],
            "p_upper": ids["p_upper"],
            "contract_key": ids["contract_key"],
            "validation": ids["validation"],
        }),
    )
    session.add(row)
    session.flush()
    return row


def generate_signals(session: Session, settings: Settings, now: datetime,
                     schedules: list[FeeSchedule] | None = None) -> list[Signal]:
    """One signal per market that has any mapping (proposed markets still get an
    explanatory ABSTAIN so the user can see what is missing)."""
    schedules = schedules if schedules is not None else load_schedules()
    market_ids = session.scalars(select(MarketMapping.market_id).distinct()).all()
    out = []
    for mid in market_ids:
        market = session.get(Market, mid)
        if market is None:
            continue
        result, ids = build_and_evaluate(session, market, settings, schedules, now)
        out.append(save_signal(session, market, result, ids, settings.signal_quantity, now))
    return out


def validity(sig: Signal, current_rules_hash: str | None, now: datetime) -> str:
    """Computed at read time; signals themselves are never modified."""
    if sig.rules_hash is not None and sig.rules_hash != current_rules_hash:
        return "INVALIDATED_RULES_CHANGED"
    if now > sig.expires_at:
        return "EXPIRED"
    return "VALID"


__all__ = ["generate_signals", "history_as_of", "validity"]
