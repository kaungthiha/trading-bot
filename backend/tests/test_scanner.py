"""Scanner tests. Kalshi payloads are SYNTHETIC, shaped like the documented /events (with
nested markets) and orderbook responses; all HTTP goes through mock transports."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from app.adapters.kalshi_public import KalshiPublicClient
from app.core.clock import FrozenClock
from app.core.config import KALSHI_REST_BASES, KalshiEnv, Settings
from app.db.models import Opportunity as OppRow
from app.db.session import make_engine, make_session_factory
from app.main import create_app
from app.scanner.detectors import (
    EventBook,
    SizingRules,
    TopOfBook,
    detect_exclusive,
    detect_ladder,
    size_combo,
)
from app.scanner.kalshi_scan import parse_event
from app.scanner.service import (
    JournalError,
    budget_state,
    record_journal,
    run_scan,
    scorecard,
    settle_journal,
)
from tests.test_signals import schedule

D = Decimal
NOW = datetime(2026, 11, 18, 23, 0, tzinfo=UTC)
SCHED = schedule()
RULES = SizingRules(max_cost=D("10"))


def tob(ticker: str, bid: str | None, ask: str | None, size: str = "100", *, title: str = "",
        strike: str | None = None, stype: str | None = None, rules: str | None = None,
        status: str = "active") -> TopOfBook:
    return TopOfBook(ticker, title or ticker, status, D(bid) if bid else None,
                     D(ask) if ask else None, D(size), D(size), stype,
                     D(strike) if strike else None, rules)


def rung(team: str, strike: str, bid: str, ask: str, size: str = "100") -> TopOfBook:
    return tob(f"T-{team}{strike}", bid, ask, size, title=f"{team} over {strike}", strike=strike,
               stype="greater", rules=f"If {team} scores more than {strike} points, Yes.")


# --- Detectors ----------------------------------------------------------------------------


def test_ladder_violation_found_with_exact_math() -> None:
    # P(>100) asked at 0.40 but P(>110) bid at 0.50: YES(100)@0.40 + NO(110)@0.50 = 0.90 < 1
    ev = EventBook("E", "Chicago total", False, [rung("CHI", "100", "0.38", "0.40"),
                                                 rung("CHI", "110", "0.50", "0.52")])
    (o,) = detect_ladder(ev, SCHED, RULES)
    assert o.kind == "LADDER" and o.guaranteed
    assert [(lg.side, lg.limit_price) for lg in o.legs] == [
        ("YES", D("0.40")), ("NO", D("0.50"))]
    # 11 sets: 4.40 + fee 0.17 -> 4.57 and 5.50 + 0.17 -> 5.67 = 10.24 > 10, so 10 sets
    assert o.quantity == D("10") and o.min_payoff == D("10")
    assert o.cost == D("4.17") + D("5.18") and o.profit == D("10") - D("9.35")


def test_ladder_never_pairs_different_underlyings() -> None:
    # Same event, but Chicago vs Brooklyn totals are different ladders (the live-data bug).
    ev = EventBook("E", "Team totals", False, [rung("CHI", "100", "0.01", "0.02"),
                                               rung("BKN", "110", "0.97", "0.99")])
    assert detect_ladder(ev, SCHED, RULES) == []


def test_consistent_ladder_and_missing_rules_yield_nothing() -> None:
    ok = EventBook("E", "t", False, [rung("CHI", "100", "0.60", "0.62"),
                                     rung("CHI", "110", "0.40", "0.42")])
    assert detect_ladder(ok, SCHED, RULES) == []
    no_rules = EventBook("E", "t", False, [
        tob("A", "0.38", "0.40", strike="100", stype="greater"),
        tob("B", "0.50", "0.52", strike="110", stype="greater")])
    assert detect_ladder(no_rules, SCHED, RULES) == []  # fail closed


def test_exclusive_no_set_guaranteed() -> None:
    # YES bids sum to 1.20 > 1: NO on all three costs 0.80 total, pays >= 2
    ev = EventBook("X", "Who wins?", True, [tob("A", "0.50", "0.52", title="Alice"),
                                            tob("B", "0.40", "0.42", title="Bob"),
                                            tob("C", "0.30", "0.32", title="Carol")])
    opps = detect_exclusive(ev, SCHED, RULES)
    (o,) = [x for x in opps if x.kind == "EXCL_NO"]
    assert o.guaranteed and o.min_payoff == o.quantity * 2
    assert [lg.limit_price for lg in o.legs] == [D("0.50"), D("0.60"), D("0.70")]
    assert o.profit > 0


def test_exclusive_yes_requires_catch_all_and_is_conditional() -> None:
    cheap = [tob("A", "0.20", "0.22", title="Alice"), tob("B", "0.20", "0.22", title="Bob"),
             tob("C", "0.20", "0.22", title="Cara")]
    ev = EventBook("X", "Who?", True, cheap)
    assert detect_exclusive(ev, SCHED, RULES) == []  # no catch-all -> not exhaustive -> skip
    other = tob("O", "0.20", "0.22", title="Someone else / Other")
    ev2 = EventBook("X", "Who?", True, [*cheap, other])
    (o,) = detect_exclusive(ev2, SCHED, RULES)
    assert o.kind == "EXCL_YES" and o.guaranteed is False
    assert any("EXHAUSTIVE" in c for c in o.checklist)


def test_inactive_outcome_blocks_exclusive_sets() -> None:
    ev = EventBook("X", "Who?", True, [tob("A", "0.70", "0.72"), tob("B", "0.60", "0.62",
                                                                      status="closed")])
    assert detect_exclusive(ev, SCHED, RULES) == []


def test_fee_rounding_kills_tiny_orders_and_depth_caps_size() -> None:
    from app.scanner.detectors import LegQuote

    # 1-cent edge per set: at 1 set each leg's fee rounds up to $0.01, so no profit
    legs = [LegQuote("A", "a", "YES", D("0.49"), D("1")),
            LegQuote("B", "b", "NO", D("0.50"), D("1"))]
    assert size_combo(legs, D("1"), SCHED, SizingRules(max_cost=D("10"), min_profit=D("0"),
                                                       min_return=D("0"))) is None
    deep = [LegQuote("A", "a", "YES", D("0.40"), D("3")),
            LegQuote("B", "b", "NO", D("0.50"), D("50"))]
    q, *_ = size_combo(deep, D("1"), SCHED, RULES)
    assert q == D("3")  # limited by the thinner leg


def test_max_legs_and_budget_cap() -> None:
    many = EventBook("X", "Many", True, [tob(f"M{i}", "0.15", "0.17") for i in range(10)])
    assert detect_exclusive(many, SCHED, SizingRules(max_cost=D("10"), max_legs=8)) == []
    ev = EventBook("E", "t", False, [rung("CHI", "100", "0.38", "0.40"),
                                     rung("CHI", "110", "0.50", "0.52")])
    (o,) = detect_ladder(ev, SCHED, SizingRules(max_cost=D("2.5")))
    assert o.cost <= D("2.5")


def test_parse_event_treats_zero_and_one_as_no_quote() -> None:
    ev = parse_event({"event_ticker": "E", "title": "t", "mutually_exclusive": True, "markets": [
        {"ticker": "A", "status": "active", "yes_bid_dollars": "0.0000",
         "yes_ask_dollars": "1.0000",
         "yes_bid_size_fp": "0.00", "yes_ask_size_fp": "0.00", "rules_primary": "r"}]})
    m = ev.markets[0]
    assert m.yes_bid is None and m.yes_ask is None and ev.mutually_exclusive


# --- Service with mock Kalshi ----------------------------------------------------------------


def _market(ticker: str, bid: str, ask: str, strike: str) -> dict:
    return {"ticker": ticker, "status": "active", "yes_sub_title": f"over {strike}",
            "yes_bid_dollars": bid, "yes_ask_dollars": ask, "yes_bid_size_fp": "100.00",
            "yes_ask_size_fp": "100.00", "strike_type": "greater", "floor_strike": float(strike),
            "rules_primary": f"If Chicago scores more than {strike} points, Yes."}


EVENTS = {"events": [{"event_ticker": "KXTEST-1", "title": "Chicago total",
                      "mutually_exclusive": False,
                      "markets": [_market("KXTEST-1-100", "0.3800", "0.4000", "100"),
                                  _market("KXTEST-1-110", "0.5000", "0.5200", "110")]}],
          "cursor": ""}
BOOKS = {
    # buying YES on -100 lifts the best NO bid (0.60 -> ask 0.40)
    "/markets/KXTEST-1-100/orderbook": {"orderbook_fp": {"yes_dollars": [["0.3800", "100.00"]],
                                                        "no_dollars": [["0.6000", "100.00"]]}},
    # buying NO on -110 lifts the best YES bid (0.50 -> NO ask 0.50)
    "/markets/KXTEST-1-110/orderbook": {"orderbook_fp": {"yes_dollars": [["0.5000", "100.00"]],
                                                        "no_dollars": [["0.4800", "100.00"]]}},
}


def kalshi(routes: dict) -> KalshiPublicClient:
    def handle(req: httpx.Request) -> httpx.Response:
        body = routes.get(req.url.path.removeprefix("/trade-api/v2"))
        return httpx.Response(200, json=body) if body is not None else httpx.Response(404)
    return KalshiPublicClient(KALSHI_REST_BASES[KalshiEnv.PRODUCTION],
                              transport=httpx.MockTransport(handle), sleep=lambda _: None,
                              min_interval=0.0, max_retries=0)


@pytest.fixture
def ssettings(settings: Settings) -> Settings:
    return Settings(_env_file=None, database_url=settings.database_url,
                    experiment_budget_dollars=D("50"))


@pytest.fixture
def factory(ssettings: Settings):  # type: ignore[no-untyped-def]
    engine = make_engine(ssettings.database_url)
    yield make_session_factory(engine)
    engine.dispose()


def test_scan_confirms_persists_dedupes_and_alerts(factory, ssettings: Settings) -> None:  # type: ignore[no-untyped-def]
    alerts: list[tuple[str, str]] = []
    r = run_scan(factory, ssettings, kalshi({"/events": EVENTS, **BOOKS}), FrozenClock(NOW),
                 schedules=[SCHED], notifier=lambda t, b: alerts.append((t, b)))
    assert (r.status, r.events, r.markets, r.candidates, r.confirmed) == ("success", 1, 2, 1, 1)
    assert len(r.new_cards) == 1 and alerts and "1 new idea" in alerts[0][1]
    with factory() as s:
        o = s.get(OppRow, r.new_cards[0])
        assert o.kind == "LADDER" and o.confirmed and o.cost <= D("10")  # 20% of $50
        assert o.budget_cap == D("10") and o.fee_schedule_version == "test-v1"
    again = run_scan(factory, ssettings, kalshi({"/events": EVENTS, **BOOKS}), FrozenClock(NOW),
                     schedules=[SCHED])
    assert again.confirmed == 1 and again.new_cards == []  # deduped


def test_scan_drops_candidates_that_vanish_on_confirmation(factory, ssettings: Settings) -> None:  # type: ignore[no-untyped-def]
    moved = dict(BOOKS)
    moved["/markets/KXTEST-1-110/orderbook"] = {"orderbook_fp": {
        "yes_dollars": [["0.3500", "100.00"]], "no_dollars": []}}  # gap closed
    r = run_scan(factory, ssettings, kalshi({"/events": EVENTS, **moved}), FrozenClock(NOW),
                 schedules=[SCHED])
    assert r.candidates == 1 and r.confirmed == 0 and r.new_cards == []


def test_scan_refuses_without_verified_fees(factory, ssettings: Settings) -> None:  # type: ignore[no-untyped-def]
    r = run_scan(factory, ssettings, kalshi({"/events": EVENTS, **BOOKS}), FrozenClock(NOW),
                 schedules=[schedule(verified=False)])
    assert r.status == "failed" and "verified fee schedule" in r.error


# --- Journal, budget, scorecard ---------------------------------------------------------------


def _card(factory, ssettings) -> str:  # type: ignore[no-untyped-def]
    r = run_scan(factory, ssettings, kalshi({"/events": EVENTS, **BOOKS}), FrozenClock(NOW),
                 schedules=[SCHED])
    return r.new_cards[0]


def test_journal_settle_scorecard_and_budget(factory, ssettings: Settings) -> None:  # type: ignore[no-untyped-def]
    cid = _card(factory, ssettings)
    with factory() as s:
        legs = [{"ticker": "KXTEST-1-100", "side": "YES", "quantity": 10, "avg_price": "0.40",
                 "fee": "0.17"},
                {"ticker": "KXTEST-1-110", "side": "NO", "quantity": 10, "avg_price": "0.50",
                 "fee": "0.18"}]
        record_journal(s, cid, "EXECUTED", NOW, legs, "filled both legs")
        with pytest.raises(JournalError):
            record_journal(s, cid, "SKIPPED", NOW)  # decision already recorded
        b = budget_state(s, ssettings)
        assert b.open_cost == D("9.35") and b.available == D("40.65")
        # outcome: Chicago scored 105 -> YES(>100) wins and NO(>110) wins = $20 payout
        assert settle_journal(s, {"KXTEST-1-100": "yes"}, NOW) == []  # not all legs final
        (st,) = settle_journal(s, {"KXTEST-1-100": "yes", "KXTEST-1-110": "no"}, NOW)
        assert st.payoff == D("20")
        s.commit()
        card = scorecard(s, ssettings)
        assert card["guaranteed"] == {"executed": 1, "settled": 1, "pnl": "10.65", "wins": 1}
        assert card["realized_pnl"] == "10.65" and card["open_cost"] == "0"
        with pytest.raises(DatabaseError, match="append-only"):
            s.execute(text("UPDATE journal_entries SET payoff = '999'"))


def test_invalid_journal_legs_rejected(factory, ssettings: Settings) -> None:  # type: ignore[no-untyped-def]
    cid = _card(factory, ssettings)
    with factory() as s:
        for bad in ([], [{"ticker": "X", "side": "MAYBE", "quantity": 1, "avg_price": "0.4"}],
                    [{"ticker": "X", "side": "YES", "quantity": 1, "avg_price": "1.5"}]):
            with pytest.raises(JournalError):
                record_journal(s, cid, "EXECUTED", NOW, bad)


def test_drawdown_pauses_new_cards(factory, ssettings: Settings) -> None:  # type: ignore[no-untyped-def]
    cid = _card(factory, ssettings)
    with factory() as s:
        record_journal(s, cid, "EXECUTED", NOW, [
            {"ticker": "KXTEST-1-100", "side": "YES", "quantity": 40, "avg_price": "0.40"}])
        settle_journal(s, {"KXTEST-1-100": "no"}, NOW)  # lost $16 = 32% of $50
        s.commit()
        assert budget_state(s, ssettings).paused
    r = run_scan(factory, ssettings, kalshi({"/events": EVENTS, **BOOKS}),
                 FrozenClock(NOW + timedelta(hours=1)), schedules=[SCHED])
    assert r.candidates == 0 and "Paused" in r.budget_note


def test_unset_budget_uses_small_cap(factory, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    unset = Settings(_env_file=None, database_url=settings.database_url)
    with factory() as s:
        b = budget_state(s, unset)
        assert b.budget is None and b.guaranteed_cap == D("5") and "not set" in b.note


def test_scanner_api(factory, ssettings: Settings) -> None:  # type: ignore[no-untyped-def]
    cid = _card(factory, ssettings)
    app = create_app(ssettings, FrozenClock(NOW))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        (card,) = c.get("/api/opportunities").json()
        assert card["id"] == cid and card["status"] == "OPEN" and card["guaranteed"]
        assert card["checklist"] and card["legs"][0]["side"] == "YES"
        assert c.get("/api/scanner/status").json()["caps"]["guaranteed"] == "10.00"
        body = {"action": "SKIPPED", "note": "rules unclear"}
        assert c.post(f"/api/opportunities/{cid}/journal", json=body).status_code == 403
        r = c.post(f"/api/opportunities/{cid}/journal", json=body,
                   headers={"X-KRT-Request": "journal"})
        assert r.status_code == 201 and r.json()["status"] == "SKIPPED"
        assert c.post(f"/api/opportunities/{cid}/journal", json=body,
                      headers={"X-KRT-Request": "journal"}).status_code == 409
        assert c.get("/api/scorecard").json()["skipped"] == 1
    app.state.engine.dispose()
    later = create_app(ssettings, FrozenClock(NOW + timedelta(minutes=10)))
    with TestClient(later, base_url="http://127.0.0.1") as c:
        assert c.get("/api/opportunities").json()[0]["status"] == "SKIPPED"
        one = c.get(f"/api/opportunities/{cid}").json()  # deep link from the research page
        assert one["id"] == cid and one["status"] == "SKIPPED" and one["journal"]
        assert c.get("/api/opportunities/missing").status_code == 404
    later.state.engine.dispose()


def test_scanner_never_imports_execution() -> None:
    pkg = Path(__file__).resolve().parents[1] / "app" / "scanner"
    for py in pkg.glob("*.py"):
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            assert not any(m.startswith("app.execution") for m in mods), py.name


def test_journal_rows_are_json_and_clean(factory, ssettings: Settings) -> None:  # type: ignore[no-untyped-def]
    cid = _card(factory, ssettings)
    with factory() as s:
        e = record_journal(s, cid, "EXECUTED", NOW, [
            {"ticker": "KXTEST-1-100", "side": "YES", "quantity": 1, "avg_price": "0.40"}])
        assert json.loads(e.legs_json)[0] == {"ticker": "KXTEST-1-100", "side": "YES",
                                              "quantity": "1", "avg_price": "0.40", "fee": "0"}
        assert s.scalars(select(OppRow)).first().id == cid


def test_truncated_scan_is_reported_not_hidden(factory, ssettings: Settings) -> None:  # type: ignore[no-untyped-def]
    from app.scanner.kalshi_scan import fetch_open_events

    page = {**EVENTS, "cursor": "more"}  # server always says there is another page
    client = kalshi({"/events": page, **BOOKS})
    events, truncated = fetch_open_events(client, max_pages=3)
    assert truncated and len(events) == 3


def test_deadline_events_need_a_none_outcome_not_just_other() -> None:
    # Live case 2026-11-18: "Which AI will be the first to hit 1550 on Text Arena?"
    rule = "If a model by {} is the first to hit 1550 on Text Arena before Jan 1, 2027, Yes."
    outs = [tob(n, "0.05", "0.09", title=n, rules=rule.format(n)) for n in
            ("Gemini", "Claude", "ChatGPT", "Grok")]
    with_other = [*outs, tob("O", "0.05", "0.09", title="Other", rules=rule.format("other"))]
    assert detect_exclusive(EventBook("X", "First to 1550", True, with_other), SCHED, RULES) == []
    with_none = [*with_other, tob("N", "0.05", "0.09", title="None before 2027",
                                  rules="If no model hits 1550 before Jan 1, 2027, Yes.")]
    (o,) = detect_exclusive(EventBook("X", "First to 1550", True, with_none), SCHED, RULES)
    assert o.kind == "EXCL_YES"
    # Without a deadline (e.g. an election that must have a winner) "Other" suffices.
    elect = [tob(n, "0.15", "0.19", title=n, rules=f"If {n} wins the election, Yes.")
             for n in ("A", "B", "Other")]
    assert detect_exclusive(EventBook("E", "Election", True, elect), SCHED, RULES)


def test_two_outcome_events_allow_buy_both_as_conditional() -> None:
    from app.scanner.detectors import detect_exclusive as de

    game = EventBook("KXNBAGAME-26NOV18UTALAL", "Utah vs LA", True,
                     [tob("UTA", "0.38", "0.40", title="Utah"),
                      tob("LAL", "0.43", "0.45", title="Los Angeles L")])  # 0.85 < 1
    (o,) = de(game, SCHED, RULES)
    assert o.kind == "EXCL_YES" and not o.guaranteed
    assert any("postponement" in c for c in o.checklist)


def test_near_misses_and_coverage_explain_empty_scans() -> None:
    from app.scanner.detectors import coverage, near_misses

    game = EventBook("KXNBAGAME-26NOV18UTALAL", "Utah vs LA", True,
                     [tob("UTA", "0.21", "0.22", title="Utah"),
                      tob("LAL", "0.78", "0.79", title="Los Angeles L")], category="Sports")
    cpi = EventBook("KXCPI-26NOV", "CPI", False, [rung("CPI", "100", "0.60", "0.62"),
                                                  rung("CPI", "110", "0.40", "0.42")],
                    category="Economics")
    nm = near_misses([game, cpi])
    assert nm[0].event_ticker == "KXNBAGAME-26NOV18UTALAL"  # 0.22 + 0.79 = 1.01: gap -0.01
    assert nm[0].gap == D("-0.01") and nm[0].category == "Sports"
    cov = coverage([game, cpi])
    assert {c["name"]: c["markets"] for c in cov["categories"]} == {"Sports": 2, "Economics": 2}
    assert {s["name"] for s in cov["top_series"]} == {"KXNBAGAME", "KXCPI"}


def test_scan_records_coverage_for_the_ui(factory, ssettings: Settings) -> None:  # type: ignore[no-untyped-def]
    run_scan(factory, ssettings, kalshi({"/events": EVENTS, **BOOKS}), FrozenClock(NOW),
             schedules=[SCHED])
    app = create_app(ssettings, FrozenClock(NOW))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        last = c.get("/api/scanner/status").json()["last_scan"]
        assert last["coverage"]["top_series"][0]["name"] == "KXTEST"
        assert last["near_misses"] and last["near_misses"][0]["kind"] == "LADDER"
    app.state.engine.dispose()


def test_two_candidate_elections_are_not_exhaustive() -> None:
    # Live false positives 2026-11-18: KXGOVNOM-VTR-28, KXADELAIDEMAYOR-27APR07, ...
    race = EventBook("KXADELAIDEMAYOR-27APR07", "Adelaide Lord Mayor election winner?", True,
                     [tob("A", "0.39", "0.41", title="Jane Lomax-Smith"),
                      tob("B", "0.21", "0.23", title="Henry Davis")])
    assert detect_exclusive(race, SCHED, RULES) == []
    from app.scanner.detectors import near_misses
    assert all(n.kind != "EXCL_YES" for n in near_misses([race]))


def test_near_misses_skip_non_exhaustive_yes_sets() -> None:
    from app.scanner.detectors import near_misses

    state = EventBook("KXSTATE51-29", "51st state?", True,
                      [tob(n, "0.01", "0.02", title=n) for n in ("Greenland", "Canada", "DC")])
    assert [n.kind for n in near_misses([state])] == ["EXCL_NO"]  # YES set not eligible
