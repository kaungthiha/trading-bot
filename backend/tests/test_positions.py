"""Open-position analysis, the stored price trail, combo legs, and the playbook."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.kalshi_public import KalshiPublicClient
from app.catalog.store import CatalogWriter
from app.core.clock import FrozenClock
from app.core.config import KALSHI_REST_BASES, KalshiEnv, Settings
from app.db.models import AccountPosition, AccountSettlement, ComboLeg, PositionMark
from app.db.session import make_engine, make_session_factory
from app.history.analysis import playbook, report
from app.history.combo_legs import combo_breakdown, open_combo, refresh_combo_legs
from app.history.positions import entry_quality, open_analysis, record_marks
from app.history.sync import sync_account
from app.jobs import JobRunner
from app.main import create_app
from tests.test_history import NOW, C, reader

COMBO = "KXMVECROSSCATEGORY-S2026ABC-XYZ"
LEG1, LEG2, LEG3 = "KXNBAGAME-26NOV20BOSDEN-BOS", "KXNBATOTAL-26NOV20BOSDEN-221", \
    "KXNBAPTS-26NOV19NYKMIN-NYKJBRUNSON11-25"


@pytest.fixture
def factory(settings: Settings):  # type: ignore[no-untyped-def]
    engine = make_engine(settings.database_url)
    f = make_session_factory(engine)
    CatalogWriter(f, NOW).write_page([
        {"event_ticker": "KXNBATOTAL-26NOV20BOSDEN", "series_ticker": "KXNBATOTAL",
         "title": "BOS vs DEN total", "mutually_exclusive": False,
         "markets": [{"ticker": C, "title": "Over 220.5", "status": "active",
                      "yes_bid_dollars": "0.3900", "yes_ask_dollars": "0.4100",
                      "close_time": "2026-11-19T01:00:00Z"}]},
        {"event_ticker": "KXNBAGAME-26NOV20BOSDEN", "series_ticker": "KXNBAGAME",
         "title": "Boston vs Denver", "mutually_exclusive": True,
         "markets": [{"ticker": LEG1, "title": "Boston", "status": "active",
                      "yes_bid_dollars": "0.5900", "yes_ask_dollars": "0.6100"}]}])
    yield f
    engine.dispose()


def _pos(f, ticker: str, position: str, exposure: str) -> None:  # type: ignore[no-untyped-def]
    with f() as s:
        s.merge(AccountPosition(ticker=ticker, position=D(position), exposure=D(exposure),
                                realized_pnl=D(0), fees_paid=D(0), total_traded=D(exposure),
                                last_updated=NOW, source="live"))
        s.commit()


def test_marks_are_recorded_once_per_moment(factory) -> None:  # type: ignore[no-untyped-def]
    _pos(factory, C, "4", "2.00")
    _pos(factory, "KXCLOSED-1", "0", "0")
    assert record_marks(factory, NOW, "sync") == 1
    assert record_marks(factory, NOW, "scan") == 1  # same moment: ignored, not duplicated
    record_marks(factory, NOW + timedelta(hours=1), "scan")
    with factory() as s:
        marks = s.query(PositionMark).order_by(PositionMark.at).all()
    assert len(marks) == 2 and marks[0].mid == D("0.4") and marks[0].side == "yes"


def test_open_analysis_marks_flags_and_portfolio(factory) -> None:  # type: ignore[no-untyped-def]
    _pos(factory, C, "4", "2.40")  # bought at 60c, now 40c
    record_marks(factory, NOW - timedelta(hours=2), "sync")
    with factory() as s:
        out = open_analysis(s, None, D("20"), NOW)
    (r,) = out["positions"]
    assert r["side"] == "yes" and r["avg_cost"] == "0.600" and r["mid"] == "0.4"
    assert r["value"] == "1.60" and r["unrealized"] == "-0.80" and r["move_pts"] == -20.0
    assert r["hours_to_close"] == 2.0 and len(r["trail"]) == 1
    texts = " ".join(f["text"] for f in r["flags"])
    assert "Down 20 pts" in texts and "Closes within 3 hours" in texts
    assert "Over 10% of your budget" in texts
    p = out["portfolio"]
    assert p["cost"] == "2.40" and p["max_payout"] == "4.00" and p["budget_share"] == 0.12
    assert out["evidence_enabled"] is False


def test_entry_quality_clv_and_disposition(factory) -> None:  # type: ignore[no-untyped-def]
    with factory() as s:
        s.add(PositionMark(ticker="T1", at=NOW, side="yes", contracts=D(1), cost=D("0.4"),
                           mid=D("0.55"), source="scan"))
        s.commit()
        q = entry_quality(s, [{"ticker": "T1", "status": "settled", "pnl": "0.6",
                               "sold_early": False},
                              {"ticker": "T2", "status": "closed", "pnl": "0.2",
                               "sold_early": True}],
                          {("T1", "yes"): D("0.40"), ("T2", "yes"): D("0.30")})
    assert q["clv"] == {"n": 1, "avg_pts": 15.0, "beat_share": 1.0}
    assert q["early_exits"] == {"n": 1, "in_profit": 1}
    assert q["held_to_settlement"] == {"n": 1, "lost": 0}


def _public(markets: dict[str, dict]) -> KalshiPublicClient:
    def handle(req: httpx.Request) -> httpx.Response:
        t = req.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"market": markets[t]}) if t in markets \
            else httpx.Response(404)
    return KalshiPublicClient(KALSHI_REST_BASES[KalshiEnv.PRODUCTION],
                              transport=httpx.MockTransport(handle), sleep=lambda _: None,
                              min_interval=0.0, max_retries=0)


PUBLIC = {
    COMBO: {"ticker": COMBO, "mve_selected_legs": [
        {"event_ticker": "KXNBAGAME-26NOV20BOSDEN", "market_ticker": LEG1, "side": "yes"},
        {"event_ticker": "KXNBAPTS-26NOV19NYKMIN", "market_ticker": LEG3, "side": "no"}]},
    LEG3: {"ticker": LEG3, "title": "Jalen Brunson: 25+ points", "result": "no"},
}


def test_combo_legs_are_stored_and_valued(factory) -> None:  # type: ignore[no-untyped-def]
    _pos(factory, COMBO, "10", "1.00")
    calls = refresh_combo_legs(factory, _public(PUBLIC), NOW)
    assert calls == 2  # the combo, plus the finished leg (open leg comes from the catalog)
    assert refresh_combo_legs(factory, _public(PUBLIC), NOW) == 0  # settled legs are kept
    with factory() as s:
        c = open_combo(s, COMBO)
        assert c is not None
        assert [x["status"] for x in c["legs"]] == ["open", "won"]  # NO on a leg that lost
        assert c["fair"] == 0.6 and c["won"] == 1 and c["open"] == 1
        out = open_analysis(s, None, None, NOW)
    r = out["positions"][0]
    assert r["title"] == "2-leg combo" and r["value"] == "6.00"
    assert any("1 leg(s) won, 1 still open" in f["text"] for f in r["flags"])


def test_combo_breakdown_and_playbook_rules(factory) -> None:  # type: ignore[no-untyped-def]
    with factory() as s:
        for i in range(12):
            for j in range(6):
                s.add(ComboLeg(combo_ticker=f"KXMVEX-{i}", leg_ticker=f"KXNBAPTS-G{i}-P{j}",
                               event_ticker=f"KXNBAPTS-G{i}", side="yes", title="p",
                               result="no" if j == 0 else "yes", refreshed_at=NOW))
        s.commit()
        b = combo_breakdown(s, {f"KXMVEX-{i}": D("-1") for i in range(12)})
    assert b["avg_legs"] == 6.0 and b["lost"] == 12 and b["lost_by_one"] == 12
    assert b["by_size"] == [{"legs": "6+", "n": 12, "won": 0}]
    assert b["breakers"] == [{"type": "player prop", "legs": 12}]
    rules = [p["rule"] for p in playbook(
        {"budget": "50"}, {"taker_share": 0.95}, [], [],
        {"clv": {"n": 0, "avg_pts": None}, "early_exits": {"n": 0, "in_profit": 0},
         "held_to_settlement": {"n": 0, "lost": 0}}, b)]
    assert rules[0] == "Cap each idea at $2.50"
    assert "Keep combos to 2–3 legs" in rules and "Check player prop legs hardest" in rules
    assert "'One leg away' is the design, not bad luck" in rules
    assert "Rest limit orders instead of crossing the spread" in rules


def test_report_includes_entry_quality_combos_and_playbook(factory) -> None:  # type: ignore[no-untyped-def]
    sync_account(factory, reader(), NOW)
    with factory() as s:
        s.add(AccountSettlement(ticker=COMBO, event_ticker="", market_result="no",
                                yes_count=D(1), yes_cost=D("0.1"), no_count=D(0), no_cost=D(0),
                                revenue=D(0), fee=D(0), settled_at=NOW))
        s.commit()
        rep = report(s, D("50"))
    assert rep["entry_quality"]["held_to_settlement"]["n"] >= 2
    assert rep["combo_breakdown"] == {"combos": 1, "with_legs": 0}
    assert rep["playbook"][0]["rule"] == "Cap each idea at $2.50"


def test_sync_records_marks_and_open_api(settings: Settings, tmp_path: Path) -> None:
    s = Settings(_env_file=None, database_url=settings.database_url,
                 experiment_budget_dollars="50", sports_evidence_enabled=False)
    engine = make_engine(s.database_url)
    f = make_session_factory(engine)
    runner = JobRunner(s, f, FrozenClock(NOW), synchronous=True, account_factory=reader,
                       client_factory=lambda: _public({}), worker_lock_path=tmp_path / "w.lock")
    app = create_app(s, FrozenClock(NOW), jobs=runner)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.post("/api/jobs/history/run", headers={"X-KRT-Request": "ops"})
        with f() as sess:
            assert sess.query(PositionMark).count() == 1  # C is the one open position
        out = c.get("/api/history/open").json()
        assert out["portfolio"]["count"] == 1 and out["positions"][0]["ticker"] == C
        assert out["evidence_enabled"] is False
    engine.dispose()



def test_coach_runs_on_the_local_model_with_csrf_and_cache(settings: Settings, tmp_path: Path,
                                                          monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import json

    import app.api.history_routes as hr
    from app.sportsdata import llm

    sent: list[dict] = []

    def handle(req: httpx.Request) -> httpx.Response:
        sent.append(json.loads(req.content))
        return httpx.Response(200, json={"model": "gemma4:12b", "message": {"content": json.dumps({
            "summary": "Combos are the leak.", "strengths": [], "leaks": ["9.4 legs per combo"],
            "rules_for_next_50": ["Max 3 legs"], "questions": ["Why 9 legs?"],
            "open_positions": [{"ticker": C, "note": "Down vs entry"}]})}})

    monkeypatch.setattr(hr, "local_reviewer", lambda s: llm.OllamaReviewer(llm.OllamaClient(
        "http://127.0.0.1:11434", "gemma4:12b", transport=httpx.MockTransport(handle))))
    s = Settings(_env_file=None, database_url=settings.database_url,
                 experiment_budget_dollars="50", sports_evidence_enabled=False)
    engine = make_engine(s.database_url)
    f = make_session_factory(engine)
    runner = JobRunner(s, f, FrozenClock(NOW), synchronous=True, account_factory=reader,
                       client_factory=lambda: _public({}), worker_lock_path=tmp_path / "w.lock")
    app = create_app(s, FrozenClock(NOW), jobs=runner)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.post("/api/jobs/history/run", headers={"X-KRT-Request": "ops"})
        assert c.post("/api/history/coach").status_code == 403
        out = c.post("/api/history/coach", headers={"X-KRT-Request": "review"}).json()
        assert out["rules_for_next_50"] == ["Max 3 legs"] and out["cached"] is False
        assert out["open_positions"] == [{"ticker": C, "note": "Down vs entry"}]
        facts = json.loads(sent[0]["messages"][1]["content"])
        assert facts["summary"]["realized_pnl"] == "2.51"
        assert facts["open_positions"][0]["ticker"] == C
        assert facts["rule_based_playbook"][0]["rule"] == "Cap each idea at $2.50"
        again = c.post("/api/history/coach", headers={"X-KRT-Request": "review"}).json()
        assert again["cached"] is True and len(sent) == 1
    engine.dispose()


def test_open_review_reads_each_position_with_ids_csrf_and_cache(
        settings: Settings, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import json

    import app.api.history_routes as hr
    from app.sportsdata import llm

    sent: list[dict] = []

    def handle(req: httpx.Request) -> httpx.Response:
        sent.append(json.loads(req.content))
        return httpx.Response(200, json={"model": "gemma4:12b", "message": {"content": json.dumps({
            "summary": "One position, down from entry.",
            "positions": [{"id": "P1", "stance": "reconsider", "read": "Paid 60c, now 40c.",
                           "plan": "Reassess under 30c", "sources": ["H9"]},
                          {"id": "P7", "stance": "on_track", "read": "invented", "plan": "x"}],
            "portfolio": ["P1 is all in one game"], "check": ["Starting lineups"]})}})

    monkeypatch.setattr(hr, "local_reviewer", lambda s: llm.OllamaReviewer(llm.OllamaClient(
        "http://127.0.0.1:11434", "gemma4:12b", transport=httpx.MockTransport(handle))))
    s = Settings(_env_file=None, database_url=settings.database_url,
                 experiment_budget_dollars="50", sports_evidence_enabled=False)
    engine = make_engine(s.database_url)
    f = make_session_factory(engine)
    runner = JobRunner(s, f, FrozenClock(NOW), synchronous=True, account_factory=reader,
                       client_factory=lambda: _public({}), worker_lock_path=tmp_path / "w.lock")
    app = create_app(s, FrozenClock(NOW), jobs=runner)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.post("/api/jobs/history/run", headers={"X-KRT-Request": "ops"})
        assert c.post("/api/history/open/review").status_code == 403
        out = c.post("/api/history/open/review", headers={"X-KRT-Request": "review"}).json()
        # unknown id P7 and unknown source H9 are dropped; the id maps back to the ticker
        assert out["positions"] == [{"ticker": C, "stance": "reconsider",
                                     "read": "Paid 60c, now 40c.", "plan": "Reassess under 30c",
                                     "sources": []}]
        assert out["portfolio"] == [f"“{C}” is all in one game"]  # id -> name (ticker here)
        assert out["cached"] is False
        facts = json.loads(sent[0]["messages"][1]["content"])
        assert facts["positions"][0]["id"] == "P1" and facts["budget"] == "50"
        assert "ticker" not in facts["positions"][0]  # the model works with ids only
        again = c.post("/api/history/open/review", headers={"X-KRT-Request": "review"}).json()
        assert again["cached"] is True and len(sent) == 1
    engine.dispose()
