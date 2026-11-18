"""End-to-end workflow on deterministic fixtures, through the REAL adapters.

FRED and Kalshi are served by mock HTTP transports (no network): ingest evidence ->
evaluate models -> ingest market -> propose/confirm mapping -> signal -> trace lineage ->
paper order from the signal -> new CPI release -> exchange finalizes -> settle -> report.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.kalshi_public import KalshiPublicClient, KalshiPublicMarketAdapter
from app.core.config import KALSHI_REST_BASES, KalshiEnv, Settings
from app.db.models import Market
from app.db.repositories import MarketRepository
from app.db.session import make_engine, make_session_factory
from app.demo import synthetic_cpi
from app.evidence.fred import FredClient, FredEvidenceAdapter
from app.evidence.ingest import run_evidence_ingestion
from app.evidence.sources import SOURCES
from app.ingest import run_ingestion
from app.main import create_app
from app.paper.service import account_summary, settle
from app.research.service import evaluate_and_save, forecast_all, load_first_prints
from app.signals.mapping import decide, propose_all
from app.signals.service import generate_signals
from tests.test_signals import schedule

D = Decimal
NOW = datetime(2024, 12, 20, 15, 0, tzinfo=UTC)  # Nov-2024 print released 2024-12-12
KEY = "0123456789abcdef0123456789abcdef"


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at


def fred_transport(through: date) -> httpx.MockTransport:
    rows = [{"realtime_start": o.vintage_date.isoformat(), "realtime_end": "9999-12-31",
             "date": o.observation_date.isoformat(), "value": str(o.value)}
            for o in synthetic_cpi(date(1990, 1, 1), through)]
    series = {"seriess": [{"id": "CPIAUCSL", "title": "CPI (synthetic)", "units": "Index",
                           "frequency": "Monthly", "notes": "synthetic"}]}

    def handle(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/fred/series":
            return httpx.Response(200, json=series)
        return httpx.Response(200, json={"count": len(rows), "offset": 0, "limit": 100000,
                                         "observations": rows})
    return httpx.MockTransport(handle)


RULES = ("If the Consumer Price Index (CPI) increases by more than 0.2% (single-decimal) in "
         "December 2024, then the market resolves to Yes.\n\nThe market will always close at "
         "8:29 AM ET on the scheduled day of the data release. Please note: the Expiration "
         "Value is the single-decimal value published at the Source Agency.")


def kalshi_transport(p_yes: float, status: str = "active", result: str = "") -> httpx.MockTransport:
    ask = round(min(0.97, p_yes + 0.02), 2)
    bid = round(max(0.03, p_yes - 0.02), 2)
    market = {
        "ticker": "KXCPI-24DEC-T0.2", "event_ticker": "KXCPI-24DEC", "market_type": "binary",
        "yes_sub_title": "Above 0.2%", "title": "Will CPI rise more than 0.2% in December 2024?",
        "status": status, "result": result, "open_time": "2024-11-13T15:00:00Z",
        "close_time": "2025-01-15T13:29:00Z", "notional_value_dollars": "1.0000",
        "rules_primary": RULES.split("\n\n")[0], "rules_secondary": RULES.split("\n\n")[1],
        "price_ranges": [{"start": "0.0000", "end": "1.0000", "step": "0.0100"}],
    }
    book = {"orderbook_fp": {
        "yes_dollars": [[f"{bid - 0.01:.4f}", "300.00"], [f"{bid:.4f}", "200.00"]],
        "no_dollars": [[f"{1 - ask - 0.01:.4f}", "300.00"], [f"{1 - ask:.4f}", "200.00"]],
    }} if status == "active" else {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}}
    routes = {
        "/series/KXCPI": {"series": {"ticker": "KXCPI", "category": "Economics",
                                     "fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1,
                                     "contract_url": "https://example.invalid/CPI.pdf"}},
        "/events/KXCPI-24DEC": {"event": {"event_ticker": "KXCPI-24DEC",
                                          "fee_type_override": None,
                                          "fee_multiplier_override": None}},
        "/markets": {"markets": [market], "cursor": ""},
        "/markets/KXCPI-24DEC-T0.2/orderbook": book,
    }

    def handle(req: httpx.Request) -> httpx.Response:
        body = routes.get(req.url.path.removeprefix("/trade-api/v2"))
        return httpx.Response(200, json=body) if body is not None else httpx.Response(404)
    return httpx.MockTransport(handle)


def kalshi_adapter(transport: httpx.MockTransport, clock: Clock) -> KalshiPublicMarketAdapter:
    client = KalshiPublicClient(KALSHI_REST_BASES[KalshiEnv.PRODUCTION], transport=transport,
                                sleep=lambda _: None, min_interval=0.0, max_retries=0)
    return KalshiPublicMarketAdapter(client, clock, series_watchlist=["KXCPI"])


def fred_adapter(transport: httpx.MockTransport, clock: Clock) -> FredEvidenceAdapter:
    client = FredClient(KEY, transport=transport, sleep=lambda _: None, min_interval=0.0)
    return FredEvidenceAdapter(SOURCES["fred:CPIAUCSL"], client, clock)


def test_full_workflow(settings: Settings) -> None:
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    clock = Clock(NOW)
    sched = [schedule()]

    # 1. Evidence through Nov 2024 (vintages), 2. model evaluation
    ev = run_evidence_ingestion(fred_adapter(fred_transport(date(2024, 11, 1)), clock),
                                factory, clock)
    assert ev.status == "success" and ev.count > 400
    with factory() as s:
        evaluate_and_save(s, NOW)
        _, fcs, _ = forecast_all(s, D("0.2"), NOW)
        s.commit()
    p_yes = next(f.p_yes for f in fcs if f.model == "gaussian_trailing")

    # 3. Kalshi market ingest (public adapter), 4. mapping proposed + confirmed by "user"
    clock.at = NOW - timedelta(seconds=5)
    mk = run_ingestion(kalshi_adapter(kalshi_transport(p_yes), clock), factory, clock)
    assert (mk.status, mk.count) == ("success", 1)
    clock.at = NOW
    with factory() as s:
        (created,) = propose_all(s, NOW)
        assert created[1].status == "proposed"
        decide(s, created[0], NOW, confirm=True, note="e2e")
        # 5. signal
        (sig,) = generate_signals(s, settings, NOW, schedules=sched)
        s.commit()
        sig_id, market_id = sig.id, sig.market_id
        assert "RULES_CHANGED" not in sig.reasons_json and "QUOTE_STALE" not in sig.reasons_json

    app = create_app(settings, clock)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        # 6. lineage: quote <- ingestion run, rules, mapping, model run <- exact evidence
        lin = c.get(f"/api/lineage/signal/{sig_id}").json()
        assert lin["quote"]["ingestion_run"]["adapter"] == "kalshi_public"
        assert lin["rules"]["is_current"] and lin["mapping"]["status"] == "confirmed"
        assert lin["model_run"]["model"] == "gaussian_trailing"
        assert len(lin["evidence"]) == 36 and lin["leakage_check"] == "pass"
        assert all(e["available_at"] <= lin["model_run"]["as_of"] for e in lin["evidence"])
        assert lin["fee_schedule"] is None  # test schedule is not in the shipped file

        # 7. paper order linked to the signal, traced back
        r = c.post("/api/paper/orders", headers={"X-KRT-Request": "paper"}, json={
            "client_order_id": "e2e-order-001", "market_id": market_id, "side": "YES",
            "action": "BUY", "quantity": 10, "limit_price": "0.99", "signal_id": sig_id})
        assert r.status_code == 201, r.text
        order = r.json()
        olin = c.get(f"/api/lineage/paper-order/{order['id']}").json()
        assert olin["signal"]["signal"]["id"] == sig_id and olin["quote"]["id"]

        diag = c.get("/api/diagnostics").json()
        assert {a["adapter"] for a in diag["ingestion"]} == {"kalshi_public", "fred:CPIAUCSL"}
        assert diag["safety"] == {"trading_mode": "paper", "live_execution_enabled": False}
        steps = {x["key"]: x["status"] for x in c.get("/api/setup-status").json()["steps"]}
        assert steps["evidence"] == steps["models"] == steps["mappings"] == "ok"
    app.state.engine.dispose()

    # 8. BLS publishes Dec 2024 (new vintage) and the exchange finalizes the market
    release = datetime(2025, 1, 13, 15, 0, tzinfo=UTC)
    clock.at = release
    ev2 = run_evidence_ingestion(fred_adapter(fred_transport(date(2024, 12, 1)), clock),
                                 factory, clock)
    assert ev2.count >= 1  # new vintage rows appended, old ones untouched
    with factory() as s:
        dec = next(p for p in load_first_prints(s).prints if p.month == date(2024, 12, 1))
        outcome = "yes" if dec.mom_rounded > D("0.2") else "no"
    adapter = kalshi_adapter(kalshi_transport(p_yes, "finalized", outcome), clock)
    with factory() as s:
        res = adapter.refresh_tickers(["KXCPI-24DEC-T0.2"])
        assert res.errors == [] and res.snapshots[0].result == outcome
        MarketRepository(s, clock).upsert_snapshot(res.snapshots[0], "kalshi_public")
        (st,) = settle(s, release)
        assert (st.status, st.evidence_check) == ("SETTLED", "agree")
        summ, rows = account_summary(s, release, schedules=sched)
        ((p, _, _),) = rows
        assert p.settled and p.open_qty == 0
        assert abs((summ.equity - summ.deposits) - (summ.realized + summ.unrealized)) < D("1e-18")
        m = s.scalar(select(Market).where(Market.external_ticker == "KXCPI-24DEC-T0.2"))
        assert m.status == "finalized"
        s.commit()
    engine.dispose()
