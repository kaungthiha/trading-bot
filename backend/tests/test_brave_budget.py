"""One app-wide Brave budget: every caller (research, "Headlines here", AI-review headlines)
draws from the same daily/monthly caps. Mocked transports only: no real Brave request."""

from __future__ import annotations

import threading
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.clock import FrozenClock
from app.core.config import Settings
from app.db.session import make_engine
from app.investigate.ledger import BudgetExhausted, Ledger, record_hook
from app.main import create_app
from app.sportsdata import news as news_mod
from tests.test_games import NOW
from tests.test_research_search import Brave, art

H = {"X-KRT-Request": "research"}
_RealNews = news_mod.NewsSearch


def mocked(brave: Brave):  # type: ignore[no-untyped-def]
    return lambda key, **kw: _RealNews(key, transport=httpx.MockTransport(brave.handler), **kw)


def test_defaults_and_upper_bounds() -> None:
    s = Settings(_env_file=None)
    assert (s.research_brave_daily_request_cap, s.research_brave_monthly_request_cap) == (60, 800)
    assert s.research_max_searches_per_investigation == 5
    assert s.research_max_sources_per_investigation == 7
    # Lower is fine; above the defaults (beyond the ~$4 of a $5 credit) is refused.
    assert (
        Settings(
            _env_file=None, research_brave_monthly_request_cap=100
        ).research_brave_monthly_request_cap
        == 100
    )
    for field, value in (
        ("research_brave_monthly_request_cap", 801),
        ("research_brave_daily_request_cap", 61),
        ("research_max_searches_per_investigation", 6),
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{field: value})


def test_concurrent_requests_across_purposes_never_exceed_the_shared_cap(
    settings: Settings,
) -> None:
    engine = make_engine(settings.database_url)
    led = Ledger(engine, FrozenClock(NOW), daily_cap=20, monthly_cap=800)
    ok: list[str] = []
    refused: list[str] = []
    purposes = ("research", "news", "headlines")

    def worker(i: int) -> None:
        p = purposes[i % 3]
        try:
            led.reserve(p, f"q{i}")
            ok.append(p)
        except BudgetExhausted:
            refused.append(p)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(60)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    u = led.usage()
    engine.dispose()
    assert len(ok) == 20 and len(refused) == 40
    assert u["total_today"] == 20 and u["used_today"] == 20
    assert sum(v["today"] for v in u["by_purpose"].values()) == 20
    assert set(u["by_purpose"]) >= set(purposes)


def test_monthly_cap_counts_every_purpose(settings: Settings) -> None:
    engine = make_engine(settings.database_url)
    led = Ledger(engine, FrozenClock(NOW), daily_cap=60, monthly_cap=3)
    led.reserve("research", "a")
    led.reserve("news", "b")
    led.reserve("headlines", "c")
    with pytest.raises(BudgetExhausted) as e:
        led.reserve("research", "d")
    engine.dispose()
    assert e.value.scope == "This month's"


def _app(settings: Settings, **over: Any):  # type: ignore[no-untyped-def]
    s = Settings(
        _env_file=None, database_url=settings.database_url, brave_search_api_key="test-key", **over
    )
    return create_app(s, FrozenClock(NOW))


def test_headlines_here_is_post_only_capped_cached_and_reported(
    settings: Settings, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from app.api import games_routes

    brave = Brave([art("Towns returns", "https://www.espn.com/nba/story/a")])
    monkeypatch.setattr(games_routes, "NewsSearch", mocked(brave))
    with TestClient(
        _app(settings, research_brave_daily_request_cap=2), base_url="http://127.0.0.1"
    ) as c:
        assert c.get("/api/games/news", params={"q": "Towns NBA"}).status_code == 405  # no GET
        assert c.post("/api/games/news", json={"q": "Towns NBA"}).status_code == 403  # no header
        assert brave.calls == 0
        r = c.post("/api/games/news", json={"q": "Towns NBA"}, headers=H).json()
        assert r["items"] and r["cached"] is False and brave.calls == 1
        again = c.post("/api/games/news", json={"q": "towns nba"}, headers=H).json()
        assert again["cached"] is True and brave.calls == 1  # cache hits are free
        c.post("/api/games/news", json={"q": "Brunson NBA"}, headers=H)
        assert brave.calls == 2
        # Cap reached (2/day across the app): refused before anything is sent.
        over = c.post("/api/games/news", json={"q": "Bridges NBA"}, headers=H)
        assert (
            over.status_code == 429
            and "no headline search was sent" in over.json()["error"]["message"]
        )
        assert brave.calls == 2
        u = c.get("/api/research/usage").json()
    assert u["used_today"] == 2 and u["daily_cap"] == 2 and u["monthly_cap"] == 800
    assert u["by_purpose"]["news"] == {"today": 2, "month": 2}
    assert u["by_purpose"]["research"] == {"today": 0, "month": 0}


def test_headlines_here_does_not_retry_a_429(settings: Settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.api import games_routes

    brave = Brave([], status=429)
    monkeypatch.setattr(games_routes, "NewsSearch", mocked(brave))
    with TestClient(_app(settings), base_url="http://127.0.0.1") as c:
        r = c.post("/api/games/news", json={"q": "Towns NBA"}, headers=H)
        u = c.get("/api/research/usage").json()
    assert r.status_code == 502 and brave.calls == 1 and u["used_today"] == 1


def test_ai_review_headlines_share_the_cap_and_stop_when_it_is_reached(
    settings: Settings, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    brave = Brave([art("Towns returns", "https://www.espn.com/nba/story/a")])
    monkeypatch.setattr(news_mod, "NewsSearch", mocked(brave))
    app = _app(settings, research_brave_daily_request_cap=3)
    # Research already used 2 of the 3 requests today.
    led = Ledger(app.state.engine, app.state.clock, 3, 800)
    led.reserve("research", "a")
    led.reserve("research", "b")
    heads = news_mod.headlines(
        app.state.settings,
        ["Karl-Anthony Towns", "Jalen Brunson", "Mikal Bridges"],
        on_attempt=record_hook(app.state, "headlines"),
    )
    u = led.usage()
    assert brave.calls == 1  # one subject searched, then the shared cap stopped it
    assert {h["about"] for h in heads} == {"Karl-Anthony Towns"}
    assert u["total_today"] == 3 and u["by_purpose"]["headlines"]["today"] == 1
    # With the budget gone, a review still works: just no headlines, and nothing sent.
    assert (
        news_mod.headlines(
            app.state.settings, ["Jalen Brunson"], on_attempt=record_hook(app.state, "headlines")
        )
        == []
    )
    assert brave.calls == 1
    app.state.engine.dispose()


def test_ledger_stores_no_brave_response_or_query_text(settings: Settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from app.api import games_routes

    brave = Brave([art("SECRET-HEADLINE", "https://www.espn.com/nba/story/a", "SECRET-SNIPPET")])
    monkeypatch.setattr(games_routes, "NewsSearch", mocked(brave))
    app = _app(settings)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.post("/api/games/news", json={"q": "Unique Query Text"}, headers=H)
    with app.state.engine.connect() as conn:
        rows = [tuple(map(str, r)) for r in conn.execute(text("SELECT * FROM search_ledger")).all()]
    app.state.engine.dispose()
    flat = " ".join(" ".join(r) for r in rows)
    assert rows and "SECRET" not in flat and "Unique Query Text" not in flat
