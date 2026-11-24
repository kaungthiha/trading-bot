"""NFL investigations: exact market mapping, status-safe quarterback reads, point-in-time
nflverse context, kickoff weather, no invented probability. Mocked transports only (no
GitHub, Open-Meteo, ESPN or Brave network calls)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.base import AdapterError
from app.catalog.store import CatalogWriter
from app.core.clock import FrozenClock
from app.core.config import Settings
from app.db.session import make_engine, make_session_factory
from app.investigate import nfl, search, sources, synth
from app.investigate import schemas as S
from app.main import create_app
from app.sportsdata import nflverse as nv
from app.sportsdata import weather as wx
from app.sportsdata.espn import EspnSource
from app.sportsdata.news import NewsSearch
from tests.test_nhl import _hockey_result, _mk
from tests.test_research_search import Brave, art
from tests.test_research_synth import fake

NOW = datetime(2026, 11, 24, 15, 0, tzinfo=UTC)
KEY = "26NOV26KCBUF"
H = {"X-KRT-Request": "research"}
WIN = f"KXNFLGAME-{KEY}-BUF"
SPREAD = f"KXNFLSPREAD-{KEY}-BUF8"
TOTAL = f"KXNFLTOTAL-{KEY}-46"
TEAMTOTAL = f"KXNFLTEAMTOTAL-{KEY}-KC21"

GAMES_HEAD = (
    "game_id,season,game_type,week,gameday,weekday,gametime,away_team,away_score,home_team,"
    "home_score,location,result,total,overtime,away_rest,home_rest,away_moneyline,"
    "home_moneyline,spread_line,total_line,div_game,roof,surface,temp,wind,away_qb_name,"
    "home_qb_name,stadium_id,stadium\n"
)
GAMES_CSV = GAMES_HEAD + "\n".join(
    [
        "2025_10_KC_BUF,2025,REG,10,2025-11-09,Sunday,16:25,KC,3,BUF,40,Home,,,,7,7,,,,,0,"
        "outdoors,a_turf,,,Old Guy,Josh Allen,BUF00,Highmark Stadium",
        "2026_01_KC_DEN,2026,REG,1,2026-09-13,Sunday,16:25,KC,27,DEN,20,Home,,,,7,7,-150,130,"
        "3,44,1,outdoors,grass,,,Patrick Mahomes,Bo Nix,DEN00,Empower Field",
        "2026_02_BUF_MIA,2026,REG,2,2026-09-20,Sunday,13:00,BUF,31,MIA,17,Home,,,,7,7,,,,,1,"
        "outdoors,grass,,,Josh Allen,Tua Tagovailoa,MIA00,Hard Rock Stadium",
        "2026_03_KC_LV,2026,REG,3,2026-09-27,Sunday,16:05,KC,24,LV,21,Home,,,,7,7,,,,,1,"
        "dome,grass,,,Patrick Mahomes,Geno Smith,VEG00,Allegiant Stadium",
        "2026_03_NYJ_BUF,2026,REG,3,2026-09-27,Sunday,13:00,NYJ,10,BUF,30,Home,,,,7,7,,,,,1,"
        "outdoors,a_turf,,,Justin Fields,Mitchell Trubisky,BUF00,Highmark Stadium",
        # The game under investigation: sportsbook columns carry junk that must never surface.
        "2026_12_KC_BUF,2026,REG,12,2026-11-26,Thursday,20:20,KC,,BUF,,Home,,,,4,4,-777,555,"
        "-99.5,88.5,0,outdoors,a_turf,,,Patrick Mahomes,Josh Allen,BUF00,Highmark Stadium",
    ]
)
STATS_HEAD = "season,week,team,season_type,game_id,opponent_team,attempts,sacks_suffered,carries,"
STATS_HEAD += "passing_epa,rushing_epa\n"
STATS_CSV = STATS_HEAD + "\n".join(
    [
        "2026,1,KC,REG,2026_01_KC_DEN,DEN,35,2,25,4,1",
        "2026,1,DEN,REG,2026_01_KC_DEN,KC,35,2,25,-2,-1",
        "2026,2,BUF,REG,2026_02_BUF_MIA,MIA,35,2,25,9,3",
        "2026,2,MIA,REG,2026_02_BUF_MIA,BUF,35,2,25,-4,-2",
        "2026,3,KC,REG,2026_03_KC_LV,LV,35,2,25,6,2",
        "2026,3,LV,REG,2026_03_KC_LV,KC,35,2,25,1,1",
        "2026,3,BUF,REG,2026_03_NYJ_BUF,NYJ,35,2,25,7,3",
        "2026,3,NYJ,REG,2026_03_NYJ_BUF,BUF,35,2,25,-7,-3",
    ]
)
INJ_HEAD = (
    "season,season_type,game_type,team,week,gsis_id,position,full_name,first_name,last_name,"
    "report_primary_injury,report_secondary_injury,report_status,practice_primary_injury,"
    "practice_secondary_injury,practice_status\n"
)
INJ_ROWS = [
    "2026,REG,REG,BUF,11,1,QB,Mitchell Trubisky,Mitchell,Trubisky,,,,,,Full Participation",
    "2026,REG,REG,BUF,12,2,QB,Josh Allen,Josh,Allen,Ankle,,Questionable,Ankle,,Limited",
    "2026,REG,REG,KC,12,3,TE,Travis Kelce,Travis,Kelce,Knee,,Out,Knee,,Did Not Participate",
    "2026,REG,REG,BUF,12,4,WR,Khalil Shakir,Khalil,Shakir,Hamstring,,Doubtful,,,DNP",
]


class GitHub:
    """github.com answers with one redirect to the asset host, like the real release CDN."""

    def __init__(
        self,
        injuries_through: int = 12,
        last_modified: str = "Tue, 24 Nov 2026 05:00:00 GMT",
        redirect_host: str = "release-assets.githubusercontent.com",
    ) -> None:
        self.paths: list[str] = []
        self.lm = last_modified
        self.host = redirect_host
        rows = [r for r in INJ_ROWS if int(r.split(",")[4]) <= injuries_through]
        self.files = {
            "schedules/games.csv": GAMES_CSV,
            "stats_team/stats_team_week_2026.csv": STATS_CSV,
            "injuries/injuries_2026.csv": INJ_HEAD + "\n".join(rows),
        }

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.paths.append(f"{req.url.host}{req.url.path}")
        if req.url.host == "github.com":
            name = req.url.path.removeprefix(nv.ROOT)
            if name not in self.files:
                return httpx.Response(404)
            return httpx.Response(
                302, headers={"location": f"https://{self.host}/asset/{name}?sig=1"}
            )
        assert req.url.host == "release-assets.githubusercontent.com", req.url
        name = req.url.path.removeprefix("/asset/")
        return httpx.Response(200, text=self.files[name], headers={"last-modified": self.lm})

    def downloads(self) -> list[str]:
        return [p for p in self.paths if p.startswith("github.com")]


class Meteo:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        assert req.url.host == "api.open-meteo.com" and req.url.path == wx.PATH
        self.calls.append(dict(req.url.params))
        day = req.url.params["start_date"]
        return httpx.Response(
            200,
            json={
                "hourly": {
                    "time": [f"{day}T00:00", f"{day}T01:00"],
                    "temperature_2m": [36.0, 34.2],
                    "wind_speed_10m": [12.0, 17.6],
                    "wind_gusts_10m": [20.0, 29.4],
                    "precipitation_probability": [70, 85],
                }
            },
        )


def _ev(series: str, title: str, markets: list[dict[str, Any]], me: bool = False) -> dict[str, Any]:
    return {
        "event_ticker": f"{series}-{KEY}",
        "series_ticker": series,
        "category": "Sports",
        "title": title,
        "sub_title": "KC vs BUF (Nov 26)",
        "mutually_exclusive": me,
        "markets": markets,
    }


PAGE = [
    _ev(
        "KXNFLGAME",
        "Kansas City vs Buffalo",
        [
            _mk(f"KXNFLGAME-{KEY}-KC", "Kansas City wins", "0.40", "0.42", sub="Kansas City"),
            _mk(WIN, "Buffalo wins", "0.58", "0.60", sub="Buffalo"),
        ],
        me=True,
    ),
    _ev(
        "KXNFLSPREAD",
        "Kansas City vs Buffalo: Spread",
        [_mk(SPREAD, "Buffalo wins by over 7.5 points", "0.30", "0.32", strike=7.5)],
    ),
    _ev(
        "KXNFLTOTAL",
        "Kansas City vs Buffalo: Total Points",
        [_mk(TOTAL, "Over 45.5 points", "0.50", "0.52", strike=45.5)],
    ),
    _ev(
        "KXNFLTEAMTOTAL",
        "Kansas City vs Buffalo: Team Total",
        [_mk(TEAMTOTAL, "Kansas City over 20.5 points", "0.55", "0.57", strike=20.5)],
    ),
    _ev(
        "KXNFL1HTEAMTOTAL",
        "Kansas City vs Buffalo: 1H Team Total",
        [_mk(f"KXNFL1HTEAMTOTAL-{KEY}-KC10", "KC 1H over 9.5", "0.5", "0.52", strike=9.5)],
    ),
]


def _no_espn(req: httpx.Request) -> httpx.Response:
    raise AssertionError(f"ESPN must not be called for football: {req.url}")


def _app(settings: Settings, gh: GitHub, meteo: Meteo, **over: Any):  # type: ignore[no-untyped-def]
    s = Settings(_env_file=None, database_url=settings.database_url, llm_provider="openai", **over)
    engine = make_engine(s.database_url)
    CatalogWriter(make_session_factory(engine), NOW).write_page(PAGE)
    engine.dispose()
    app = create_app(s, FrozenClock(NOW))
    app.state.espn = EspnSource(
        transport=httpx.MockTransport(_no_espn), min_interval=0.0, sleep=lambda _: None
    )
    app.state.nflverse = nv.Nflverse(s, transport=httpx.MockTransport(gh.handler), now=lambda: NOW)
    app.state.weather = wx.OpenMeteo(
        s, transport=httpx.MockTransport(meteo.handler), now=lambda: NOW
    )
    return app


def run(c: TestClient, ticker: str, side: str = "yes") -> dict[str, Any]:
    r = c.post("/api/research/investigations", json={"ticker": ticker, "side": side}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def every(r: dict[str, Any]) -> list[dict[str, Any]]:
    return r["summary"]["findings"] + r["details"]["against"] + r["details"]["supports"]


# --- mapping -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "series,kind",
    [
        ("KXNFLGAME", "moneyline"),
        ("KXNFLSPREAD", "spread"),
        ("KXNFLTOTAL", "total"),
        ("KXNFLTEAMTOTAL", "team_total"),
        ("KXNFL1HTEAMTOTAL", "other"),
        ("KXNFLTOTALPRECISE", "other"),
    ],
)
def test_market_kinds(series: str, kind: str) -> None:
    assert nfl.market_kind(series) == kind


def test_unsupported_markets_say_why_and_settlement_is_exact() -> None:
    ev = f"X-{KEY}"
    assert "Half and quarter" in (nfl.unsupported_reason("KXNFL1HTEAMTOTAL", ev) or "")
    assert "Half and quarter" in (nfl.unsupported_reason("KXNFL2QBTTS", ev) or "")
    for prop in ("KXNFLPASSYDS", "KXNFLRSHYDS", "KXNFLRECYDS", "KXNFLFIRSTTD", "KXNFLTD"):
        assert "Player props" in (nfl.unsupported_reason(prop, ev) or ""), prop
    assert "Only NFL game winner" in (nfl.unsupported_reason("KXNFLWINMARGIN", ev) or "")
    assert nfl.unsupported_reason("KXNFLGAME", ev) is None
    assert "single-game" in (nfl.unsupported_reason("KXNFLGAME", "KXNFLGAME-27") or "")
    assert nfl.is_nfl(WIN) and not nfl.is_nfl("KXNHLGAME-26NOV19BOSNYR-BOS")
    assert "tie" in nfl.SETTLEMENT["moneyline"] and "$0.50" in nfl.SETTLEMENT["moneyline"]
    assert "overtime included" in nfl.SETTLEMENT["total"]
    assert "A tie isn't a win" in nfl.SETTLEMENT["spread"]


def test_team_codes_seasons_and_kickoff_time() -> None:
    assert [nv.nv_code(c) for c in ("JAC", "LAR", "LAC", "KC")] == ["JAX", "LA", "LAC", "KC"]
    assert len(nv.NFL_TEAMS) == 32
    assert nv.season_of(date(2026, 11, 1)) == 2026 and nv.season_of(date(2027, 1, 20)) == 2026
    g = next(g for g in nv.parse_games(GAMES_CSV, 2026) if g.week == 12)
    # 20:20 Eastern on Nov 26 (EST, UTC-5) is 01:20 UTC on Nov 27.
    assert g.kickoff == datetime(2026, 11, 27, 1, 20, tzinfo=UTC)
    early = next(g for g in nv.parse_games(GAMES_CSV, 2026) if g.week == 1)
    assert early.kickoff == datetime(2026, 9, 13, 20, 25, tzinfo=UTC)  # EDT, UTC-4
    assert not hasattr(g, "spread_line") and not hasattr(g, "total_line")
    assert len(nv.parse_games(GAMES_CSV, 2025)) == 1  # one season at a time


def _season(injuries_through: int = 12) -> nv.SeasonData:
    rows = [r for r in INJ_ROWS if int(r.split(",")[4]) <= injuries_through]
    return nv.SeasonData(
        season=2026,
        games=nv.parse_games(GAMES_CSV, 2026),
        weeks=nv.parse_weeks(STATS_CSV),
        injuries=nv.parse_injuries(INJ_HEAD + "\n".join(rows)),
    )


def test_form_is_point_in_time() -> None:
    s = _season()
    full = s.form("BUF", datetime(2026, 11, 27, tzinfo=UTC))
    assert (full.games, full.pf_pg, full.pa_pg) == (2, 30.5, 13.5)
    assert full.off_epa_play == pytest.approx(22 / 124)
    assert full.def_epa_play == pytest.approx(-16 / 124)
    # Before week 3 kicked off, week 3 doesn't exist yet.
    early = s.form("BUF", datetime(2026, 9, 25, tzinfo=UTC))
    assert (early.games, early.pf_pg) == (1, 31.0) and early.off_epa_play is None  # < 100 plays
    assert s.find_game("KC", "BUF", date(2026, 11, 26)).week == 12  # type: ignore[union-attr]
    assert s.find_game("BUF", "KC", date(2026, 11, 27)).week == 12  # type: ignore[union-attr]
    assert s.find_game("KC", "BUF", date(2026, 12, 20)) is None
    assert s.prior_starters("BUF", datetime(2026, 11, 27, tzinfo=UTC)) == [
        ("Mitchell Trubisky", 1),
        ("Josh Allen", 1),
    ]


# --- quarterback status --------------------------------------------------------------------


def _news(*items: tuple[str, str, str | None]) -> search.Gathered:
    g = search.Gathered()
    for i, (title, snippet, dup) in enumerate(items, 1):
        g.sources.append(
            S.Source(
                id=f"N{i}",
                url=f"https://www.nfl.com/news/{i}",
                title=title,
                publisher="NFL.com",
                retrieved_at=NOW.isoformat(),
                access="snippet",
                duplicate_of=dup,
            )
        )
        g.snippets[f"N{i}"] = snippet
    return g


def test_qb_status_is_never_confirmed_and_respects_the_injury_report() -> None:
    s = _season()
    game = s.find_game("KC", "BUF", date(2026, 11, 26))
    silent = nfl.qb_status(["KC", "BUF"], game, s, None, report_week=True)
    assert silent["KC"].state == "expected" and silent["KC"].basis == "listed"
    assert silent["BUF"].injury == "Questionable (ankle)" and silent["BUF"].state == "expected"
    news = nfl.qb_status(
        ["KC", "BUF"],
        game,
        s,
        _news(("Bills confirm Josh Allen will start Thursday vs Chiefs", "", None)),
        report_week=True,
    )
    assert news["BUF"].state == "expected" and news["BUF"].basis == "news report"
    assert news["BUF"].source_ids == ["N1"]
    assert all(q.state != "confirmed" for q in news.values())
    # A report naming a different starter than the listed one is a conflict.
    other = nfl.qb_status(
        ["BUF"], game, s, _news(("Mitchell Trubisky to start for Bills", "", None)), True
    )
    assert other["BUF"].state == "conflicting" and other["BUF"].name is None
    # A syndicated copy isn't a second report; a mere mention proves nothing.
    dup = nfl.qb_status(
        ["BUF"],
        game,
        s,
        _news(("Josh Allen will start", "", None), ("Trubisky gets the start", "", "N1")),
        True,
    )
    assert dup["BUF"].state == "expected"
    meh = nfl.qb_status(["KC"], game, s, _news(("Mahomes contract talks", "", None)), True)
    assert meh["KC"].basis == "listed"
    # Listed QB ruled Out -> unknown, never 'expected'.
    out_rows = INJ_ROWS + ["2026,REG,REG,KC,12,9,QB,Patrick Mahomes,P,M,Ankle,,Out,,,DNP"]
    s2 = nv.SeasonData(
        season=2026,
        games=s.games,
        weeks=s.weeks,
        injuries=nv.parse_injuries(INJ_HEAD + "\n".join(out_rows)),
    )
    out = nfl.qb_status(["KC"], game, s2, None, True)
    assert out["KC"].state == "unknown" and out["KC"].injury == "Out (ankle)"
    # No listed QB at all -> unknown, with this season's starters as options.
    blank = nv.SeasonData(
        season=2026,
        games=[
            g if g.week != 12 else nv.Game(**{**g.__dict__, "away_qb": "", "home_qb": ""})
            for g in s.games
        ],
    )
    gb = blank.find_game("KC", "BUF", date(2026, 11, 26))
    none = nfl.qb_status(["BUF"], gb, blank, None, False)
    assert none["BUF"].state == "unknown" and none["BUF"].options[0] == ("Mitchell Trubisky", 1)


# --- end to end (deterministic) ------------------------------------------------------------


def test_nfl_moneyline_end_to_end_with_weather_and_no_edge(settings: Settings) -> None:
    gh, meteo = GitHub(), Meteo()
    with TestClient(_app(settings, gh, meteo), base_url="http://127.0.0.1") as c:
        pre = c.get("/api/research/preflight", params={"ticker": WIN, "side": "yes"}).json()
        assert pre["unsupported"] is None and "No NFL model" in pre["model"]
        assert gh.paths == [] and meteo.calls == []  # preflight is free
        r = run(c, WIN)
        sp = run(c, SPREAD)
        tot = run(c, TOTAL)
        tt = run(c, TEAMTOTAL, "no")
    h, p, sm = r["hypothesis"], r["price_assessment"], r["summary"]
    assert (h["sport"], h["league"], h["market_type"], h["subject"]) == (
        "football",
        "NFL",
        "moneyline",
        "Buffalo Bills",
    )
    assert p["model_p"] is None and p["conservative_edge"] is None and p["walk_away"] is None
    assert nfl.NO_MODEL in p["abstain_reasons"]
    assert any("$0.50" in a for a in p["assumptions"])
    assert [s["id"] for s in r["sources"]] == ["K1", "F1", "W1"]
    f1, w1 = r["sources"][1], r["sources"][2]
    assert nv.ATTRIBUTION in f1["title"] and f1["url"] == nv.PAGE
    assert wx.ATTRIBUTION in w1["title"]
    qb = sm["findings"][0]["text"]
    assert qb.startswith("Starting quarterbacks")
    assert "Kansas City Chiefs: Patrick Mahomes listed (a projection)" in qb
    assert "Josh Allen listed (a projection), Questionable (ankle) on the report" in qb
    assert "neither is confirmed" in qb
    pts = sm["findings"][1]
    assert "Buffalo Bills 30.5 for / 13.5 against (2 games)" in pts["text"]
    assert "margin near +6.0" in pts["text"] and pts["stance"] == "supports"
    inj = sm["findings"][2]["text"]
    assert inj.startswith("Week 12 injury report")
    assert "Travis Kelce (TE, Out)" in inj and "Khalil Shakir (WR, Doubtful)" in inj
    assert "1 questionable" in inj
    texts = " ".join(f["text"] for f in every(r))
    assert "Kansas City Chiefs offense +0.10, defense allows -0.01" in texts
    assert "Rest: Kansas City Chiefs 4 days, Buffalo Bills 4 days" in texts
    assert "Highmark Stadium: open-air" in texts
    assert "34°F, wind 18 mph (gusts 29), 85% chance of precipitation" in texts
    assert "Forecast for kickoff (Nov 27 01:00 UTC), retrieved Nov 24 15:00 UTC" in texts
    assert "-777" not in texts and "99.5" not in texts and "88.5" not in texts  # no book lines
    assert "2 and 2 games played before this kickoff" in texts
    assert sm["takeaway"].startswith("Season scoring margins favour")
    assert "Listed or reported quarterbacks aren't official" in sm["takeaway"]
    assert sm["gaps"][0].startswith("Who starts at quarterback")
    assert sm["coverage"] == "2 factual datasets · 0 commentary links · starting QBs unconfirmed"
    assert len(sm["findings"]) <= 3
    # Four investigations: each file downloaded once (12 h cache), one forecast (1 h cache).
    assert sorted(gh.downloads()) == sorted(f"github.com{nv.ROOT}{n}" for n in gh.files)
    assert len(meteo.calls) == 1
    assert meteo.calls[0]["start_date"] == "2026-11-27"
    assert meteo.calls[0]["wind_speed_unit"] == "mph"
    # Spread: the better team still isn't expected to cover 7.5.
    spf = sp["summary"]["findings"][1]
    assert "margin near +6.0 vs the 7.5-point line" in spf["text"]
    assert spf["stance"] == "neutral"
    assert sp["summary"]["takeaway"].startswith("Season scoring margins sit close to")
    assert any("A tie isn't a win" in a for a in sp["price_assessment"]["assumptions"])
    tf = tot["summary"]["findings"][1]
    assert "combined points near 45.0 vs the 45.5 line" in tf["text"]
    assert tot["hypothesis"]["threshold"] == 45.5 and tot["hypothesis"]["subject"] is None
    ttf = tt["summary"]["findings"][1]
    # KC: (25.5 own + 13.5 BUF allows) / 2 = 19.5 vs 20.5; a NO leans the other way.
    assert "Kansas City Chiefs points near 19.5 vs the 20.5 line" in ttf["text"]
    assert tt["hypothesis"]["statement"].startswith("NOT:")


def test_missing_injury_week_is_unknown_not_healthy(settings: Settings) -> None:
    gh, meteo = GitHub(injuries_through=11), Meteo()
    with TestClient(_app(settings, gh, meteo), base_url="http://127.0.0.1") as c:
        r = run(c, WIN)
    texts = " ".join(f["text"] for f in every(r))
    assert "isn't in the nflverse file yet (latest: week 11)" in texts
    assert "Questionable" not in texts  # no stale report presented as this week's
    assert any("injury report (week 12) isn't available" in g for g in r["summary"]["gaps"])


def test_half_market_refused_and_switches_turn_sources_off(settings: Settings) -> None:
    gh, meteo = GitHub(), Meteo()
    app = _app(settings, gh, meteo, research_disabled_sources="nflverse_injuries,open_meteo")
    with TestClient(app, base_url="http://127.0.0.1") as c:
        bad = c.post(
            "/api/research/investigations",
            json={"ticker": f"KXNFL1HTEAMTOTAL-{KEY}-KC10", "side": "yes"},
            headers=H,
        )
        assert bad.status_code == 422 and "Half and quarter" in bad.json()["error"]["message"]
        r = run(c, WIN)
        src = c.get("/api/research/sources").json()
    assert not any("injuries" in p for p in gh.downloads())  # switched off: never fetched
    assert meteo.calls == []
    assert [s["id"] for s in r["sources"]] == ["K1", "F1"]
    gaps = r["summary"]["gaps"]
    assert any("injury report is switched off" in g for g in gaps)
    assert any("Weather not checked (weather lookup switched off)" in g for g in gaps)
    assert "Questionable" not in " ".join(f["text"] for f in every(r))
    row = next(x for x in src["sources"] if x["source_id"] == "nflverse_injuries")
    assert row["enabled"] is False


def test_schedule_switched_off_leaves_price_only(settings: Settings) -> None:
    gh, meteo = GitHub(), Meteo()
    app = _app(settings, gh, meteo, research_disabled_sources="nflverse_schedules")
    app.state.nflverse = None  # the route builds none either when the switch is off
    with TestClient(app, base_url="http://127.0.0.1") as c:
        r = run(c, WIN)
    assert gh.paths == [] and meteo.calls == []
    assert [s["id"] for s in r["sources"]] == ["K1"]
    assert any("switched off" in e for e in r["processing"]["errors"])
    assert r["summary"]["takeaway"].startswith("There's no season data")
    assert r["price_assessment"]["conservative_edge"] is None


def test_nflverse_adapter_allowlist_redirects_and_cache() -> None:
    gh = GitHub()
    src = nv.Nflverse(None, transport=httpx.MockTransport(gh.handler), now=lambda: NOW)
    d = src.season(2026)
    assert len(d.games) == 5 and len(d.weeks) == 8 and d.latest_injury_week() == 12
    assert d.data_as_of == datetime(2026, 11, 24, 5, 0, tzinfo=UTC)
    src.season(2026)
    assert len(gh.downloads()) == 3  # cached
    later = nv.Nflverse(
        None, transport=httpx.MockTransport(gh.handler), now=lambda: NOW + timedelta(hours=13)
    )
    later.season(2026)
    assert len(gh.downloads()) == 6  # cache expired
    assert nv.PATH.match(f"{nv.ROOT}schedules/games.csv")
    assert nv.PATH.match(f"{nv.ROOT}injuries/injuries_2026.csv")
    assert not nv.PATH.match(f"{nv.ROOT}pbp/play_by_play_2026.csv")
    assert not nv.PATH.match(f"{nv.ROOT}ftn_charting/ftn_charting_2026.csv")
    assert not nv.PATH.match(f"{nv.ROOT}depth_charts/depth_charts_2026.csv")
    evil = GitHub(redirect_host="evil.example.com")
    bad = nv.Nflverse(None, transport=httpx.MockTransport(evil.handler), now=lambda: NOW)
    with pytest.raises(AdapterError, match="redirected somewhere unexpected"):
        bad.season(2026)
    assert not any("evil" in p for p in evil.paths)  # the redirect was never followed
    # Optional files failing doesn't sink the schedule.
    partial = GitHub()
    del partial.files["injuries/injuries_2026.csv"]
    p = nv.Nflverse(None, transport=httpx.MockTransport(partial.handler), now=lambda: NOW)
    d2 = p.season(2026)
    assert d2.injuries == [] and any("injury report unavailable" in e for e in d2.errors)


def test_weather_lookups_are_limited_to_open_air_home_games() -> None:
    k = datetime(2026, 11, 27, 1, 20, tzinfo=UTC)
    assert wx.skip_reason("BUF00", "outdoors", "Home", k, NOW) is None
    assert wx.skip_reason("DET00", "dome", "Home", k, NOW) == "indoors"
    assert wx.skip_reason("DAL00", "", "Home", k, NOW).startswith("retractable")  # type: ignore[union-attr]
    assert wx.skip_reason("JAX00", "outdoors", "Neutral", k, NOW) == "neutral site"
    assert wx.skip_reason("BUF00", "outdoors", "Home", k + timedelta(days=9), NOW) == (
        "more than 7 days out"
    )
    assert wx.skip_reason("XXX00", "outdoors", "Home", k, NOW) == "stadium not in the app's table"
    m = Meteo()
    src = wx.OpenMeteo(None, transport=httpx.MockTransport(m.handler), now=lambda: NOW)
    f = src.kickoff("BUF00", k)
    assert (f.temp_f, f.wind_mph, f.precip_prob) == (34.2, 17.6, 85.0)
    src.kickoff("BUF00", k)
    assert len(m.calls) == 1  # cached for an hour
    with pytest.raises(AdapterError):
        src.kickoff("DET00", k)  # not an open-air stadium: refused before any request
    assert len(m.calls) == 1


# --- news + summary ------------------------------------------------------------------------


def test_nfl_news_queries_filter_other_sports_and_feed_the_qb_read(
    settings: Settings, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from app.api import investigate_routes

    h = S.Hypothesis(
        ticker=TOTAL,
        event_ticker=f"KXNFLTOTAL-{KEY}",
        side="yes",
        sport="football",
        league="NFL",
        market_type="total",
        threshold=45.5,
        subject=None,
        label="x",
        statement="x",
        snapshot_at=None,
        rules_url=None,
    )
    teams = [
        {"code": "KC", "name": "Kansas City Chiefs"},
        {"code": "BUF", "name": "Buffalo Bills"},
    ]
    qs = search.plan_queries(h, teams, 5)
    assert qs[0] == "Kansas City Chiefs Buffalo Bills NFL starting quarterback"
    assert qs[-1] == "Kansas City Chiefs Buffalo Bills NFL over under 45.5" and len(qs) == 4
    nyg = h.model_copy(update={"league": "NFL"})
    assert search.sport_mismatch(nyg, "Giants rally past Dodgers in the ninth")  # baseball
    assert search.sport_mismatch(nyg, "Panthers goalie stops 40 shots")  # hockey
    assert not search.sport_mismatch(nyg, "Giants quarterback sharp in win")
    assert search.line_match(h, "Chiefs-Bills total set at 48.5 points") == "different_line"
    brave = Brave(
        [
            art(
                "Mitchell Trubisky to start for Bills against Chiefs",
                "https://www.nfl.com/news/a",
                "Bills quarterback Mitchell Trubisky will start Thursday night.",
                age="2026-11-24T10:00:00",
            ),
            art(
                "Chiefs Royals rally in the ninth",
                "https://www.mlb.com/b",
                "Baseball.",
                age="2026-11-24T10:00:00",
            ),
        ]
    )
    monkeypatch.setattr(
        investigate_routes,
        "NewsSearch",
        lambda key, **kw: NewsSearch(key, transport=httpx.MockTransport(brave.handler), **kw),
    )
    with TestClient(
        _app(settings, GitHub(), Meteo(), brave_search_api_key="test-key"),
        base_url="http://127.0.0.1",
    ) as c:
        r = run(c, WIN)
        u = c.get("/api/research/usage").json()
    assert brave.calls == 4 and u["by_purpose"]["research"]["today"] == 4  # <= 5 per run
    assert brave.queries[0].endswith("NFL starting quarterback")
    news = [s for s in r["sources"] if s["id"].startswith("N")]
    assert [s["publisher"] for s in news] == ["NFL.com"]  # the MLB story was dropped
    q = r["summary"]["findings"][0]
    assert "Buffalo Bills: reports name different starters" in q["text"]
    assert "N1" in q["source_ids"]
    assert r["summary"]["coverage"] == (
        "2 factual datasets · 1 commentary link · QB reports conflict"
    )
    assert "Reports disagree on a starting quarterback" in r["summary"]["takeaway"]


def _football_result() -> S.Result:
    r = _hockey_result()
    qb = S.Finding(
        text="Starting quarterbacks — Buffalo Bills: Josh Allen listed (a projection). No "
        "official lineup source is connected, so neither is confirmed.",
        kind="factual",
        stance="neutral",
        source_ids=["M1"],
        verified=True,
    )
    r.hypothesis = r.hypothesis.model_copy(update={"sport": "football", "league": "NFL"})
    r.summary = r.summary.model_copy(
        update={
            "findings": [qb, r.summary.findings[1]],
            "gaps": ["Who starts at quarterback (no official lineup source is connected)."],
            "takeaway": "Deterministic football takeaway.",
        }
    )
    return r


def test_summary_never_calls_a_quarterback_confirmed() -> None:
    reply = {
        "claims": [
            {"source_id": "N1", "text": "Allen is confirmed to start.", "kind": "factual"},
            {"source_id": "N1", "text": "A headline reports Allen will start.", "kind": "factual"},
        ],
        "takeaway": "Allen is confirmed, so Buffalo looks good.",
        "findings": [
            {
                "text": "Buffalo's offense is strong.",
                "kind": "interpretation",
                "stance": "supports",
                "source_ids": ["M1"],
            },
        ],
        "gaps": ["QB confirmed?"],
        "stance": "supports",
    }
    out = synth.apply(_football_result(), {"N1": "Allen will start."}, fake(reply))
    texts = [c.text for c in out.details.supports + out.details.against]
    assert "A headline reports Allen will start." in texts
    assert not any("confirmed to start" in t for t in texts)
    assert out.summary.findings[0].text.startswith("Starting quarterbacks")  # pinned
    assert out.summary.takeaway == "Deterministic football takeaway."
    assert out.summary.gaps[0].startswith("Who starts at quarterback")
    assert "QB confirmed?" not in out.summary.gaps


# --- source registry -----------------------------------------------------------------------


def test_nfl_sources_are_registered_per_dataset() -> None:
    for sid, op in (
        ("nflverse_schedules", "download_schedule_release"),
        ("nflverse_team_stats", "download_team_stats_release"),
        ("nflverse_injuries", "download_injury_report_release"),
        ("open_meteo", "forecast_lookup_noncommercial"),
    ):
        assert sources.allows(sid, op), sid
        assert sources.SOURCES[sid].connector != "none"
    # One release's licence never covers another's operation.
    assert not sources.allows("nflverse_schedules", "download_injury_report_release")
    assert not sources.allows("nflverse_ftn", "download_schedule_release")
    assert sources.SOURCES["nflverse_ftn"].rights_status == "blocked_pending_review"
    assert "nflverse" not in sources.SOURCES  # no blanket entry
    assert "sportsbook" in sources.SOURCES["nflverse_schedules"].notes
    assert "football" not in sources.SOURCES["espn_site_api"].sport  # not used for NFL
