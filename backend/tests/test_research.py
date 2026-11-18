from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from scipy.stats import norm
from sqlalchemy.exc import IntegrityError

from app.core.clock import FrozenClock
from app.core.config import Settings
from app.db.models import ModelRun
from app.db.session import make_engine, make_session_factory
from app.evidence.repository import EvidenceRepository
from app.main import create_app
from app.research.backtest import walk_forward
from app.research.cpi import (
    CpiMomContract,
    LeakageError,
    build_first_prints,
    history_as_of,
    round_tenth,
)
from app.research.metrics import brier, calibration_bins, log_loss, summarize
from app.research.models import (
    AbstainReason,
    BaseRateModel,
    Decision,
    GaussianTrailingModel,
)
from app.research.service import evaluate_and_save, forecast_all, save_forecast
from tests.research_fixtures import as_records, obs, synthetic_vintages

D = Decimal


@pytest.fixture(scope="module")
def prints():  # type: ignore[no-untyped-def]
    return build_first_prints(as_records(synthetic_vintages())).prints


# --- First prints ---------------------------------------------------------------------


def test_first_prints_reconstructed_with_rounding(prints) -> None:  # type: ignore[no-untyped-def]
    assert len(prints) == 59  # first month has no previous month
    # Indexes are rounded to 3 dp, so recovered MoM rounds back to the pattern value.
    assert [str(p.mom_rounded) for p in prints[:6]] == ["0.2", "0.3", "0.4", "0.2", "0.3", "0.1"]
    p = prints[0]
    assert p.released_at == datetime(2019, 3, 12, 12, 30, tzinfo=UTC)  # 08:30 EDT


def test_prev_index_taken_from_same_vintage_revision() -> None:
    rows = [
        obs(date(2026, 1, 1), date(2026, 2, 12), D("300.000")),
        # Feb release also revises January to 301.000; Feb MoM must use the revised value
        obs(date(2026, 1, 1), date(2026, 3, 12), D("301.000")),
        obs(date(2026, 2, 1), date(2026, 3, 12), D("301.903")),
    ]
    build = build_first_prints(as_records(rows))
    (feb,) = build.prints  # January excluded: no December index in its vintage
    assert build.excluded == {"previous_month_missing_in_vintage": 1}
    assert feb.prev_index == D("301.000")
    assert feb.mom_rounded == D("0.3")


def test_late_first_vintage_excluded() -> None:
    rows = [obs(date(2000, 1, 1), date(2000, 2, 15), D("100")),
            obs(date(2000, 2, 1), date(2003, 1, 1), D("101"))]  # years late: not a first print
    build = build_first_prints(as_records(rows))
    assert build.prints == [] or all(p.month != date(2000, 2, 1) for p in build.prints)
    assert build.excluded["earliest_vintage_not_a_first_print"] == 1


def test_rounding_and_resolution_are_strict() -> None:
    assert round_tenth(D("0.25")) == D("0.3")  # half-up
    assert round_tenth(D("0.2499")) == D("0.2")
    c = CpiMomContract(date(2026, 11, 1), D("0.3"))
    assert not c.resolves_yes(D("0.3")) and c.resolves_yes(D("0.4"))
    with pytest.raises(ValueError):
        CpiMomContract(date(2026, 11, 15), D("0.3"))


# --- Chronology & abstention ----------------------------------------------------------


def test_history_as_of_excludes_future(prints) -> None:  # type: ignore[no-untyped-def]
    cutoff = prints[10].released_at - timedelta(seconds=1)
    hist = history_as_of(prints, cutoff)
    assert hist == prints[:10]


def test_model_rejects_leaked_inputs(prints) -> None:  # type: ignore[no-untyped-def]
    target = prints[40]
    early = target.released_at - timedelta(days=1)
    with pytest.raises(LeakageError):
        BaseRateModel(min_history=12).predict(
            CpiMomContract(target.month, D("0.2")), prints[:41], early)


def _next(prints, i):  # type: ignore[no-untyped-def]
    cutoff = prints[i].released_at - timedelta(seconds=1)
    return CpiMomContract(prints[i].month, D("0.2")), history_as_of(prints, cutoff), cutoff


@pytest.mark.parametrize("model", [BaseRateModel(min_history=36),
                                   GaussianTrailingModel(min_history=36)])
