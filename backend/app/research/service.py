"""Glue: load first prints from stored evidence, forecast, evaluate, persist."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EvidenceRecord, ModelEvaluation, ModelRun
from app.research.backtest import (
    DEFAULT_HOLDOUT_START,
    DEFAULT_THRESHOLDS,
    EvaluationReport,
    walk_forward,
)
from app.research.cpi import (
    SOURCE_ID,
    CpiMomContract,
    FirstPrintBuild,
    build_first_prints,
    history_as_of,
    next_month,
)
from app.research.models import REGISTRY, Forecast


def load_first_prints(session: Session) -> FirstPrintBuild:
    rows = session.scalars(
        select(EvidenceRecord).where(EvidenceRecord.source_id == SOURCE_ID)
    ).all()
    return build_first_prints(rows)


def next_contract_month(build: FirstPrintBuild, as_of: datetime):  # type: ignore[no-untyped-def]
    hist = history_as_of(build.prints, as_of)
    return next_month(hist[-1].month) if hist else None


def forecast_all(
    session: Session, threshold: Decimal, as_of: datetime, reference_month=None  # type: ignore[no-untyped-def]
) -> tuple[CpiMomContract | None, list[Forecast], FirstPrintBuild]:
    build = load_first_prints(session)
    hist = history_as_of(build.prints, as_of)
    month = reference_month or (next_month(hist[-1].month) if hist else None)
    if month is None:
        return None, [], build
    contract = CpiMomContract(month, threshold)
    return contract, [m.predict(contract, hist, as_of) for m in REGISTRY.values()], build


def save_forecast(session: Session, f: Forecast, created_at: datetime,
                  market_id: str | None = None) -> ModelRun:
    run = ModelRun(
        created_at=created_at,
        contract_key=f.contract_key,
        market_id=market_id,
        model=f.model,
        version=f.version,
        feature_version=f.feature_version,
        as_of=f.as_of,
        decision=f.decision.value,
        p_yes=f.p_yes,
        lower=f.lower,
        upper=f.upper,
        uncertainty_method=f.uncertainty_method,
        reasons_json=json.dumps(f.reasons),
        inputs_json=json.dumps(f.inputs),
    )
    session.add(run)
    session.flush()
    return run


def evaluate_and_save(session: Session, created_at: datetime) -> list[EvaluationReport]:
    build = load_first_prints(session)
    if not build.prints:
        raise ValueError(f"No {SOURCE_ID} evidence stored; run ingest-evidence first")
    reports = []
    for model in REGISTRY.values():
        rep = walk_forward(model, build.prints)
        session.add(ModelEvaluation(
            created_at=created_at,
            model=rep.model,
            version=rep.version,
            feature_version=rep.feature_version,
            dataset_hash=rep.dataset_hash,
            config_json=json.dumps({
                "thresholds": rep.thresholds,
                "holdout_start": rep.holdout_start.isoformat(),
                "hyperparameters": model.card.hyperparameters,
                "dev_range": rep.dev_range,
                "holdout_range": rep.holdout_range,
            }),
            dev_json=json.dumps(rep.dev.to_dict()),
            holdout_json=json.dumps(rep.holdout.to_dict()),
            data_notes_json=json.dumps({
                "first_prints_used": len(build.prints),
                "excluded": build.excluded,
            }),
        ))
        reports.append(rep)
    session.flush()
    return reports


def card_dict(name: str) -> dict:
    return asdict(REGISTRY[name].card)


__all__ = [
    "DEFAULT_HOLDOUT_START",
    "DEFAULT_THRESHOLDS",
    "evaluate_and_save",
    "forecast_all",
    "load_first_prints",
    "next_contract_month",
    "save_forecast",
]
