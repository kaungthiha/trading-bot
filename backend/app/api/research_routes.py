from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import AwareDatetime, BaseModel
from sqlalchemy import select

from app.api.errors import ApiError, ErrorCode
from app.api.routes import ClockDep, SessionDep
from app.db.models import ModelEvaluation, ModelRun
from app.research.cpi import history_as_of
from app.research.models import REGISTRY
from app.research.service import forecast_all

router = APIRouter(prefix="/api")


class ModelCardOut(BaseModel):
    name: str
    version: str
    summary: str
    contract_type: str
    features: str
    uncertainty_method: str
    hyperparameters: dict[str, Any]
    limitations: list[str]


class EvaluationOut(BaseModel):
    id: str
    created_at: AwareDatetime
    model: str
    version: str
    feature_version: str
    dataset_hash: str
    config: dict[str, Any]
    dev: dict[str, Any]
    holdout: dict[str, Any]
    data_notes: dict[str, Any]


class ForecastOut(BaseModel):
    model: str
    version: str
    decision: str
    p_yes: float | None
    lower: float | None
    upper: float | None
    uncertainty_method: str
    reasons: list[str]
    inputs: dict[str, Any]


class RecentPrintOut(BaseModel):
    month: str
    mom_rounded: Decimal
    released_at: AwareDatetime


class CpiForecastOut(BaseModel):
    contract_key: str | None
    reference_month: str | None
    threshold: Decimal
    as_of: AwareDatetime
    forecasts: list[ForecastOut]
    recent_prints: list[RecentPrintOut]
    caveat: str


class ModelRunOut(BaseModel):
    id: str
    created_at: AwareDatetime
    contract_key: str
    model: str
    version: str
    as_of: AwareDatetime
    decision: str
    p_yes: float | None
    lower: float | None
    upper: float | None
    reasons: list[str]


CAVEAT = (
    "Model probabilities are estimates from past CPI prints only. They are not profits and "
    "not trade recommendations; they ignore fees, spreads and most current information. "
    "Check each market's official rules before relating a contract to this definition."
)


@router.get("/models", response_model=list[ModelCardOut])
def list_models() -> list[ModelCardOut]:
    return [ModelCardOut(**asdict(m.card)) for m in REGISTRY.values()]


@router.get("/models/metrics", response_model=list[EvaluationOut])
def model_metrics(session: SessionDep) -> list[EvaluationOut]:
    """Latest stored walk-forward evaluation per registered model."""
    out = []
    for name in REGISTRY:
        ev = session.scalar(
            select(ModelEvaluation)
            .where(ModelEvaluation.model == name)
            .order_by(ModelEvaluation.created_at.desc())
            .limit(1)
        )
        if ev:
            out.append(EvaluationOut(
                id=ev.id, created_at=ev.created_at, model=ev.model, version=ev.version,
                feature_version=ev.feature_version, dataset_hash=ev.dataset_hash,
                config=json.loads(ev.config_json), dev=json.loads(ev.dev_json),
                holdout=json.loads(ev.holdout_json), data_notes=json.loads(ev.data_notes_json),
            ))
    return out


@router.get("/research/cpi-mom/forecast", response_model=CpiForecastOut)
def cpi_forecast(
    session: SessionDep,
    clock: ClockDep,
    threshold: Annotated[Decimal, Query(ge=Decimal("-2"), le=Decimal("2"))] = Decimal("0.3"),
    as_of: AwareDatetime | None = None,
    reference_month: date | None = None,
) -> CpiForecastOut:
    """Compute (not store) forecasts from both models. Deterministic for fixed inputs."""
    cutoff = as_of or clock.now()
    if cutoff > clock.now():
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, "as_of cannot be in the future")
    if reference_month is not None and reference_month.day != 1:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, "reference_month must be YYYY-MM-01")
    contract, forecasts, build = forecast_all(session, threshold, cutoff, reference_month)
    if contract is None:
        raise ApiError(409, ErrorCode.MISSING_EVIDENCE,
                       "No CPI first prints stored; run ingest-evidence")
    hist = history_as_of(build.prints, cutoff)[-12:]
    return CpiForecastOut(
        contract_key=contract.key,
        reference_month=contract.reference_month.isoformat(),
        threshold=threshold,
        as_of=cutoff,
        forecasts=[ForecastOut(model=f.model, version=f.version, decision=f.decision.value,
                               p_yes=f.p_yes, lower=f.lower, upper=f.upper,
                               uncertainty_method=f.uncertainty_method, reasons=f.reasons,
                               inputs=f.inputs) for f in forecasts],
        recent_prints=[RecentPrintOut(month=p.month.isoformat()[:7], mom_rounded=p.mom_rounded,
                                      released_at=p.released_at) for p in reversed(hist)],
        caveat=CAVEAT,
    )


@router.get("/model-runs", response_model=list[ModelRunOut])
def model_runs(session: SessionDep,
               limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[ModelRunOut]:
    rows = session.scalars(
        select(ModelRun).order_by(ModelRun.created_at.desc()).limit(limit)
    ).all()
    return [ModelRunOut(id=r.id, created_at=r.created_at, contract_key=r.contract_key,
                        model=r.model, version=r.version, as_of=r.as_of, decision=r.decision,
                        p_yes=r.p_yes, lower=r.lower, upper=r.upper,
                        reasons=json.loads(r.reasons_json)) for r in rows]
