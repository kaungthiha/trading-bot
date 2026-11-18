from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.clock import FrozenClock
from app.core.config import Settings
from app.db.models import Market, ModelEvaluation
from app.db.repositories import MarketRepository
from app.db.session import make_engine, make_session_factory
from app.domain.models import BookLevel, MarketSnapshot, MarketStatus, OrderBook, PriceRange
from app.evidence.repository import EvidenceRepository
from app.main import create_app
from app.signals.engine import (
    Level,
    Reason,
    SignalDecision,
    SignalInputs,
    SignalParams,
    derived_asks,
    evaluate,
    walk_book,
)
from app.signals.fees import FeeSchedule, load_schedules, select_schedule, taker_buy_cost
from app.signals.mapping import MappingError, decide, latest_mapping, propose_all
from app.signals.service import generate_signals
from tests.research_fixtures import synthetic_vintages

D = Decimal
NOW = datetime(2024, 1, 20, 15, 0, tzinfo=UTC)


def schedule(verified: bool = True) -> FeeSchedule:
    return FeeSchedule(
        version="test-v1", fee_types=("quadratic", "quadratic_with_maker_fees"),
        taker_rate=D("0.07"), maker_multiplier={"quadratic_with_maker_fees": D("0.25")},
        trade_fee_rounding_step=D("0.000001"), balance_precision=D("0.01"),
        source_url="https://example.invalid/fees.pdf", verified=verified,
        verified_by="tester" if verified else None, verified_at="2026-11-18" if verified else None,
    )


PARAMS = SignalParams(quantity=D("10"), slippage_per_contract=D("0.01"), max_spread=D("0.10"),
                      min_edge=D("0.02"), quote_max_age=timedelta(seconds=60),
                      min_holdout_events=60)


def inputs(**over) -> SignalInputs:  # type: ignore[no-untyped-def]
    base = SignalInputs(
        now=NOW, market_status="active", market_type="binary",
        close_at=NOW + timedelta(days=20), notional=D("1"),
        price_ranges=[PriceRange(start=D("0"), end=D("1"), step=D("0.01"))],
        fee_type="quadratic_with_maker_fees", fee_multiplier=D("1"),
        current_rules_hash="h1", mapping_status="confirmed", mapping_rules_hash="h1",
        quote_observed_at=NOW - timedelta(seconds=10),
        yes_bids=[Level(D("0.40"), D("100"))], no_bids=[Level(D("0.55"), D("100"))],
        forecast_decision="FORECAST", forecast_reasons=[],
        p_yes=0.60, p_lower=0.55, p_upper=0.65,
        model_holdout_events=140, model_beats_baseline=True, fee_schedule=schedule(),
    )
    return replace(base, **over)


# --- Fees -----------------------------------------------------------------------------


def test_taker_cost_worked_example() -> None:
    # 10 contracts at $0.45: model fee 0.07*10*0.45*0.55 = 0.17325
    c = taker_buy_cost(schedule(), [(D("10"), D("0.45"))])
    assert c.notional == D("4.50") and c.trade_fees == D("0.173250")
    assert c.total_debit == D("4.68") and c.effective_fee == D("0.18")


def test_trade_fee_ceil_to_micro_dollar() -> None:
    c = taker_buy_cost(schedule(), [(D("1"), D("0.5"))])  # 0.0175 exactly
    assert c.trade_fees == D("0.017500") and c.total_debit == D("0.52")
    c2 = taker_buy_cost(schedule(), [(D("3"), D("0.33"))])  # 0.046431 exactly
    assert c2.trade_fees == D("0.046431")


def test_shipped_schedules_prefer_pdf_verified_entry() -> None:
    cand, verified = load_schedules()
    assert cand.verified is False and verified.verified is True
    assert verified.version == "kalshi-fee-schedule-2026-07-07"
    assert select_schedule([cand, verified], "quadratic_with_maker_fees") is verified
    assert select_schedule([cand, verified], "flat") is None  # flat fees still unsupported


def test_schedule_file_validation(tmp_path: Path) -> None:
    bad = {"schedules": [{"version": "v", "fee_types": ["quadratic"], "taker_rate": "0.07",
                          "trade_fee_rounding_step": "0.000001", "balance_precision": "0.01",
                          "source_url": "x", "verified": True}]}
    p = tmp_path / "f.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="verified_by"):
        load_schedules(p)


def test_select_prefers_verified() -> None:
    cand, ver = schedule(False), replace(schedule(True), version="v2")
    assert select_schedule([ver, cand], "quadratic") is ver