def test_abstentions(model, prints) -> None:  # type: ignore[no-untyped-def]
    c, hist, cutoff = _next(prints, 10)
    f = model.predict(c, hist, cutoff)
    assert f.decision is Decision.ABSTAIN and f.p_yes is None
    assert AbstainReason.INSUFFICIENT_HISTORY in f.reasons

    c, hist, cutoff = _next(prints, 50)
    published = model.predict(CpiMomContract(prints[49].month, D("0.2")), hist, cutoff)
    assert AbstainReason.OUTCOME_ALREADY_PUBLISHED in published.reasons
    two_ahead = model.predict(CpiMomContract(prints[51].month, D("0.2")), hist, cutoff)
    assert AbstainReason.HORIZON_NOT_SUPPORTED in two_ahead.reasons
    off_grid = model.predict(CpiMomContract(c.reference_month, D("0.25")), hist, cutoff)
    assert AbstainReason.THRESHOLD_OFF_GRID in off_grid.reasons
    ok = model.predict(c, hist, cutoff)
    assert ok.decision is Decision.FORECAST and 0 <= ok.lower <= ok.p_yes <= ok.upper <= 1


# --- Model values & reproducibility ---------------------------------------------------


def test_base_rate_jeffreys_posterior_mean(prints) -> None:  # type: ignore[no-untyped-def]
    m = BaseRateModel(window=24, min_history=24)
    c, hist, cutoff = _next(prints, 50)
    f = m.predict(c, hist, cutoff)
    win = hist[-24:]
    k = sum(p.mom_rounded > D("0.2") for p in win)
    assert f.inputs["n"] == 24 and f.inputs["k"] == k
    assert f.p_yes == pytest.approx((k + 0.5) / 25)


def test_gaussian_matches_closed_form_with_rounding_cut(prints) -> None:  # type: ignore[no-untyped-def]
    m = GaussianTrailingModel(k_mean=12, k_sd=36, min_history=36)
    c, hist, cutoff = _next(prints, 50)
    f = m.predict(c, hist, cutoff)
    vals = [float(p.mom_pct) for p in hist]
    mu = sum(vals[-12:]) / 12
    sd = (sum((v - sum(vals[-36:]) / 36) ** 2 for v in vals[-36:]) / 35) ** 0.5
    assert f.p_yes == pytest.approx(norm.sf(0.25, loc=mu, scale=sd))  # T + 0.05
    assert "NOT a confidence interval" in f.uncertainty_method


def test_predictions_are_reproducible(prints) -> None:  # type: ignore[no-untyped-def]
    c, hist, cutoff = _next(prints, 50)
    for m in (BaseRateModel(min_history=36), GaussianTrailingModel()):
        a, b = m.predict(c, hist, cutoff), m.predict(c, list(hist), cutoff)
        assert a == b and a.inputs["input_hash"] == b.inputs["input_hash"]


# --- Walk-forward ---------------------------------------------------------------------


def test_walk_forward_chronology_and_sample_sizes(prints) -> None:  # type: ignore[no-untyped-def]
    split = datetime(2022, 1, 1, tzinfo=UTC)
    rep = walk_forward(GaussianTrailingModel(min_history=24), prints,
                       thresholds=[D("0.1"), D("0.2"), D("0.3")], holdout_start=split)
    by_month = {p.month: p for p in prints}
    for pr in rep.predictions:
        assert pr.cutoff < by_month[date.fromisoformat(pr.month)].released_at
    assert all(p.cutoff < split for p in rep.predictions if p.month <= rep.dev_range[1])
    total = rep.dev.n_predictions + rep.dev.n_abstained + rep.holdout.n_predictions \
        + rep.holdout.n_abstained
    assert total == len(prints) * 3
    assert rep.holdout.n_events * 3 == rep.holdout.n_predictions
    assert rep.dev.n_abstained == 24 * 3  # first 24 months lack history
    assert rep.holdout.brier is not None and rep.holdout.n_predictions > 0


def test_walk_forward_rejects_inconsistent_release_order(prints) -> None:  # type: ignore[no-untyped-def]
    bad = list(prints)
    bad[5] = replace(bad[5], released_at=bad[4].released_at - timedelta(days=1))
    with pytest.raises(LeakageError):
        walk_forward(BaseRateModel(min_history=3), bad)


# --- Metrics --------------------------------------------------------------------------


