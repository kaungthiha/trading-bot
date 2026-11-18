"""Run a market-data adapter and persist results, recording an IngestionRun row.

Each snapshot is committed independently so one bad market cannot roll back the rest;
every failure is recorded in the run's errors -- nothing is silently dropped.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.base import AdapterError, ExchangeMarketDataAdapter, FetchError
from app.core.clock import Clock
from app.db.models import IngestionRun
from app.db.repositories import MarketRepository

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestionSummary:
    run_id: str
    adapter: str
    status: str
    count: int
    errors: list[FetchError]


def run_ingestion(
    adapter: ExchangeMarketDataAdapter, factory: sessionmaker[Session], clock: Clock
) -> IngestionSummary:
    with factory() as s:
        run = IngestionRun(adapter=adapter.name, started_at=clock.now(), status="running")
        s.add(run)
        s.commit()
        run_id = run.id

    errors: list[FetchError] = []
    count = 0
    try:
        result = adapter.fetch_markets()
        errors.extend(result.errors)
        for snap in result.snapshots:
            with factory() as s:
                try:
                    MarketRepository(s, clock).upsert_snapshot(snap, source=adapter.name)
                    s.commit()
                    count += 1
                except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
                    s.rollback()
                    log.warning("Persist failed for %s: %s", snap.external_ticker,
                                type(exc).__name__)
                    errors.append(
                        FetchError(f"market:{snap.external_ticker}", "PERSIST_ERROR",
                                   type(exc).__name__)
                    )
        status = "success" if not errors else ("partial" if count else "failed")
    except AdapterError as exc:
        errors.append(FetchError(f"adapter:{adapter.name}", exc.code, str(exc)))
        status = "failed"

    with factory() as s:
        run = s.get(IngestionRun, run_id)
        assert run is not None
        run.finished_at = clock.now()
        run.status = status
        run.count = count
        run.errors_json = json.dumps([asdict(e) for e in errors])
        s.commit()

    return IngestionSummary(run_id, adapter.name, status, count, errors)


def recent_runs(session: Session, limit: int) -> list[IngestionRun]:
    return list(
        session.scalars(
            select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit)
        )
    )
