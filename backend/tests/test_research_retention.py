"""Brave storage terms: news is removed from stored investigations after the cache window."""

from __future__ import annotations

import json
from datetime import timedelta

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.catalog.store import CatalogWriter
from app.core.clock import FrozenClock
from app.core.config import Settings
from app.db.session import make_engine, make_session_factory
from app.investigate import service, synth
from app.main import create_app
from app.sportsdata.espn import EspnSource
from app.sportsdata.news import NewsSearch
from tests.test_games import NOW, PAGE, espn_handler
from tests.test_research_search import REB12, Brave, H, art
from tests.test_research_synth import SNIPPETS, base, fake, good


def test_strip_news_removes_sources_and_text_written_from_them() -> None:
    r = synth.apply(base(), SNIPPETS, fake(good()))
    assert any(s.id.startswith("N") for s in r.sources)
    out = service.strip_news(r)
    assert [s.id for s in out.sources] == ["K1", "E1", "E2"]
    every = out.summary.findings + out.details.supports + out.details.against
    assert every and all(i in {"K1", "E1", "E2"} for f in every for i in f.source_ids)
    assert all(f.source_ids for f in every)  # model text with no source is dropped too
    assert any("E2" in f.source_ids for f in out.summary.findings)  # roster fact kept
    assert out.summary.takeaway == service.NEWS_EXPIRED
    assert out.summary.stance == "insufficient"
    assert "news_expired" in out.processing.partial_reasons
    dumped = out.model_dump_json()
    assert "title N1" not in dumped and "rotowire" not in dumped and "ruled out" not in dumped
    assert out.price_assessment == r.price_assessment  # internal numbers untouched
    # no news -> nothing changes; stripping twice is a no-op
    assert service.strip_news(out) == out


def test_strip_news_keeps_the_college_lineup_finding() -> None:
    r = base()
    r.summary.findings.insert(
        0,
        r.summary.findings[2].model_copy(update={"text": synth.LINEUP_UNKNOWN, "source_ids": []}),
    )
    r.processing.model = "fake:1b"
    out = service.strip_news(r)
    assert out.summary.findings[0].text == synth.LINEUP_UNKNOWN


def test_api_strips_news_after_cache_window(settings: Settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    brave = Brave([art("Knicks vs Wolves preview: Towns over 11.5 rebounds",
                       "https://www.covers.com/p", "Towns averages 11.7.")])
    from app.api import investigate_routes

    monkeypatch.setattr(
        investigate_routes,
        "NewsSearch",
        lambda key, **kw: NewsSearch(key, transport=httpx.MockTransport(brave.handler), **kw),
    )
    s = Settings(_env_file=None, database_url=settings.database_url, llm_provider="openai",
                 brave_search_api_key="test-key", research_search_cache_hours=6)
    engine = make_engine(s.database_url)
    CatalogWriter(make_session_factory(engine), NOW).write_page(PAGE)

    def app_at(at):  # type: ignore[no-untyped-def]
        app = create_app(s, FrozenClock(at))
        app.state.espn = EspnSource(transport=httpx.MockTransport(espn_handler([])),
                                    min_interval=0.0, sleep=lambda _: None)
        return app

    def stored() -> str:
        with engine.connect() as conn:
            return conn.execute(text("SELECT result_json FROM investigations")).scalar_one()

    with TestClient(app_at(NOW), base_url="http://127.0.0.1") as c:
        r = c.post("/api/research/investigations", json={"ticker": REB12, "side": "yes"},
                   headers=H).json()
        inside = c.get(f"/api/research/investigations/{r['investigation_id']}").json()
    assert any(x["id"].startswith("N") for x in inside["sources"])  # inside the window: kept
    assert "covers.com" in stored()

    # Restarting after the window purges at startup, before any request.
    with TestClient(app_at(NOW + timedelta(hours=6, minutes=1)), base_url="http://127.0.0.1") as c:
        raw = stored()
        assert "covers.com" not in raw and "Towns over 11.5" not in raw
        assert '"access":"snippet"' not in raw and '"access":"headline"' not in raw
        got = c.get(f"/api/research/investigations/{r['investigation_id']}").json()
    engine.dispose()
    assert got["sources"] and all(x["access"] == "internal" for x in got["sources"])
    assert got["summary"]["takeaway"] == service.NEWS_EXPIRED
    assert brave.calls == 3  # purging never searches
    assert json.loads(raw)["investigation_id"] == r["investigation_id"]


def test_purge_runs_on_requests_too(settings: Settings) -> None:
    """A long-running backend purges when the research routes are used, not only at startup."""
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    r = synth.apply(base(), SNIPPETS, fake(good()))
    r.stale_at = NOW.isoformat()
    with factory() as sess:
        service.save(sess, "k", r)
        assert service.purge_expired_news(sess, NOW - timedelta(minutes=1)) == 0
        assert service.purge_expired_news(sess, NOW) == 1
        assert service.purge_expired_news(sess, NOW) == 0  # already clean
        assert service.load(sess, "i1").summary.takeaway == service.NEWS_EXPIRED  # type: ignore[union-attr]
    engine.dispose()
