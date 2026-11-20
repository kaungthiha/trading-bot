from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import ops
from app.cli import alembic_config
from app.core.clock import FrozenClock
from app.core.config import Settings
from app.core.lock import SingleInstanceLock
from app.db.models import EvidenceRecord, Market, Signal
from app.db.session import make_engine, make_session_factory
from app.demo import build_demo
from app.main import create_app
from tests.conftest import FROZEN_NOW

HEAD = "0015_search_ledger"


def _count_markets(url: str) -> int:
    engine = make_engine(url)
    with make_session_factory(engine)() as s:
        n = len(s.scalars(select(Market)).all())
    engine.dispose()
    return n


def test_backup_restore_round_trip(seeded: Settings, tmp_path: Path) -> None:
    url, bdir, lock = seeded.database_url, tmp_path / "backups", tmp_path / "w.lock"
    before = _count_markets(url)
    b = ops.backup(url, bdir)
    assert ops.validate_backup(b) == HEAD
    ops.reset(url, alembic_config, lock_path=lock, backup_dir=bdir)
    assert _count_markets(url) == 0
    safety, rev = ops.restore(url, b, alembic_config, lock_path=lock, backup_dir=bdir)
    assert rev == HEAD and safety is not None and safety.exists()
    assert _count_markets(url) == before
    assert len(ops.list_backups(bdir)) == 3  # manual + pre-reset + pre-restore


def test_restore_rejects_non_database_and_foreign_db(seeded: Settings, tmp_path: Path) -> None:
    junk = tmp_path / "junk.sqlite3"
    junk.write_bytes(b"not sqlite at all" * 100)
    with pytest.raises(ops.OpsError):
        ops.validate_backup(junk)
    other = tmp_path / "other.sqlite3"
    with sqlite3.connect(other) as c:
        c.execute("CREATE TABLE t (x)")
    with pytest.raises(ops.OpsError, match="not a Kalshi"):
        ops.validate_backup(other)


def test_restore_refuses_while_worker_runs(seeded: Settings, tmp_path: Path) -> None:
    lock = tmp_path / "w.lock"
    b = ops.backup(seeded.database_url, tmp_path)
    with SingleInstanceLock(lock), pytest.raises(ops.OpsError, match="worker is running"):
        ops.restore(seeded.database_url, b, alembic_config, lock_path=lock, backup_dir=tmp_path)


def test_memory_db_not_supported() -> None:
    with pytest.raises(ops.OpsError):
        ops.sqlite_path("sqlite:///:memory:")


def test_demo_database_is_synthetic_isolated_and_populated(tmp_path: Path) -> None:
    path = tmp_path / "demo.sqlite3"
    summary = build_demo(path, cfg_factory=alembic_config)
    assert summary["markets"] == 7 and summary["signals"] == 7
    assert summary["candidates"] >= 1 and summary["paper_orders"] >= 1
    engine = make_engine(f"sqlite:///{path.as_posix()}")
    with make_session_factory(engine)() as s:
        markets = s.scalars(select(Market)).all()
        assert all(m.is_mock and m.external_ticker.startswith("MOCK-") for m in markets)
        ev = s.scalars(select(EvidenceRecord).limit(5)).all()
        assert all(e.source_url == "synthetic://demo" and "SYNTHETIC" in e.license_notes
                   for e in ev)
        assert {g.fee_schedule_version for g in s.scalars(select(Signal))} == {
            "demo-synthetic-fees"}
    engine.dispose()
    again = build_demo(path, cfg_factory=alembic_config)  # rebuild is deterministic
    assert again["first_prints"] == summary["first_prints"]


def test_setup_status_and_diagnostics_on_fresh_db(seeded: Settings) -> None:
    app = create_app(seeded, FrozenClock(FROZEN_NOW))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        st = c.get("/api/setup-status").json()
        assert st["paper_mode"] is True and st["complete"] is False
        status = {x["key"]: x["status"] for x in st["steps"]}
        assert status["fred_key"] == "todo" and status["fees"] == "ok"  # PDF-verified
        assert all(x["hint"] for x in st["steps"])
        d = c.get("/api/diagnostics").json()
        assert d["schema_revision"] == HEAD and d["database_bytes"] > 0
        assert d["quotes"]["markets_with_quotes"] == 4
        assert "api_key" not in str(d).lower() and "secret" not in str(d).lower()
        assert c.get("/api/lineage/signal/nope").status_code == 404
        assert c.get("/api/lineage/paper-order/nope").status_code == 404
    app.state.engine.dispose()
