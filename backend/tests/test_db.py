from datetime import timedelta
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import func, inspect, select

from app.adapters.fixture_market import FixtureMarketAdapter
from app.cli import alembic_config
from app.core.clock import FrozenClock
from app.db.models import Market, MarketRuleVersion, QuoteSnapshot
from app.db.repositories import MarketRepository
from app.db.session import make_engine, make_session_factory

TABLES = {
    "markets",
    "market_rule_versions",
    "quote_snapshots",
    "audit_events",
    "ingestion_runs",
    "evidence_records",
    "collection_gaps",
    "model_runs",
    "model_evaluations",
    "market_mappings",
    "signals",
    "paper_orders",
    "paper_fills",
    "paper_settlements",
    "paper_ledger",
    "execution_intents",
    "execution_approvals",
    "execution_events",
    "exchange_orders",
    "execution_controls",
}


def test_downgrade_one_step_drops_only_0002(db_url: str) -> None:
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0002_kalshi_read_only")
    engine = make_engine(db_url)
    names = set(inspect(engine).get_table_names())
    assert "evidence_records" not in names and "ingestion_runs" in names
    command.downgrade(cfg, "0001_initial")
    names = set(inspect(engine).get_table_names())
    assert "ingestion_runs" not in names and "markets" in names
    cols = {c["name"] for c in inspect(engine).get_columns("markets")}
    assert "series_ticker" not in cols
    engine.dispose()


def test_migration_up_down_up(db_url: str) -> None:
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    engine = make_engine(db_url)
    assert TABLES <= set(inspect(engine).get_table_names())
    command.downgrade(cfg, "base")
    assert not TABLES & set(inspect(engine).get_table_names())
    command.upgrade(cfg, "head")
    assert TABLES <= set(inspect(engine).get_table_names())
    engine.dispose()


@pytest.fixture
def session(migrated_db: str):  # type: ignore[no-untyped-def]
    engine = make_engine(migrated_db)
    with make_session_factory(engine)() as s:
        yield s
    engine.dispose()


def _count(session, model) -> int:  # type: ignore[no-untyped-def]
    return session.scalar(select(func.count()).select_from(model))


def test_reseed_is_idempotent(session, clock: FrozenClock) -> None:  # type: ignore[no-untyped-def]
    repo = MarketRepository(session, clock)
    snaps = FixtureMarketAdapter().list_markets()
    for _ in range(3):
        for snap in snaps:
            repo.upsert_snapshot(snap, "fixture")
        session.commit()
    assert _count(session, Market) == len(snaps)
    assert _count(session, QuoteSnapshot) == len(snaps)
    assert _count(session, MarketRuleVersion) == len(snaps)


def test_rule_change_appends_version(session, clock: FrozenClock) -> None:  # type: ignore[no-untyped-def]
    repo = MarketRepository(session, clock)
    snap = FixtureMarketAdapter().list_markets()[0]
    m = repo.upsert_snapshot(snap, "fixture")
    old_hash = repo.current_rules(m.id).hash
    repo.upsert_snapshot(snap.model_copy(update={"rules_text": snap.rules_text + " AMENDED"}), "f")
    session.commit()
    versions = session.scalars(
        select(MarketRuleVersion).where(MarketRuleVersion.market_id == m.id)
    ).all()
    assert len(versions) == 2
    assert sum(v.is_current for v in versions) == 1
    assert repo.current_rules(m.id).hash != old_hash


def test_new_observation_appends_quote_and_preserves_old(session, clock) -> None:  # type: ignore[no-untyped-def]
    repo = MarketRepository(session, clock)
    snap = FixtureMarketAdapter().list_markets()[0]
    m = repo.upsert_snapshot(snap, "fixture")
    later = snap.orderbook.model_copy(
        update={"observed_at": snap.orderbook.observed_at + timedelta(minutes=1)}
    )
    repo.upsert_snapshot(snap.model_copy(update={"orderbook": later}), "fixture")
    session.commit()
    assert _count(session, QuoteSnapshot) == 2
    latest = repo.latest_quote(m.id)
    assert latest.observed_at == later.observed_at
    assert latest.yes_ask_derived == Decimal("0.45")


def test_decimal_round_trip_exact(session, clock) -> None:  # type: ignore[no-untyped-def]
    repo = MarketRepository(session, clock)
    snap = FixtureMarketAdapter().list_markets()[0]
    m = repo.upsert_snapshot(snap, "fixture")
    session.commit()
    session.expire_all()
    q = repo.latest_quote(m.id)
    assert q.yes_bid == Decimal("0.43") and str(q.yes_bid) == "0.43"
    assert q.observed_at.tzinfo is not None
