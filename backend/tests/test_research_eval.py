"""Offline evidence-quality harness and the opt-in smoke command (no network in tests)."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app import cli
from app.core.config import Settings
from app.investigate import schemas as S
from app.investigate.evaluate import MappingCase, classify_error, evaluate
from tests.test_nhl import KEY, SPREAD, TOTAL, WIN, MPServer, _app, run
from tests.test_research_synth import base


def _nhl_results(settings: Settings, **over) -> list[S.Result]:  # type: ignore[no-untyped-def]
    with TestClient(_app(settings, MPServer(), **over), base_url="http://127.0.0.1") as c:
        return [
            S.Result.model_validate(run(c, t, side))
            for t, side in ((WIN, "yes"), (TOTAL, "yes"), (SPREAD, "no"))
        ]


def test_mapping_accuracy_catches_a_wrong_line_and_side(settings: Settings) -> None:
    results = _nhl_results(settings)
    good = [
        MappingCase(WIN, "yes", "moneyline", None),
        MappingCase(TOTAL, "yes", "total", 5.5),
        MappingCase(SPREAD, "no", "spread", 1.5),
    ]
    rep = evaluate(results, good).rates()
    assert rep["mapping_accuracy"] == 1.0 and rep["mapping_errors"] == []
    wrong = [MappingCase(TOTAL, "yes", "total", 6.0), MappingCase(SPREAD, "no", "moneyline", 1.5)]
    rep2 = evaluate(results, wrong).rates()
    assert rep2["mapping_accuracy"] == 0.0
    assert any("line 5.5 != 6.0" in e for e in rep2["mapping_errors"])
    assert any("kind spread != moneyline" in e for e in rep2["mapping_errors"])


def test_quality_rates_missingness_and_calibration(settings: Settings) -> None:
    results = _nhl_results(settings) + [base()]
    rep = evaluate(results).rates()
    assert rep["results"] == 4
    assert rep["unsupported_claim_rate"] == 0.0 and rep["uncited_fact_rate"] == 0.0
    # Every NHL result had MoneyPuck numbers that no headline carried.
    assert rep["structured_adds_rate"] == 1.0
    nhl = rep["missing_by_league"]["NHL"]
    assert nhl["gap:goalie"] == 3 and nhl["permission"] == 3  # Brave isn't set up in tests
    assert rep["calibration"].startswith("not applicable")
    # Syndicated copies in the basketball fixture are counted as duplicates.
    assert rep["duplicate_rate"] == 0.25


def test_leakage_and_error_classes(settings: Settings) -> None:
    r = base()
    start = datetime(2026, 11, 19, 12, 0).astimezone()
    r.sources[3].published_at = (start + timedelta(hours=2)).isoformat()  # after tip-off
    r.sources[4].published_at = (start - timedelta(hours=2)).isoformat()
    rep = evaluate([r], starts={r.hypothesis.event_ticker: start}).rates()
    assert rep["leaked_sources"] == 1
    off = _nhl_results(settings, research_disabled_sources="moneypuck")
    errs = evaluate(off).rates()["errors_by_class"]
    assert errs["permission"] >= 3  # switched-off source and unconfigured Brave
    assert classify_error("Local model unavailable (timeout)") == "model"
    assert (
        classify_error("MoneyPuck season data unavailable right now (HTTP 503)") == "data_or_source"
    )
    assert KEY in off[0].hypothesis.event_ticker


def test_smoke_command_does_nothing_without_explicit_opt_in(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    import app.sportsdata.moneypuck as mpmod

    def boom(*a, **k):  # type: ignore[no-untyped-def]
        raise AssertionError("no live call without --live-moneypuck")

    monkeypatch.setattr(mpmod, "MoneyPuck", boom)
    assert cli.main(["research-smoke"]) == 0
    assert "Nothing run" in capsys.readouterr().out
