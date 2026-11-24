"""NHL investigations: exact market mapping, status-safe goalie reads, MoneyPuck season context,
no invented probability. Mocked transports only (no MoneyPuck, ESPN or Brave network calls)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.catalog.store import CatalogWriter
from app.core.clock import FrozenClock
from app.core.config import Settings
from app.db.session import make_engine, make_session_factory
from app.investigate import nhl, search, sources, synth
from app.investigate import schemas as S
from app.main import create_app
from app.sportsdata import moneypuck as mp
from app.sportsdata.espn import EspnSource
from app.sportsdata.news import NewsSearch
from tests.test_research_search import Brave, art
from tests.test_research_synth import fake

NOW = datetime(2026, 11, 19, 15, 0, tzinfo=UTC)
KEY = "26NOV19BOSNYR"
H = {"X-KRT-Request": "research"}
WIN = f"KXNHLGAME-{KEY}-BOS"
TOTAL = f"KXNHLTOTAL-{KEY}-6"
SPREAD = f"KXNHLSPREAD-{KEY}-BOS2"

TEAMS_CSV = """team,season,name,position,situation,games_played,xGoalsPercentage,\
xGoalsFor,xGoalsAgainst,goalsFor,goalsAgainst
BOS,2026,BOS,Team Level,all,20,0.53,60.0,52.0,66.0,50.0
BOS,2026,BOS,Team Level,5on5,20,0.54,40.0,34.0,44.0,33.0
NYR,2026,NYR,Team Level,all,21,0.47,51.0,58.0,55.0,63.0
NYR,2026,NYR,Team Level,5on5,21,0.47,33.0,37.0,36.0,41.0
"""
GOALIES_CSV = """playerId,season,name,team,position,situation,games_played,xGoals,goals,ongoal
1,2026,Jeremy Swayman,BOS,G,all,15,40.0,35.0,420.0
2,2026,Joonas Korpisalo,BOS,G,all,5,14.0,15.0,140.0
3,2026,Igor Shesterkin,NYR,G,all,16,45.0,41.0,460.0
4,2026,Jonathan Quick,NYR,G,all,5,13.0,16.0,130.0
3,2026,Igor Shesterkin,NYR,G,5on5,16,30.0,28.0,300.0
"""


class MPServer:
    """moneypuck.com season files, and the game-log zips on its download host (404 unless a
    test passes logs={"goalies": bytes, "skaters": bytes})."""

    def __init__(
        self,
        last_modified: str = "Thu, 19 Nov 2026 11:40:00 GMT",
        logs: dict[str, bytes] | None = None,
    ) -> None:
        self.paths: list[str] = []
        self.log_paths: list[str] = []
        self.lm = last_modified
        self.logs = logs or {}

    def handler(self, req: httpx.Request) -> httpx.Response:
        if req.url.host == "peter-tanner.com":
            self.log_paths.append(req.url.path)
            kind = req.url.path.split("/")[-2]
            if kind in self.logs and req.url.path.endswith("/2026.zip"):
                return httpx.Response(
                    200, content=self.logs[kind], headers={"last-modified": self.lm}
                )
            return httpx.Response(404)
        self.paths.append(req.url.path)
        assert req.url.host == "moneypuck.com"
        if req.url.path.endswith("/2026/regular/teams.csv"):
            return httpx.Response(200, text=TEAMS_CSV, headers={"last-modified": self.lm})
        if req.url.path.endswith("/2026/regular/goalies.csv"):
            return httpx.Response(200, text=GOALIES_CSV, headers={"last-modified": self.lm})
        return httpx.Response(404)


def _mk(
    ticker: str, title: str, bid: str, ask: str, strike: float | None = None, sub: str | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ticker": ticker,
        "title": title,
        "yes_sub_title": sub or title,
        "status": "active",
        "yes_bid_dollars": bid,
        "yes_ask_dollars": ask,
        "no_bid_dollars": str(1 - D(ask)),
        "no_ask_dollars": str(1 - D(bid)),
        "yes_bid_size_fp": "50",
        "yes_ask_size_fp": "80",
        "volume_24h_fp": "100",
        "volume_fp": "100",
        "open_interest_fp": "10",
        "close_time": "2026-11-22T01:00:00Z",
        "occurrence_datetime": "2026-11-20T00:00:00Z",
    }
    if strike is not None:
        out.update({"strike_type": "greater", "floor_strike": strike})
    return out


def _ev(series: str, title: str, markets: list[dict[str, Any]], me: bool = False) -> dict[str, Any]:
    return {
        "event_ticker": f"{series}-{KEY}",
        "series_ticker": series,
        "category": "Sports",
        "title": title,
        "sub_title": "BOS vs NYR (Nov 19)",
        "mutually_exclusive": me,
        "markets": markets,
    }


PAGE = [
    _ev(
        "KXNHLGAME",
        "Boston vs New York R",
        [
            _mk(WIN, "Boston wins", "0.56", "0.58", sub="Boston"),
            _mk(f"KXNHLGAME-{KEY}-NYR", "New York R wins", "0.42", "0.44", sub="New York R"),
        ],
        me=True,
    ),
    _ev(
        "KXNHLSPREAD",
        "Boston vs New York R: Spread",
        [
            _mk(
                SPREAD,
                "Boston wins by over 1.5 goals",
                "0.30",
                "0.32",
                strike=1.5,
                sub="Boston wins by over 1.5 goals",
            )
        ],
    ),
    _ev(
        "KXNHLTOTAL",
        "Boston vs New York R: Total Goals",
        [
            _mk(
                TOTAL,
                "Full Game: Over 5.5 goals scored",
                "0.50",
                "0.52",
                strike=5.5,
                sub="Over 5.5 goals scored",
            )
        ],
    ),
    _ev(
        "KXNHL1P",
        "Boston vs New York R: 1st Period",
        [_mk(f"KXNHL1P-{KEY}-BOS", "Boston wins 1st period", "0.30", "0.32", sub="Boston")],
    ),
]


def _no_espn(req: httpx.Request) -> httpx.Response:
    raise AssertionError(f"ESPN must not be called for hockey: {req.url}")


def _app(settings: Settings, server: MPServer, **over: Any):  # type: ignore[no-untyped-def]
    s = Settings(_env_file=None, database_url=settings.database_url, llm_provider="openai", **over)
    engine = make_engine(s.database_url)
    CatalogWriter(make_session_factory(engine), NOW).write_page(PAGE)
    engine.dispose()
    app = create_app(s, FrozenClock(NOW))
    app.state.espn = EspnSource(
        transport=httpx.MockTransport(_no_espn), min_interval=0.0, sleep=lambda _: None
    )
    app.state.moneypuck = mp.MoneyPuck(
        s, transport=httpx.MockTransport(server.handler), now=lambda: NOW
    )
    return app


def run(c: TestClient, ticker: str, side: str = "yes") -> dict[str, Any]:
    r = c.post("/api/research/investigations", json={"ticker": ticker, "side": side}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


# --- mapping -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "series,kind",
    [
        ("KXNHLGAME", "moneyline"),
        ("KXNHLSPREAD", "spread"),
        ("KXNHLTOTAL", "total"),
        ("KXNHLTEAMTOTAL", "team_total"),
        ("KXNHL1PTOTAL", "other"),
        ("KXNHLOT", "other"),
    ],
)
def test_market_kinds(series: str, kind: str) -> None:
    assert nhl.market_kind(series) == kind


def test_unsupported_markets_say_why() -> None:
    ev = f"X-{KEY}"
    assert "Period" in (nhl.unsupported_reason("KXNHL2PSPREAD", ev) or "")
    assert "Overtime" in (nhl.unsupported_reason("KXNHLOT", ev) or "")
    assert "Player props" in (nhl.unsupported_reason("KXNHLGOAL", ev) or "")
    assert nhl.unsupported_reason("KXNHLGAME", ev) is None
    assert "single-game" in (nhl.unsupported_reason("KXNHLGAME", "KXNHLGAME-27") or "")
    assert not nhl.is_nhl("KXNHLSEASONPTS-27-X") and nhl.is_nhl(WIN)
    assert set(nhl.SETTLEMENT) == {"moneyline", "spread", "total", "team_total"}
    assert "not a 60-minute regulation bet" in nhl.SETTLEMENT["moneyline"]
    assert "shootout counts as one goal" in nhl.SETTLEMENT["total"]


def test_team_codes_and_seasons() -> None:
    assert [mp.mp_code(c) for c in ("LA", "NJ", "SJ", "TB", "BOS")] == [
        "LAK",
        "NJD",
        "SJS",
        "TBL",
        "BOS",
    ]
    assert len(mp.NHL_TEAMS) == 32
    assert (
        mp.season_of(datetime(2026, 11, 1)) == 2026 and mp.season_of(datetime(2027, 3, 1)) == 2026
    )


# --- goalie status -------------------------------------------------------------------------


def _season() -> mp.SeasonData:
    return mp.SeasonData(
        season=2026, teams=mp.parse_teams(TEAMS_CSV), goalies=mp.parse_goalies(GOALIES_CSV)
    )


def _news(*items: tuple[str, str, str | None]) -> search.Gathered:
    g = search.Gathered()
    for i, (title, snippet, dup) in enumerate(items, 1):
        g.sources.append(
            S.Source(
                id=f"N{i}",
                url=f"https://www.dailyfaceoff.com/{i}",
                title=title,
                publisher="Daily Faceoff",
                retrieved_at=NOW.isoformat(),
                access="snippet",
                duplicate_of=dup,
            )
        )
        g.snippets[f"N{i}"] = snippet
    return g


def test_goalie_status_is_never_confirmed_from_silence_or_news() -> None:
    s = _season()
    silent = nhl.goalie_status(["BOS", "NYR"], s, None)
    assert {g.state for g in silent.values()} == {"unknown"}
    assert [o.name for o in silent["BOS"].options] == ["Jeremy Swayman", "Joonas Korpisalo"]
    one = nhl.goalie_status(
        ["BOS", "NYR"],
        s,
        _news(("Swayman confirmed to start for Bruins against Rangers", "", None)),
    )
    assert one["BOS"].state == "expected" and one["BOS"].name == "Jeremy Swayman"
    assert one["BOS"].source_ids == ["N1"] and one["NYR"].state == "unknown"
    assert all(g.state != "confirmed" for g in one.values())
    both = nhl.goalie_status(
        ["BOS", "NYR"],
        s,
        _news(
            ("Swayman will start in goal", "", None), ("Korpisalo gets the nod tonight", "", None)
        ),
    )
    assert both["BOS"].state == "conflicting" and both["BOS"].name is None
    # A syndicated copy isn't a second report.
    dup = nhl.goalie_status(
        ["BOS"], s, _news(("Swayman will start", "", None), ("Korpisalo gets the nod", "", "N1"))
    )
    assert dup["BOS"].state == "expected"
    # A goalie merely mentioned (no starting phrase) proves nothing.
    meh = nhl.goalie_status(["NYR"], s, _news(("Shesterkin's contract talks continue", "", None)))
    assert meh["NYR"].state == "unknown"


# --- end to end (deterministic) ------------------------------------------------------------


def test_nhl_moneyline_uses_moneypuck_only_and_shows_no_edge(settings: Settings) -> None:
    server = MPServer()
    with TestClient(_app(settings, server), base_url="http://127.0.0.1") as c:
        pre = c.get("/api/research/preflight", params={"ticker": WIN, "side": "yes"}).json()
        assert pre["unsupported"] is None and "No NHL model" in pre["model"]
        assert server.paths == []  # preflight is free: no download
        r = run(c, WIN)
        again = run(c, TOTAL)
        pl = run(c, SPREAD)
    # Puck line: the better team (54% xG) still isn't expected to win by 2+.
    margin = pl["summary"]["findings"][1]
    assert "Boston Bruins margin near +0.6 vs the 1.5-goal line" in margin["text"]
    assert margin["stance"] == "opposes"
    assert pl["summary"]["takeaway"].startswith("Season goal margins sit below")
    h, p, sm = r["hypothesis"], r["price_assessment"], r["summary"]
    assert (h["sport"], h["league"], h["market_type"], h["subject"]) == (
        "hockey",
        "NHL",
        "moneyline",
        "Boston Bruins",
    )
    assert p["model_p"] is None and p["conservative_edge"] is None and p["walk_away"] is None
    assert nhl.NO_MODEL in p["abstain_reasons"]
    assert any("not a 60-minute regulation bet" in a for a in p["assumptions"])
    ids = [s["id"] for s in r["sources"]]
    assert ids == ["K1", "M1"]
    m1 = r["sources"][1]
    assert "Data: MoneyPuck.com" in m1["title"] and m1["url"] == mp.PAGE
    first = sm["findings"][0]["text"]
    assert first.startswith("Starting goalies") and "Boston Bruins: unknown" in first
    assert "Swayman 15 GP" in first and "neither is confirmed" in first
    xg = next(f for f in r["details"]["supports"] if "expected-goals share" in f["text"])
    assert "Boston Bruins 54% (20 games) vs New York Rangers 47% (21)" in xg["text"]
    assert sm["takeaway"].startswith("Season expected-goals numbers favour")
    assert "Neither starting goalie is known" in sm["takeaway"]
    assert sm["gaps"][0].startswith("Who starts in goal")
    assert sm["coverage"] == "1 factual dataset · 0 commentary links · goalie status unknown"
    assert len(sm["findings"]) <= 3 and len(sm["takeaway"].split(". ")) <= 2
    # Two investigations, one download of each file (12 h cache).
    assert sorted(server.paths) == sorted(
        [
            "/moneypuck/playerData/seasonSummary/2026/regular/teams.csv",
            "/moneypuck/playerData/seasonSummary/2026/regular/goalies.csv",
        ]
    )
    tot = next(
        f
        for f in again["summary"]["findings"] + again["details"]["against"]
        if "Season scoring" in f["text"]
    )
    assert "near 5.7 vs the 5.5 line" in tot["text"] and tot["stance"] == "neutral"
    assert any("shootout counts as one goal" in a for a in again["price_assessment"]["assumptions"])


def test_nhl_period_market_is_refused_and_switch_turns_moneypuck_off(settings: Settings) -> None:
    server = MPServer()
    with TestClient(
        _app(settings, server, research_disabled_sources="moneypuck"), base_url="http://127.0.0.1"
    ) as c:
        bad = c.post(
            "/api/research/investigations",
            json={"ticker": f"KXNHL1P-{KEY}-BOS", "side": "yes"},
            headers=H,
        )
        assert bad.status_code == 422 and "Period markets" in bad.json()["error"]["message"]
        r = run(c, SPREAD, "no")
        src = c.get("/api/research/sources").json()
    assert server.paths == []  # switched off: nothing downloaded
    assert any("switched off" in e for e in r["processing"]["errors"])
    assert [s["id"] for s in r["sources"]] == ["K1"]
    assert r["hypothesis"]["threshold"] == 1.5 and r["hypothesis"]["statement"].startswith("NOT:")
    assert r["price_assessment"]["conservative_edge"] is None
    mpx = next(x for x in src["sources"] if x["source_id"] == "moneypuck")
    assert mpx["enabled"] is False and mpx["rights_status"] == "structured_dataset_allowed"


def test_leakage_is_flagged_when_data_postdates_the_game(settings: Settings) -> None:
    server = MPServer(last_modified="Fri, 20 Nov 2026 11:40:00 GMT")  # after the 00:00 start
    with TestClient(_app(settings, server), base_url="http://127.0.0.1") as c:
        r = run(c, WIN)
    every = r["summary"]["findings"] + r["details"]["against"] + r["details"]["supports"]
    assert any("not a point-in-time view" in f["text"] for f in every)


def test_moneypuck_adapter_allowlist_cache_and_failures() -> None:
    server = MPServer()
    src = mp.MoneyPuck(None, transport=httpx.MockTransport(server.handler), now=lambda: NOW)
    d = src.season(2026)
    assert d.teams["BOS"].gf_pg == pytest.approx(3.3) and d.goalies_for("BOS")[0].gsax == 5.0
    assert d.goalies_for("BOS")[0].save_pct == pytest.approx(1 - 35 / 420)
    src.season(2026)
    assert len(server.paths) == 2  # cached
    with pytest.raises(Exception, match="no file for this season"):
        src.season(2031)
    later = mp.MoneyPuck(
        None, transport=httpx.MockTransport(server.handler), now=lambda: NOW + timedelta(hours=13)
    )
    later.season(2026)
    # 2 (first load) + 1 (2031: the 404 on teams.csv stops before goalies.csv) + 2 (cache expired)
    assert len(server.paths) == 5
    assert mp.PATH.match("/moneypuck/playerData/seasonSummary/2026/regular/teams.csv")
    assert not mp.PATH.match("/moneypuck/playerData/careers/gameByGame/all_teams.csv")
    assert not mp.PATH.match("/moneypuck/playerData/seasonSummary/2026/regular/shots.csv")


# --- news + summary ------------------------------------------------------------------------


def test_nhl_news_queries_filter_other_sports_and_feed_the_goalie_read(
    settings: Settings, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from app.api import investigate_routes

    h = S.Hypothesis(
        ticker=TOTAL,
        event_ticker=f"KXNHLTOTAL-{KEY}",
        side="yes",
        sport="hockey",
        league="NHL",
        market_type="total",
        threshold=5.5,
        subject=None,
        label="x",
        statement="x",
        snapshot_at=None,
        rules_url=None,
    )
    teams = [{"code": "BOS", "name": "Boston Bruins"}, {"code": "NYR", "name": "New York Rangers"}]
    qs = search.plan_queries(h, teams, 5)
    assert qs[0] == "Boston Bruins New York Rangers NHL starting goalie confirmed"
    assert qs[-1] == "Boston Bruins New York Rangers NHL over under 5.5" and len(qs) == 4
    assert search.sport_mismatch(h, "Rangers rally past Astros in Game 7")  # baseball
    assert not search.sport_mismatch(h, "Rangers goalie Shesterkin sharp in shutout")
    assert search.line_match(h, "Bruins-Rangers total set at 6.5 goals") == "different_line"
    brave = Brave(
        [
            art(
                "Swayman gets the start for Bruins vs. Rangers",
                "https://www.dailyfaceoff.com/a",
                "Bruins goalie Jeremy Swayman will start Thursday.",
            ),
            art("Rangers beat Astros in extra innings", "https://www.mlb.com/b", "Baseball."),
        ]
    )
    monkeypatch.setattr(
        investigate_routes,
        "NewsSearch",
        lambda key, **kw: NewsSearch(key, transport=httpx.MockTransport(brave.handler), **kw),
    )
    with TestClient(
        _app(settings, MPServer(), brave_search_api_key="test-key"), base_url="http://127.0.0.1"
    ) as c:
        r = run(c, WIN)
        u = c.get("/api/research/usage").json()
    assert brave.calls == 4 and u["by_purpose"]["research"]["today"] == 4  # <= 5 per run
    assert brave.queries[0].endswith("NHL starting goalie confirmed")
    news = [s for s in r["sources"] if s["id"].startswith("N")]
    assert [s["publisher"] for s in news] == ["Daily Faceoff"]  # the MLB story was dropped
    g = r["summary"]["findings"][0]
    assert (
        "Jeremy Swayman reported as the starter (news, not an official confirmation)" in g["text"]
    )
    assert "N1" in g["source_ids"]
    assert (
        r["summary"]["coverage"]
        == "1 factual dataset · 1 commentary link · goalie status unconfirmed"
    )
    assert "A reported starter isn't an official confirmation" in r["summary"]["takeaway"]


def _hockey_result() -> S.Result:
    goalie = S.Finding(
        text="Starting goalies — Boston Bruins: unknown. No official lineup source "
        "is connected, so neither is confirmed.",
        kind="interpretation",
        stance="neutral",
        source_ids=["M1"],
        verified=True,
    )
    xg = S.Finding(
        text="5-on-5 expected-goals share this season: Boston Bruins 54% (20 games).",
        kind="statistical",
        stance="supports",
        source_ids=["M1"],
        verified=True,
    )
    return S.Result(
        investigation_id="h1",
        status="done",
        created_at=NOW.isoformat(),
        completed_at=NOW.isoformat(),
        stale_at=None,
        hypothesis=S.Hypothesis(
            ticker=WIN,
            event_ticker=f"KXNHLGAME-{KEY}",
            side="yes",
            sport="hockey",
            league="NHL",
            market_type="moneyline",
            threshold=None,
            subject="Boston Bruins",
            label="Boston wins",
            statement="Boston wins",
            snapshot_at=None,
            rules_url=None,
        ),
        quote=S.Quote(ask=0.58, side="yes", observed_at=None, fresh=True, snapshot_ref=None),
        summary=S.Summary(
            takeaway="Deterministic hockey takeaway.",
            findings=[goalie, xg],
            gaps=["Who starts in goal tonight (no official lineup source is connected)."],
            stance="insufficient",
            uncertainty="u",
            coverage="1 factual dataset · 1 commentary link · goalie status unknown",
        ),
        price_assessment=S.Price(
            ask=0.58,
            model_p=None,
            model_band=None,
            model_name=None,
            raw_diff=None,
            conservative_edge=None,
            break_even=0.6,
            walk_away=None,
            fee_per_contract=0.02,
            slippage_per_contract=0.0,
            assumptions=[],
            abstain_reasons=[nhl.NO_MODEL],
        ),
        details=S.Details(supports=[xg], against=[goalie], methodology=[], data_gaps=[]),
        sources=[
            S.Source(
                id="K1",
                url="https://kalshi.com/m",
                title="k",
                publisher="Kalshi",
                retrieved_at=NOW.isoformat(),
                access="internal",
            ),
            S.Source(
                id="M1",
                url=mp.PAGE,
                title="MoneyPuck",
                publisher="MoneyPuck.com",
                retrieved_at=NOW.isoformat(),
                access="internal",
            ),
            S.Source(
                id="N1",
                url="https://www.dailyfaceoff.com/a",
                title="Swayman starts",
                publisher="Daily Faceoff",
                retrieved_at=NOW.isoformat(),
                access="snippet",
            ),
        ],
        processing=S.Processing(
            model=None, searches=1, cache="miss", errors=[], partial_reasons=["deterministic_only"]
        ),
    )


def test_summary_never_calls_a_goalie_confirmed_or_claims_to_have_read_an_article() -> None:
    reply = {
        "claims": [
            {
                "source_id": "N1",
                "text": "Swayman is confirmed as the starter.",
                "kind": "factual",
                "stance": "supports",
            },
            {
                "source_id": "N1",
                "text": "According to the article, Boston is rested.",
                "kind": "factual",
                "stance": "supports",
            },
            {
                "source_id": "N1",
                "text": "A headline reports Swayman will start.",
                "kind": "factual",
                "stance": "neutral",
            },
        ],
        "takeaway": "Swayman is confirmed, so Boston looks good. Check the price.",
        "findings": [
            {
                "text": "The full article says Boston dominates.",
                "kind": "factual",
                "stance": "supports",
                "source_ids": ["N1"],
            },
            {
                "text": "Boston's expected-goals share is 54%.",
                "kind": "statistical",
                "stance": "supports",
                "source_ids": ["M1"],
            },
        ],
        "gaps": ["Starter confirmed?"],
        "stance": "supports",
    }
    out = synth.apply(_hockey_result(), {"N1": "Swayman will start."}, fake(reply))
    texts = [c.text for c in out.details.supports + out.details.against]
    assert "A headline reports Swayman will start." in texts
    assert not any(
        "confirmed as the starter" in t or "According to the article" in t for t in texts
    )
    assert out.summary.findings[0].text.startswith("Starting goalies")  # pinned, first
    assert not any("full article" in f.text for f in out.summary.findings)
    assert out.summary.takeaway == "Deterministic hockey takeaway."  # "confirmed" rejected
    assert out.summary.coverage == "1 factual dataset · 1 commentary link · goalie status unknown"
    assert out.summary.gaps[0].startswith("Who starts in goal")
    assert "Starter confirmed?" not in out.summary.gaps


# --- source registry -----------------------------------------------------------------------


def test_source_registry_is_conservative() -> None:
    required = {
        "source_id",
        "sport",
        "information_type",
        "connector",
        "usage_terms_url",
        "rights_status",
        "allowed_operations",
        "attribution",
        "expiry",
        "last_reviewed_at",
        "notes",
    }
    rows = sources.matrix()
    assert rows and all(required <= set(r) for r in rows)
    assert not any(r["rights_status"] == "licensed_full_text" for r in rows)
    for sid in (
        "nhl_api_web",
        "guardian_open_platform",
        "statsbomb_open",
        "the_odds_api",
        "football_data_uk",
        "puckapi",
    ):
        assert sources.SOURCES[sid].rights_status == "blocked_pending_review"
        assert not sources.allows(sid, "anything")
    assert sources.allows("moneypuck", "download_listed_season_csv")
    assert not sources.allows("moneypuck", "scrape_site")  # only the listed operation
    assert not sources.allows("unknown_source", "download_listed_season_csv")
    off = Settings(_env_file=None, research_disabled_sources="moneypuck, brave_news")
    assert not sources.allows("moneypuck", "download_listed_season_csv", off)
    assert "hockey" not in sources.SOURCES["espn_site_api"].sport  # not used for new sports
    assert sources.SOURCES["moneypuck"].review_quotes
