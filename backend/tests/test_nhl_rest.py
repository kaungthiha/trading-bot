"""NHL rest and lineup: MoneyPuck game logs (rest days, back-to-backs, last start in goal,
regulars who missed recent games), Kalshi's own listings for tomorrow, and injury mentions
from news. Point in time; mocked transports only."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.base import AdapterError
from app.catalog.store import CatalogWriter
from app.core.config import Settings
from app.db.session import make_engine, make_session_factory
from app.investigate import nhl, sources
from app.sportsdata import moneypuck as mp
from app.sportsdata.news import NewsSearch
from tests.test_nhl import NOW, TOTAL, WIN, MPServer, _app, _mk, run
from tests.test_research_search import Brave, art

GAME_DAY = date(2026, 11, 19)
G_HEAD = (
    "playerId,name,gameId,season,playerTeam,opposingTeam,home_or_away,gameDate,position,"
    "situation,icetime\n"
)
S_HEAD = G_HEAD


def _zip(text: str, name: str = "2026.csv", extra: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, text)
        if extra:
            z.writestr(extra, text)
    return buf.getvalue()


def _g(
    pid: str, name: str, gid: str, team: str, opp: str, day: str, secs: float, sit: str = "all"
) -> str:
    return f"{pid},{name},{gid},2026,{team},{opp},HOME,{day},G,{sit},{secs}"


def _s(pid: str, name: str, pos: str, gid: str, team: str, day: str, secs: float) -> str:
    return f"{pid},{name},{gid},2026,{team},XXX,HOME,{day},{pos},all,{secs}"


BOS_GAMES = [
    ("b10", "20261110", "Jeremy Swayman"),
    ("b12", "20261112", "Joonas Korpisalo"),
    ("b14", "20261114", "Jeremy Swayman"),
    ("b16", "20261116", "Joonas Korpisalo"),
    ("b18", "20261118", "Jeremy Swayman"),
]
NYR_GAMES = [("n11", "20261111"), ("n13", "20261113"), ("n15", "20261115")]
GOALIES = G_HEAD + "\n".join(
    [_g("1", who, gid, "BOS", "OPP", d, 3600) for gid, d, who in BOS_GAMES]
    # the backup's short relief appearance must not count as the start
    + [_g("2", "Joonas Korpisalo", "b18", "BOS", "OPP", "20261118", 300)]
    + [_g("3", "Igor Shesterkin", gid, "NYR", "OPP", d, 3600) for gid, d in NYR_GAMES]
    + [_g("3", "Igor Shesterkin", "n11", "NYR", "OPP", "20261111", 900, "5on5")]
    # after this game: never part of a pre-game view
    + [_g("1", "Jeremy Swayman", "b20", "BOS", "MTL", "20261120", 3600)]
)
SKATERS = (
    S_HEAD
    + "\n".join(
        [_s("p1", "David Pastrnak", "R", g, "BOS", d, 1200) for g, d, _ in BOS_GAMES[:4]]
        + [_s("p2", "Charlie McAvoy", "D", g, "BOS", d, 1500) for g, d, _ in BOS_GAMES]
        + [_s("p3", "Charlie Coyle", "C", g, "BOS", d, 1000) for g, d, _ in BOS_GAMES[:3]]
        # Zacha played three for Boston, then for the Rangers: moved, not absent.
        + [_s("p4", "Pavel Zacha", "C", g, "BOS", d, 1100) for g, d, _ in BOS_GAMES[:3]]
        + [_s("p4", "Pavel Zacha", "C", "n15", "NYR", "20261115", 900)]
        + [_s("p5", "Artemi Panarin", "L", g, "NYR", d, 1250) for g, d in NYR_GAMES]
        + [_s("p1", "David Pastrnak", "R", "b20", "BOS", "20261120", 1200)]
    )
)
LOGS = {"goalies": _zip(GOALIES), "skaters": _zip(SKATERS)}


def _logs() -> mp.GameLogs:
    logs = mp.GameLogs(season=2026, games=mp.parse_goalie_log(LOGS["goalies"]))
    mp.parse_skater_log(LOGS["skaters"], logs)
    return logs


def test_rest_and_last_start_are_point_in_time() -> None:
    logs = _logs()
    bos = logs.rest("BOS", GAME_DAY)
    assert bos.last_game == date(2026, 11, 18) and bos.days_off == 0
    assert bos.starter_last_night and bos.last_starter == "Jeremy Swayman"  # not the reliever
    assert bos.games_last_4_nights == 3  # Nov 16, 18 and tonight
    assert bos.recent_starts == [("Jeremy Swayman", 3), ("Joonas Korpisalo", 2)]
    nyr = logs.rest("NYR", GAME_DAY)
    assert nyr.days_off == 3 and not nyr.starter_last_night and nyr.games_last_4_nights == 1
    # Kalshi codes map to MoneyPuck's (LA -> LAK); an unknown team has no history.
    assert logs.rest("LA", GAME_DAY).days_off is None
    assert len(logs.prior("BOS", GAME_DAY)) == 5  # the Nov 20 game is excluded


def test_absences_skip_moved_players_and_need_regulars() -> None:
    logs = _logs()
    gone = logs.absences("BOS", GAME_DAY)
    assert [(a.name, a.missed) for a in gone] == [("David Pastrnak", 1), ("Charlie Coyle", 2)]
    assert gone[0].position == "R" and gone[0].toi_per_game == 1200 and gone[0].games == 4
    assert logs.absences("NYR", GAME_DAY) == []  # everyone played; Zacha isn't a Ranger regular
    assert "Igor Shesterkin" in logs.roster("NYR", GAME_DAY)
    assert logs.roster("BOS", GAME_DAY)[0] == "Jeremy Swayman"  # most ice time
    # A day earlier, Pastrnak hadn't missed anything yet.
    assert [a.name for a in logs.absences("BOS", date(2026, 11, 18))] == ["Charlie Coyle"]


def test_injury_mentions_from_news() -> None:
    from tests.test_nhl import _news

    roster = {"BOS": ["David Pastrnak", "Charlie McAvoy"], "NYR": ["Artemi Panarin"]}
    news = _news(
        ("Bruins' Pastrnak (upper-body) out vs. Rangers", "", None),
        ("McAvoy scores twice in win", "", None),  # mentioned, no injury wording
        ("Panarin day-to-day after blocking a shot", "", "N1"),  # a copy: ignored
    )
    out = nhl.injury_reports(roster, news)
    assert out == {"BOS": [("David Pastrnak", ["N1"])]}
    assert nhl.injury_reports(roster, None) == {}


def _with_tomorrow(app: Any) -> None:
    key = "26NOV20BOSMTL"
    page = [
        {
            "event_ticker": f"KXNHLGAME-{key}",
            "series_ticker": "KXNHLGAME",
            "category": "Sports",
            "title": "Boston vs Montreal",
            "sub_title": "BOS vs MTL",
            "mutually_exclusive": True,
            "markets": [
                _mk(f"KXNHLGAME-{key}-BOS", "Boston wins", "0.5", "0.52", sub="Boston"),
                _mk(f"KXNHLGAME-{key}-MTL", "Montreal wins", "0.48", "0.5", sub="Montreal"),
            ],
        }
    ]
    engine = make_engine(app.state.settings.database_url)
    CatalogWriter(make_session_factory(engine), NOW).write_page(page)
    engine.dispose()


def test_end_to_end_rest_and_lineup_finding(settings: Settings) -> None:
    server = MPServer(logs=LOGS)
    app = _app(settings, server)
    _with_tomorrow(app)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        r = run(c, WIN)
        t = run(c, TOTAL)
    assert sorted(server.log_paths) == [
        "/moneypuck/downloads/seasonPlayersSummary/goalies/2026.zip",
        "/moneypuck/downloads/seasonPlayersSummary/skaters/2026.zip",
    ]  # once each, cached for both investigations
    ids = [s["id"] for s in r["sources"]]
    assert ids == ["K1", "M1", "M2"] and mp.ATTRIBUTION in r["sources"][2]["title"]
    sm = r["summary"]
    goalie = sm["findings"][0]["text"]
    assert "Boston Bruins: unknown" in goalie and "[last start: Swayman, last night]" in goalie
    assert "[last start: Shesterkin]" in goalie and "neither is confirmed" in goalie
    lineup = sm["findings"][2]
    assert lineup["text"].startswith(
        "Rest and lineup — Boston Bruins: back-to-back (played last "
        "night), game 3 in 4 nights, plays again tomorrow"
    )
    assert (
        "missed recent games: Pastrnak (R, 20:00 a game, last 1), Coyle (C, 16:40 a game, "
        "last 2)" in lineup["text"]
    )
    assert "Zacha" not in lineup["text"]  # moved to the Rangers, not absent
    assert "New York Rangers: 3 days off; no regular missed the last game" in lineup["text"]
    assert "reason not given" in lineup["text"] and lineup["source_ids"] == ["M2"]
    assert sm["coverage"] == "2 factual datasets · 0 commentary links · goalie status unknown"
    assert not any("Rest, travel and injuries aren't checked" in g for g in sm["gaps"])
    assert any("no official injury report" in g for g in sm["gaps"])
    assert any(
        m.startswith("Rest and lineup: MoneyPuck game logs") for m in r["details"]["methodology"]
    )
    assert t["summary"]["findings"][2]["text"].startswith("Rest and lineup")


def test_news_injury_report_joins_the_lineup_finding(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import investigate_routes

    brave = Brave(
        [
            art(
                "NHL: Bruins' McAvoy (lower-body) ruled out vs. Rangers",
                "https://www.nhl.com/bruins/news/a",
                "Boston defenceman McAvoy is out.",
            )
        ]
    )
    monkeypatch.setattr(
        investigate_routes,
        "NewsSearch",
        lambda key, **kw: NewsSearch(key, transport=httpx.MockTransport(brave.handler), **kw),
    )
    with TestClient(
        _app(settings, MPServer(logs=LOGS), brave_search_api_key="test-key"),
        base_url="http://127.0.0.1",
    ) as c:
        r = run(c, WIN)
    lineup = r["summary"]["findings"][2]
    assert "news reports an injury: McAvoy (N1)" in lineup["text"]
    assert lineup["source_ids"] == ["M2", "N1"]


def test_missing_logs_degrade_honestly(settings: Settings) -> None:
    only_goalies = MPServer(logs={"goalies": LOGS["goalies"]})
    with TestClient(_app(settings, only_goalies), base_url="http://127.0.0.1") as c:
        r = run(c, WIN)
    lineup = r["summary"]["findings"][2]["text"]
    assert "back-to-back" in lineup and "lineups not checked" in lineup
    assert any("skater game log unavailable" in e for e in r["processing"]["errors"])
    none = MPServer()  # no logs at all (404)
    with TestClient(_app(settings, none), base_url="http://127.0.0.1") as c:
        r2 = run(c, TOTAL)  # a different market: WIN's result is cached from the first app
    assert [s["id"] for s in r2["sources"]] == ["K1", "M1"]
    assert any("game logs unavailable" in e for e in r2["processing"]["errors"])
    assert any("Rest, travel and injuries aren't checked" in g for g in r2["summary"]["gaps"])
    assert not any(f["text"].startswith("Rest and lineup") for f in r2["summary"]["findings"])


def test_goalie_line_keeps_the_disclaimer_when_long(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import investigate_routes

    brave = Brave(
        [
            art(
                "NHL: Swayman will start for Bruins; Shesterkin gets the nod for Rangers",
                "https://www.dailyfaceoff.com/a",
                "Both starting goalies named.",
            )
        ]
    )
    monkeypatch.setattr(
        investigate_routes,
        "NewsSearch",
        lambda key, **kw: NewsSearch(key, transport=httpx.MockTransport(brave.handler), **kw),
    )
    with TestClient(
        _app(settings, MPServer(logs=LOGS), brave_search_api_key="test-key"),
        base_url="http://127.0.0.1",
    ) as c:
        r = run(c, WIN)
    g = r["summary"]["findings"][0]["text"]
    assert "Jeremy Swayman reported as the starter" in g and "Igor Shesterkin reported" in g
    assert "[last start: Swayman, last night]" in g
    assert len(g) <= 400
    assert g.endswith("No official lineup source is connected, so neither is confirmed.")


def test_log_adapter_allowlist_zip_safety_and_cache() -> None:
    server = MPServer(logs=LOGS)
    src = mp.MoneyPuck(None, transport=httpx.MockTransport(server.handler), now=lambda: NOW)
    a = src.game_logs(2026)
    b = src.game_logs(2026)
    assert a is b and len(server.log_paths) == 2  # cached 12 h
    assert mp.LOG.match(mp.LOG_URL.format(kind="skaters", season=2026))
    assert not mp.LOG.match("https://peter-tanner.com/moneypuck/downloads/shots_2026.zip")
    assert not mp.LOG.match(
        "https://evil.example/moneypuck/downloads/seasonPlayersSummary/goalies/2026.zip"
    )
    with pytest.raises(AdapterError, match="isn't a zip"):
        mp.parse_goalie_log(b"not a zip")
    with pytest.raises(AdapterError, match="unexpected layout"):
        mp.parse_goalie_log(_zip(GOALIES, extra="second.csv"))
    with pytest.raises(AdapterError, match="unexpectedly large"):
        mp.parse_goalie_log(b"x" * (mp.MAX_ZIP + 1))
    assert sources.allows("moneypuck", "download_listed_game_logs")
    assert not sources.allows("moneypuck", "download_shot_data")
    off = Settings(_env_file=None, research_disabled_sources="moneypuck")
    with pytest.raises(AdapterError, match="switched off"):
        mp.MoneyPuck(off, transport=httpx.MockTransport(server.handler)).game_logs(2026)
