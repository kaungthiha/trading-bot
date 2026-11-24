"""Soccer investigations: exact three-way and 90-minute mapping, point-in-time results from
football-data.org (keyed), team news always unknown, no invented probability. Mocked
transports only (no football-data.org, ESPN or Brave network calls)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.base import AdapterError
from app.catalog.store import CatalogWriter
from app.core.clock import FrozenClock
from app.core.config import Settings
from app.db.session import make_engine, make_session_factory
from app.investigate import schemas as S
from app.investigate import search, soccer, sources, synth
from app.main import create_app
from app.sportsdata import footballdata as fd
from app.sportsdata.espn import EspnSource
from app.sportsdata.news import NewsSearch
from tests.test_nhl import _hockey_result, _mk
from tests.test_research_search import Brave, art
from tests.test_research_synth import fake

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
KEY = "26NOV29ARSMCI"
H = {"X-KRT-Request": "research"}
SECRET = "test-fd-key-123"
WIN = f"KXEPLGAME-{KEY}-ARS"
TIE = f"KXEPLGAME-{KEY}-TIE"
TOTAL = f"KXEPLTOTAL-{KEY}-3"
BTTS = f"KXEPLBTTS-{KEY}-BTTS"
SPREAD = f"KXEPLSPREAD-{KEY}-MCI2"

ARS = {"id": 57, "name": "Arsenal FC", "shortName": "Arsenal", "tla": "ARS"}
MCI = {"id": 65, "name": "Manchester City FC", "shortName": "Man City", "tla": "MCI"}


def _t(i: int, name: str, tla: str) -> dict[str, Any]:
    return {"id": i, "name": f"{name} FC", "shortName": name, "tla": tla}


def _m(
    i: int,
    when: str,
    home: dict[str, Any],
    away: dict[str, Any],
    ft: tuple[int, int] | None,
    duration: str = "REGULAR",
    regular: tuple[int, int] | None = None,
) -> dict[str, Any]:
    score: dict[str, Any] = {"duration": duration, "fullTime": {"home": None, "away": None}}
    if ft is not None:
        score["fullTime"] = {"home": ft[0], "away": ft[1]}
    if regular is not None:
        score["regularTime"] = {"home": regular[0], "away": regular[1]}
    return {
        "id": i,
        "utcDate": when,
        "status": "FINISHED" if ft is not None else "TIMED",
        "matchday": 1,
        "stage": "REGULAR_SEASON",
        "homeTeam": home,
        "awayTeam": away,
        "score": score,
    }


CHE, LIV, TOT, NEW = (
    _t(61, "Chelsea", "CHE"),
    _t(64, "Liverpool", "LIV"),
    _t(73, "Tottenham", "TOT"),
    _t(67, "Newcastle", "NEW"),
)
EVE, BRE, AVL, FUL = (
    _t(62, "Everton", "EVE"),
    _t(402, "Brentford", "BRE"),
    _t(58, "Aston Villa", "AVL"),
    _t(63, "Fulham", "FUL"),
)
BOU, LEE, WOL = _t(1044, "Bournemouth", "BOU"), _t(341, "Leeds", "LEE"), _t(76, "Wolves", "WOL")
MATCHES = {
    "matches": [
        # Arsenal: W D W L, then a match decided in extra time (regular time 1-1 is used).
        _m(1, "2026-08-22T14:00:00Z", ARS, CHE, (2, 0)),
        _m(2, "2026-09-13T15:30:00Z", LIV, ARS, (1, 1)),
        _m(3, "2026-10-04T14:00:00Z", ARS, TOT, (3, 1)),
        _m(4, "2026-10-25T16:30:00Z", NEW, ARS, (1, 0)),
        _m(5, "2026-11-07T15:00:00Z", ARS, BOU, (2, 1), "EXTRA_TIME", (1, 1)),
        # Man City: W D W W, then a shoot-out with no regular-time score (left out).
        _m(11, "2026-08-23T14:00:00Z", MCI, EVE, (3, 0)),
        _m(12, "2026-09-14T15:30:00Z", BRE, MCI, (2, 2)),
        _m(13, "2026-10-05T14:00:00Z", MCI, AVL, (1, 0)),
        _m(14, "2026-10-26T16:30:00Z", FUL, MCI, (1, 4)),
        _m(15, "2026-11-08T15:00:00Z", MCI, LEE, (5, 4), "PENALTY_SHOOTOUT"),
        # The match itself, a same-day decoy, and a "finished" match AFTER kickoff that a
        # pre-match view must never count.
        _m(99, "2026-11-29T16:30:00Z", ARS, MCI, None),
        _m(98, "2026-11-29T14:00:00Z", TOT, FUL, None),
        _m(97, "2026-12-01T19:30:00Z", ARS, WOL, (5, 0)),
    ]
}


class FDServer:
    def __init__(self, status: int = 200) -> None:
        self.calls: list[httpx.Request] = []
        self.status = status

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        assert req.url.host == "api.football-data.org"
        if self.status != 200:
            return httpx.Response(self.status, json={"message": "nope"})
        return httpx.Response(200, json=MATCHES)


def _ev(series: str, title: str, markets: list[dict[str, Any]], me: bool = False) -> dict[str, Any]:
    return {
        "event_ticker": f"{series}-{KEY}",
        "series_ticker": series,
        "category": "Sports",
        "title": title,
        "sub_title": "ARS vs MCI (Nov 29)",
        "mutually_exclusive": me,
        "markets": markets,
    }


PAGE = [
    _ev(
        "KXEPLGAME",
        "Arsenal vs Manchester City",
        [
            _mk(WIN, "Arsenal", "0.38", "0.40", sub="Arsenal"),
            _mk(f"KXEPLGAME-{KEY}-MCI", "Manchester City", "0.33", "0.35", sub="Manchester City"),
            _mk(TIE, "Tie", "0.26", "0.28", sub="Tie"),
        ],
        me=True,
    ),
    _ev(
        "KXEPLTOTAL",
        "Arsenal vs Manchester City: Total Goals",
        [_mk(TOTAL, "Over 2.5 goals scored", "0.52", "0.54", strike=2.5)],
    ),
    _ev(
        "KXEPLBTTS",
        "Arsenal vs Manchester City: BTTS",
        [_mk(BTTS, "Both Teams To Score", "0.55", "0.57")],
    ),
    _ev(
        "KXEPLSPREAD",
        "Arsenal vs Manchester City: Spread",
        [_mk(SPREAD, "Manchester City wins by more than 1.5 goals", "0.15", "0.17", strike=1.5)],
    ),
    _ev(
        "KXEPLCORNERS",
        "Arsenal vs Manchester City: Total Corners",
        [_mk(f"KXEPLCORNERS-{KEY}-9", "Over 9.5 corners", "0.5", "0.52", strike=9.5)],
    ),
]


def _no_espn(req: httpx.Request) -> httpx.Response:
    raise AssertionError(f"ESPN must not be called for soccer: {req.url}")


def _app(settings: Settings, server: FDServer, key: str | None = SECRET, **over: Any):  # type: ignore[no-untyped-def]
    s = Settings(_env_file=None, database_url=settings.database_url, llm_provider="openai", **over)
    engine = make_engine(s.database_url)
    CatalogWriter(make_session_factory(engine), NOW).write_page(PAGE)
    engine.dispose()
    app = create_app(s, FrozenClock(NOW))
    app.state.espn = EspnSource(
        transport=httpx.MockTransport(_no_espn), min_interval=0.0, sleep=lambda _: None
    )
    app.state.football_data = fd.FootballData(
        s, key, transport=httpx.MockTransport(server.handler), now=lambda: NOW
    )
    return app


def run(c: TestClient, ticker: str, side: str = "yes") -> dict[str, Any]:
    r = c.post("/api/research/investigations", json={"ticker": ticker, "side": side}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def every(r: dict[str, Any]) -> list[dict[str, Any]]:
    return r["summary"]["findings"] + r["details"]["against"] + r["details"]["supports"]


def texts(r: dict[str, Any]) -> str:
    return " ".join(f["text"] for f in every(r))


# --- mapping -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "series,kind",
    [
        ("KXEPLGAME", "moneyline"),
        ("KXUCLSPREAD", "spread"),
        ("KXLALIGATOTAL", "total"),
        ("KXUCLTEAMTOTAL", "team_total"),
        ("KXSERIEABTTS", "btts"),
        ("KXMLSGAME", "moneyline"),
        ("KXUCL1HTOTAL", "other"),
        ("KXLALIGA2GAME", "other"),
    ],
)
def test_market_kinds(series: str, kind: str) -> None:
    assert soccer.market_kind(series) == kind


def test_unsupported_markets_say_why_and_settlement_is_90_minutes() -> None:
    ev = f"X-{KEY}"
    assert "Half markets" in (soccer.unsupported_reason("KXUCL1HSPREAD", ev) or "")
    assert "Half markets" in (soccer.unsupported_reason("KXUCL2HBTTS", ev) or "")
    assert "Corner" in (soccer.unsupported_reason("KXLALIGATCORNERS", ev) or "")
    assert "Correct-score" in (soccer.unsupported_reason("KXUCLSCORE", ev) or "")
    assert "First-team" in (soccer.unsupported_reason("KXUCLFTTS", ev) or "")
    assert "Only soccer" in (soccer.unsupported_reason("KXLALIGA2GAME", ev) or "")
    assert "single-match" in (soccer.unsupported_reason("KXEPLGAME", "KXEPLGAME-27") or "")
    assert soccer.unsupported_reason("KXBUNDESLIGABTTS", ev) is None
    assert soccer.is_soccer(WIN) and soccer.is_soccer("KXMLSGAME-26NOV28PORDAL-POR")
    assert not soccer.is_soccer("KXNFLGAME-26NOV26KCBUF-BUF")
    for kind, rule in soccer.SETTLEMENT.items():
        assert "extra time and penalties don't count" in rule, kind
    assert "“Tie”" in soccer.SETTLEMENT["moneyline"]
    assert fd.season_of(date(2026, 11, 1)) == 2026 and fd.season_of(date(2027, 5, 1)) == 2026


def test_ninety_minute_scores_never_include_extra_time_or_penalties() -> None:
    assert fd.score90("FINISHED", {"duration": "REGULAR", "fullTime": {"home": 2, "away": 1}}) == (
        2,
        1,
        "REGULAR",
    )
    et = {
        "duration": "EXTRA_TIME",
        "fullTime": {"home": 2, "away": 1},
        "regularTime": {"home": 1, "away": 1},
    }
    assert fd.score90("FINISHED", et) == (1, 1, "EXTRA_TIME")
    pens = {"duration": "PENALTY_SHOOTOUT", "fullTime": {"home": 5, "away": 4}}
    assert fd.score90("FINISHED", pens)[:2] == (None, None)  # no regular-time score: unknown
    assert fd.score90("TIMED", {"fullTime": {"home": None, "away": None}})[:2] == (None, None)


def test_team_names_resolve_including_kalshi_quirks() -> None:
    def best(code: str, name: str, options: list[str]) -> str:
        return max(options, key=lambda n: fd.team_score(code, name, fd.Team(0, n, "", "")))

    liga = ["FC Barcelona", "RCD Espanyol de Barcelona", "Athletic Club", "Club Atlético de Madrid"]
    assert best("BAR", "Barcelona", liga) == "FC Barcelona"
    assert best("ATH", "Bilbao", liga) == "Athletic Club"
    assert best("ATM", "Atletico", liga) == "Club Atlético de Madrid"
    bl = ["FC Bayern München", "Bayer 04 Leverkusen", "Borussia Mönchengladbach", "1. FC Köln"]
    assert best("BMU", "Bayern Munich", bl) == "FC Bayern München"
    assert best("BMG", "M´gladbach", bl) == "Borussia Mönchengladbach"  # Kalshi's spelling
    assert best("KOE", "FC Cologne", bl) == "1. FC Köln"
    f1 = ["Paris Saint-Germain FC", "Paris FC", "Olympique Lyonnais"]
    assert best("PSG", "PSG", f1) == "Paris Saint-Germain FC"
    assert best("PAR", "Paris FC", f1) == "Paris FC"
    assert best("OL", "Lyon", f1) == "Olympique Lyonnais"
    sa = ["FC Internazionale Milano", "AC Milan"]
    assert best("INT", "Inter", sa) == "FC Internazionale Milano"
    assert best("ACM", "Milan", sa) == "AC Milan"
    # A code alone still matches, but a full name beats it.
    assert fd.team_score("ARS", "Gunners", fd.Team(1, "Arsenal FC", "Arsenal", "ARS")) == 0.9


def test_form_is_point_in_time_and_venue_split() -> None:
    sm = fd.SeasonMatches("PL", 2026, fd.parse_matches(MATCHES))
    kickoff = datetime(2026, 11, 29, 16, 30, tzinfo=UTC)
    found = sm.find(("ARS", "Arsenal"), ("MCI", "Manchester City"), date(2026, 11, 29))
    assert found is not None
    match, who = found
    assert match.id == 99 and who["ARS"].id == 57 and who["MCI"].id == 65
    a = sm.form(57, kickoff)
    assert (a.games, a.wins, a.draws, a.losses, a.gf, a.ga) == (5, 2, 2, 1, 7, 4)
    assert a.last == "WDWLD" and a.btts == 3 and a.clean_sheets == 1
    home = sm.form(57, kickoff, "home")
    assert (home.games, home.gf, home.ga) == (3, 6, 2)
    m = sm.form(65, kickoff)
    assert (m.games, m.gf, m.ga) == (4, 10, 3)  # the shoot-out match is left out
    assert sm.undetermined(65, kickoff) == 1
    assert sm.form(57, datetime(2026, 9, 1, tzinfo=UTC)).games == 1  # earlier cut-off
    assert sm.find(("ARS", "Arsenal"), ("MCI", "Man City"), date(2026, 12, 20)) is None


# --- end to end (deterministic) ------------------------------------------------------------


def test_soccer_end_to_end_all_kinds_with_no_edge(settings: Settings) -> None:
    server = FDServer()
    with TestClient(_app(settings, server), base_url="http://127.0.0.1") as c:
        pre = c.get("/api/research/preflight", params={"ticker": WIN, "side": "yes"}).json()
        assert pre["unsupported"] is None and "No soccer model" in pre["model"]
        assert server.calls == []  # preflight is free
        win = run(c, WIN)
        tie = run(c, TIE)
        tot = run(c, TOTAL)
        btts = run(c, BTTS)
        sp = run(c, SPREAD, "no")
        raw = c.get(f"/api/research/investigations/{win['investigation_id']}").text
    # One request for the whole league-season (cached), with the key only in its header.
    assert len(server.calls) == 1
    req = server.calls[0]
    assert req.url.path == "/v4/competitions/PL/matches" and req.url.params["season"] == "2026"
    assert req.headers["X-Auth-Token"] == SECRET and SECRET not in str(req.url)
    assert SECRET not in raw and SECRET not in json.dumps([win, tie, tot, btts, sp])
    h, p, sm = win["hypothesis"], win["price_assessment"], win["summary"]
    assert (h["sport"], h["league"], h["market_type"], h["subject"]) == (
        "soccer",
        "EPL",
        "moneyline",
        "Arsenal",
    )
    assert p["model_p"] is None and p["conservative_edge"] is None and p["walk_away"] is None
    assert soccer.NO_MODEL in p["abstain_reasons"]
    assert any("extra time and penalties don't count" in a for a in p["assumptions"])
    assert [s["id"] for s in win["sources"]] == ["K1", "D1"]
    assert fd.ATTRIBUTION in win["sources"][1]["title"]
    assert sm["findings"][0]["text"].startswith("Team news")
    main = sm["findings"][1]
    assert "Arsenal 2-2-1 (1.4 scored, 0.8 conceded a match, 5 matches)" in main["text"]
    assert "Man City 3-1-0 (2.5 / 0.8, 4)" in main["text"]
    assert "goal margin near -0.6" in main["text"] and main["stance"] == "opposes"
    t = texts(win)
    assert "Arsenal at home 2-1-0 (2.0 scored, 0.7 conceded, 3 matches)" in t
    assert "Man City away 1-1-0 (3.0 / 1.5, 2)" in t
    assert "Last five: Arsenal WDWLD, Man City WDWW" in t
    assert "5 and 4 Premier League matches played before this kickoff" in t
    assert "1 match decided after 90 minutes left out" in t
    assert "5-0" not in t and "6 matches" not in t  # the post-kickoff match never counts
    assert sm["takeaway"].startswith("Past goal margins cut against")
    assert "Team news isn't known" in sm["takeaway"]
    assert sm["gaps"][0].startswith("Who's playing tonight")
    assert sm["coverage"] == (
        "1 factual dataset · 0 commentary links · team news unknown (no lineup source)"
    )
    # Draw ("Tie") is its own hypothesis, about the 90-minute result.
    assert tie["hypothesis"]["subject"] is None
    assert "Draws: Arsenal 2/5, Man City 1/4" in texts(tie)
    assert tie["summary"]["takeaway"].startswith("Past draw rates are context")
    tf = tot["summary"]["findings"][1]["text"]
    assert "more than 2.5 goals: Arsenal 1/5, Man City 3/4" in tf
    assert "combined goals near 2.7" in tf and tot["hypothesis"]["threshold"] == 2.5
    bf = btts["summary"]["findings"][1]
    assert "Both teams scored in 3/5 of Arsenal's matches and 2/4 of Man City's" in bf["text"]
    assert bf["stance"] == "neutral" and btts["hypothesis"]["market_type"] == "btts"
    sf = sp["summary"]["findings"][1]
    assert (
        "Man City won by more than 1.5 in 2/4 matches; Arsenal lost by more than 1.5 in 0/5"
        in (sf["text"])
    )
    # A NO on "City by 2+": a +0.6 margin vs the 1.5 line supports the NO.
    assert sf["stance"] == "supports" and sp["hypothesis"]["statement"].startswith("NOT:")


def test_no_key_means_price_only_and_no_request(settings: Settings) -> None:
    server = FDServer()
    with TestClient(_app(settings, server, key=None), base_url="http://127.0.0.1") as c:
        r = run(c, WIN)
    assert server.calls == []
    assert any("KRT_FOOTBALL_DATA_API_KEY" in e for e in r["processing"]["errors"])
    assert [s["id"] for s in r["sources"]] == ["K1"]
    assert r["summary"]["takeaway"].startswith("Past results weren't checked")
    assert "Past results weren't checked" in texts(r)
    assert r["price_assessment"]["conservative_edge"] is None


def test_switch_off_corners_refused_and_bad_key_reported(settings: Settings) -> None:
    server = FDServer()
    app = _app(settings, server, research_disabled_sources="football_data_org")
    with TestClient(app, base_url="http://127.0.0.1") as c:
        bad = c.post(
            "/api/research/investigations",
            json={"ticker": f"KXEPLCORNERS-{KEY}-9", "side": "yes"},
            headers=H,
        )
        assert bad.status_code == 422 and "Corner" in bad.json()["error"]["message"]
        r = run(c, WIN)
        src = c.get("/api/research/sources").json()
    assert server.calls == []
    assert any("switched off" in e for e in r["processing"]["errors"])
    row = next(x for x in src["sources"] if x["source_id"] == "football_data_org")
    assert row["enabled"] is False and SECRET not in json.dumps(src)
    refused = FDServer(status=403)
    with TestClient(_app(settings, refused), base_url="http://127.0.0.1") as c:
        r2 = run(c, TOTAL)
    assert any("refused the key" in e for e in r2["processing"]["errors"])
    assert SECRET not in json.dumps(r2)


def test_adapter_allowlist_cache_and_throttle() -> None:
    server = FDServer()
    ticks = iter(range(100))
    src = fd.FootballData(
        None,
        SECRET,
        transport=httpx.MockTransport(server.handler),
        now=lambda: NOW,
        clock=lambda: float(next(ticks)),
    )
    src.season("PL", 2026)
    src.season("PL", 2026)
    assert len(server.calls) == 1  # cached for 3 hours
    with pytest.raises(AdapterError, match="not allowed"):
        src.season("PPL", 2026)  # Primeira Liga isn't on the allow-list
    for yr in range(2017, 2025):  # 8 more distinct requests: 9 within a minute is the cap
        src.season("PL", yr)
    with pytest.raises(AdapterError, match="10 requests a minute"):
        src.season("PL", 2025)
    assert len(server.calls) == 9
    assert fd.PATH.match("/v4/competitions/CL/matches")
    assert not fd.PATH.match("/v4/teams/57/matches")
    unkeyed = fd.FootballData(None, None, transport=httpx.MockTransport(server.handler))
    with pytest.raises(AdapterError, match="isn't configured"):
        unkeyed.season("PL", 2026)


def test_mls_runs_on_price_and_rules_only(settings: Settings) -> None:
    key = "26NOV28PORDAL"
    page = [
        {
            "event_ticker": f"KXMLSGAME-{key}",
            "series_ticker": "KXMLSGAME",
            "category": "Sports",
            "title": "Portland vs Dallas",
            "sub_title": "POR vs DAL",
            "mutually_exclusive": True,
            "markets": [
                _mk(f"KXMLSGAME-{key}-POR", "Portland", "0.45", "0.47", sub="Portland"),
                _mk(f"KXMLSGAME-{key}-DAL", "Dallas", "0.28", "0.30", sub="Dallas"),
                _mk(f"KXMLSGAME-{key}-TIE", "Tie", "0.25", "0.27", sub="Tie"),
            ],
        }
    ]
    server = FDServer()
    app = _app(settings, server)
    engine = make_engine(app.state.settings.database_url)
    CatalogWriter(make_session_factory(engine), NOW).write_page(page)
    engine.dispose()
    with TestClient(app, base_url="http://127.0.0.1") as c:
        r = run(c, f"KXMLSGAME-{key}-POR")
    assert server.calls == []
    assert not any("football-data" in e or "FOOTBALL" in e for e in r["processing"]["errors"])
    assert r["hypothesis"]["league"] == "MLS"
    assert "No permitted results source covers MLS" in texts(r)
    assert any("MLS" in g for g in r["summary"]["gaps"])


# --- news + summary ------------------------------------------------------------------------


def test_soccer_news_queries_and_filter(settings: Settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.api import investigate_routes

    h = S.Hypothesis(
        ticker=TOTAL,
        event_ticker=f"KXEPLTOTAL-{KEY}",
        side="yes",
        sport="soccer",
        league="EPL",
        market_type="total",
        threshold=2.5,
        subject=None,
        label="x",
        statement="x",
        snapshot_at=None,
        rules_url=None,
    )
    teams = [{"code": "ARS", "name": "Arsenal"}, {"code": "MCI", "name": "Man City"}]
    qs = search.plan_queries(h, teams, 5)
    assert qs == [
        "Arsenal vs Man City team news",
        "Arsenal vs Man City preview EPL",
        "Arsenal vs Man City over under 2.5 goals",
    ]
    btts_h = h.model_copy(update={"market_type": "btts", "threshold": None})
    assert search.plan_queries(btts_h, teams, 5)[-1].endswith("both teams to score")
    assert search.sport_mismatch(h, "Dallas Cowboys quarterback throws three touchdowns")
    assert search.sport_mismatch(h, "Houston Rockets rally late")  # no soccer words
    assert not search.sport_mismatch(h, "Arsenal boss gives team news before City clash")
    assert search.line_match(h, "Arsenal v City: over 3.5 goals tip") == "different_line"
    brave = Brave(
        [
            art(
                "Arsenal team news: Saka out against Man City",
                "https://www.bbc.co.uk/sport/a",
                "Arsenal manager confirms the winger misses the clash.",
                age="2026-11-27T08:00:00",
            ),
            art(
                "Arsenal Firearms recall announced",
                "https://example.com/b",
                "A product recall.",
                age="2026-11-27T08:00:00",
            ),
        ]
    )
    monkeypatch.setattr(
        investigate_routes,
        "NewsSearch",
        lambda key, **kw: NewsSearch(key, transport=httpx.MockTransport(brave.handler), **kw),
    )
    with TestClient(
        _app(settings, FDServer(), brave_search_api_key="test-key"), base_url="http://127.0.0.1"
    ) as c:
        r = run(c, TOTAL)
    assert brave.calls == 3  # <= 5 per run
    news = [s for s in r["sources"] if s["id"].startswith("N")]
    assert [s["publisher"] for s in news] == ["BBC Sport"]  # the off-topic story was dropped
    assert r["summary"]["coverage"].startswith("1 factual dataset · 1 commentary link")


def test_summary_keeps_team_news_first() -> None:
    r = _hockey_result()
    tn = S.Finding(
        text=soccer.TEAM_NEWS, kind="interpretation", stance="neutral", source_ids=[], verified=True
    )
    r.hypothesis = r.hypothesis.model_copy(update={"sport": "soccer", "league": "EPL"})
    r.summary = r.summary.model_copy(
        update={
            "findings": [tn, r.summary.findings[1]],
            "gaps": ["Who's playing tonight: no lineup or injury source is connected for soccer."],
        }
    )
    reply = {
        "claims": [
            {
                "source_id": "N1",
                "text": "A headline says the winger is out.",
                "kind": "factual",
                "stance": "neutral",
            }
        ],
        "takeaway": "A headline says the winger is out, so check the lineup.",
        "findings": [
            {
                "text": "Boston look strong.",
                "kind": "interpretation",
                "stance": "supports",
                "source_ids": ["M1"],
            }
        ],
        "gaps": [],
        "stance": "insufficient",
    }
    out = synth.apply(r, {"N1": "Winger out."}, fake(reply))
    assert out.summary.findings[0].text.startswith("Team news")  # pinned
    assert out.summary.gaps[0].startswith("Who's playing tonight")


# --- source registry -----------------------------------------------------------------------


def test_soccer_sources_registered_honestly() -> None:
    assert sources.allows("football_data_org", "read_competition_matches")
    assert not sources.allows("football_data_org", "download_team_logos")
    fdo = sources.SOURCES["football_data_org"]
    assert fdo.connector == "app.sportsdata.footballdata" and fdo.review_quotes
    assert "logos" in fdo.notes and "MLS" in fdo.notes
    of = sources.SOURCES["openfootball"]
    assert of.connector == "none" and "Sep 20" in of.notes
    for sid in ("football_data_uk", "statsbomb_open"):
        assert not sources.allows(sid, "anything")
    assert "soccer" not in sources.SOURCES["espn_site_api"].sport
    off = Settings(_env_file=None, research_disabled_sources="football_data_org")
    assert not sources.allows("football_data_org", "read_competition_matches", off)
    # The key is a secret setting: blank means unset, and it never prints.
    s = Settings(_env_file=None, football_data_api_key="  ")
    assert s.football_data_api_key is None
    s2 = Settings(_env_file=None, football_data_api_key=SECRET)
    assert SECRET not in repr(s2) and SECRET not in str(s2.model_dump())
