"""Account history: read-only signed client, sync, P&L/reconciliation, analysis, API."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi.testclient import TestClient

from app.catalog.store import CatalogWriter
from app.core.clock import FrozenClock
from app.core.config import KALSHI_REST_BASES, KalshiEnv, Settings
from app.db.models import AccountFill, AccountSync
from app.db.session import make_engine, make_session_factory
from app.execution.signing import Signer
from app.history.analysis import market_type, report
from app.history.client import READ_PATHS, AccountError, AccountReader
from app.history.sync import side_and_action, sync_account
from app.jobs import JobRunner
from app.main import create_app

NOW = datetime(2026, 11, 18, 23, 0, tzinfo=UTC)
BASE = KALSHI_REST_BASES[KalshiEnv.PRODUCTION]
SIGNER = Signer("test-key-id", ed25519.Ed25519PrivateKey.generate())


def fill(fid: str, ticker: str, count: str, yes: str, fee: str, at: str, **kw: object) -> dict:
    return {"fill_id": fid, "trade_id": fid, "order_id": "o-" + fid, "ticker": ticker,
            "market_ticker": ticker, "count_fp": count, "yes_price_dollars": yes,
            "no_price_dollars": str(1 - D(yes)), "fee_cost": fee, "is_taker": True,
            "created_time": at, **kw}


A, B = "KXNBAGAME-26NOV10BOSNYK-BOS", "KXNBAPTS-26NOV10BOSNYK-BOSJTATUM0-25"
C, DD = "KXNBATOTAL-26NOV20BOSDEN-221", "KXNBAGAME-26NOV12LALGSW-LAL"
HIST_FILLS = [fill("f1", A, "10.00", "0.4000", "0.1700", "2026-11-10T20:00:00Z",
                   side="yes", action="buy")]
LIVE_FILLS = [
    HIST_FILLS[0],  # overlap must dedupe
    # no side/action: inferred from outcome_side/book_side -> buy NO
    fill("f2", B, "5.00", "0.3000", "0.0800", "2026-11-10T21:00:00Z",
         outcome_side="no", book_side="ask"),
    fill("f3", C, "4.00", "0.5000", "0.0700", "2026-11-18T20:00:00Z", side="yes", action="buy"),
    fill("f4", DD, "2.00", "0.3000", "0.0200", "2026-11-12T20:00:00Z", side="yes", action="buy"),
    fill("f5", DD, "2.00", "0.4500", "0.0200", "2026-11-12T22:00:00Z", side="yes", action="sell"),
]
SETTLEMENTS = [
    {"ticker": A, "event_ticker": "KXNBAGAME-26NOV10BOSNYK", "market_result": "yes",
     "yes_count_fp": "10.00", "yes_total_cost_dollars": "4.0000", "no_count_fp": "0.00",
     "no_total_cost_dollars": "0.0000", "revenue": 1000, "settled_time": "2026-11-11T04:00:00Z",
     "fee_cost": "0.0000"},
    {"ticker": B, "event_ticker": "KXNBAPTS-26NOV10BOSNYK", "market_result": "yes",
     "yes_count_fp": "0.00", "yes_total_cost_dollars": "0.0000", "no_count_fp": "5.00",
     "no_total_cost_dollars": "3.5000", "revenue": 0, "settled_time": "2026-11-11T04:00:00Z",
     "fee_cost": "0.0000"},
]


def pos(t: str, p: str, exp: str, pnl: str, fees: str) -> dict:
    return {"ticker": t, "position_fp": p, "market_exposure_dollars": exp,
            "realized_pnl_dollars": pnl, "fees_paid_dollars": fees, "total_traded_dollars": exp,
            "last_updated_ts": "2026-11-18T20:00:00Z", "netting_enabled": True}


LIVE_POS = [pos(A, "0.00", "0.0000", "5.8300", "0.1700"),  # Kalshi realized = net of fees
            pos(B, "0.00", "0.0000", "-3.5000", "0.0800"),  # Kalshi realized = gross
            pos(C, "4.00", "2.0000", "0.0000", "0.0700"),
            pos(DD, "0.00", "0.0000", "0.2600", "0.0400")]


def routes(seen: list[httpx.Request]) -> httpx.MockTransport:
    data = {"/portfolio/fills": {"fills": LIVE_FILLS, "cursor": ""},
            "/historical/fills": {"fills": HIST_FILLS, "cursor": ""},
            "/portfolio/settlements": {"settlements": SETTLEMENTS, "cursor": ""},
            "/portfolio/positions": {"market_positions": LIVE_POS, "event_positions": [],
                                     "cursor": ""},
            "/historical/positions": {"market_positions": [], "event_positions": [],
                                      "cursor": ""},
            "/portfolio/balance": {"balance": 4210, "balance_dollars": "42.1000",
                                   "portfolio_value": 240, "updated_ts": 1}}

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        body = data.get(req.url.path.removeprefix("/trade-api/v2"))
        return httpx.Response(200, json=body) if body else httpx.Response(404)
    return httpx.MockTransport(handle)


def reader(seen: list[httpx.Request] | None = None, transport=None) -> AccountReader:  # type: ignore[no-untyped-def]
    return AccountReader(SIGNER, BASE, transport=transport or routes(seen if seen is not None
                                                                     else []),
                         sleep=lambda _: None, min_interval=0.0, max_retries=1)


# --- client safety ----------------------------------------------------------------------------


def test_client_is_get_only_and_allowlisted() -> None:
    r = reader()
    assert not any(hasattr(r, m) for m in ("post", "put", "delete", "create_order"))
    assert all(p.startswith(("/portfolio/", "/historical/")) for p in READ_PATHS)
    assert "/portfolio/orders" not in READ_PATHS and "/portfolio/events/orders" not in READ_PATHS
    with pytest.raises(ValueError, match="allow-listed"):
        r.get("/portfolio/orders")
    for bad in ("https://evil.example/trade-api/v2", "http://api.elections.kalshi.com/trade-api/v2"):
        with pytest.raises(ValueError):
            AccountReader(SIGNER, bad)
    assert "test-key-id" not in repr(r)


def test_requests_are_signed_gets_without_query_in_signature() -> None:
    seen: list[httpx.Request] = []
    r = reader(seen)
    r.paginate("/portfolio/fills", "fills")
    req = seen[0]
    assert req.method == "GET" and req.headers["KALSHI-ACCESS-KEY"] == "test-key-id"
    assert "KALSHI-ACCESS-SIGNATURE" in req.headers and "limit=1000" in str(req.url)


def test_auth_failure_and_retry_messages() -> None:
    calls = {"n": 0}

    def handle(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429) if calls["n"] == 1 else httpx.Response(401)
    with pytest.raises(AccountError, match="READ scope"):
        reader(transport=httpx.MockTransport(handle)).get("/portfolio/balance")
    assert calls["n"] == 2  # one retry after 429


def test_unconfigured_settings_give_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(AccountError, match="KRT_KALSHI_API_KEY_ID"):
        AccountReader.from_settings(Settings(_env_file=None))


def test_side_and_action_inference() -> None:
    assert side_and_action({"side": "no", "action": "sell"}) == ("no", "sell")
    assert side_and_action({"outcome_side": "yes", "book_side": "bid"}) == ("yes", "buy")
    assert side_and_action({"outcome_side": "no", "book_side": "ask"}) == ("no", "buy")
    assert side_and_action({"outcome_side": "yes", "book_side": "ask"}) == ("yes", "sell")
    assert side_and_action({"outcome_side": "no", "book_side": "bid"}) == ("no", "sell")
    assert side_and_action({}) is None


def test_market_types() -> None:
    assert market_type("KXNBAGAME") == "game winner"
    assert market_type("KXNBASPREAD") == "spread"
    assert market_type("KXNBATOTAL") == "total"
    assert market_type("KXNBAPTS") == "player prop"
    assert market_type("KXNBA3PT") == "player prop"
    assert market_type("KXMVECROSSCATEGORY") == "combo"
    assert market_type("KXCPI") == "other"


# --- sync + report ----------------------------------------------------------------------------


@pytest.fixture
def factory(settings: Settings):  # type: ignore[no-untyped-def]
    engine = make_engine(settings.database_url)
    yield make_session_factory(engine)
    engine.dispose()


def _catalog(factory) -> None:  # type: ignore[no-untyped-def]
    CatalogWriter(factory, NOW).write_page([
        {"event_ticker": "KXNBATOTAL-26NOV20BOSDEN", "series_ticker": "KXNBATOTAL",
         "title": "BOS vs DEN total", "mutually_exclusive": False,
         "markets": [{"ticker": C, "title": "Over 220.5", "status": "active",
                      "yes_bid_dollars": "0.5900", "yes_ask_dollars": "0.6100"}]},
        {"event_ticker": "KXNBAGAME-26NOV22BOSPHI", "series_ticker": "KXNBAGAME",
         "title": "Boston vs Philadelphia", "mutually_exclusive": True, "markets": []}])


def test_sync_and_report_pnl_reconciliation_and_marks(factory) -> None:  # type: ignore[no-untyped-def]
    _catalog(factory)
    r = sync_account(factory, reader(), NOW)
    assert r.status == "success" and "5 fills" in r.message and "$42.10" in r.message
    with factory() as s:
        assert s.get(AccountFill, "f2").side == "no" and s.get(AccountFill, "f2").price == D("0.7")
        rep = report(s, D("50"))
    by = {m["ticker"]: m for m in rep["markets"]}
    assert by[A]["pnl"] == "5.83" and by[B]["pnl"] == "-3.58" and by[DD]["pnl"] == "0.26"
    assert by[DD]["status"] == "closed"
    assert rep["reconciliation"] == {"checked": 3, "net": 2, "gross": 1}
    s_ = rep["summary"]
    assert s_["realized_pnl"] == "2.51" and s_["balance"] == "42.10"
    assert s_["unrealized_pnl"] == "0.40"  # 4 x 0.60 mid - 2.00 cost
    open_c = rep["open_positions"][0]
    assert open_c["ticker"] == C and open_c["mark"]["mid"] == "0.600"
    wr = s_["win_rate"]
    assert wr["n"] == 2 and wr["won"] == 1 and wr["small_sample"]
    assert rep["behavior"]["taker_share"] == 1.0
    assert any("Only 2 settled" in i["text"] for i in rep["insights"])
    types = {t["name"] for t in rep["by_type"]}
    assert {"game winner", "player prop"} <= types


def test_failed_sync_is_recorded(factory) -> None:  # type: ignore[no-untyped-def]
    bad = reader(transport=httpx.MockTransport(lambda req: httpx.Response(401)))
    r = sync_account(factory, bad, NOW)
    assert r.status == "failed"
    with factory() as s:
        last = s.query(AccountSync).one()
        assert last.status == "failed" and "refused the key" in last.message


# --- API + job --------------------------------------------------------------------------------


def test_history_job_and_api(settings: Settings, tmp_path: Path) -> None:
    s = Settings(_env_file=None, database_url=settings.database_url,
                 experiment_budget_dollars="50")
    engine = make_engine(s.database_url)
    runner = JobRunner(s, make_session_factory(engine), FrozenClock(NOW), synchronous=True,
                       account_factory=reader, worker_lock_path=tmp_path / "w.lock")
    app = create_app(s, FrozenClock(NOW), jobs=runner)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.get("/api/history/status").json()["configured"] is False
        assert c.post("/api/jobs/history/run").status_code == 403  # CSRF header required
        assert c.post("/api/jobs/history/run", headers={"X-KRT-Request": "ops"}).status_code == 202
        assert c.get("/api/jobs").json()["jobs"]["history"]["last_status"] == "success"
        rep = c.get("/api/history/report").json()
        assert rep["summary"]["realized_pnl"] == "2.51"
        fills = c.get("/api/history/fills", params={"limit": 2}).json()["items"]
        assert len(fills) == 2 and fills[0]["fill_id"] == "f3"  # newest first
        body = json.dumps(rep) + json.dumps(c.get("/api/health").json())
        assert "test-key-id" not in body
    engine.dispose()


def test_history_job_without_keys_fails_cleanly(settings: Settings, tmp_path: Path) -> None:
    s = Settings(_env_file=None, database_url=settings.database_url)
    engine = make_engine(s.database_url)
    runner = JobRunner(s, make_session_factory(engine), FrozenClock(NOW), synchronous=True,
                       worker_lock_path=tmp_path / "w.lock")
    runner.run("history")
    st = runner.state["history"]
    assert st.last_status == "failed" and "KRT_KALSHI_API_KEY_ID" in (st.last_message or "")
    engine.dispose()


def test_timeline_is_cumulative_by_close_day(factory) -> None:  # type: ignore[no-untyped-def]
    sync_account(factory, reader(), NOW)
    with factory() as s:
        tl = report(s, D("50"))["timeline"]
    # A and B settle 2026-11-11 (+5.83, -3.58); DD sold out 2026-11-12 (+0.26)
    assert [(d["date"], d["pnl"], d["cumulative"]) for d in tl] == [
        ("2026-11-11", "2.25", "2.25"), ("2026-11-12", "0.26", "2.51")]
    assert tl[0]["markets"] == 2 and tl[0]["wins"] == 1
    assert tl[0]["by_type"] == {"game winner": "5.83", "player prop": "-3.58"}
