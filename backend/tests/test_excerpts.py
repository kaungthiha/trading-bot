"""User-provided excerpts (Phase 4, stream 3): pasted locally, never fetched, always marked
user-provided and unverified until corroborated, kept across refresh and the news purge,
removable to the exact pre-excerpt state. No real network: any real HTTP attempt fails."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.investigate import excerpts, service, sources
from app.investigate import schemas as S
from tests.test_nhl import NOW, TOTAL, WIN, H, MPServer, _app, _hockey_result
from tests.test_research_synth import fake

TEXT = (
    "Bruins coach says Jeremy Swayman will start in goal on Thursday after a full practice; "
    "the hockey club expects a tight game against the Rangers."
)


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """A link the user gives must never be fetched: any real HTTP request fails the test."""

    def refuse(self: Any, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected network request: {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


def _run(c: TestClient, ticker: str = WIN) -> dict[str, Any]:
    body = {"ticker": ticker, "side": "yes"}
    r = c.post("/api/research/investigations", json=body, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def _add(c: TestClient, inv: str, **body: Any) -> httpx.Response:
    payload = {
        "text": TEXT,
        "source": "The Athletic",
        "url": "https://www.nytimes.com/athletic/x",
        "published_on": "2026-11-19",
    } | body
    return c.post(f"/api/research/investigations/{inv}/excerpts", json=payload, headers=H)


def test_add_view_and_remove_excerpt(settings: Settings) -> None:
    server = MPServer()
    with TestClient(_app(settings, server), base_url="http://127.0.0.1") as c:
        base = _run(c)
        inv = base["investigation_id"]
        calls = len(server.paths)
        r = _add(c, inv)
        assert r.status_code == 200, r.text
        out = r.json()
        stored = c.get(f"/api/research/investigations/{inv}").json()
        gone = c.post(f"/api/research/investigations/{inv}/excerpts/U1/remove", headers=H).json()
    assert len(server.paths) == calls  # no data re-download, no search
    u = next(s for s in out["sources"] if s["id"] == "U1")
    assert u["access"] == "user_provided" and u["excerpt"] == TEXT
    assert u["url"] == "https://www.nytimes.com/athletic/x" and u["publisher"] == "The Athletic"
    assert u["published_at"] == "2026-11-19"
    f = next(x for x in out["details"]["against"] if x["source_ids"] == ["U1"])
    assert f["verified"] is False
    assert "user-provided and unverified until another source agrees" in f["text"]
    assert TEXT[:30] not in f["text"]  # the app never quotes the paste back as a finding
    assert "1 excerpt you pasted" in out["summary"]["coverage"]
    assert out["summary"]["coverage"].startswith("1 factual dataset · 0 commentary links")
    assert stored["sources"][-1]["id"] == "U1"  # saved on the same investigation
    # Removing the only excerpt restores the original exactly.
    assert gone["excerpt_base"] is None
    for k in ("summary", "details", "sources"):
        assert gone[k] == base[k], k


def test_checks_flag_wrong_sport_line_and_date(settings: Settings) -> None:
    with TestClient(_app(settings, MPServer()), base_url="http://127.0.0.1") as c:
        inv = _run(c)["investigation_id"]
        a = _add(
            c, inv, text="Rangers rally past the Astros in extra innings at the ballpark.", url=None
        ).json()
        inv2 = _run(c, TOTAL)["investigation_id"]
        b = _add(
            c,
            inv2,
            text="Bruins and Rangers hockey total set at 6.5 goals tonight.",
            published_on="2026-11-25",
        ).json()
    fa = next(x for x in a["details"]["against"] if x["source_ids"] == ["U1"])["text"]
    assert "it doesn't read like hockey coverage" in fa
    assert next(s for s in a["sources"] if s["id"] == "U1")["url"] == ""
    fb = next(x for x in b["details"]["against"] if x["source_ids"] == ["U1"])["text"]
    assert "different line" in fb and "dated after this game" in fb
    assert "1 excerpt you pasted" in b["summary"]["coverage"]


def test_validation_csrf_limits_and_switch(settings: Settings) -> None:
    with TestClient(_app(settings, MPServer()), base_url="http://127.0.0.1") as c:
        inv = _run(c)["investigation_id"]
        url = f"/api/research/investigations/{inv}/excerpts"
        body = {"text": TEXT, "source": "x"}
        assert c.post(url, json=body).status_code == 403  # no CSRF header
        assert _add(c, inv, text="too short").status_code == 422
        assert _add(c, inv, url="javascript:alert(1)").status_code == 422
        assert _add(c, inv, source="   ").status_code == 422
        assert _add(c, inv, text="x" * 4001).status_code == 422
        for _ in range(excerpts.MAX_EXCERPTS):
            assert _add(c, inv).status_code == 200
        sixth = _add(c, inv)
        assert sixth.status_code == 422 and "At most 5" in sixth.json()["error"]["message"]
        assert c.post(f"{url}/U9/remove", headers=H).status_code == 404
        assert c.post(f"{url}/N1/remove", headers=H).status_code == 422  # only U ids
        assert _add(c, "no-such-id").status_code == 404
    with TestClient(
        _app(settings, MPServer(), research_disabled_sources="user_excerpt"),
        base_url="http://127.0.0.1",
    ) as c:
        inv = _run(c)["investigation_id"]
        off = _add(c, inv)
        assert off.status_code == 403 and "switched off" in off.json()["error"]["message"]


def test_excerpts_survive_refresh(settings: Settings) -> None:
    with TestClient(_app(settings, MPServer()), base_url="http://127.0.0.1") as c:
        inv = _run(c)["investigation_id"]
        _add(c, inv)
        new = c.post(f"/api/research/investigations/{inv}/refresh", headers=H).json()
        again = c.get(f"/api/research/investigations/{new['investigation_id']}").json()
    assert new["investigation_id"] != inv
    for r in (new, again):
        u = [s for s in r["sources"] if s["access"] == "user_provided"]
        assert [s["id"] for s in u] == ["U1"] and u[0]["excerpt"] == TEXT
        assert "1 excerpt you pasted" in r["summary"]["coverage"]


def _inp(text: str = TEXT) -> excerpts.ExcerptIn:
    return excerpts.ExcerptIn(text=text, source="The Athletic", published_on=date(2026, 11, 19))


def test_news_purge_keeps_excerpts_and_drops_news_text_from_the_snapshot() -> None:
    r = _hockey_result()  # has a news source N1
    r.stale_at = (NOW - timedelta(hours=1)).isoformat()
    reply = {
        "claims": [
            {
                "source_id": "N1",
                "text": "A headline reports Swayman will start.",
                "kind": "factual",
                "stance": "neutral",
            }
        ],
        "takeaway": "A headline reports Swayman will start; the excerpt agrees.",
        "findings": [],
        "gaps": [],
        "stance": "insufficient",
    }
    with_ex = excerpts.add(r, _inp(), NOW, fake(reply))
    assert any(c.text.startswith("A headline reports") for c in with_ex.details.against)
    out = service.strip_news(with_ex)
    ids = [s.id for s in out.sources]
    assert "N1" not in ids and "U1" in ids
    assert any(f.source_ids == ["U1"] for f in out.details.against)  # excerpt note kept
    text = out.model_dump_json()
    assert "A headline reports" not in text  # nothing written from news survives, anywhere
    assert out.excerpt_base is not None
    assert not any("N1" in f.source_ids for f in out.excerpt_base.details.against)
    assert out.summary.takeaway == service.NEWS_EXPIRED
    # Excerpts alone never trigger the purge (they aren't news).
    only = excerpts.add(
        _hockey_result().model_copy(update={"sources": _hockey_result().sources[:2]}), _inp(), NOW
    )
    assert service.strip_news(only) == only


def test_model_claims_resting_only_on_an_excerpt_stay_unverified() -> None:
    seen: list[Any] = []
    reply = {
        "claims": [
            {
                "source_id": "U1",
                "text": "An excerpt you added says Swayman will start.",
                "kind": "factual",
                "stance": "supports",
            },
        ],
        "takeaway": "An excerpt you added says Swayman will start. Check before the game.",
        "findings": [
            {
                "text": "An excerpt you added says Swayman will start.",
                "kind": "factual",
                "stance": "supports",
                "source_ids": ["U1"],
            },
            {
                "text": "Boston's expected-goals share is 54%, and an excerpt agrees.",
                "kind": "statistical",
                "stance": "supports",
                "source_ids": ["U1", "M1"],
            },
        ],
        "gaps": [],
        "stance": "insufficient",
    }
    long = TEXT + " " + ("More context about the matchup. " * 40)
    out = excerpts.add(_hockey_result(), _inp(long[:4000]), NOW, fake(reply, seen))
    facts = seen[0][1]
    u = next(s for s in facts["sources"] if s["id"] == "U1")
    assert u["publisher_kind"] == "user_excerpt_unverified"
    assert 400 < len(u["snippet"]) <= 1500  # more of the paste than a news snippet
    assert "U1, U2... are excerpts the user pasted" in seen[0][0]
    only_u = next(f for f in out.details.supports if f.source_ids == ["U1"])
    assert only_u.verified is False
    both = next(f for f in out.summary.findings if f.source_ids == ["U1", "M1"])
    assert both.verified is True  # corroborated by app data
    assert "user_excerpts" in out.processing.partial_reasons
    assert any("Re-summarised locally" in m for m in out.details.methodology)
    # A second excerpt rebuilds from the snapshot: the model's claims don't pile up.
    twice = excerpts.add(out, _inp(), NOW, fake(reply))
    n = sum(1 for f in twice.details.supports if f.text.startswith("An excerpt you added says"))
    assert n == 1
    # Removing both restores the original exactly.
    back = excerpts.remove(excerpts.remove(twice, "U2"), "U1")
    orig = _hockey_result()
    assert back.summary == orig.summary and back.details == orig.details
    assert back.processing.model is None and back.excerpt_base is None


def test_failed_model_keeps_the_apps_summary() -> None:
    from app.sportsdata.llm import LlmError

    def broken(*_: Any) -> Any:
        raise LlmError("down")

    out = excerpts.add(_hockey_result(), _inp(), NOW, broken)
    assert not any("Re-summarised" in m for m in out.details.methodology)
    assert "user_excerpts" not in out.processing.partial_reasons
    assert any("Local model unavailable" in e for e in out.processing.errors)
    assert any(f.source_ids == ["U1"] for f in out.details.against)


def test_registry_entry_and_schema() -> None:
    s = sources.SOURCES["user_excerpt"]
    assert s.rights_status == "manual_user_input" and "never fetched" in s.notes
    assert not sources.allows("user_excerpt", "crawl_publisher")
    assert S.Source.model_fields["excerpt"].metadata  # length-capped
    with pytest.raises(ValueError):
        excerpts.ExcerptIn(text=TEXT, source="x", url="ftp://example.com/a")
    assert excerpts.ExcerptIn(text=TEXT, source="x", url="  ").url is None
    assert datetime.now(UTC)  # (keeps the UTC import meaningful for readers)
