from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from app.core.clock import FrozenClock
from app.core.config import Settings
from app.db.models import Market, PaperFill, PaperLedgerEntry, PaperOrder, QuoteSnapshot, Signal
from app.db.repositories import MarketRepository
from app.db.session import make_engine, make_session_factory
from app.domain.models import BookLevel, MarketStatus, OrderBook, PriceRange
from app.evidence.repository import EvidenceRepository
from app.main import create_app
from app.paper.replay import replay
from app.paper.service import OrderRequest, account_summary, positions, settle, submit_order
from app.paper.simulator import SCENARIOS, simulate
from app.signals.engine import Level
from app.signals.mapping import decide, propose_all
from tests.research_fixtures import synthetic_vintages
from tests.test_signals import kxcpi_snapshot, schedule

D = Decimal
T0 = datetime(2024, 1, 20, 15, 0, tzinfo=UTC)
GRID = [PriceRange(start=D("0"), end=D("1"), step=D("0.01"))]
CONS, BASE = SCENARIOS["conservative"], SCENARIOS["baseline"]


# --- Simulator (pure) -----------------------------------------------------------------


def sim(action="BUY", side="YES", qty="10", limit="0.50", yes=None, no=None, sc=CONS):  # type: ignore[no-untyped-def]
    return simulate(action=action, side=side, quantity=D(qty), limit_price=D(limit),
                    yes_bids=yes if yes is not None else [Level(D("0.40"), D("100"))],
                    no_bids=no if no is not None else [Level(D("0.55"), D("100"))],
                    notional=D("1"), price_ranges=GRID, scenario=sc)


def test_buy_conservative_pays_one_tick_worse_than_displayed_ask() -> None:
    (f,) = sim()
    assert (f.quantity, f.displayed_price, f.price) == (D("10"), D("0.45"), D("0.46"))


def test_partial_fill_never_exceeds_scaled_depth() -> None:
    fills = sim(qty="80")
    assert sum(f.quantity for f in fills) == D("50")  # 100 displayed x 0.5
    fills = sim(qty="80", no=[Level(D("0.55"), D("3"))])
    assert sum(f.quantity for f in fills) == D("1")  # floor(3 x 0.5)


def test_limit_is_respected_and_no_midpoint_fills() -> None:
    assert sim(limit="0.45") == []  # 0.45 + 1 tick > limit
    (f,) = sim(limit="0.45", sc=BASE)
    assert f.price == D("0.45")  # exactly the derived ask, never the 0.425 midpoint


def test_walks_multiple_levels_in_price_order() -> None:
    fills = sim(qty="60", limit="0.60", no=[Level(D("0.55"), D("100")), Level(D("0.54"), D("40"))])
    assert [(f.quantity, f.price) for f in fills] == [(D("50"), D("0.46")), (D("10"), D("0.47"))]


def test_sell_hits_own_bids_one_tick_worse() -> None:
    (f,) = sim(action="SELL", limit="0.30")
    assert (f.displayed_price, f.price) == (D("0.40"), D("0.39"))
    assert sim(action="SELL", limit="0.40") == []


# --- Service (DB) ---------------------------------------------------------------------


@pytest.fixture
def factory(settings: Settings):  # type: ignore[no-untyped-def]
    engine = make_engine(settings.database_url)
    f = make_session_factory(engine)
    with f() as s:
        MarketRepository(s, FrozenClock(T0)).upsert_snapshot(kxcpi_snapshot(), "kalshi_public")
        s.commit()
    yield f
    engine.dispose()


def mid(s, ticker="KXCPI-24JAN-T0.2") -> str:  # type: ignore[no-untyped-def]
    return s.scalar(select(Market.id).where(Market.external_ticker == ticker))


def order(s, settings, coid="order-0001", side="YES", action="BUY", qty="10", limit="0.50",  # type: ignore[no-untyped-def]
          at=T0, ticker="KXCPI-24JAN-T0.2", scenario="conservative"):
    return submit_order(s, settings, OrderRequest(coid, mid(s, ticker), side, action, D(qty),
                                                  D(limit), scenario), at,
                        schedules=[schedule()])


