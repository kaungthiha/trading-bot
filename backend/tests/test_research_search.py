"""Investigate this pick, Phase C: bounded Brave discovery. Every test uses a mocked transport:
no real Brave request is ever made."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.adapters.base import AdapterError
from app.catalog.store import CatalogWriter
from app.core.clock import FrozenClock
from app.core.config import Settings
from app.db.session import make_engine, make_session_factory
from app.investigate import registry, search
from app.investigate import schemas as S
from app.investigate.ledger import BudgetExhausted, Ledger
from app.main import create_app
from app.sportsdata.espn import EspnSource
from app.sportsdata.news import NewsSearch
from tests.test_games import KEY, NOW, PAGE, espn_handler

H = {"X-KRT-Request": "research"}
REB12 = f"KXNBAREB-{KEY}-NYKKTOWNS32-12"
TEAMS = [
    {"code": "NYK", "name": "New York Knicks"},
    {"code": "MIN", "name": "Minnesota Timberwolves"},
]


def hyp(**kw: Any) -> S.Hypothesis:
    base = dict(
        ticker=REB12,
        event_ticker=f"KXNBAREB-{KEY}",
        side="yes",
        sport="basketball",
        league="NBA",
        market_type="player_prop",
        threshold=11.5,
        subject="Karl-Anthony Towns",
        label="Karl-Anthony Towns: 12+ rebounds",
        statement="x",
        snapshot_at=None,
        rules_url=None,
    )
    return S.Hypothesis(**{**base, **kw})


def art(title: str, url: str, desc: str = "", age: str = "2026-11-19T10:00:00") -> dict[str, Any]:
    host = httpx.URL(url).host
    return {
        "title": title,
        "url": url,
        "description": desc,
        "age": "5 hours ago",
        "page_age": age,
        "meta_url": {"hostname": host},
    }


class Brave:
    """Mock Brave News endpoint: canned results, counts every request, optional status."""

    def __init__(self, results: list[dict[str, Any]], status: int = 200) -> None:
        self.results, self.status, self.calls = results, status, 0
        self.queries: list[str] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.queries.append(req.url.params.get("q", ""))
        assert req.headers["X-Subscription-Token"] == "test-key"
        if self.status != 200:
            return httpx.Response(self.status)
        return httpx.Response(200, json={"results": self.results})

    def factory(self):  # type: ignore[no-untyped-def]
        return lambda hook: NewsSearch(
            "test-key", transport=httpx.MockTransport(self.handler), max_retries=0, on_attempt=hook
        )


@pytest.fixture
def engine(settings: Settings):  # type: ignore[no-untyped-def]
    e = make_engine(settings.database_url)
    yield e
    e.dispose()


def ledger(engine, daily: int | None = 20, monthly: int | None = 200, now=NOW) -> Ledger:  # type: ignore[no-untyped-def]
    return Ledger(engine, FrozenClock(now), daily, monthly)


def gather(
    h: S.Hypothesis, brave: Brave, led: Ledger, cache: dict | None = None, **kw: Any
) -> search.Gathered:
    return search.gather(
        h,
        TEAMS,
        configured=kw.pop("configured", True),
        client_factory=brave.factory(),
        ledger=led,
        cache={} if cache is None else cache,
        cache_ttl=timedelta(hours=6),
        now=NOW,
        max_searches=kw.pop("max_searches", 3),
        max_sources=kw.pop("max_sources", 5),
    )


# --- ledger ---------------------------------------------------------------------------------


def test_caps_hold_under_concurrent_requests(engine) -> None:  # type: ignore[no-untyped-def]
    led = ledger(engine, daily=20)
    ok, refused = [], []

    def worker(i: int) -> None:
        try:
            led.reserve("research", f"q{i}")
            ok.append(i)
        except BudgetExhausted:
            refused.append(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ok) == 20 and len(refused) == 20
    assert led.usage("research") == {"used_today": 20, "used_month": 20}


def test_monthly_cap_and_day_rollover(engine) -> None:  # type: ignore[no-untyped-def]
    for d in range(3):
        led = ledger(engine, daily=2, monthly=5, now=NOW + timedelta(days=d))
        for _ in range(2):
            try:
                led.reserve("research", "q")
            except BudgetExhausted as e:
                assert e.scope == "This month's" and d == 2
    assert ledger(engine, now=NOW + timedelta(days=2)).usage()["used_month"] == 5
    # other purposes are recorded but never capped, and don't use up research budget
    ledger(engine, daily=0, monthly=0).reserve("headlines", "headlines", capped=False)
    with engine.connect() as c:
        raw = c.execute(text("SELECT query_hash FROM search_ledger")).scalars().all()
    assert all(len(q) == 64 for q in raw)  # hashes only, never the query text


# --- discovery ------------------------------------------------------------------------------


def test_queries_are_targeted_bounded_and_deduplicated() -> None:
    qs = search.plan_queries(hyp(), TEAMS, 3)
    assert qs == [
        "New York Knicks vs Minnesota Timberwolves preview",
        "Karl-Anthony Towns injury status",
        "Karl-Anthony Towns rebounds prop 11.5",
    ]
    assert (
        len(
            search.plan_queries(
                hyp(market_type="moneyline", threshold=None, ticker=f"KXNBAGAME-{KEY}-NYK"),
                TEAMS,
                2,
            )
        )
        == 2
    )
    assert search.plan_queries(hyp(), TEAMS, 0) == []


def test_cache_hits_cost_nothing_and_are_counted_as_hits(engine) -> None:  # type: ignore[no-untyped-def]
    brave = Brave(
        [art("Knicks vs Timberwolves preview: Towns 11.5 rebounds", "https://www.covers.com/a")]
    )
    led, cache = ledger(engine), {}
    g1 = gather(hyp(), brave, led, cache)
    assert g1.searches == 3 and brave.calls == 3 and g1.cache_hits == 0
    g2 = gather(hyp(), brave, led, cache)
    assert g2.searches == 0 and g2.cache_hits == 3 and brave.calls == 3  # no new network calls
    assert led.usage()["used_today"] == 3


def test_budget_exhausted_stops_before_sending(engine) -> None:  # type: ignore[no-untyped-def]
    brave = Brave([art("Knicks Towns rebounds", "https://espn.com/x")])
    g = gather(hyp(), brave, ledger(engine, daily=1))
    assert g.searches == 1 and brave.calls == 1
    assert any("Today's search budget (1) is used up" in e for e in g.errors)


def test_429_is_not_retried_and_downtime_is_explained(engine) -> None:  # type: ignore[no-untyped-def]
    brave = Brave([], status=429)
    g = gather(hyp(), brave, ledger(engine))
    assert brave.calls == 1 and g.searches == 1
    assert g.errors == ["Brave rate-limited the request (429); not retried."]
    down = Brave([], status=503)
    g2 = gather(hyp(), down, ledger(engine))
    assert down.calls == 3 and all("news search failed" in e for e in g2.errors)


def test_not_configured_and_no_results(engine) -> None:  # type: ignore[no-untyped-def]
    brave = Brave([])
    g = gather(hyp(), brave, ledger(engine), configured=False)
    assert brave.calls == 0 and not g.attempted and "isn't set up" in g.errors[0]
    g2 = gather(hyp(), brave, ledger(engine))
    assert g2.attempted and g2.errors == ["No relevant articles were found for this game."]


def test_relevance_past_matchups_lines_and_syndication(engine) -> None:  # type: ignore[no-untyped-def]
    brave = Brave(
        [
            art(
                "Towns rebounds prop: over 11.5 vs Wolves",
                "https://www.covers.com/nba/towns-prop",
                "Towns has cleared 11.5 boards in 6 of 10.",
            ),
            art(
                "Towns rebounds prop: over 11.5 vs Wolves", "https://covers.com/nba/towns-prop/amp/"
            ),  # same page
            art(
                "Karl-Anthony Towns rebound line set at 9.5",
                "https://pickswise.com/towns-95",
                "Towns over 9.5 rebounds tonight.",
            ),
            art(
                "Knicks beat Wolves as Towns grabs 15",
                "https://espn.com/old-recap",
                age="2026-10-30T10:00:00",
            ),
            art(
                "Karl-Anthony Towns questionable for Knicks vs Wolves",
                "https://www.rotowire.com/t",
                "Towns listed questionable.",
            ),
            art(
                "Karl-Anthony Towns questionable for Knicks vs Wolves",
                "https://syndicator.example/t",
                "Towns listed questionable.",
            ),
            art("Lakers rout Celtics", "https://espn.com/lakers"),  # off-topic: no Towns
        ]
    )
    g = gather(hyp(), brave, ledger(engine), max_searches=1)
    by = {s.url: s for s in g.sources}
    assert "https://espn.com/lakers" not in by and g.dropped["off_topic"] == 1
    assert g.dropped["duplicate_url"] == 1  # www/amp variants are one page
    assert by["https://www.covers.com/nba/towns-prop"].line_match == "exact"
    assert by["https://pickswise.com/towns-95"].line_match == "different_line"
    assert by["https://espn.com/old-recap"].line_match == "past_matchup"
    syn = by["https://syndicator.example/t"]
    assert syn.duplicate_of == by["https://www.rotowire.com/t"].id  # not independent confirmation
    assert (
        syn.publisher == "syndicator.example"
        and by["https://www.rotowire.com/t"].publisher == "RotoWire"
    )
    assert g.sources[0].line_match == "exact"  # exact-line sources rank first
    assert all(s.access in ("snippet", "headline") for s in g.sources)  # never full text
    assert set(g.snippets) <= {s.id for s in g.sources}


def test_source_limit_is_enforced(engine) -> None:  # type: ignore[no-untyped-def]
    brave = Brave([art(f"Towns note {i}", f"https://espn.com/n{i}") for i in range(10)])
    g = gather(hyp(), brave, ledger(engine), max_searches=1, max_sources=5)
    assert len(g.sources) == 5 and [s.id for s in g.sources] == ["N1", "N2", "N3", "N4", "N5"]


def test_registry_permits_no_full_text_and_knows_subdomains() -> None:
    assert registry.full_text_allowed() == []
    assert registry.lookup("www.covers.com")[1].name == "Covers"
    assert registry.lookup("m.espn.com")[1].name == "ESPN"
    dom, pub = registry.lookup("news.unknown-site.io")
    assert dom == "unknown-site.io" and pub is registry.UNKNOWN and pub.priority == 4
    for d, p in registry.REGISTRY.items():
        assert p.full_text == "not_permitted" and p.discovery == "brave_news_metadata", d


# --- through the API ------------------------------------------------------------------------


def test_api_searches_only_on_run_and_never_stores_snippets(
    settings: Settings, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    brave = Brave(
        [
            art(
                "Knicks vs Wolves preview: Towns over 11.5 rebounds",
                "https://www.covers.com/p",
                "SECRET-SNIPPET-TEXT Towns averages 11.7.",
            )
        ]
    )
    from app.api import investigate_routes

    monkeypatch.setattr(
        investigate_routes,
        "NewsSearch",
        lambda key, **kw: NewsSearch(key, transport=httpx.MockTransport(brave.handler), **kw),
    )
    s = Settings(
        _env_file=None,
        database_url=settings.database_url,
        llm_provider="openai",
        brave_search_api_key="test-key",
    )
    engine = make_engine(s.database_url)
    CatalogWriter(make_session_factory(engine), NOW).write_page(PAGE)
    app = create_app(s, FrozenClock(NOW))
    app.state.espn = EspnSource(
        transport=httpx.MockTransport(espn_handler([])), min_interval=0.0, sleep=lambda _: None
    )
    with TestClient(app, base_url="http://127.0.0.1") as c:
        pre = c.get("/api/research/preflight", params={"ticker": REB12, "side": "yes"}).json()
        assert brave.calls == 0 and pre["usage"]["configured"] is True
        r = c.post(
            "/api/research/investigations", json={"ticker": REB12, "side": "yes"}, headers=H
        ).json()
        assert brave.calls == 3 and r["processing"]["searches"] == 3
        news = [x for x in r["sources"] if x["id"].startswith("N")]
        assert news and news[0]["line_match"] == "exact" and news[0]["access"] == "snippet"
        assert "were found but aren't summarised" in r["summary"]["takeaway"]
        # reading it again, previewing, or checking usage never searches
        c.get(f"/api/research/investigations/{r['investigation_id']}")
        c.post("/api/research/investigations", json={"ticker": REB12, "side": "yes"}, headers=H)
        c.get("/api/research/preflight", params={"ticker": REB12, "side": "yes"})
        u = c.get("/api/research/usage").json()
        assert brave.calls == 3 and u["used_today"] == 3
        # refresh re-runs, but the in-memory search cache answers: still no new calls
        again = c.post(
            f"/api/research/investigations/{r['investigation_id']}/refresh", headers=H
        ).json()
        assert brave.calls == 3 and again["processing"]["cache"] == "hit"
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT result_json FROM investigations")).scalars().all()
    engine.dispose()
    assert stored and all("SECRET-SNIPPET-TEXT" not in j for j in stored)
    assert all(json.loads(j)["sources"] for j in stored)


def test_brave_client_meters_every_attempt_including_retries() -> None:
    hits: list[int] = []
    calls = {"n": 0}

    def flaky(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    client = NewsSearch(
        "test-key",
        transport=httpx.MockTransport(flaky),
        max_retries=1,
        on_attempt=lambda: hits.append(1),
    )
    client._http._sleep = lambda _: None  # no real backoff wait in tests
    with pytest.raises(AdapterError):
        client.search("x")
    assert calls["n"] == 2 and len(hits) == 2  # the retry was billed and counted too


def test_game_date_parses_event_tickers() -> None:
    assert search.game_date(f"KXNBAREB-{KEY}") == datetime(2026, 11, 19, tzinfo=UTC)
    assert search.game_date("KXNBAMVP-27") is None
