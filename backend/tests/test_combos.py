"""Kalshi combos: eligibility from collections, the settled-combo study, builder info."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.adapters.kalshi_public import KalshiPublicClient
from app.catalog.combos import (
    latest_study,
    refresh_combo_eligibility,
    run_combo_study,
    study,
    summarize,
)
from app.catalog.service import combo, event_detail
from app.catalog.store import CatalogWriter
from app.core.clock import FrozenClock
from app.core.config import KALSHI_REST_BASES, KalshiEnv, Settings
from app.db.session import make_engine, make_session_factory
from app.jobs import JobRunner

NOW = datetime(2026, 11, 18, 23, 0, tzinfo=UTC)
COLLECTIONS = {"multivariate_contracts": [
    {"collection_ticker": "KXMVECROSSCATEGORY-R",
     "associated_event_tickers": ["KXNBAGAME-26NOV18BOSDEN", "KXNBATOTAL-26NOV18BOSDEN"]},
    {"collection_ticker": "KXMVESPORTSMULTIGAMEEXTENDED-R",
     "associated_event_tickers": ["KXNBAGAME-26NOV18BOSDEN"]}]}


def settled(price: str, result: str, legs: int, vol: str = "10") -> dict:
    return {"ticker": f"KXMVE-{price}-{result}-{legs}", "last_price_dollars": price,
            "volume_fp": vol, "result": result, "mve_selected_legs": [{}] * legs}


SETTLED = {"markets": [settled("0.3000", "yes", 2), settled("0.3000", "no", 2),
                       settled("0.3000", "no", 2), settled("0.0500", "no", 7),
                       settled("0.5000", "no", 3, vol="0"),  # untraded: ignored
                       settled("0.2000", "", 3)],  # no result: ignored
           "cursor": ""}


def client() -> KalshiPublicClient:
    def handle(req: httpx.Request) -> httpx.Response:
        path = req.url.path.removeprefix("/trade-api/v2")
        if path == "/multivariate_event_collections":
            return httpx.Response(200, json=COLLECTIONS)
        if path == "/markets" and req.url.params.get("mve_filter") == "only":
            return httpx.Response(200, json=SETTLED)
        return httpx.Response(404)
    return KalshiPublicClient(KALSHI_REST_BASES[KalshiEnv.PRODUCTION],
                              transport=httpx.MockTransport(handle), sleep=lambda _: None,
                              min_interval=0.0, max_retries=0)


@pytest.fixture
def factory(settings: Settings):  # type: ignore[no-untyped-def]
    engine = make_engine(settings.database_url)
    f = make_session_factory(engine)
    CatalogWriter(f, NOW).write_page([
        {"event_ticker": "KXNBAGAME-26NOV18BOSDEN", "series_ticker": "KXNBAGAME",
         "title": "Boston vs Denver", "mutually_exclusive": True,
         "markets": [{"ticker": "KXNBAGAME-26NOV18BOSDEN-BOS", "title": "Boston",
                      "yes_sub_title": "Boston", "status": "active",
                      "yes_bid_dollars": "0.4900", "yes_ask_dollars": "0.5100"}]},
        {"event_ticker": "KXNBATOTAL-26NOV18BOSDEN", "series_ticker": "KXNBATOTAL",
         "title": "Total", "mutually_exclusive": False,
         "markets": [{"ticker": "KXNBATOTAL-26NOV18BOSDEN-221", "title": "Over 220.5",
                      "status": "active", "yes_bid_dollars": "0.4900",
                      "yes_ask_dollars": "0.5100"}]},
        {"event_ticker": "KXCPI-26DEC", "series_ticker": "KXCPI", "title": "CPI",
         "mutually_exclusive": False,
         "markets": [{"ticker": "KXCPI-26DEC-T0.3", "title": "Above 0.3", "status": "active",
                      "yes_bid_dollars": "0.3000", "yes_ask_dollars": "0.3200"}]}])
    yield f
    engine.dispose()


def test_summarize_return_per_dollar() -> None:
    s = summarize([(0.30, True), (0.30, False), (0.30, False)])
    assert s is not None
    assert (s["n"], s["hit_rate"], s["avg_price"]) == (3, 0.3333, 0.3)
    assert s["return_per_dollar"] == round(1 / 0.9, 4)  # paid 0.90, collected 1.00
    assert summarize([]) is None


def test_study_buckets_and_filters() -> None:
    st = study(SETTLED["markets"])
    assert st["overall"]["n"] == 4  # untraded and unresolved excluded
    legs = {b["bucket"]: b["n"] for b in st["by_legs"]}
    assert legs == {"2 legs": 3, "6+ legs": 1}
    assert {b["bucket"] for b in st["by_price"]} == {"5–15¢", "15–35¢"}


def test_eligibility_study_and_builder(factory) -> None:  # type: ignore[no-untyped-def]
    c = client()
    assert refresh_combo_eligibility(factory, c, NOW) == 2
    run_combo_study(factory, c, NOW)
    with factory() as s:
        assert latest_study(s)["overall"]["n"] == 4
        ev = event_detail(s, "KXNBAGAME-26NOV18BOSDEN")
        assert ev is not None and ev["combo_collections"] == [
            "KXMVECROSSCATEGORY-R", "KXMVESPORTSMULTIGAMEEXTENDED-R"]
        ok = combo(s, [("KXNBAGAME-26NOV18BOSDEN-BOS", "yes"),
                       ("KXNBATOTAL-26NOV18BOSDEN-221", "yes")])
        assert ok["kalshi"]["eligible"] and ok["kalshi"]["collections"] == ["KXMVECROSSCATEGORY-R"]
        assert ok["kalshi"]["history"]["bucket"] == "2 legs"
        bad = combo(s, [("KXNBAGAME-26NOV18BOSDEN-BOS", "yes"), ("KXCPI-26DEC-T0.3", "no")])
        assert not bad["kalshi"]["eligible"]
        assert bad["kalshi"]["ineligible_events"] == ["KXCPI-26DEC"]


def test_combos_job(settings: Settings, tmp_path: Path) -> None:
    engine = make_engine(settings.database_url)
    runner = JobRunner(settings, make_session_factory(engine), FrozenClock(NOW),
                       synchronous=True, client_factory=client,
                       worker_lock_path=tmp_path / "w.lock")
    runner.run("combos")
    st = runner.state["combos"]
    assert st.last_status == "success" and "4 settled combos" in (st.last_message or "")
    engine.dispose()