# --- Book math ------------------------------------------------------------------------


def test_derived_asks_and_vwap_across_levels() -> None:
    asks = derived_asks([Level(D("0.55"), D("5")), Level(D("0.54"), D("10"))], D("1"))
    assert asks == [Level(D("0.45"), D("5")), Level(D("0.46"), D("10"))]
    fills = walk_book(asks, D("10"))
    assert fills == [(D("5"), D("0.45")), (D("5"), D("0.46"))]
    assert walk_book(asks, D("16")) is None


# --- Engine ---------------------------------------------------------------------------


def test_candidate_yes_with_exact_numbers() -> None:
    r = evaluate(inputs(), PARAMS)
    assert r.decision is SignalDecision.CANDIDATE_YES and r.reasons == []
    y = r.chosen
    assert (y.entry, y.fee, y.slippage) == (D("0.450000"), D("0.018000"), D("0.01"))
    assert y.ev == D("0.122000")  # 0.60 - 0.45 - 0.018 - 0.01
    assert y.lower_edge == D("0.072000")  # 0.55 - ...
    assert y.lower_edge_stressed == D("0.044000")  # doubled fee + slippage
    assert r.spread_yes == D("0.05")
    assert any("not an order" in c for c in r.caveats)


def test_fees_turn_positive_raw_edge_negative() -> None:
    r = evaluate(inputs(p_yes=0.47, p_lower=0.46, p_upper=0.48), PARAMS)
    y = r.yes
    assert D("0.47") - y.entry > 0  # raw edge positive
    assert y.ev < 0  # after fees + slippage
    assert r.decision is SignalDecision.ABSTAIN and Reason.EDGE_BELOW_MARGIN in r.reasons


def test_candidate_no_and_cost_robustness() -> None:
    fragile = evaluate(inputs(p_yes=0.30, p_lower=0.25, p_upper=0.35), PARAMS)
    assert fragile.side == "NO" and fragile.chosen.lower_edge == D("0.023000")
    assert Reason.EDGE_NOT_ROBUST_TO_COSTS in fragile.reasons
    robust = evaluate(inputs(p_yes=0.30, p_lower=0.25, p_upper=0.33), PARAMS)
    assert robust.decision is SignalDecision.CANDIDATE_NO


@pytest.mark.parametrize("over,reason", [
    ({"quote_observed_at": NOW - timedelta(seconds=61)}, Reason.QUOTE_STALE),
    ({"quote_observed_at": NOW + timedelta(seconds=5)}, Reason.QUOTE_STALE),
    ({"quote_observed_at": None, "yes_bids": [], "no_bids": []}, Reason.QUOTE_MISSING),
    ({"mapping_rules_hash": "old"}, Reason.RULES_CHANGED),
    ({"mapping_status": "proposed"}, Reason.MAPPING_NOT_CONFIRMED),
    ({"mapping_status": None, "mapping_rules_hash": None}, Reason.NO_MAPPING),
    ({"market_status": "closed"}, Reason.MARKET_NOT_OPEN),
    ({"market_type": "scalar"}, Reason.NOT_BINARY),
    ({"model_holdout_events": 10}, Reason.MODEL_NOT_VALIDATED),
    ({"model_beats_baseline": False}, Reason.MODEL_NOT_VALIDATED),
    ({"fee_type": None}, Reason.FEE_TYPE_UNKNOWN),
    ({"fee_schedule": None}, Reason.FEE_TYPE_UNSUPPORTED),
    ({"fee_multiplier": D("2")}, Reason.FEE_MULTIPLIER_UNVERIFIED),
    ({"yes_bids": [Level(D("0.30"), D("100"))]}, Reason.SPREAD_TOO_WIDE),
    ({"price_ranges": [PriceRange(start=D("0"), end=D("1"), step=D("0.02"))]},
     f"{Reason.PRICE_OFF_GRID}:YES"),
])
def test_gates_force_abstain(over, reason) -> None:  # type: ignore[no-untyped-def]
    r = evaluate(inputs(**over), PARAMS)
    assert r.decision is SignalDecision.ABSTAIN
    assert str(reason) in r.reasons


def test_unverified_fees_abstain_but_still_show_numbers() -> None:
    r = evaluate(inputs(fee_schedule=schedule(verified=False)), PARAMS)
    assert r.decision is SignalDecision.ABSTAIN and r.reasons == ["FEE_SCHEDULE_UNVERIFIED"]
    assert r.chosen.ev == D("0.122000")
    assert any("UNVERIFIED" in c for c in r.caveats)


