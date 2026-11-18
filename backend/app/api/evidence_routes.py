from __future__ import annotations

import json
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Path, Query
from pydantic import AwareDatetime
from sqlalchemy import select

from app.api.errors import ApiError, ErrorCode
from app.api.routes import ClockDep, SessionDep, SettingsDep
from app.api.schemas import (
    CollectionGapListOut,
    CollectionGapOut,
    EvidenceAsOfOut,
    EvidenceObservationOut,
    EvidenceSourceListOut,
    EvidenceSourceOut,
    EvidenceVintagesOut,
    IngestionErrorOut,
    IngestionRunOut,
)
from app.db.models import CollectionGap, EvidenceRecord, IngestionRun
from app.evidence.repository import EvidenceRepository, is_fresh
from app.evidence.sources import FRED_NOTICE, SOURCES, SourceSpec

router = APIRouter(prefix="/api")

SourceIdPath = Annotated[str, Path(max_length=64, pattern=r"^[a-z]+:[A-Z0-9_]+$")]


def _spec(source_id: str) -> SourceSpec:
    spec = SOURCES.get(source_id)
    if spec is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Unknown evidence source")
    return spec


def _obs(r: EvidenceRecord) -> EvidenceObservationOut:
    return EvidenceObservationOut(
        observation_date=r.observation_date,
        vintage_date=r.vintage_date,
        value=r.value,
        quality=r.quality,
        available_at=r.available_at,
        retrieved_at=r.retrieved_at,
        units=r.units,
        source_url=r.source_url,
    )


def _run_out(r: IngestionRun) -> IngestionRunOut:
    return IngestionRunOut(
        id=r.id,
        adapter=r.adapter,
        started_at=r.started_at,
        finished_at=r.finished_at,
        status=r.status,
        count=r.count,
        errors=[IngestionErrorOut(**e) for e in json.loads(r.errors_json)],
    )


@router.get("/evidence/sources", response_model=EvidenceSourceListOut)
def evidence_sources(
    session: SessionDep, settings: SettingsDep, clock: ClockDep
) -> EvidenceSourceListOut:
    repo = EvidenceRepository(session)
    now = clock.now()
    items = []
    for spec in SOURCES.values():
        count, latest_avail, latest_vintage = repo.stats(spec.id)
        last = session.scalar(
            select(IngestionRun)
            .where(IngestionRun.adapter == spec.id)
            .order_by(IngestionRun.started_at.desc())
            .limit(1)
        )
        items.append(
            EvidenceSourceOut(
                id=spec.id,
                title=spec.title,
                series_id=spec.series_id,
                category=spec.category,
                frequency=spec.frequency,
                upstream_agency=spec.upstream_agency,
                source_page_url=spec.source_page_url,
                license_notes=spec.license_notes,
                attribution=FRED_NOTICE if spec.adapter == "fred" else None,
                release_timing_note=spec.release_time_source,
                configured=spec.id in settings.evidence_sources,
                record_count=count,
                latest_vintage=latest_vintage,
                latest_available_at=latest_avail,
                is_fresh=is_fresh(spec, latest_avail, now),
                freshness_max_age_days=spec.freshness_max_age_days,
                last_run=_run_out(last) if last else None,
            )
        )
    return EvidenceSourceListOut(items=items)


@router.get("/evidence/{source_id}/observations", response_model=EvidenceAsOfOut)
def evidence_as_of(
    source_id: SourceIdPath,
    session: SessionDep,
    clock: ClockDep,
    as_of: AwareDatetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 24,
) -> EvidenceAsOfOut:
    _spec(source_id)
    cutoff = as_of or clock.now()
    rows = EvidenceRepository(session).as_of(source_id, cutoff, limit)
    return EvidenceAsOfOut(source_id=source_id, as_of=cutoff, items=[_obs(r) for r in rows])


@router.get("/evidence/{source_id}/vintages", response_model=EvidenceVintagesOut)
def evidence_vintages(
    source_id: SourceIdPath, session: SessionDep, observation_date: date
) -> EvidenceVintagesOut:
    _spec(source_id)
    od = observation_date.isoformat()
    rows = EvidenceRepository(session).vintages_of(source_id, od)
    return EvidenceVintagesOut(
        source_id=source_id, observation_date=od, items=[_obs(r) for r in rows]
    )


@router.get("/collection-gaps", response_model=CollectionGapListOut)
def collection_gaps(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> CollectionGapListOut:
    rows = session.scalars(
        select(CollectionGap).order_by(CollectionGap.detected_at.desc()).limit(limit)
    ).all()
    return CollectionGapListOut(
        items=[
            CollectionGapOut(
                id=g.id,
                job=g.job,
                gap_start=g.gap_start,
                gap_end=g.gap_end,
                detected_at=g.detected_at,
                backfillable=g.backfillable,
                reason=g.reason,
            )
            for g in rows
        ]
    )
