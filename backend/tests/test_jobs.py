"""UI job buttons: refresh / evidence / scan / auto-scan (synchronous runner, mock HTTP)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.adapters.kalshi_public import KalshiPublicClient
from app.core.clock import FrozenClock
from app.core.config import KALSHI_REST_BASES, KalshiEnv, Settings
from app.core.lock import SingleInstanceLock
from app.db.session import make_engine, make_session_factory
from app.jobs import JobRunner
from app.main import create_app
from tests.kalshi_payloads import DEFAULT_BOOK, SERIES, market
from tests.test_scanner import BOOKS, EVENTS

NOW = datetime(2026, 11, 18, 23, 0, tzinfo=UTC)
HDR = {"X-KRT-Request": "ops"}


def client_factory():  # type: ignore[no-untyped-def]
    routes = {"/events": EVENTS, **BOOKS,
              "/series/TESTCPI": SERIES,
              "/events/TESTCPI-26DEC": {"event": {"event_ticker": "TESTCPI-26DEC",
                                                  "fee_type_override": None,
                                                  "fee_multiplier_override": None}},
              "/markets": {"markets": [market("TESTCPI-26DEC-T3.0")], "cursor": ""},
              "/markets/TESTCPI-26DEC-T3.0/orderbook": DEFAULT_BOOK}

    def handle(req: httpx.Request) -> httpx.Response:
        body = routes.get(req.url.path.removeprefix("/trade-api/v2"))
        return httpx.Response(200, json=body) if body is not None else httpx.Response(404)

    return lambda: KalshiPublicClient(KALSHI_REST_BASES[KalshiEnv.PRODUCTION],
                                      transport=httpx.MockTransport(handle),
                                      sleep=lambda _: None, min_interval=0.0, max_retries=0)


def make(settings: Settings, tmp_path: Path, **over):  # type: ignore[no-untyped-def]
    s = Settings(_env_file=None, database_url=settings.database_url,
                 kalshi_series_watchlist=["TESTCPI"], experiment_budget_dollars="50", **over)
    engine = make_engine(s.database_url)
    runner = JobRunner(s, make_session_factory(engine), FrozenClock(NOW), synchronous=True,
                       client_factory=client_factory(), worker_lock_path=tmp_path / "w.lock")
    return s, runner, engine


def test_buttons_run_jobs_and_report_status(settings: Settings, tmp_path: Path) -> None:
    s, runner, engine = make(settings, tmp_path)
    app = create_app(s, FrozenClock(NOW), jobs=runner)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.post("/api/jobs/scan/run").status_code == 403  # CSRF header required
        r = c.post("/api/jobs/refresh/run", headers=HDR)
        assert r.status_code == 202 and r.json()["started"] is True
        st = c.get("/api/jobs").json()
        ref = st["jobs"]["refresh"]
        assert ref["running"] is False and ref["last_status"] == "success"
        assert "1 markets from TESTCPI" in ref["last_message"]
        scan = c.post("/api/jobs/scan/run", headers=HDR).json()["jobs"]["scan"]
        assert scan["last_status"] == "success" and "1 new card" in scan["last_message"]
        ev = c.post("/api/jobs/evidence/run", headers=HDR).json()["jobs"]["evidence"]
        assert ev["last_status"] == "failed" and "KRT_FRED_API_KEY" in ev["last_message"]
        assert c.post("/api/jobs/bogus/run", headers=HDR).status_code == 404
        assert st["watchlist"] == ["TESTCPI"] and st["worker_running"] is False
    app.state.engine.dispose()
    engine.dispose()


def test_single_flight(settings: Settings, tmp_path: Path) -> None:
    s, runner, engine = make(settings, tmp_path)
    runner._locks["scan"].acquire()  # simulate a scan already in progress
    assert runner.run("scan") is False
    runner._locks["scan"].release()
    engine.dispose()


def test_auto_scan_refused_while_worker_runs(settings: Settings, tmp_path: Path) -> None:
    s, runner, engine = make(settings, tmp_path)
    app = create_app(s, FrozenClock(NOW), jobs=runner)
    with SingleInstanceLock(tmp_path / "w.lock"), TestClient(app,
                                                              base_url="http://127.0.0.1") as c:
        r = c.post("/api/jobs/auto-scan", json={"enabled": True}, headers=HDR)
        assert r.status_code == 409 and "worker" in r.json()["error"]["message"]
        assert c.get("/api/jobs").json()["worker_running"] is True
    app.state.engine.dispose()
    engine.dispose()


def test_auto_scan_toggle(settings: Settings, tmp_path: Path) -> None:
    s, runner, engine = make(settings, tmp_path, scanner_interval_seconds=3600)
    app = create_app(s, FrozenClock(NOW), jobs=runner)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        on = c.post("/api/jobs/auto-scan", json={"enabled": True}, headers=HDR).json()
        assert on["auto_scan"]["enabled"] is True and on["auto_scan"]["interval_seconds"] == 3600
        off = c.post("/api/jobs/auto-scan", json={"enabled": False}, headers=HDR).json()
        assert off["auto_scan"]["enabled"] is False
    runner.shutdown()
    app.state.engine.dispose()
    engine.dispose()


def test_crashing_job_reports_failure_and_unlocks(settings: Settings, tmp_path: Path) -> None:
    s, runner, engine = make(settings, tmp_path)

    def boom():  # type: ignore[no-untyped-def]
        raise RuntimeError("kaboom")

    runner._job_scan = boom  # type: ignore[method-assign]
    assert runner.run("scan") is True
    st = runner.state["scan"]
    assert st.last_status == "failed" and "kaboom" in st.last_message and not st.running
    assert runner.run("scan") is True  # lock released after failure
    engine.dispose()
