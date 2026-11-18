from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.adapters.base import AdapterError, FetchResult
from app.adapters.kalshi_public import KalshiPublicClient, KalshiPublicMarketAdapter
from app.core.clock import FrozenClock
from app.core.config import KALSHI_REST_BASES, KalshiEnv, Settings
from app.db.models import IngestionRun, Market, QuoteSnapshot
from app.db.session import make_engine, make_session_factory
from app.ingest import run_ingestion
from app.main import create_app
from tests.conftest import FROZEN_NOW
from tests.kalshi_payloads import DEFAULT_BOOK, SERIES, market, orderbook


def kalshi_adapter(routes: dict[str, object]) -> KalshiPublicMarketAdapter:
    def handle(req: httpx.Request) -> httpx.Response:
        body = routes.get(req.url.path.removeprefix("/trade-api/v2"))
        return httpx.Response(200, json=body) if body is not None else httpx.Response(404)

    client = KalshiPublicClient(
        KALSHI_REST_BASES[KalshiEnv.PRODUCTION],
        transport=httpx.MockTransport(handle),
        sleep=lambda _: None,
        min_interval=0.0,
        max_retries=0,
    )
    return KalshiPublicMarketAdapter(client, FrozenClock(FROZEN_NOW), series_watchlist=["TESTCPI"])


ROUTES: dict[str, object] = {
    "/series/TESTCPI": SERIES,
    "/markets": {
        "markets": [
            market("TESTCPI-26DEC-T3.0"),
            market("TESTCPI-26DEC-SCALAR", market_type="scalar"),
            market("TESTCPI-26DEC-BAD"),
        ],
        "cursor": "",
    },
    "/markets/TESTCPI-26DEC-T3.0/orderbook": DEFAULT_BOOK,
    "/markets/TESTCPI-26DEC-SCALAR/orderbook": orderbook(yes=[["0.3000", "5.00"]],
                                                         no=[["0.6000", "5.00"]]),
    "/markets/TESTCPI-26DEC-BAD/orderbook": {"nope": 1},
}


@pytest.fixture
def factory(settings: Settings):  # type: ignore[no-untyped-def]
    engine = make_engine(settings.database_url)
    yield make_session_factory(engine)
    engine.dispose()


def test_kalshi_ingestion_persists_and_records_partial(factory, clock: FrozenClock) -> None:  # type: ignore[no-untyped-def]
    summary = run_ingestion(kalshi_adapter(ROUTES), factory, clock)
    assert summary.status == "partial"
    assert summary.count == 2
    assert [e.scope for e in summary.errors] == ["market:TESTCPI-26DEC-BAD"]

    with factory() as s:
        run = s.get(IngestionRun, summary.run_id)
        assert run.status == "partial" and run.count == 2 and run.finished_at is not None
        m = s.scalar(select(Market).where(Market.external_ticker == "TESTCPI-26DEC-T3.0"))
        assert m.category == "economics" and m.series_ticker == "TESTCPI" and not m.is_mock
        q = s.scalar(select(QuoteSnapshot).where(QuoteSnapshot.market_id == m.id))
        assert q.yes_ask_derived == Decimal("0.4500") and q.no_ask_derived == Decimal("0.5700")
        assert q.raw_ref == "kalshi_public:TESTCPI-26DEC-T3.0"

        scalar = s.scalar(select(Market).where(Market.external_ticker == "TESTCPI-26DEC-SCALAR"))
        sq = s.scalar(select(QuoteSnapshot).where(QuoteSnapshot.market_id == scalar.id))
        # Complement derivation not verified for scalar markets: bids only, no asks.
        assert sq.yes_bid == Decimal("0.3000")
        assert sq.yes_ask_derived is None and sq.no_ask_derived is None


def test_repeated_ingestion_same_observation_no_duplicates(factory, clock) -> None:  # type: ignore[no-untyped-def]
    run_ingestion(kalshi_adapter(ROUTES), factory, clock)
    run_ingestion(kalshi_adapter(ROUTES), factory, clock)  # same frozen observed_at
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Market)) == 2
        assert s.scalar(select(func.count()).select_from(QuoteSnapshot)) == 2
        assert s.scalar(select(func.count()).select_from(IngestionRun)) == 2


def test_total_failure_recorded_as_failed(factory, clock) -> None:  # type: ignore[no-untyped-def]
    class Down:
        name = "down"

        def fetch_markets(self) -> FetchResult:
            raise AdapterError("source down")

    summary = run_ingestion(Down(), factory, clock)
    assert summary.status == "failed" and summary.count == 0
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Market)) == 0


def test_api_filters_quotes_and_runs(seeded: Settings, clock: FrozenClock) -> None:
    engine = make_engine(seeded.database_url)
    run_ingestion(kalshi_adapter(ROUTES), make_session_factory(engine), clock)
    engine.dispose()

    app = create_app(seeded, clock)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.get("/api/categories").json()["items"] == ["economics", "nba", "technology"]

        active = c.get("/api/markets", params={"status": "active"}).json()["items"]
        assert all(m["status"] == "active" for m in active) and len(active) == 5
        assert c.get("/api/markets", params={"status": "bogus"}).status_code == 422

        by_series = c.get("/api/markets", params={"series_ticker": "TESTCPI"}).json()["items"]
        assert {m["external_ticker"] for m in by_series} == {
            "TESTCPI-26DEC-T3.0", "TESTCPI-26DEC-SCALAR"}
        scalar = next(m for m in by_series if m["market_type"] == "scalar")
        assert scalar["quote"]["yes_ask"] is None
        assert scalar["quote"]["yes_ask_provenance"] is None

        found = c.get("/api/markets", params={"q": "fomc"}).json()["items"]
        assert [m["external_ticker"] for m in found] == ["MOCK-FEDRATE-26DEC-CUT"]
        # LIKE wildcards in user input are literal, not wildcards.
        assert c.get("/api/markets", params={"q": "_"}).json()["items"] == []
        pct = c.get("/api/markets", params={"q": "%"}).json()["items"]
        assert [m["external_ticker"] for m in pct] == ["MOCK-CPIYOY-26DEC-T3.0"]  # "3.0%"

        mid = by_series[0]["id"]
        hist = c.get(f"/api/markets/{mid}/quotes").json()
        assert hist["market_id"] == mid and len(hist["items"]) == 1
        assert c.get("/api/markets/nope/quotes").status_code == 404

        runs = c.get("/api/ingestion/runs").json()["items"]
        assert runs[0]["adapter"] == "kalshi_public" and runs[0]["status"] == "partial"
        assert runs[0]["errors"][0]["scope"] == "market:TESTCPI-26DEC-BAD"
    app.state.engine.dispose()
