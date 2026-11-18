from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.api.errors import ApiError, ErrorCode
from app.api.schemas import (
    BookLevelOut,
    CategoriesOut,
    HealthOut,
    IngestionErrorOut,
    IngestionRunListOut,
    IngestionRunOut,
    MarketDetailOut,
    MarketListOut,
    MarketSummaryOut,
    QuoteHistoryItemOut,
    QuoteHistoryOut,
    QuoteOut,
    RulesOut,
)
from app.core.clock import Clock
from app.core.config import Settings
from app.db.models import Market, QuoteSnapshot
from app.db.repositories import MarketRepository
from app.domain.models import MarketStatus, PriceProvenance, PriceRange
from app.domain.pricing import is_stale
from app.ingest import recent_runs

router = APIRouter(prefix="/api")


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ClockDep = Annotated[Clock, Depends(get_clock)]


def _quote_out(q: QuoteSnapshot | None, clock: Clock, max_age: int) -> QuoteOut | None:
    if q is None:
        return None
    now = clock.now()
    spread = (
        q.yes_ask_derived - q.yes_bid
        if q.yes_ask_derived is not None and q.yes_bid is not None
        else None
    )
    derived = PriceProvenance.DERIVED_FROM_COMPLEMENT
    return QuoteOut(
        observed_at=q.observed_at,
        received_at=q.received_at,
        age_seconds=(now - q.observed_at).total_seconds(),
        is_stale=is_stale(q.observed_at, now, timedelta(seconds=max_age)),
        max_age_seconds=max_age,
        yes_bid=q.yes_bid,
        no_bid=q.no_bid,
        yes_ask=q.yes_ask_derived,
        no_ask=q.no_ask_derived,
        yes_ask_provenance=derived if q.yes_ask_derived is not None else None,
        no_ask_provenance=derived if q.no_ask_derived is not None else None,
        spread_yes=spread,
    )


def _summary(m: Market, repo: MarketRepository, clock: Clock, max_age: int) -> dict:
    return {
        "id": m.id,
        "exchange": m.exchange,
        "external_ticker": m.external_ticker,
        "event_ticker": m.event_ticker,
        "series_ticker": m.series_ticker,
        "title": m.title,
        "category": m.category,
        "status": m.status,
        "status_raw": m.status_raw,
        "market_type": m.market_type,
        "open_at": m.open_at,
        "close_at": m.close_at,
        "is_mock": m.is_mock,
        "quote": _quote_out(repo.latest_quote(m.id), clock, max_age),
    }


@router.get("/health", response_model=HealthOut)
def health(session: SessionDep, settings: SettingsDep, clock: ClockDep) -> HealthOut:
    try:
        session.execute(text("SELECT 1"))
        db = "ok"
    except Exception:  # noqa: BLE001
        db = "error"
    creds = {
        "kalshi": settings.kalshi_api_key_id is not None
        and settings.kalshi_private_key_path is not None,
        "fred": settings.fred_api_key is not None,
        "bls": settings.bls_api_key is not None,
        "bea": settings.bea_api_key is not None,
        "census": settings.census_api_key is not None,
        "sec_user_agent": settings.sec_user_agent is not None,
        "nyt": settings.nyt_api_key is not None,
    }
    return HealthOut(
        status="ok" if db == "ok" else "degraded",
        version=__version__,
        env=settings.env,
        trading_mode=settings.trading_mode.value,
        live_execution_enabled=settings.live_execution_enabled,
        market_data_source=settings.market_data_source.value,
        kalshi_env=settings.kalshi_env.value,
        database=db,
        server_time=clock.now(),
        credentials_configured=creds,
    )


@router.get("/markets", response_model=MarketListOut)
def list_markets(
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
    category: Annotated[str | None, Query(max_length=64, pattern=r"^[a-z0-9_-]+$")] = None,
    status: MarketStatus | None = None,
    series_ticker: Annotated[
        str | None, Query(max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    ] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> MarketListOut:
    repo = MarketRepository(session, clock)
    rows = repo.list_markets(
        category,
        limit,
        offset,
        status=status.value if status else None,
        series_ticker=series_ticker,
        q=q,
    )
    items = [
        MarketSummaryOut(**_summary(m, repo, clock, settings.quote_max_age_seconds)) for m in rows
    ]
    return MarketListOut(items=items, limit=limit, offset=offset)


@router.get("/categories", response_model=CategoriesOut)
def list_categories(session: SessionDep, clock: ClockDep) -> CategoriesOut:
    return CategoriesOut(items=MarketRepository(session, clock).categories())


@router.get("/markets/{market_id}/quotes", response_model=QuoteHistoryOut)
def market_quotes(
    market_id: Annotated[str, Path(min_length=1, max_length=36)],
    session: SessionDep,
    clock: ClockDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> QuoteHistoryOut:
    repo = MarketRepository(session, clock)
    if repo.get(market_id) is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Market not found")
    return QuoteHistoryOut(
        market_id=market_id,
        items=[
            QuoteHistoryItemOut(
                id=q.id,
                observed_at=q.observed_at,
                received_at=q.received_at,
                yes_bid=q.yes_bid,
                no_bid=q.no_bid,
                yes_ask=q.yes_ask_derived,
                no_ask=q.no_ask_derived,
                raw_ref=q.raw_ref,
            )
            for q in repo.quotes(market_id, limit)
        ],
    )


@router.get("/ingestion/runs", response_model=IngestionRunListOut)
def ingestion_runs(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> IngestionRunListOut:
    return IngestionRunListOut(
        items=[
            IngestionRunOut(
                id=r.id,
                adapter=r.adapter,
                started_at=r.started_at,
                finished_at=r.finished_at,
                status=r.status,
                count=r.count,
                errors=[IngestionErrorOut(**e) for e in json.loads(r.errors_json)],
            )
            for r in recent_runs(session, limit)
        ]
    )


@router.get("/markets/{market_id}", response_model=MarketDetailOut)
def get_market(
    market_id: Annotated[str, Path(min_length=1, max_length=36)],
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> MarketDetailOut:
    repo = MarketRepository(session, clock)
    m = repo.get(market_id)
    if m is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Market not found")
    rules = repo.current_rules(m.id)
    q = repo.latest_quote(m.id)
    depth = json.loads(q.depth_json) if q else {"yes_bids": [], "no_bids": []}
    return MarketDetailOut(
        **_summary(m, repo, clock, settings.quote_max_age_seconds),
        notional_value=m.notional_value,
        price_ranges=[PriceRange.model_validate(r) for r in json.loads(m.price_ranges_json)],
        rules=RulesOut(
            text=rules.rules_text,
            official_source_url=rules.official_source_url,
            hash=rules.hash,
            observed_at=rules.observed_at,
        )
        if rules
        else None,
        yes_bids=[BookLevelOut(**lvl) for lvl in depth.get("yes_bids", [])],
        no_bids=[BookLevelOut(**lvl) for lvl in depth.get("no_bids", [])],
        updated_at=m.updated_at,
    )