def test_scoring_rules() -> None:
    assert brier([0.7], [1]) == pytest.approx(0.09)
    assert brier([0.5, 0.5], [0, 1]) == pytest.approx(0.25)
    assert log_loss([0.5], [1]) == pytest.approx(math.log(2))
    assert math.isfinite(log_loss([0.0], [1]))  # clipped, not infinite
    with pytest.raises(ValueError):
        log_loss([1.2], [1])
    bins = calibration_bins([0.05, 0.07, 0.95], [0, 1, 1])
    assert bins[0].count == 2 and bins[0].observed_rate == 0.5 and bins[9].count == 1
    s = summarize([0.2, 0.8], [0, 1], n_events=1, n_abstained=3)
    assert (s.n_predictions, s.n_events, s.n_abstained, s.base_rate) == (2, 1, 3, 0.5)
    empty = summarize([], [], 0, 5)
    assert empty.brier is None and empty.n_abstained == 5


# --- Service, persistence, API --------------------------------------------------------


@pytest.fixture
def seeded_cpi(seeded: Settings) -> Settings:
    engine = make_engine(seeded.database_url)
    with make_session_factory(engine)() as s:
        EvidenceRepository(s).insert_new("fred:CPIAUCSL", synthetic_vintages())
        s.commit()
    engine.dispose()
    return seeded


NOW = datetime(2024, 1, 20, tzinfo=UTC)  # after the Dec-2023 print (released 2024-01-12)


def test_service_forecast_evaluate_and_save(seeded_cpi: Settings) -> None:
    engine = make_engine(seeded_cpi.database_url)
    with make_session_factory(engine)() as s:
        contract, fs, build = forecast_all(s, D("0.2"), NOW)
        assert contract.reference_month == date(2024, 1, 1)
        assert {f.model for f in fs} == {"base_rate", "gaussian_trailing"}
        assert all(f.decision is Decision.FORECAST for f in fs)
        run = save_forecast(s, fs[0], NOW)
        reports = evaluate_and_save(s, NOW)
        s.commit()
        assert run.p_yes == fs[0].p_yes and len(reports) == 2
        bad = ModelRun(created_at=NOW, contract_key="x", model="m", version="1",
                       feature_version="f", as_of=NOW, decision="FORECAST", p_yes=1.5,
                       uncertainty_method="none", reasons_json="[]", inputs_json="{}")
        s.add(bad)
        with pytest.raises(IntegrityError):  # DB CHECK: probabilities within [0,1]
            s.flush()
        s.rollback()
    engine.dispose()


def test_research_api(seeded_cpi: Settings) -> None:
    app = create_app(seeded_cpi, FrozenClock(NOW))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        cards = c.get("/api/models").json()
        assert {m["name"] for m in cards} == {"base_rate", "gaussian_trailing"}
        assert all(m["limitations"] and m["uncertainty_method"] for m in cards)

        r = c.get("/api/research/cpi-mom/forecast", params={"threshold": "0.2"}).json()
        assert r["reference_month"] == "2024-01-01"
        assert r["contract_key"] == "CPI_MOM_SA_FIRST>0.2@2024-01"
        assert len(r["recent_prints"]) == 12 and r["recent_prints"][0]["month"] == "2023-12"
        assert all(f["decision"] == "FORECAST" for f in r["forecasts"])
        assert "not trade recommendations" in r["caveat"]

        # Point-in-time: as of mid-2020 the next month is different and history shorter
        past = c.get("/api/research/cpi-mom/forecast",
                     params={"threshold": "0.2", "as_of": "2020-06-20T00:00:00Z"}).json()
        assert past["reference_month"] == "2020-06-01"
        assert all(f["decision"] == "ABSTAIN" for f in past["forecasts"])
        assert all("INSUFFICIENT_HISTORY" in f["reasons"] for f in past["forecasts"])

        assert c.get("/api/research/cpi-mom/forecast",
                     params={"as_of": "2030-01-01T00:00:00Z"}).status_code == 422
        assert c.get("/api/research/cpi-mom/forecast",
                     params={"threshold": "9"}).status_code == 422
        assert c.get("/api/models/metrics").json() == []  # nothing evaluated yet
        assert c.get("/api/model-runs").json() == []
    app.state.engine.dispose()


def test_forecast_without_evidence_is_409(seeded: Settings) -> None:
    app = create_app(seeded, FrozenClock(NOW))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        r = c.get("/api/research/cpi-mom/forecast")
        assert r.status_code == 409 and r.json()["error"]["code"] == "MISSING_EVIDENCE"
    app.state.engine.dispose()
