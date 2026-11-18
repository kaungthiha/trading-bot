"""Operational, read-only endpoints: lineage, diagnostics, setup checklist.

Lineage answers "where exactly did this number come from?" for any signal or paper order:
quote snapshot -> ingestion run -> rules version -> mapping -> model run -> the exact
evidence vintages used (with a leakage check) -> evaluation -> fee schedule.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta
from pathlib import Path as FsPath
from typing import Annotated, Any

from fastapi import APIRouter, Path
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from app import __version__
from app.api.errors import ApiError, ErrorCode
from app.api.routes import ClockDep, SessionDep, SettingsDep
from app.db.models import (
    CollectionGap,
    EvidenceRecord,
    IngestionRun,
    Market,
    MarketMapping,
    MarketRuleVersion,
    ModelEvaluation,
    ModelRun,
    PaperOrder,
    QuoteSnapshot,
    Signal,
)
from app.evidence.repository import EvidenceRepository, is_fresh
from app.evidence.sources import SOURCES
from app.signals.fees import load_schedules
from app.signals.mapping import current_rules

router = APIRouter(prefix="/api")

IdPath = Annotated[str, Path(min_length=1, max_length=36)]


def _iso(d: Any) -> Any:
    return d.isoformat() if hasattr(d, "isoformat") else d


def _quote_lineage(s, q: QuoteSnapshot | None) -> dict | None:  # type: ignore[no-untyped-def]
    if q is None:
        return None
    adapter = (q.raw_ref or "").split(":", 1)[0] or None
    run = s.scalar(
        select(IngestionRun).where(IngestionRun.adapter == adapter,
                                   IngestionRun.started_at <= q.received_at)
        .order_by(IngestionRun.started_at.desc()).limit(1)
    ) if adapter else None
    return {
        "id": q.id, "observed_at": _iso(q.observed_at), "received_at": _iso(q.received_at),
        "raw_ref": q.raw_ref, "yes_bid": str(q.yes_bid) if q.yes_bid is not None else None,
        "no_bid": str(q.no_bid) if q.no_bid is not None else None,
        "yes_ask_derived": str(q.yes_ask_derived) if q.yes_ask_derived is not None else None,
        "no_ask_derived": str(q.no_ask_derived) if q.no_ask_derived is not None else None,
        "depth": json.loads(q.depth_json),
        "ingestion_run": {"id": run.id, "adapter": run.adapter, "started_at": _iso(run.started_at),
                          "finished_at": _iso(run.finished_at), "status": run.status}
        if run else None,
    }


def _signal_lineage(s, sig: Signal) -> dict:  # type: ignore[no-untyped-def]
    m = s.get(Market, sig.market_id)
    rules = s.scalar(select(MarketRuleVersion).where(
        MarketRuleVersion.market_id == sig.market_id, MarketRuleVersion.hash == sig.rules_hash)
        .order_by(MarketRuleVersion.observed_at.desc()).limit(1)) if sig.rules_hash else None
    cur = current_rules(s, sig.market_id)
    mp = s.get(MarketMapping, sig.mapping_id) if sig.mapping_id else None
    run = s.get(ModelRun, sig.model_run_id) if sig.model_run_id else None
    details = json.loads(sig.details_json)
    evidence, leak = [], False
    if run:
        ids = json.loads(run.inputs_json).get("evidence_ids", [])
        rows = {r.id: r for r in s.scalars(select(EvidenceRecord).where(
            EvidenceRecord.id.in_(ids))).all()} if ids else {}
        for eid in ids:
            r = rows.get(eid)
            if r is None:
                evidence.append({"id": eid, "missing": True})
                continue
            after_cutoff = r.available_at > run.as_of
            leak = leak or after_cutoff
            evidence.append({"id": r.id, "source_id": r.source_id,
                             "observation_date": r.observation_date,
                             "vintage_date": r.vintage_date,
                             "value": str(r.value) if r.value is not None else None,
                             "available_at": _iso(r.available_at), "source_url": r.source_url,
                             "after_cutoff": after_cutoff})
    ev_id = (details.get("validation") or {}).get("evaluation_id")
    ev = s.get(ModelEvaluation, ev_id) if ev_id else None
    sched = next((x for x in load_schedules() if x.version == sig.fee_schedule_version), None)
    return {
        "signal": {"id": sig.id, "created_at": _iso(sig.created_at), "decision": sig.decision,
                   "side": sig.side, "p_yes": sig.p_yes,
                   "entry": str(sig.entry) if sig.entry is not None else None,
                   "lower_edge": str(sig.lower_edge) if sig.lower_edge is not None else None,
                   "reasons": json.loads(sig.reasons_json)},
        "market": {"id": m.id, "ticker": m.external_ticker, "title": m.title, "status": m.status,
                   "fee_type": m.fee_type,
                   "fee_multiplier": str(m.fee_multiplier) if m.fee_multiplier is not None
                   else None},
        "quote": _quote_lineage(s, s.get(QuoteSnapshot, sig.quote_id) if sig.quote_id else None),
        "rules": {"hash": rules.hash, "observed_at": _iso(rules.observed_at),
                  "official_source_url": rules.official_source_url, "text": rules.rules_text,
                  "is_current": bool(cur and cur.hash == rules.hash)} if rules else None,
        "mapping": {"id": mp.id, "status": mp.status, "actor": mp.actor,
                    "created_at": _iso(mp.created_at), "contract_type": mp.contract_type,
                    "reference_month": mp.reference_month,
                    "threshold": str(mp.threshold) if mp.threshold is not None else None,
                    "notes": json.loads(mp.notes_json)} if mp else None,
        "model_run": {"id": run.id, "model": run.model, "version": run.version,
                      "feature_version": run.feature_version, "as_of": _iso(run.as_of),
                      "decision": run.decision, "p_yes": run.p_yes, "lower": run.lower,
                      "upper": run.upper, "uncertainty_method": run.uncertainty_method,
                      "inputs": {k: v for k, v in json.loads(run.inputs_json).items()
                                 if k != "evidence_ids"}} if run else None,
        "evidence": evidence,
        "leakage_check": "FAIL: input published after model cutoff" if leak
        else ("pass" if evidence else "n/a"),
        "evaluation": {"id": ev.id, "model": ev.model, "version": ev.version,
                       "dataset_hash": ev.dataset_hash, "created_at": _iso(ev.created_at),
                       "holdout": json.loads(ev.holdout_json)} if ev else None,
        "fee_schedule": {"version": sched.version, "verified": sched.verified,
                         "verified_by": sched.verified_by, "source_url": sched.source_url}
        if sched else None,
    }


@router.get("/lineage/signal/{signal_id}")
def signal_lineage(signal_id: IdPath, session: SessionDep) -> dict:
    sig = session.get(Signal, signal_id)
    if sig is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Signal not found")
    return _signal_lineage(session, sig)


@router.get("/lineage/paper-order/{order_id}")
def paper_order_lineage(order_id: IdPath, session: SessionDep) -> dict:
    o = session.get(PaperOrder, order_id)
    if o is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Paper order not found")
    sig = session.get(Signal, o.signal_id) if o.signal_id else None
    return {
        "order": {"id": o.id, "client_order_id": o.client_order_id,
                  "submitted_at": _iso(o.submitted_at), "status": o.status,
                  "side": o.side, "action": o.action, "quantity": str(o.quantity),
                  "filled_quantity": str(o.filled_quantity), "limit_price": str(o.limit_price),
                  "scenario": o.scenario, "simulation_version": o.simulation_version,
                  "fee_schedule_version": o.fee_schedule_version,
                  "fee_schedule_verified": o.fee_schedule_verified},
        "quote": _quote_lineage(session, session.get(QuoteSnapshot, o.quote_id)
                                if o.quote_id else None),
        "signal": _signal_lineage(session, sig) if sig else None,
    }


@router.get("/diagnostics")
def diagnostics(session: SessionDep, settings: SettingsDep, clock: ClockDep) -> dict:
    now = clock.now()
    try:
        schema = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:  # noqa: BLE001
        schema = None
    url = make_url(settings.database_url)
    db_bytes = None
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        f = FsPath(url.database)
        db_bytes = f.stat().st_size if f.exists() else None

    adapters = []
    for name in session.scalars(select(IngestionRun.adapter).distinct()).all():
        runs = session.scalars(select(IngestionRun).where(IngestionRun.adapter == name)
                               .order_by(IngestionRun.started_at.desc()).limit(20)).all()
        ok = [r for r in runs if r.status in ("success", "partial")]
        codes = Counter(e["code"] for r in runs for e in json.loads(r.errors_json))
        adapters.append({
            "adapter": name, "last_status": runs[0].status if runs else None,
            "last_started_at": _iso(runs[0].started_at) if runs else None,
            "last_success_at": _iso(ok[0].finished_at) if ok else None,
            "recent_runs": len(runs), "recent_failures": sum(r.status == "failed" for r in runs),
            "top_error_codes": codes.most_common(5),
        })

    max_age = timedelta(seconds=settings.quote_max_age_seconds)
    latest = session.execute(
        select(QuoteSnapshot.market_id, func.max(QuoteSnapshot.observed_at))
        .group_by(QuoteSnapshot.market_id)).all()
    stale = 0
    for _, observed in latest:
        if isinstance(observed, str):
            from datetime import datetime
            observed = datetime.fromisoformat(observed)
        if observed is None or now - observed > max_age:
            stale += 1

    repo = EvidenceRepository(session)
    evidence = []
    for spec in SOURCES.values():
        n, avail, vintage = repo.stats(spec.id)
        evidence.append({"source_id": spec.id, "records": n, "latest_vintage": vintage,
                         "fresh": is_fresh(spec, avail, now),
                         "configured": spec.id in settings.evidence_sources})

    since = now - timedelta(days=1)
    sigs = session.scalars(select(Signal).where(Signal.created_at >= since)).all()
    reasons = Counter(r for g in sigs for r in json.loads(g.reasons_json))
    rejects = Counter(session.scalars(select(PaperOrder.reject_reason).where(
        PaperOrder.reject_reason.is_not(None))).all())
    return {
        "app_version": __version__, "schema_revision": schema, "database_bytes": db_bytes,
        "server_time": now.isoformat(),
        "safety": {"trading_mode": settings.trading_mode.value,
                   "live_execution_enabled": settings.live_execution_enabled},
        "config": {"market_data_source": settings.market_data_source.value,
                   "kalshi_env": settings.kalshi_env.value,
                   "kalshi_series_watchlist": settings.kalshi_series_watchlist,
                   "evidence_sources": settings.evidence_sources,
                   "quote_max_age_seconds": settings.quote_max_age_seconds},
        "ingestion": adapters,
        "collection_gaps": session.scalar(select(func.count()).select_from(CollectionGap)),
        "quotes": {"markets_with_quotes": len(latest), "stale": stale,
                   "fresh": len(latest) - stale},
        "evidence": evidence,
        "signals_24h": {"count": len(sigs),
                        "by_decision": Counter(g.decision for g in sigs),
                        "top_reasons": reasons.most_common(8)},
        "paper_rejections": rejects.most_common(8),
    }


@router.get("/setup-status")
def setup_status(session: SessionDep, settings: SettingsDep, clock: ClockDep) -> dict:
    """Onboarding checklist. Each step: ok | todo | warn, with the exact next command."""
    now = clock.now()
    n_cpi, avail, _ = EvidenceRepository(session).stats("fred:CPIAUCSL")
    real_markets = session.scalar(select(func.count()).select_from(Market).where(
        Market.is_mock.is_(False)))
    confirmed = session.scalar(select(func.count()).select_from(MarketMapping).where(
        MarketMapping.status == "confirmed"))
    evaluated = session.scalar(select(func.count()).select_from(ModelEvaluation))
    verified_fees = any(s.verified for s in load_schedules())
    recent = session.scalar(select(func.max(IngestionRun.finished_at)).where(
        IngestionRun.status.in_(("success", "partial"))))

    def step(key: str, title: str, ok: bool, hint: str, warn: bool = False) -> dict:
        return {"key": key, "title": title, "status": "ok" if ok else ("warn" if warn else "todo"),
                "hint": hint}

    steps = [
        step("fred_key", "Add your FRED API key", settings.fred_api_key is not None,
             "Put KRT_FRED_API_KEY=... in .env (never in .env.example), then restart."),
        step("evidence", "Download CPI vintages", n_cpi > 0,
             "cd backend; .venv\\Scripts\\python -m app.cli ingest-evidence"),
        step("models", "Evaluate the models", evaluated > 0,
             ".venv\\Scripts\\python -m app.cli evaluate-models"),
        step("markets", "Fetch Kalshi CPI markets (public, no key)", real_markets > 0,
             ".venv\\Scripts\\python -m app.cli ingest --source kalshi_public --series KXCPI"),
        step("mappings", "Review and confirm at least one market mapping", confirmed > 0,
             "propose-mappings, list-mappings, then confirm-mapping <TICKER> --yes"),
        step("fees", "Verify the fee schedule against Kalshi's official PDF", verified_fees,
             "Edit backend/app/signals/fee_schedules.json (see README). Until then signals "
             "abstain.", warn=True),
        step("fresh_data", "Keep data fresh (worker)",
             recent is not None and now - recent < timedelta(hours=24),
             ".\\scripts\\start-worker.ps1 (or re-run the ingest commands)", warn=True),
    ]
    _ = avail
    return {"steps": steps, "complete": all(x["status"] == "ok" for x in steps),
            "paper_mode": settings.trading_mode.value == "paper"
            and not settings.live_execution_enabled}