def test_buy_fills_and_debits_ledger(factory, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    with factory() as s:
        r = order(s, settings)
        s.commit()
        o = r.order
        assert (o.status, o.filled_quantity, o.reject_reason) == ("FILLED", D("10"), None)
        assert o.fee_schedule_verified and o.simulation_version == "paper-sim-v1"
        (f,) = s.scalars(select(PaperFill)).all()
        assert (f.price, f.displayed_price, f.assumption_code) == (
            D("0.46"), D("0.45"), "IOC_DEPTH50_TICK1")
        kinds = [(e.kind, e.amount) for e in s.scalars(
            select(PaperLedgerEntry).order_by(PaperLedgerEntry.at, PaperLedgerEntry.kind))]
        # 10 @ 0.46: fee 0.07*10*0.46*0.54 = 0.17388 -> total ceil(4.77388, 0.01) = 4.78
        assert ("DEPOSIT", D("1000")) in kinds and ("BUY", D("-4.78")) in kinds


def test_partial_fill_charges_only_filled(factory, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    with factory() as s:
        o = order(s, settings, qty="80").order
        assert (o.status, o.filled_quantity) == ("PARTIAL", D("50"))
        (p,) = positions(s).values()
        assert p.open_qty == D("50")  # never the unfilled 30


@pytest.mark.parametrize("kw,reason", [
    ({"limit": "0.455"}, "LIMIT_OFF_GRID"),
    ({"qty": "0"}, "INVALID_QUANTITY"),
    ({"qty": "2.5"}, "INVALID_QUANTITY"),
    ({"action": "SELL"}, "INSUFFICIENT_POSITION"),
    ({"at": T0 + timedelta(minutes=5)}, "QUOTE_STALE"),
    ({"scenario": "dreamy"}, "UNKNOWN_SCENARIO"),
])
def test_rejections_are_recorded_and_move_no_cash(factory, settings, kw, reason) -> None:  # type: ignore[no-untyped-def]
    with factory() as s:
        o = order(s, settings, **kw).order
        assert (o.status, o.reject_reason, o.filled_quantity) == ("REJECTED", reason, D("0"))
        assert s.scalars(select(PaperLedgerEntry.kind)).all() == ["DEPOSIT"]


def test_insufficient_cash(factory, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    poor = settings.model_copy(update={"paper_starting_cash": D("1")})
    with factory() as s:
        assert order(s, poor).order.reject_reason == "INSUFFICIENT_CASH"


def test_cancelled_when_nothing_fillable_within_limit(factory, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    with factory() as s:
        assert order(s, settings, limit="0.45").order.status == "CANCELLED"


def test_idempotent_client_order_id(factory, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    with factory() as s:
        a, b = order(s, settings), order(s, settings, qty="5")
        assert b.duplicate and b.order.id == a.order.id
        assert len(s.scalars(select(PaperOrder)).all()) == 1


def test_ledger_orders_fills_are_append_only(factory, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    with factory() as s:
        order(s, settings)
        s.commit()
        for stmt in ("UPDATE paper_ledger SET amount = '0'", "DELETE FROM paper_fills",
                     "UPDATE paper_orders SET status = 'FILLED'"):
            with pytest.raises(DatabaseError, match="append-only"):
                s.execute(text(stmt))
            s.rollback()


def test_sell_realizes_pnl(factory, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    with factory() as s:
        order(s, settings, coid="buy-00001")
        o = order(s, settings, coid="sell-0001", action="SELL", qty="4", limit="0.30").order
        assert o.status == "FILLED"
        (p,) = positions(s).values()
        assert p.open_qty == D("6") and p.realized < 0  # bought 0.46+fee, sold 0.39-fee


def _equity_identity(s, at) -> None:  # type: ignore[no-untyped-def]
    summ, _ = account_summary(s, at, schedules=[schedule()])
    assert abs((summ.equity - summ.deposits) - (summ.realized + summ.unrealized)) < D("1e-18")


def test_account_identity_and_restart_persistence(settings: Settings, factory) -> None:  # type: ignore[no-untyped-def]
    with factory() as s:
        order(s, settings, coid="buy-00001", qty="7")
        order(s, settings, coid="sell-0001", action="SELL", qty="3", limit="0.30")
        s.commit()
        _equity_identity(s, T0)
        before, _ = account_summary(s, T0, schedules=[schedule()])
    engine2 = make_engine(settings.database_url)  # "restart": brand-new engine
    with make_session_factory(engine2)() as s2:
        after, _ = account_summary(s2, T0, schedules=[schedule()])
        assert (after.cash, after.realized, after.unrealized) == (
            before.cash, before.realized, before.unrealized)
        assert len(s2.scalars(select(PaperOrder)).all()) == 2
    engine2.dispose()


# --- Settlement -----------------------------------------------------------------------

DEC_RULES = ("If the Consumer Price Index (CPI) increases by more than 0.2% in December 2023, as "
             "reported to one decimal place, then the market resolves to Yes.\n\nPlease note: the "
             "Expiration Value is the single-decimal value published at the Source Agency.")


def _dec_market(s, status=MarketStatus.ACTIVE, result=None, observed=T0 - timedelta(seconds=5)):  # type: ignore[no-untyped-def]
    snap = kxcpi_snapshot("KXCPI-23DEC-T0.2", DEC_RULES, observed).model_copy(update={
        "event_ticker": "KXCPI-23DEC", "status": status, "status_raw": status.value,
        "result": result})
    MarketRepository(s, FrozenClock(observed)).upsert_snapshot(snap, "kalshi_public")


@pytest.fixture
def dec(factory):  # type: ignore[no-untyped-def]
    with factory() as s:
        EvidenceRepository(s).insert_new("fred:CPIAUCSL", synthetic_vintages())  # Dec-23 = 0.3%
        _dec_market(s)
        propose_all(s, T0)
        decide(s, s.get(Market, mid(s, "KXCPI-23DEC-T0.2")), T0, confirm=True)
        s.commit()
    return factory


def _finalize(s, result: str, status=MarketStatus.FINALIZED) -> None:  # type: ignore[no-untyped-def]
    _dec_market(s, status=status, result=result, observed=T0 + timedelta(hours=1))


def test_settles_on_finalized_result_that_matches_evidence(dec, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    with dec() as s:
        order(s, settings, ticker="KXCPI-23DEC-T0.2")
        _finalize(s, "yes")
        (st,) = settle(s, T0 + timedelta(hours=1))
        assert (st.status, st.evidence_check) == ("SETTLED", "agree")
        payouts = s.scalars(select(PaperLedgerEntry.amount).where(
            PaperLedgerEntry.kind == "SETTLEMENT_PAYOUT")).all()
        assert payouts == [D("10.0000")]
        (p,) = positions(s).values()
        assert p.settled and p.open_qty == 0 and p.realized == D("10.0000") - D("4.78")
        assert settle(s, T0 + timedelta(hours=2)) == []  # idempotent
        _equity_identity(s, T0 + timedelta(hours=2))
        r = order(s, settings, coid="late-0001", ticker="KXCPI-23DEC-T0.2",
                  at=T0 + timedelta(hours=1))
        assert r.order.reject_reason == "ALREADY_SETTLED"


def test_held_when_exchange_contradicts_evidence(dec, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    with dec() as s:
        order(s, settings, ticker="KXCPI-23DEC-T0.2")
        _finalize(s, "no")  # our first print says 0.3% > 0.2% -> yes
        (st,) = settle(s, T0 + timedelta(hours=1))
        assert (st.status, st.evidence_check) == ("HELD", "disagree")
        assert s.scalars(select(PaperLedgerEntry).where(
            PaperLedgerEntry.kind == "SETTLEMENT_PAYOUT")).all() == []
        assert next(iter(positions(s).values())).held


@pytest.mark.parametrize("status", [MarketStatus.DETERMINED, MarketStatus.DISPUTED,
                                    MarketStatus.CLOSED])
def test_no_payout_before_finalized(dec, settings, status) -> None:  # type: ignore[no-untyped-def]
    with dec() as s:
        order(s, settings, ticker="KXCPI-23DEC-T0.2")
        _finalize(s, "yes", status=status)
        assert settle(s, T0 + timedelta(hours=1)) == []


# --- API ------------------------------------------------------------------------------


def test_paper_api_and_csrf(factory, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    with factory() as s:
        market_id = mid(s)
    app = create_app(settings, FrozenClock(T0))
    body = {"client_order_id": "ui-order-0001", "market_id": market_id, "side": "YES",
            "action": "BUY", "quantity": 10, "limit_price": "0.50"}
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.post("/api/paper/orders", json=body).status_code == 403  # no custom header
        evil = c.post("/api/paper/orders", json=body,
                      headers={"X-KRT-Request": "paper", "Origin": "https://evil.example"})
        assert evil.status_code == 403 and evil.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"
        hdr = {"X-KRT-Request": "paper"}
        r = c.post("/api/paper/orders", json=body, headers=hdr)
        assert r.status_code == 201 and r.json()["status"] == "FILLED"
        assert r.json()["fills"][0]["assumption_code"] == "IOC_DEPTH50_TICK1"
        again = c.post("/api/paper/orders", json=body, headers=hdr)
        assert again.status_code == 200 and again.json()["duplicate"] is True
        bad = c.post("/api/paper/orders", json={**body, "client_order_id": "ui-order-0002",
                                                "limit_price": "1.5"}, headers=hdr)
        assert bad.status_code == 422
        acct = c.get("/api/paper/account").json()
        assert acct["positions"][0]["open_qty"] == "10" and acct["deposits"] == "1000"
        assert acct["fee_schedule_verified"] is True  # filled with the PDF-verified schedule
        assert len(c.get("/api/paper/orders").json()) == 1
        assert c.get("/api/paper/settlements").json() == []
        assert c.get("/api/paper/replay", params={"scenario": "nope"}).status_code == 422
    app.state.engine.dispose()


# --- Replay ---------------------------------------------------------------------------


def test_replay_uses_signal_quote_and_scores_resolved(dec, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    with dec() as s:
        m = s.get(Market, mid(s, "KXCPI-23DEC-T0.2"))
        q = s.scalar(select(QuoteSnapshot).where(QuoteSnapshot.market_id == m.id))
        s.add(Signal(created_at=T0, expires_at=T0 + timedelta(seconds=60), market_id=m.id,
                     quote_id=q.id, decision="CANDIDATE_YES", side="YES", quantity=D("10"),
                     p_yes=0.6, entry=D("0.45"), fee=D("0.018"), slippage=D("0.01"),
                     ev=D("0.122"), lower_edge=D("0.07"), reasons_json="[]",
                     caveats_json="[]", details_json="{}"))
        s.flush()
        open_rep = replay(s, CONS, T0, [schedule()])
        (t,) = open_rep.trades
        assert (t.status, t.filled, t.avg_price, t.outcome) == ("FILLED", D("10"),
                                                                 D("0.460000"), None)
        assert open_rep.unresolved_cost == D("4.78") and open_rep.resolved_brier is None
        _finalize(s, "yes")
        done = replay(s, CONS, T0 + timedelta(hours=2), [schedule()])
        assert done.realized_pnl == D("10.0000") - D("4.78")
        assert done.resolved_brier == pytest.approx(0.16)  # (0.6 - 1)^2
        harsh = replay(s, SCENARIOS["harsh"], T0, [schedule()])
        assert harsh.trades[0].status == "CANCELLED"  # 0.45 + 2 ticks > limit 0.46


# --- Isolation from execution code ---------------------------------------------------


def test_paper_package_imports_no_network_or_execution_code() -> None:
    forbidden = ("httpx", "requests", "urllib", "socket", "execution", "kalshi_public")
    pkg = Path(__file__).resolve().parents[1] / "app" / "paper"
    for py in pkg.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                assert not any(f in n for f in forbidden), f"{py.name} imports {n}"


def test_market_result_captured_from_kalshi_payload() -> None:
    from app.adapters.kalshi_public import parse_market, parse_orderbook
    from tests.kalshi_payloads import DEFAULT_BOOK, market

    book = parse_orderbook(DEFAULT_BOOK, T0)
    assert parse_market(market("T", status="finalized", result="yes"), series=None,
                        orderbook=book).result == "yes"
    assert parse_market(market("T"), series=None, orderbook=book).result is None


def test_orderbook_level_type_unchanged() -> None:
    # guard: simulator consumes the same Level type the signal engine produces
    assert Level(D("0.1"), D("1")) == Level(D("0.1"), D("1"))
    assert BookLevel(price=D("0.1"), quantity=D("1")).price == D("0.1")
    assert OrderBook(observed_at=T0).yes_bids == ()
    assert json.dumps({"ok": True})
