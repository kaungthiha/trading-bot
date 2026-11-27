"""Investigate this pick, Phase B: deterministic result from the existing quote, box-score
evidence and slip-check maths. No search and no model calls exist yet."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.catalog.store import CatalogWriter
from app.core.clock import FrozenClock
from app.core.config import Settings
from app.db.session import make_engine, make_session_factory
from app.investigate import service
from app.main import create_app
from app.sportsdata.espn import EspnSource
from tests.test_games import KEY, NOW, PAGE, espn_handler

H = {"X-KRT-Request": "research"}
WIN = f"KXNBAGAME-{KEY}-NYK"
REB12 = f"KXNBAREB-{KEY}-NYKKTOWNS32-12"
SPREAD = f"KXNBASPREAD-{KEY}-NYK3"


@pytest.fixture
def iset(settings: Settings) -> Settings:
    return Settings(_env_file=None, database_url=settings.database_url, llm_provider="openai")


def _client(iset: Settings, now=NOW):  # type: ignore[no-untyped-def]
    engine = make_engine(iset.database_url)
    CatalogWriter(make_session_factory(engine), NOW).write_page(PAGE)
    app = create_app(iset, FrozenClock(now))
    seen: list[str] = []
    app.state.espn = EspnSource(
        transport=httpx.MockTransport(espn_handler(seen)), min_interval=0.0, sleep=lambda _: None
    )
    app.state.espn_seen = seen
    return app, engine


@pytest.fixture
def api(iset: Settings):  # type: ignore[no-untyped-def]
    app, engine = _client(iset)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c
    engine.dispose()


def run(c: TestClient, ticker: str, side: str = "yes", label: str | None = None) -> dict:
    r = c.post(
        "/api/research/investigations",
        json={"ticker": ticker, "side": side, "label": label},
        headers=H,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_post_needs_the_csrf_header_and_a_supported_market(api: TestClient) -> None:
    body = {"ticker": WIN, "side": "yes"}
    assert api.post("/api/research/investigations", json=body).status_code == 403
    r = api.post(
        "/api/research/investigations", json={"ticker": "KXCPI-26DEC-T3", "side": "yes"}, headers=H
    )
    assert r.status_code == 404  # not in the catalog
    bad = api.post(
        "/api/research/investigations", json={"ticker": "../x", "side": "yes"}, headers=H
    )
    assert bad.status_code == 422


def test_player_prop_uses_box_scores_and_the_slip_check_maths(api: TestClient) -> None:
    r = run(api, REB12, label="Karl-Anthony Towns: 12+ rebounds")
    h = r["hypothesis"]
    assert h["market_type"] == "player_prop" and h["threshold"] == 11.5
    assert (
        h["subject"] == "Karl-Anthony Towns"
        and h["statement"] == "Karl-Anthony Towns: 12+ rebounds"
    )
    q = r["quote"]
    assert (
        q["ask"] == 0.66 and q["fresh"] is True and q["observed_at"].startswith("2026-11-19T15:00")
    )
    p = r["price_assessment"]
    assert p["model_name"].startswith("Box-score history (frequency")
    assert p["break_even"] > 0.66  # ask + taker fee
    assert p["fee_per_contract"] > 0
    assert any("not a calibrated probability" in a for a in p["abstain_reasons"])
    s = r["summary"]
    assert len(s["findings"]) <= 3 and s["takeaway"].endswith(
        "No news or analyst views were checked yet."
    )
    assert {src["id"] for src in r["sources"]} >= {"K1", "E1"}
    # every cited id exists
    ids = {src["id"] for src in r["sources"]}
    assert all(set(f["source_ids"]) <= ids for f in s["findings"])
    proc = r["processing"]
    assert proc["searches"] == 0 and proc["cache"] == "none" and proc["model"] is None
    assert proc["errors"] == [
        "Brave Search isn't set up, so no news was checked (set KRT_BRAVE_SEARCH_API_KEY)."
    ]


def test_yes_and_no_and_market_types_are_distinct(api: TestClient) -> None:
    yes, no = run(api, WIN), run(api, WIN, "no")
    assert (
        yes["hypothesis"]["market_type"] == "moneyline" and yes["hypothesis"]["threshold"] is None
    )
    assert no["hypothesis"]["statement"].startswith("NOT: ")
    assert yes["quote"]["ask"] == 0.51 and no["quote"]["ask"] == 0.5  # NO ask = 1 - YES bid
    sp = run(api, SPREAD)
    assert sp["hypothesis"]["market_type"] == "spread"
    assert yes["investigation_id"] != no["investigation_id"]


def test_cached_result_is_reused_refresh_recomputes_and_get_reads_the_same(api: TestClient) -> None:
    first = run(api, REB12)
    second = run(api, REB12)
    assert second["investigation_id"] == first["investigation_id"]
    assert second["processing"]["cache"] == "hit"
    pre = api.get("/api/research/preflight", params={"ticker": REB12, "side": "yes"}).json()
    assert pre["cached"] is True and pre["unsupported"] is None and pre["quote"]["ask"] == 0.66
    got = api.get(f"/api/research/investigations/{first['investigation_id']}").json()
    assert got["summary"] == first["summary"]
    assert (
        api.post(f"/api/research/investigations/{first['investigation_id']}/refresh").status_code
        == 403
    )
    fresh = api.post(
        f"/api/research/investigations/{first['investigation_id']}/refresh", headers=H
    ).json()
    assert fresh["investigation_id"] != first["investigation_id"]
    assert api.get("/api/research/investigations/nope").status_code == 404


def test_stale_quote_is_never_used_for_an_edge(iset: Settings) -> None:
    app, engine = _client(iset, now=NOW + timedelta(hours=2))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        r = run(c, REB12)
    engine.dispose()
    assert r["quote"]["fresh"] is False
    p = r["price_assessment"]
    assert p["conservative_edge"] is None and p["walk_away"] is None
    assert any("stale" in a for a in p["abstain_reasons"])
    assert r["summary"]["gaps"][0].startswith("The price is stale")


def test_usage_reports_app_caps_without_claiming_a_brave_balance(api: TestClient) -> None:
    u = api.get("/api/research/usage").json()
    assert u == {
        "configured": False,
        "used_today": 0,
        "daily_cap": 100,
        "used_month": 0,
        "monthly_cap": 2000,
        "by_purpose": {p: {"today": 0, "month": 0}
                       for p in ("research", "news", "headlines", "slate", "review")},
        "max_searches_per_investigation": 5,
    }
    assert not any("balance" in k or "dollar" in k or "remaining" in k for k in u)


def test_supported_checks() -> None:
    # NHL game markets are supported (see test_nhl.py); period markets still aren't.
    service.check_supported("KXNHLGAME-26NOV19BOSNYR-BOS", "KXNHLGAME-26NOV19BOSNYR", "KXNHLGAME")
    with pytest.raises(service.Unsupported):
        service.check_supported(
            "KXNHL1P-26NOV19BOSNYR-BOS", "KXNHL1P-26NOV19BOSNYR", "KXNHL1P"
        )
    with pytest.raises(service.Unsupported):
        service.check_supported("KXNBAMVP-27-SGA", "KXNBAMVP-27", "KXNBAMVP")
    service.check_supported(WIN, f"KXNBAGAME-{KEY}", "KXNBAGAME")


def test_no_execution_or_paper_tables_are_touched(api: TestClient) -> None:
    run(api, WIN)
    j = api.get("/api/execution/intents").json()
    assert j == []


def test_players_out_tonight_withhold_the_edge_and_lead_the_findings(iset: Settings) -> None:
    """History assumes a normal lineup. With New York starters out, a NYK-wins investigation
    must not show an edge, and the roster finding must come first, against the pick."""
    engine = make_engine(iset.database_url)
    CatalogWriter(make_session_factory(engine), NOW).write_page(PAGE)
    app = create_app(iset, FrozenClock(NOW))
    base = espn_handler([])

    def handle(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/nba/injuries"):
            return httpx.Response(
                200,
                json={
                    "injuries": [
                        {
                            "id": "18",
                            "displayName": "New York Knicks",
                            "injuries": [
                                {
                                    "status": "Out",
                                    "shortComment": "Out (knee)",
                                    "date": "2026-11-19",
                                    "athlete": {"displayName": "Jalen Brunson"},
                                },
                                {
                                    "status": "Out",
                                    "shortComment": "Out (ankle)",
                                    "date": "2026-11-19",
                                    "athlete": {"displayName": "Mikal Bridges"},
                                },
                            ],
                        }
                    ]
                },
            )
        return base(req)

    app.state.espn = EspnSource(
        transport=httpx.MockTransport(handle), min_interval=0.0, sleep=lambda _: None
    )
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yes, no = run(c, WIN), run(c, WIN, "no")
    engine.dispose()
    p = yes["price_assessment"]
    assert p["conservative_edge"] is None and p["walk_away"] is None
    assert any("lineup isn't normal" in a for a in p["abstain_reasons"])
    first = yes["summary"]["findings"][0]
    assert first["text"].startswith("New York Knicks: 2 out (Jalen Brunson, Mikal Bridges)")
    assert first["stance"] == "opposes" and first["source_ids"] == ["E2"]
    assert no["summary"]["findings"][0]["stance"] == "supports"  # same fact, other side
    assert "lineup isn't normal" in yes["summary"]["takeaway"]
    assert len(yes["summary"]["takeaway"].split(". ")) <= 2


def test_cache_key_carries_the_policy_version_and_no_reads_cleanly(api: TestClient) -> None:
    from types import SimpleNamespace

    key = service.cache_key(WIN, "yes", SimpleNamespace(refreshed_at=NOW))  # type: ignore[arg-type]
    from app.investigate import registry

    # a rules or source-policy change invalidates old results
    assert key.endswith(f"{service.POLICY_VERSION}|{registry.REGISTRY_VERSION}|none")
    assert service.cache_key(WIN, "yes", SimpleNamespace(refreshed_at=NOW), "gemma4:12b") != key  # type: ignore[arg-type]
    no = run(api, WIN, "no", label="New York wins")
    assert "a NO on “New York wins”" in no["summary"]["takeaway"]
    assert "not happening happens" not in no["summary"]["takeaway"]