def test_model_abstention_forwarded_and_no_ev() -> None:
    r = evaluate(inputs(forecast_decision="ABSTAIN", forecast_reasons=["HORIZON_NOT_SUPPORTED"],
                        p_yes=None, p_lower=None, p_upper=None), PARAMS)
    assert "MODEL_ABSTAINED" in r.reasons and "model:HORIZON_NOT_SUPPORTED" in r.reasons
    assert r.chosen is None and r.yes.entry == D("0.450000") and r.yes.ev is None


def test_insufficient_depth_on_one_side() -> None:
    r = evaluate(inputs(no_bids=[Level(D("0.55"), D("5"))]), PARAMS)
    assert f"{Reason.INSUFFICIENT_DEPTH}:YES" in r.yes.reasons
    assert r.no.entry is not None  # other side still evaluated


def test_expiry_is_quote_age_capped_by_close() -> None:
    r = evaluate(inputs(), PARAMS)
    assert r.expires_at == NOW - timedelta(seconds=10) + timedelta(seconds=60)
    r2 = evaluate(inputs(close_at=NOW + timedelta(seconds=5)), PARAMS)
    assert r2.expires_at == NOW + timedelta(seconds=5)


# --- Mapping + service + API (DB) -----------------------------------------------------

RULES = ("If the Consumer Price Index (CPI) increases by more than 0.2% in January 2024, as "
         "reported to one decimal place, then the market resolves to Yes.\n\nPlease note: the "
         "Expiration Value is the single-decimal value published at the Source Agency.")


def kxcpi_snapshot(ticker: str = "KXCPI-24JAN-T0.2", rules: str = RULES,
                   observed: datetime = NOW - timedelta(seconds=10)) -> MarketSnapshot:
    return MarketSnapshot(
        exchange="kalshi", external_ticker=ticker, event_ticker="KXCPI-24JAN",
        series_ticker="KXCPI", title="Will CPI rise more than 0.2% in January 2024?",
        category="economics", status=MarketStatus.ACTIVE, status_raw="active",
        close_at=datetime(2024, 2, 13, 13, 29, tzinfo=UTC), rules_text=rules,
        official_source_url="https://assets.kalshi.com/contract_terms/CPI.pdf",
        notional_value=D("1.0000"),
        price_ranges=(PriceRange(start=D("0"), end=D("1"), step=D("0.01")),),
        orderbook=OrderBook(observed_at=observed,
                            yes_bids=(BookLevel(price=D("0.40"), quantity=D("100")),),
                            no_bids=(BookLevel(price=D("0.55"), quantity=D("100")),)),
        fee_type="quadratic_with_maker_fees", fee_multiplier=D("1"),
    )


@pytest.fixture
def db(settings: Settings):  # type: ignore[no-untyped-def]
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    with factory() as s:
        EvidenceRepository(s).insert_new("fred:CPIAUCSL", synthetic_vintages())
        MarketRepository(s, FrozenClock(NOW)).upsert_snapshot(kxcpi_snapshot(), "kalshi_public")
        MarketRepository(s, FrozenClock(NOW)).upsert_snapshot(
            kxcpi_snapshot("KXCPI-24JAN-T0.5"), "kalshi_public")  # ticker/rules disagree
        for model, brier in (("gaussian_trailing", 0.15), ("base_rate", 0.17)):
            s.add(ModelEvaluation(created_at=NOW, model=model, version="1.0.0",
                                  feature_version="f", dataset_hash="x", config_json="{}",
                                  dev_json="{}", data_notes_json="{}",
                                  holdout_json=json.dumps({"n_events": 140, "brier": brier})))
        s.commit()
    yield factory
    engine.dispose()


def _market(s, ticker: str) -> Market:  # type: ignore[no-untyped-def]
    from sqlalchemy import select
    return s.scalar(select(Market).where(Market.external_ticker == ticker))


