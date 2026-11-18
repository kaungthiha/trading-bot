from __future__ import annotations

import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient

from app.adapters.fixture_market import FixtureMarketAdapter
from app.cli import alembic_config
from app.core.clock import FrozenClock
from app.core.config import Settings
from app.db.repositories import MarketRepository
from app.db.session import make_engine, make_session_factory
from app.main import create_app

FROZEN_NOW = datetime(2026, 11, 18, 15, 0, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that tries to open a non-loopback network connection."""
    real_connect = socket.socket.connect

    def guarded(self: socket.socket, address) -> None:  # type: ignore[no-untyped-def]
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise RuntimeError(f"Network access blocked in tests: {host!r}")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(FROZEN_NOW)


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'test.sqlite3').as_posix()}"


@pytest.fixture
def migrated_db(db_url: str) -> str:
    command.upgrade(alembic_config(db_url), "head")
    return db_url


@pytest.fixture
def settings(migrated_db: str) -> Settings:
    # _env_file=None so a developer's real .env never leaks into tests.
    return Settings(_env_file=None, database_url=migrated_db, quote_max_age_seconds=60)


@pytest.fixture
def seeded(settings: Settings, clock: FrozenClock) -> Settings:
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    with factory() as s:
        repo = MarketRepository(s, clock)
        for snap in FixtureMarketAdapter().list_markets():
            repo.upsert_snapshot(snap, source="fixture")
        s.commit()
    engine.dispose()
    return settings


@pytest.fixture
def client(seeded: Settings, clock: FrozenClock) -> TestClient:
    app = create_app(seeded, clock)
    # TestClient's default host is "testserver"; use an allow-listed loopback host.
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c
    app.state.engine.dispose()
