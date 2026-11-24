"""Background research jobs (Phase 6): an explicit POST queues work and returns at once;
polling reports the stage and returns the result; nothing else starts work or searches."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.errors import ApiError, ErrorCode
from app.core.config import Settings
from app.investigate import jobs
from app.investigate import schemas as S
from app.sportsdata.news import NewsSearch
from tests.test_nhl import KEY, TOTAL, WIN, H, MPServer, _app, _hockey_result
from tests.test_research_search import Brave, art

T0 = datetime(2026, 11, 19, 15, 0, tzinfo=UTC)


def wait(pred: Any, timeout: float = 10.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


# --- the queue itself ------------------------------------------------------------------------


def test_queue_order_join_cancel_cap_and_failures() -> None:
    clock = {"now": T0}
    q = jobs.JobQueue(lambda: clock["now"], max_queued=2)
    gate = threading.Event()

    def slow(job: jobs.Job) -> S.Result:
        job.phase = "searching"
        gate.wait(5)
        return _hockey_result()

    a = q.submit("investigate", "T-A", "yes", slow)
    wait(lambda: a.status == "running")
    assert a.phase == "searching" and q.position(a) == 0
    b = q.submit("investigate", "T-B", "yes", lambda j: _hockey_result())
    c = q.submit("investigate", "T-C", "no", lambda j: _hockey_result())
    assert q.position(b) == 1 and q.position(c) == 2  # running job counts as one ahead
    # The same pick again joins the existing job instead of running twice.
    assert q.submit("investigate", "T-B", "yes", lambda j: _hockey_result()) is b
    with pytest.raises(jobs.QueueFull):
        q.submit("investigate", "T-D", "yes", lambda j: _hockey_result())
    assert q.cancel(c.id) and c.status == "cancelled"
    assert not q.cancel(a.id)  # running: can't be interrupted
    assert q.active_for("T-B", "yes") is b and q.active_for("T-C", "no") is None
    gate.set()
    wait(lambda: b.status == "done")
    assert a.status == "done" and a.result is not None
    view = q.view(a)
    assert view["status"] == "done" and view["result"]["investigation_id"] == "h1"
    assert q.view(b)["position"] == 0
    # Expected failures say why; unexpected ones don't leak internals.
    bad = q.submit(
        "investigate",
        "T-E",
        "yes",
        lambda j: (_ for _ in ()).throw(
            ApiError(422, ErrorCode.VALIDATION_ERROR, "Period markets aren't covered")
        ),
    )
    boom = q.submit(
        "investigate",
        "T-F",
        "yes",
        lambda j: (_ for _ in ()).throw(RuntimeError("secret internals")),
    )
    wait(lambda: boom.status == "failed")
    assert bad.status == "failed" and bad.error == "Period markets aren't covered"
    assert "secret" not in (boom.error or "") and "unexpectedly" in (boom.error or "")
    assert q.view(bad)["result"] is None
    # Finished jobs are forgotten after an hour.
    clock["now"] = T0 + timedelta(hours=2)
    assert q.get(a.id) is None
    q.shutdown()


# --- through the API -------------------------------------------------------------------------


def _start(c: TestClient, **over: Any) -> dict[str, Any]:
    body = {"kind": "investigate", "ticker": WIN, "side": "yes"} | over
    r = c.post("/api/research/jobs", json=body, headers=H)
    assert r.status_code == 202, r.text
    return r.json()


def _until_done(c: TestClient, job_id: str) -> dict[str, Any]:
    out: dict[str, Any] = {}

    def done() -> bool:
        out.update(c.get(f"/api/research/jobs/{job_id}").json())
        return out["status"] in ("done", "failed", "cancelled")

    wait(done)
    return out


def test_job_runs_in_background_and_saves_the_result(settings: Settings) -> None:
    server = MPServer()
    with TestClient(_app(settings, server), base_url="http://127.0.0.1") as c:
        job = _start(c)
        assert job["status"] in ("queued", "running") and job["result"] is None
        assert job["ticker"] == WIN and job["kind"] == "investigate"
        done = _until_done(c, job["id"])
        stored = c.get(f"/api/research/investigations/{done['result']['investigation_id']}")
        pre = c.get("/api/research/preflight", params={"ticker": WIN, "side": "yes"}).json()
        # A refresh job for the same pick, by id.
        ref = _start(c, kind="refresh", investigation_id=done["result"]["investigation_id"])
        ref_done = _until_done(c, ref["id"])
    assert done["status"] == "done" and done["error"] is None
    assert done["result"]["hypothesis"]["ticker"] == WIN
    assert stored.status_code == 200 and stored.json()["sources"][1]["id"] == "M1"
    assert pre["cached"] is True and pre["job"] is None  # finished: nothing to resume
    assert ref_done["status"] == "done"
    assert ref_done["result"]["investigation_id"] != done["result"]["investigation_id"]


def test_failures_validation_and_csrf(settings: Settings) -> None:
    with TestClient(_app(settings, MPServer()), base_url="http://127.0.0.1") as c:
        r = c.post("/api/research/jobs", json={"kind": "investigate", "ticker": WIN, "side": "yes"})
        assert r.status_code == 403  # no CSRF header: nothing queued
        bad = _start(c, ticker=f"KXNHL1P-{KEY}-BOS")
        failed = _until_done(c, bad["id"])
        assert failed["status"] == "failed" and "Period markets" in failed["error"]
        assert (
            c.post(
                "/api/research/jobs",
                json={"kind": "refresh", "ticker": WIN, "side": "yes"},
                headers=H,
            ).status_code
            == 422
        )  # refresh without an id
        lost = _start(c, kind="refresh", investigation_id="nope")
        assert "not found" in _until_done(c, lost["id"])["error"]
        assert c.get("/api/research/jobs/not-a-uuid").status_code == 422
        unknown = c.get("/api/research/jobs/00000000-0000-0000-0000-000000000000")
        assert unknown.status_code == 404 and "restarted" in unknown.json()["error"]["message"]
        assert (
            c.post(
                "/api/research/jobs/00000000-0000-0000-0000-000000000000/cancel", headers=H
            ).status_code
            == 404
        )


def test_polling_and_preflight_never_search_and_phases_are_reported(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import investigate_routes

    seen_phase: list[str] = []
    brave = Brave(
        [
            art(
                "Swayman gets the start for Bruins vs. Rangers",
                "https://www.dailyfaceoff.com/a",
                "Bruins goalie will start.",
            )
        ]
    )
    app = _app(settings, MPServer(), brave_search_api_key="test-key")
    real = brave.handler

    def handler(req: httpx.Request) -> httpx.Response:
        q = app.state.research_jobs
        seen_phase.extend(j.phase for j in q._jobs.values() if j.status == "running")
        return real(req)

    monkeypatch.setattr(
        investigate_routes,
        "NewsSearch",
        lambda key, **kw: NewsSearch(key, transport=httpx.MockTransport(handler), **kw),
    )
    with TestClient(app, base_url="http://127.0.0.1") as c:
        for _ in range(3):  # opening the drawer / polling: free
            c.get("/api/research/preflight", params={"ticker": TOTAL, "side": "yes"})
        assert brave.calls == 0
        job = _start(c, ticker=TOTAL)
        done = _until_done(c, job["id"])
        for _ in range(3):
            c.get(f"/api/research/jobs/{job['id']}")
        calls_after = brave.calls
        c.get("/api/research/preflight", params={"ticker": TOTAL, "side": "yes"})
    assert done["status"] == "done" and calls_after == 4 and brave.calls == 4
    assert set(seen_phase) == {"searching"}


def test_double_post_joins_and_preflight_shows_the_running_job(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import investigate_routes

    gate = threading.Event()
    real_run = investigate_routes._run

    def held(*a: Any, **kw: Any) -> Any:
        gate.wait(5)
        return real_run(*a, **kw)

    monkeypatch.setattr(investigate_routes, "_run", held)
    with TestClient(_app(settings, MPServer()), base_url="http://127.0.0.1") as c:
        a = _start(c)
        b = _start(c)  # a double click
        pre = c.get("/api/research/preflight", params={"ticker": WIN, "side": "yes"}).json()
        other = _start(c, side="no")
        cancelled = c.post(f"/api/research/jobs/{other['id']}/cancel", headers=H).json()
        running = c.post(f"/api/research/jobs/{a['id']}/cancel", headers=H)
        gate.set()
        done = _until_done(c, a["id"])
    assert a["id"] == b["id"]
    assert pre["job"]["id"] == a["id"] and pre["job"]["status"] in ("queued", "running")
    assert cancelled["status"] == "cancelled"
    assert running.status_code == 409
    assert done["status"] == "done"
