"""Run an EvidenceAdapter and persist results, recording an IngestionRun."""

from __future__ import annotations

import json
from dataclasses import asdict

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.base import AdapterError, FetchError
from app.core.clock import Clock
from app.core.config import Settings
from app.db.models import IngestionRun
from app.evidence.fred import FredClient, FredEvidenceAdapter
from app.evidence.models import EvidenceAdapter
from app.evidence.repository import EvidenceRepository
from app.evidence.sources import SOURCES
from app.ingest import IngestionSummary


def build_evidence_adapter(source_id: str, settings: Settings, clock: Clock) -> EvidenceAdapter:
    spec = SOURCES.get(source_id)
    if spec is None:
        raise ValueError(f"Unregistered evidence source {source_id!r}")
    if spec.adapter == "fred":
        return FredEvidenceAdapter(spec, FredClient.from_settings(settings), clock)
    raise ValueError(f"No adapter implementation for {spec.adapter!r}")


def run_evidence_ingestion(
    adapter: EvidenceAdapter, factory: sessionmaker[Session], clock: Clock
) -> IngestionSummary:
    with factory() as s:
        run = IngestionRun(adapter=adapter.source_id, started_at=clock.now(), status="running")
        s.add(run)
        s.commit()
        run_id = run.id

    errors: list[FetchError] = []
    count = 0
    try:
        result = adapter.fetch()
        errors.extend(result.errors)
        with factory() as s:
            ins = EvidenceRepository(s).insert_new(adapter.source_id, result.observations)
            s.commit()
        count = ins.inserted
        errors.extend(ins.conflicts)
        # A refresh that inserts nothing new is still a success (data was current).
        status = "success" if not errors else "partial"
    except AdapterError as exc:
        errors.append(FetchError(f"adapter:{adapter.source_id}", exc.code, str(exc)))
        status = "failed"

    with factory() as s:
        run = s.get(IngestionRun, run_id)
        assert run is not None
        run.finished_at = clock.now()
        run.status = status
        run.count = count
        run.errors_json = json.dumps([asdict(e) for e in errors])
        s.commit()
    return IngestionSummary(run_id, adapter.source_id, status, count, errors)