def test_propose_and_confirm_mapping(db) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        created = {m.external_ticker: row for m, row in propose_all(s, NOW)}
        good, bad = created["KXCPI-24JAN-T0.2"], created["KXCPI-24JAN-T0.5"]
        assert good.status == "proposed" and good.threshold == D("0.2")
        assert good.reference_month == "2024-01-01"
        assert any("seasonally adjusted" in n for n in json.loads(good.notes_json))
        assert bad.status == "rejected" and "disagrees" in json.loads(bad.notes_json)[0]
        assert propose_all(s, NOW) == []  # idempotent for unchanged rules
        with pytest.raises(MappingError):
            decide(s, _market(s, "KXCPI-24JAN-T0.5"), NOW, confirm=True)  # rejected
        row = decide(s, _market(s, "KXCPI-24JAN-T0.2"), NOW, confirm=True, note="checked PDF")
        assert row.status == "confirmed" and row.actor == "user"
        assert latest_mapping(s, row.market_id).id == row.id
        s.commit()


def _confirm(s) -> None:  # type: ignore[no-untyped-def]
    propose_all(s, NOW)
    decide(s, _market(s, "KXCPI-24JAN-T0.2"), NOW, confirm=True)


def test_generate_signals_end_to_end(db, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        _confirm(s)
        sigs = {(_market_ticker(s, g)): g for g in
                generate_signals(s, settings, NOW, schedules=[schedule(verified=True)])}
        g = sigs["KXCPI-24JAN-T0.2"]
        assert g.quote_id and g.model_run_id and g.mapping_id and g.rules_hash
        assert g.fee_schedule_version == "test-v1"
        assert json.loads(g.caveats_json)
        reasons = json.loads(g.reasons_json)
        assert g.decision in ("CANDIDATE_YES", "CANDIDATE_NO", "ABSTAIN")
        assert not any(r in reasons for r in ("QUOTE_STALE", "RULES_CHANGED",
                                              "MAPPING_NOT_CONFIRMED", "MODEL_ABSTAINED"))
        rejected = sigs["KXCPI-24JAN-T0.5"]
        assert rejected.decision == "ABSTAIN"
        assert "MAPPING_NOT_CONFIRMED" in json.loads(rejected.reasons_json)

        default = generate_signals(s, settings, NOW)  # shipped schedules (PDF-verified)
        mine = [x for x in default if _market_ticker(s, x) == "KXCPI-24JAN-T0.2"]
        assert all("FEE_SCHEDULE_UNVERIFIED" not in json.loads(x.reasons_json) for x in mine)
        assert {x.fee_schedule_version for x in mine} == {"kalshi-fee-schedule-2026-07-07"}
        s.commit()


def _market_ticker(s, sig) -> str:  # type: ignore[no-untyped-def]
    return s.get(Market, sig.market_id).external_ticker


def test_rule_change_invalidates_signals_and_mapping(db, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        _confirm(s)
        generate_signals(s, settings, NOW, schedules=[schedule()])
        s.commit()
    with db() as s:  # exchange edits the rules
        MarketRepository(s, FrozenClock(NOW)).upsert_snapshot(
            kxcpi_snapshot(rules=RULES + " AMENDED."), "kalshi_public")
        s.commit()
    app = create_app(settings, FrozenClock(NOW))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        sig = next(x for x in c.get("/api/signals").json()
                   if x["market_ticker"] == "KXCPI-24JAN-T0.2")
        assert sig["validity"] == "INVALIDATED_RULES_CHANGED"
        maps = {m["market_ticker"]: m for m in c.get("/api/mappings").json()}
        assert maps["KXCPI-24JAN-T0.2"]["rules_current"] is False
    app.state.engine.dispose()
    with db() as s:
        new = [g for g in generate_signals(s, settings, NOW, schedules=[schedule()])
               if _market_ticker(s, g) == "KXCPI-24JAN-T0.2"][0]
        assert new.decision == "ABSTAIN" and "RULES_CHANGED" in json.loads(new.reasons_json)
        with pytest.raises(MappingError):
            decide(s, _market(s, "KXCPI-24JAN-T0.2"), NOW, confirm=True)


def test_signal_api_shapes(db, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        _confirm(s)
        generate_signals(s, settings, NOW, schedules=[schedule()])
        s.commit()
    app = create_app(settings, FrozenClock(NOW + timedelta(minutes=5)))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        sig = next(x for x in c.get("/api/signals").json()
                   if x["market_ticker"] == "KXCPI-24JAN-T0.2")
        assert sig["validity"] == "EXPIRED"  # quote older than 60s by now
        assert sig["quote_id"] and sig["model_run_id"] and sig["caveats"]
        assert sig["rules_source_url"].startswith("https://assets.kalshi.com/")
        assert sig["details"]["yes"]["entry"] == "0.450000"
        fees = c.get("/api/fee-schedules").json()
        assert fees[0]["verified"] is False
        mid = sig["market_id"]
        assert len(c.get(f"/api/markets/{mid}/signals").json()) == 1
        paths = c.get("/api/openapi.json").json()["paths"]
        writes = {(p, m) for p, ops in paths.items() for m in ops if m != "get"}
        assert writes == {("/api/paper/orders", "post")}  # only simulated paper orders
    app.state.engine.dispose()


NOV_RULES = ("If the Consumer Price Index (CPI) increases by more than 0.3% (single-decimal) in "
             "November 2026, then the market resolves to Yes.\n\nThe market will always close "
             "at 8:29 AM ET on the scheduled day of the data release (December 10, 2026). "
             "Please note: the Expiration Value is the single-decimal value published at the "
             "Source Agency.")


def test_both_live_rule_templates_parse_and_others_reject() -> None:
    from types import SimpleNamespace

    from app.signals.mapping import propose_cpi_mom

    def mk(ticker: str):  # type: ignore[no-untyped-def]
        return SimpleNamespace(series_ticker="KXCPI", market_type="binary",
                               external_ticker=ticker)

    nov = propose_cpi_mom(mk("KXCPI-26NOV-T0.3"), NOV_RULES, None)
    assert (nov.status, nov.reference_month, nov.threshold) == (
        "proposed", date(2026, 11, 1), D("0.3"))
    neg = propose_cpi_mom(mk("KXCPI-26NOV-T-0.1"), NOV_RULES.replace("0.3%", "-0.1%"), None)
    assert neg.status == "proposed" and neg.threshold == D("-0.1")
    # Missing the single-decimal qualifier -> not recognised -> rejected, not guessed
    vague = NOV_RULES.replace(" (single-decimal)", "")
    assert propose_cpi_mom(mk("KXCPI-26NOV-T0.3"), vague, None).status == "rejected"
    # Inclusive wording must not be mistaken for strict
    incl = NOV_RULES.replace("more than", "at least")
    assert propose_cpi_mom(mk("KXCPI-26NOV-T0.3"), incl, None).status == "rejected"


def test_parser_rejection_revisited_but_human_decision_stands(db) -> None:  # type: ignore[no-untyped-def]
    from app.db.models import MarketMapping

    with db() as s:
        propose_all(s, NOW)
        m = _market(s, "KXCPI-24JAN-T0.2")
        # Simulate an older parser that had rejected this market for the same rules.
        s.add(MarketMapping(created_at=NOW + timedelta(seconds=1), market_id=m.id,
                            contract_type="CPI_MOM_SA_FIRST", rules_hash=latest_mapping(
                                s, m.id).rules_hash, status="rejected", actor="parser",
                            notes_json="[]"))
        s.flush()
        revisited = [row for mk, row in propose_all(s, NOW + timedelta(seconds=2))
                     if mk.id == m.id]
        assert revisited and revisited[0].status == "proposed"
        decide(s, m, NOW + timedelta(seconds=3), confirm=False, note="not comfortable")
        assert [row for mk, row in propose_all(s, NOW + timedelta(seconds=4))
                if mk.id == m.id] == []  # human rejection stands


def test_live_like_divergence_abstains() -> None:
    # Shape of the real KXCPI-26NOV-T0.1 book on 2026-11-18: YES bid 0.01, NO bids up to
    # 0.97 (YES ask 0.03), while the past-prints-only model said ~0.80.
    r = evaluate(inputs(p_yes=0.799, p_lower=0.709, p_upper=0.87,
                        yes_bids=[Level(D("0.01"), D("32751"))],
                        no_bids=[Level(D("0.97"), D("266")), Level(D("0.96"), D("252"))]),
                 PARAMS)
    assert r.decision is SignalDecision.ABSTAIN
    assert Reason.MODEL_MARKET_DIVERGENCE in r.reasons
    assert r.model_market_divergence == D("0.769000")  # 0.799 - 0.03
    assert r.chosen.lower_edge > 0  # the naive "edge" exists, which is exactly the trap


def test_one_sided_book_abstains() -> None:
    r = evaluate(inputs(yes_bids=[]), PARAMS)
    assert Reason.ONE_SIDED_BOOK in r.reasons and r.decision is SignalDecision.ABSTAIN


def test_divergence_within_tolerance_is_allowed() -> None:
    r = evaluate(inputs(), PARAMS)  # p 0.60 vs [0.40, 0.45] -> 0.15 <= 0.20
    assert r.model_market_divergence == D("0.150000") and r.decision is SignalDecision.CANDIDATE_YES
