"""Market catalog: storage from scan pages, research statistics, and the read-only API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.kalshi_public import KalshiPublicClient
from app.catalog.stats import (
    Quote,
    combo_stats,
    exclusive_stats,
    expected_value,
    implied,
    ladder_groups,
    ladder_stats,
    merge_margin_ladders,
    scaled_schedule,
)
from app.catalog.store import CatalogWriter
from app.core.clock import FrozenClock
from app.core.config import KALSHI_REST_BASES, KalshiEnv, Settings
from app.db.models import CatalogEvent, CatalogMarket, CatalogSeries
from app.db.session import make_engine, make_session_factory
from app.jobs import JobRunner
from app.main import create_app
from app.scanner.service import run_scan
from app.signals.fees import load_schedules, select_schedule
from tests.test_scanner import BOOKS, EVENTS, SCHED, kalshi

NOW = datetime(2026, 11, 18, 23, 0, tzinfo=UTC)
FEES = select_schedule(load_schedules(), "quadratic")
assert FEES is not None and FEES.verified


def q(ticker: str, bid: str | None, ask: str | None, strike: str | None = None,
      title: str = "", group: str = "") -> Quote:
    return Quote(ticker, title or ticker, D(bid) if bid else None, D(ask) if ask else None,
                 "greater" if strike else None, D(strike) if strike else None, group,
                 title or ticker)


# --- statistics -------------------------------------------------------------------------------


def test_implied_probability_mid_and_tails() -> None:
    assert implied(q("A", "0.47", "0.49")) == (0.48, "mid")
    assert implied(q("A", None, "0.02")) == (0.01, "tail")  # deep tail, one-sided
    assert implied(q("A", "0.98", None)) == (0.99, "tail")
    assert implied(q("A", None, "0.40")) == (None, "none")  # one-sided mid-range: unknown


def test_exclusive_overround_and_normalization() -> None:
    st = exclusive_stats([q("A", "0.49", "0.51"), q("B", "0.29", "0.31"),
                          q("C", "0.24", "0.26")])
    assert st is not None
    assert st["overround"] == 0.05 and st["sum_yes_ask"] == "1.08"
    assert abs(sum(st["normalized"].values()) - 1) < 1e-3


def _ladder(probs: list[str], group: str = "", name: str = "Over") -> list[Quote]:
    out = []
    for i, p in enumerate(probs):
        k = str(200 + 5 * i) + ".5"
        mid = D(p)
        out.append(q(f"T-{k}", str(mid - D("0.01")), str(mid + D("0.01")), k,
                     title=f"{name} {k} points", group=group))
    return out


def test_ladder_distribution_fit_quantiles_and_off_curve_strikes() -> None:
    st = ladder_stats(_ladder(["0.90", "0.70", "0.50", "0.55", "0.10"]))
    assert st is not None
    assert st["monotonicity_violations"] == 1  # 215.5 priced above 210.5
    fitted = [p["fitted"] for p in st["points"]]
    assert all(a >= b for a, b in zip(fitted, fitted[1:], strict=False))  # non-increasing
    assert 215.5 < st["median"] < 220.5
    assert abs(sum(b["p"] for b in st["buckets"]) - 1) < 1e-3
    assert any(p["off_curve"] for p in st["points"])
    assert st["label"] == "Over X points"


def test_ladder_groups_split_by_team_or_player() -> None:
    quotes = _ladder(["0.8", "0.5", "0.2"], group='{"team":"DEN"}', name="Denver by over") + \
        _ladder(["0.7", "0.4", "0.1"], group='{"team":"BOS"}', name="Boston by over") + \
        [q("X", "0.4", "0.5")]  # not a ladder
    groups = ladder_groups(quotes)
    assert len(groups) == 2 and all(len(g) == 3 for g in groups.values())


def test_spread_ladders_merge_into_one_margin_distribution() -> None:
    bos = [q(f"S-BOS{k}", str(D(p) - D("0.01")), str(D(p) + D("0.01")), f"{k}.5",
             title=f"Boston wins by over {k}.5 points", group="BOS")
           for k, p in [(1, "0.45"), (5, "0.30"), (9, "0.15")]]
    den = [q(f"S-DEN{k}", str(D(p) - D("0.01")), str(D(p) + D("0.01")), f"{k}.5",
             title=f"Denver wins by over {k}.5 points", group="DEN")
           for k, p in [(1, "0.45"), (5, "0.30"), (9, "0.15")]]
    merged = merge_margin_ladders(ladder_groups(bos + den))
    assert len(merged) == 1
    st = ladder_stats(next(iter(merged.values())))
    assert st is not None and st["strikes"] == 6
    assert st["label"].startswith("Boston margin over X")
    assert abs(st["median"]) < 1.6  # symmetric prices -> margin centred near 0


def test_expected_value_uses_verified_fees_and_kelly() -> None:
    assert FEES is not None
    ev = expected_value(FEES, D("0.48"), 10, D("0.55"), D("50"), D("0.05"), depth=D("5"))
    # fee 0.07*10*0.48*0.52 = 0.17472 -> debit 4.97472 rounded up to 4.98
    assert ev["total_cost"] == "4.98" and ev["fee"] == "0.18"
    assert ev["expected_value"] == "0.5200" and ev["breakeven_probability"] == "0.4980"
    assert D(ev["kelly_fraction"]) > 0 and ev["suggested_contracts"] >= 1
    assert ev["depth_warning"] is True  # 10 wanted, 5 at the price
    bad = expected_value(FEES, D("0.60"), 10, D("0.55"), D("50"), D("0.05"))
    assert D(bad["expected_value"]) < 0 and bad["kelly_fraction"] == "0.0000"
    assert "suggested_contracts" not in bad


def test_fee_multiplier_scales_the_rate() -> None:
    assert FEES is not None
    half = scaled_schedule(FEES, D("0.5"))
    assert half.taker_rate == FEES.taker_rate / 2
    assert scaled_schedule(FEES, D("1")) is FEES


def test_combo_independence_and_warnings() -> None:
    bos = q("KXNBAGAME-26NOV18BOSDEN-BOS", "0.47", "0.49")
    den = q("KXNBAGAME-26NOV18BOSDEN-DEN", "0.51", "0.53")
    tot = q("KXNBATOTAL-26NOV18BOSDEN-220", "0.49", "0.51")
    lal = q("KXNBAGAME-26NOV18UTALAL-LAL", "0.59", "0.61")
    c = combo_stats([(bos, "yes", "KXNBAGAME-26NOV18BOSDEN", True),
                     (lal, "no", "KXNBAGAME-26NOV18UTALAL", True)])
    assert c["independent_probability"] == round(0.48 * 0.40, 6) and not c["warnings"]
    c = combo_stats([(bos, "yes", "KXNBAGAME-26NOV18BOSDEN", True),
                     (tot, "yes", "KXNBATOTAL-26NOV18BOSDEN", False)])
    assert any("Same game" in w for w in c["warnings"])
    c = combo_stats([(bos, "yes", "KXNBAGAME-26NOV18BOSDEN", True),
                     (den, "yes", "KXNBAGAME-26NOV18BOSDEN", True)])
    assert c["independent_probability"] == 0.0 and "can't both win" in c["warnings"][0]


# --- storage via the scanner ------------------------------------------------------------------


@pytest.fixture
def cset(settings: Settings) -> Settings:
    return Settings(_env_file=None, database_url=settings.database_url,
                    experiment_budget_dollars=D("50"))


@pytest.fixture
def factory(cset: Settings):  # type: ignore[no-untyped-def]
    engine = make_engine(cset.database_url)
    yield make_session_factory(engine)
    engine.dispose()


SERIES_LIST = {"series": [{"ticker": "KXTEST", "title": "Chicago points", "category": "Sports",
                           "fee_type": "quadratic", "fee_multiplier": 0.5}]}


def test_scan_writes_catalog_and_prunes_closed_events(factory, cset: Settings) -> None:  # type: ignore[no-untyped-def]
    r = run_scan(factory, cset, kalshi({"/events": EVENTS, "/series": SERIES_LIST, **BOOKS}),
                 FrozenClock(NOW), schedules=[SCHED])
    assert r.status == "success"
    with factory() as s:
        ev = s.get(CatalogEvent, "KXTEST-1")
        assert ev is not None and ev.market_count == 2 and ev.series_ticker == "KXTEST"
        m = s.get(CatalogMarket, "KXTEST-1-100")
        assert m is not None and m.yes_bid == D("0.38") and m.floor_strike == D("100")
        assert s.get(CatalogSeries, "KXTEST").fee_multiplier == D("0.5")
    later = {"events": [{"event_ticker": "KXOTHER-1", "series_ticker": "KXOTHER",
                         "title": "Other", "mutually_exclusive": True, "markets": []}],
             "cursor": ""}
    run_scan(factory, cset, kalshi({"/events": later}), FrozenClock(NOW + timedelta(hours=1)),
             schedules=[SCHED])
    with factory() as s:
        assert s.get(CatalogEvent, "KXTEST-1") is None  # no longer open
        assert s.get(CatalogMarket, "KXTEST-1-100") is None
        assert s.get(CatalogEvent, "KXOTHER-1") is not None


# --- API --------------------------------------------------------------------------------------


def _mk(ticker: str, title: str, bid: str, ask: str, strike: float | None = None,
        team: str | None = None, vol: str = "100") -> dict:
    out = {"ticker": ticker, "title": title, "yes_sub_title": title, "status": "active",
           "yes_bid_dollars": bid, "yes_ask_dollars": ask,
           "no_bid_dollars": str(1 - D(ask)), "no_ask_dollars": str(1 - D(bid)),
           "yes_bid_size_fp": "50.00", "yes_ask_size_fp": "80.00", "last_price_dollars": bid,
           "previous_price_dollars": "0.4000", "volume_24h_fp": vol, "volume_fp": vol,
           "open_interest_fp": "10", "close_time": "2026-11-21T02:30:00Z",
           "rules_primary": f"If {title}, Yes."}
    if strike is not None:
        out.update({"strike_type": "greater", "floor_strike": strike})
    if team:
        out["custom_strike"] = {"basketball_team": team}
    return out


PAGE = [
    {"event_ticker": "KXNBAGAME-26NOV18BOSDEN", "series_ticker": "KXNBAGAME",
     "category": "Sports", "title": "Boston vs Denver", "sub_title": "BOS vs DEN (Nov 18)",
     "mutually_exclusive": True, "product_metadata": {"competition": "Pro Basketball (M)"},
     "markets": [_mk("KXNBAGAME-26NOV18BOSDEN-BOS", "Boston", "0.47", "0.48", vol="5000"),
                 _mk("KXNBAGAME-26NOV18BOSDEN-DEN", "Denver", "0.52", "0.53", vol="4000")]},
    {"event_ticker": "KXNBATOTAL-26NOV18BOSDEN", "series_ticker": "KXNBATOTAL",
     "category": "Sports", "title": "Boston vs Denver: Total Points",
     "sub_title": "BOS vs DEN (Nov 18)", "mutually_exclusive": False,
     "markets": [_mk(f"KXNBATOTAL-26NOV18BOSDEN-{k}", f"Over {k - 0.5} points scored", b, a,
                     strike=k - 0.5) for k, b, a in
                 [(211, "0.80", "0.82"), (216, "0.60", "0.62"), (221, "0.40", "0.42"),
                  (226, "0.20", "0.22")]]},
    {"event_ticker": "KXCPI-26DEC", "series_ticker": "KXCPI", "category": "Economics",
     "title": "CPI in December", "mutually_exclusive": False,
     "markets": [_mk("KXCPI-26DEC-T0.3", "Above 0.3%", "0.30", "0.33", vol="10")]},
]


@pytest.fixture
def api(cset: Settings, tmp_path: Path):  # type: ignore[no-untyped-def]
    engine = make_engine(cset.database_url)
    factory = make_session_factory(engine)
    CatalogWriter(factory, NOW).write_page(PAGE)

    def handle(req: httpx.Request) -> httpx.Response:
        path = req.url.path.removeprefix("/trade-api/v2")
        if path == "/markets/KXNBAGAME-26NOV18BOSDEN-BOS":
            return httpx.Response(200, json={"market": {**PAGE[0]["markets"][0],
                                                         "rules_secondary": "Postponed: 48h"}})
        if path == "/markets/KXNBAGAME-26NOV18BOSDEN-BOS/orderbook":
            return httpx.Response(200, json={"orderbook_fp": {
                "yes_dollars": [["0.4600", "10.00"], ["0.4700", "50.00"]],
                "no_dollars": [["0.5200", "80.00"]]}})
        return httpx.Response(404)

    runner = JobRunner(cset, factory, FrozenClock(NOW), synchronous=True,
                       client_factory=lambda: KalshiPublicClient(
                           KALSHI_REST_BASES[KalshiEnv.PRODUCTION],
                           transport=httpx.MockTransport(handle), sleep=lambda _: None,
                           min_interval=0.0, max_retries=0),
                       worker_lock_path=tmp_path / "w.lock")
    app = create_app(cset, FrozenClock(NOW), jobs=runner)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c
    engine.dispose()


def test_api_browse_categories_series_events(api: TestClient) -> None:
    st = api.get("/api/catalog/status").json()
    assert (st["events"], st["markets"]) == (3, 7)
    cats = api.get("/api/catalog/categories").json()["items"]
    assert cats[0]["name"] == "Sports" and cats[0]["events"] == 2
    ser = api.get("/api/catalog/series", params={"category": "Sports"}).json()["items"]
    assert [x["ticker"] for x in ser] == ["KXNBAGAME", "KXNBATOTAL"]  # by 24h volume
    evs = api.get("/api/catalog/events", params={"q": "denver"}).json()
    assert evs["total"] == 2
    evs = api.get("/api/catalog/events", params={"series": "KXCPI"}).json()
    assert [e["event_ticker"] for e in evs["items"]] == ["KXCPI-26DEC"]
    assert api.get("/api/catalog/events", params={"sort": "bogus"}).status_code == 422


def test_api_event_detail_has_markets_and_statistics(api: TestClient) -> None:
    game = api.get("/api/catalog/events/KXNBAGAME-26NOV18BOSDEN").json()
    assert len(game["markets"]) == 2 and game["stats"]["exclusive"]["overround"] == 0.0
    bos = next(m for m in game["markets"] if m["ticker"].endswith("BOS"))
    assert bos["implied"] == 0.475 and bos["change_24h"] == "0.0700"
    tot = api.get("/api/catalog/events/KXNBATOTAL-26NOV18BOSDEN").json()
    lad = tot["stats"]["ladders"]
    assert len(lad) == 1 and 215.5 < lad[0]["median"] < 220.5
    assert api.get("/api/catalog/events/NOPE-1").status_code == 404


def test_api_expected_value_and_combo(api: TestClient) -> None:
    r = api.get("/api/catalog/markets/KXNBAGAME-26NOV18BOSDEN-BOS/ev",
                params={"prob": "0.55", "contracts": 10})
    assert r.status_code == 200, r.text
    ev = r.json()
    assert ev["price"] == "0.48" and ev["price_source"] == "snapshot ask"
    assert D(ev["expected_value"]) > 0
    assert api.get("/api/catalog/markets/KXNBAGAME-26NOV18BOSDEN-BOS/ev",
                   params={"prob": "1.5"}).status_code == 422
    c = api.get("/api/catalog/combo", params={
        "legs": "KXNBAGAME-26NOV18BOSDEN-BOS:yes,KXNBATOTAL-26NOV18BOSDEN-221:yes"}).json()
    assert c["independent_probability"] is not None
    assert any("Same game" in w for w in c["warnings"])
    assert api.get("/api/catalog/combo", params={"legs": "bad leg"}).status_code == 422


def test_api_fresh_book_from_public_api(api: TestClient) -> None:
    r = api.get("/api/catalog/markets/KXNBAGAME-26NOV18BOSDEN-BOS/book").json()
    assert r["market"]["rules_secondary"] == "Postponed: 48h"
    assert r["yes_bids"][0] == {"price": "0.4700", "quantity": "50.00"}  # best first
    assert api.get("/api/catalog/markets/MISSING-1/book").status_code == 502
