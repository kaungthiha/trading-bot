"""Performance budgets (generous, to catch order-of-magnitude regressions, not to
benchmark). Sizes approximate several years of real use."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.clock import FrozenClock
from app.core.config import Settings
from app.db.repositories import MarketRepository
from app.db.session import make_engine, make_session_factory
from app.demo import synthetic_cpi
from app.domain.models import BookLevel, MarketSnapshot, MarketStatus, OrderBook, PriceRange
from app.evidence.repository import EvidenceRepository
from app.main import create_app
from app.research.backtest import walk_forward
from app.research.cpi import build_first_prints
from app.research.models import REGISTRY
from app.signals.engine import evaluate
from tests.research_fixtures import as_records
from tests.test_signals import PARAMS, inputs

T = datetime(2026, 11, 18, 15, 0, tzinfo=UTC)
D = Decimal


def timed(fn):  # type: ignore[no-untyped-def]
    t0 = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - t0


def test_walk_forward_both_models_full_history_under_budget() -> None:
    prints = build_first_prints(as_records(synthetic_cpi(date(1960, 1, 1),
                                                         date(2026, 9, 1)))).prints
    assert len(prints) > 750
    for m in REGISTRY.values():
        _, secs = timed(lambda m=m: walk_forward(m, prints))
        assert secs < 15, f"{m.card.name} walk-forward took {secs:.1f}s"


def test_signal_engine_throughput() -> None:
    inp = inputs()
    _, secs = timed(lambda: [evaluate(inp, PARAMS) for _ in range(2000)])
    assert secs < 3, f"2000 evaluations took {secs:.2f}s"


def test_evidence_insert_and_as_of_with_many_vintages(settings: Settings) -> None:
    obs = synthetic_cpi(date(1950, 1, 1), date(2026, 9, 1))
    engine = make_engine(settings.database_url)
    with make_session_factory(engine)() as s:
        _, ins = timed(lambda: EvidenceRepository(s).insert_new("fred:CPIAUCSL", obs))
        s.commit()
        _, dup = timed(lambda: EvidenceRepository(s).insert_new("fred:CPIAUCSL", obs))
        rows, q = timed(lambda: EvidenceRepository(s).as_of("fred:CPIAUCSL", T, 1000))
    engine.dispose()
    assert len(rows) > 900
    assert ins < 10 and dup < 10 and q < 2, (ins, dup, q)


def test_market_list_api_with_many_markets(settings: Settings) -> None:
    engine = make_engine(settings.database_url)
    with make_session_factory(engine)() as s:
        repo = MarketRepository(s, FrozenClock(T))
        for i in range(400):
            repo.upsert_snapshot(MarketSnapshot(
                exchange="kalshi", external_ticker=f"MOCK-PERF-{i:04d}", event_ticker="MOCK-PERF",
                title=f"perf {i}", category="economics", status=MarketStatus.ACTIVE,
                status_raw="active", close_at=T + timedelta(days=i % 30), rules_text=f"r{i}",
                official_source_url=None, notional_value=D("1"),
                price_ranges=(PriceRange(start=D("0"), end=D("1"), step=D("0.01")),),
                orderbook=OrderBook(observed_at=T, yes_bids=(BookLevel(price=D("0.4"),
                                    quantity=D("10")),), no_bids=()), is_mock=True), "perf")
        s.commit()
    engine.dispose()
    app = create_app(settings, FrozenClock(T))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        r, secs = timed(lambda: c.get("/api/markets", params={"limit": 200}))
        assert r.status_code == 200 and len(r.json()["items"]) == 200
        assert secs < 3, f"/api/markets took {secs:.2f}s"
    app.state.engine.dispose()
