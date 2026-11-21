"""Games page: grouping one game's markets, leg specs, ESPN evidence and its statistics."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal as D
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.catalog import games
from app.catalog.store import CatalogWriter
from app.core.clock import FrozenClock
from app.core.config import Settings
from app.db.session import make_engine, make_session_factory
from app.main import create_app
from app.sportsdata.espn import EspnSource, GameRow, parse_gamelog, parse_schedule
from app.sportsdata.evidence import (
    adjusted_probability,
    joint,
    leg_summary,
    predicate,
    wilson,
)
from app.sportsdata.news import NewsSearch

NOW = datetime(2026, 11, 19, 15, 0, tzinfo=UTC)
KEY = "26NOV19NYKMIN"
NYK_TEAM, MIN_TEAM, KAT = "team-nyk", "team-min", "player-kat"


def _mk(ticker: str, title: str, bid: str, ask: str, strike: float | None = None,
        custom: dict[str, str] | None = None, sub: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ticker": ticker, "title": title, "yes_sub_title": sub or title, "status": "active",
        "yes_bid_dollars": bid, "yes_ask_dollars": ask, "no_bid_dollars": str(1 - D(ask)),
        "no_ask_dollars": str(1 - D(bid)), "yes_bid_size_fp": "50", "yes_ask_size_fp": "80",
        "volume_24h_fp": "100", "volume_fp": "100", "open_interest_fp": "10",
        "close_time": "2026-11-22T01:00:00Z", "occurrence_datetime": "2026-11-20T00:30:00Z"}
    if strike is not None:
        out.update({"strike_type": "greater", "floor_strike": strike})
    if custom:
        out["custom_strike"] = custom
    return out


def _ev(series: str, title: str, markets: list[dict[str, Any]], me: bool = False) -> dict[str, Any]:
    return {"event_ticker": f"{series}-{KEY}", "series_ticker": series, "category": "Sports",
            "title": title, "sub_title": "NYK vs MIN (Nov 19)", "mutually_exclusive": me,
            "markets": markets}


def _reb(series: str) -> list[dict[str, Any]]:
    return [_mk(f"{series}-{KEY}-NYKKTOWNS32-{n}", f"Karl-Anthony Towns: {n}+ rebounds", b, a,
                strike=n - 0.5, custom={"basketball_player": KAT, "basketball_team": NYK_TEAM},
                sub=f"Karl-Anthony Towns: {n}+")
            for n, b, a in [(8, "0.89", "0.93"), (10, "0.80", "0.82"), (12, "0.61", "0.66"),
                            (14, "0.43", "0.44")]]


PAGE = [
    _ev("KXNBAGAME", "New York vs Minnesota", [
        _mk(f"KXNBAGAME-{KEY}-NYK", "New York wins", "0.50", "0.51", sub="New York"),
        _mk(f"KXNBAGAME-{KEY}-MIN", "Minnesota wins", "0.49", "0.50", sub="Minnesota")], me=True),
    _ev("KXNBASPREAD", "New York vs Minnesota: Spread", [
        _mk(f"KXNBASPREAD-{KEY}-{t}{k + 1}", f"{name} wins by over {k + 0.5} points", b, a,
            strike=k + 0.5, custom={"basketball_team": team})
        for t, name, team in [("NYK", "New York", NYK_TEAM), ("MIN", "Minnesota", MIN_TEAM)]
        for k, b, a in [(2, "0.40", "0.42"), (6, "0.28", "0.30"), (10, "0.15", "0.17")]]),
    _ev("KXNBATOTAL", "New York vs Minnesota: Total Points", [
        _mk(f"KXNBATOTAL-{KEY}-{k + 1}", f"Full Game: Over {k + 0.5} points scored", b, a,
            strike=k + 0.5) for k, b, a in
        [(205, "0.80", "0.82"), (210, "0.65", "0.67"), (215, "0.49", "0.51"),
         (220, "0.33", "0.35")]]),
    _ev("KXNBAREB", "New York vs Minnesota: Rebounds", _reb("KXNBAREB")),
    _ev("KXNBAREBPROT", "New York vs Minnesota: Rebounds", _reb("KXNBAREBPROT")),
    _ev("KXNBA1Q", "New York vs Minnesota: 1st Quarter Winner", [
        _mk(f"KXNBA1Q-{KEY}-NYK", "New York wins the 1st quarter", "0.45", "0.47", sub="New York"),
        _mk(f"KXNBA1Q-{KEY}-TIE", "1st quarter tie", "0.05", "0.07", sub="Tie")], me=True),
]


# --- ESPN fixtures ----------------------------------------------------------------------------

LABELS = ["MIN", "FG", "FG%", "3PT", "3P%", "FT", "FT%", "REB", "AST", "BLK", "STL", "PF", "TO",
          "PTS"]


def _gamelog(games_: list[tuple[str, str, str, int, int, int, int]], season: str) -> dict:
    """games: (event id, date, '@'|'vs', team score, opp score, rebounds, points)."""
    events, rows = {}, []
    for eid, date, at, ts, os_, reb, pts in games_:
        away = at == "@"
        events[eid] = {"id": eid, "atVs": at, "gameDate": f"{date}T00:30:00.000+00:00",
                       "homeTeamScore": str(os_ if away else ts),
                       "awayTeamScore": str(ts if away else os_),
                       "gameResult": "W" if ts > os_ else "L",
                       "opponent": {"abbreviation": "TOR"}}
        rows.append({"eventId": eid, "stats": ["34", "7-9", "77.8", "2-4", "50", "1-1", "100",
                                               str(reb), "3", "1", "1", "2", "2", str(pts)]})
    return {"labels": LABELS, "events": events,
            "filters": [{"name": "season", "value": season}],
            "seasonTypes": [{"displayName": "Regular Season",
                             "categories": [{"events": rows}]},
                            {"displayName": "Preseason", "categories": [{"events": [
                                {"eventId": "pre1", "stats": ["10"] * 14}]}]}]}


# 12 current-season games, 12 last-season: KAT rebounds, and whether NYK won.
CUR = [(f"c{i}", f"2026-11-{i + 1:02d}", "@" if i % 2 else "vs", 110 + (i % 3) * 5,
        105 if i % 4 else 125, 13 if i % 3 else 9, 22) for i in range(12)]
PREV = [(f"p{i}", f"2026-03-{i + 1:02d}", "vs", 100 + i, 104, 12 if i % 2 else 10, 20)
        for i in range(12)]


def _schedule(gs: list[tuple[str, str, str, int, int, int, int]], tid: str = "18") -> dict:
    evs = []
    for eid, date, at, ts, os_, *_ in gs:
        me = {"homeAway": "away" if at == "@" else "home",
              "team": {"id": tid, "abbreviation": "NY"},
              "score": {"value": float(ts)}, "winner": ts > os_}
        opp = {"homeAway": "home" if at == "@" else "away",
               "team": {"id": "28", "abbreviation": "TOR"},
               "score": {"value": float(os_)}, "winner": os_ > ts}
        evs.append({"id": eid, "date": f"{date}T00:30Z", "competitions": [
            {"status": {"type": {"completed": True}}, "competitors": [me, opp]}]})
    evs.append({"id": "future", "date": "2026-12-01T00:30Z", "competitions": [
        {"status": {"type": {"completed": False}}, "competitors": []}]})
    return {"events": evs, "requestedSeason": {"year": 2027}}


def espn_handler(seen: list[str]):  # type: ignore[no-untyped-def]
    def handle(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.host + req.url.path)
        p, season = req.url.path, req.url.params.get("season")
        if p == "/apis/common/v3/search":
            return httpx.Response(200, json={"items": [
                {"id": "3136195", "league": "nba", "displayName": "Karl-Anthony Towns"}]})
        if p.endswith("/athletes/3136195/gamelog"):
            return httpx.Response(200, json=_gamelog(PREV if season else CUR,
                                                     "2026" if season else "2027"))
        if p.endswith("/nba/teams"):
            return httpx.Response(200, json={"sports": [{"leagues": [{"teams": [
                {"team": {"id": "18", "abbreviation": "NY", "location": "New York",
                          "displayName": "New York Knicks"}},
                {"team": {"id": "16", "abbreviation": "MIN", "location": "Minnesota",
                          "displayName": "Minnesota Timberwolves"}}]}]}]})
        if p.endswith("/teams/18/schedule"):
            return httpx.Response(200, json=_schedule(PREV if season else CUR))
        if p.endswith("/nba/injuries"):
            return httpx.Response(200, json={"injuries": [{"id": "16", "displayName":
                "Minnesota Timberwolves", "injuries": [{"status": "Day-To-Day",
                "shortComment": "Questionable (shoulder)", "date": "2026-11-18T10:00Z",
                "athlete": {"displayName": "Jonathan Kuminga"}}]}]})
        return httpx.Response(404)
    return handle


# --- fixtures ---------------------------------------------------------------------------------


@pytest.fixture
def gset(settings: Settings) -> Settings:
    # Provider "openai" with no key: tests never talk to a real local Ollama.
    return Settings(_env_file=None, database_url=settings.database_url, llm_provider="openai")


@pytest.fixture
def factory(gset: Settings):  # type: ignore[no-untyped-def]
    engine = make_engine(gset.database_url)
    f = make_session_factory(engine)
    CatalogWriter(f, NOW).write_page(PAGE)
    yield f
    engine.dispose()


@pytest.fixture
def api(gset: Settings, factory):  # type: ignore[no-untyped-def]
    seen: list[str] = []
    app = create_app(gset, FrozenClock(NOW))
    app.state.espn = EspnSource(transport=httpx.MockTransport(espn_handler(seen)),
                                min_interval=0.0, sleep=lambda _: None)
    app.state.espn_seen = seen
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


# --- grouping ---------------------------------------------------------------------------------


def test_game_list_groups_every_event_of_a_game(factory) -> None:  # type: ignore[no-untyped-def]
    with factory() as s:
        out = games.list_games(s, "NBA")
    (g,) = out["items"]
    assert g["game_key"] == KEY and g["events"] == 6
    assert [t["code"] for t in g["teams"]] == ["NYK", "MIN"]  # away team first
    assert out["leagues"] == [{"league": "NBA", "games": 1}]


def test_game_detail_sections_players_and_medians(factory) -> None:  # type: ignore[no-untyped-def]
    with factory() as s:
        g = games.game_detail(s, "KXNBA", KEY)
    assert g is not None
    main = {x["label"]: x for x in g["sections"][0]["groups"]}
    assert list(main) == ["Winner", "Spread", "Total points"]
    spread = main["Spread"]
    assert [c["label"] for c in spread["markets"]] == [
        "NYK by 11+", "NYK by 7+", "NYK by 3+", "MIN by 3+", "MIN by 7+", "MIN by 11+"]
    assert spread["median_label"] is not None
    assert main["Total points"]["median_label"].startswith("≈ 21")
    periods = g["sections"][1]
    assert periods["label"] == "Halves & quarters" and periods["groups"][0]["label"] == "Q1 winner"
    (kat,) = g["players"]
    assert kat["name"] == "Karl-Anthony Towns" and kat["team"] == "NYK"
    reb = kat["stats"]["REB"]
    assert [c["label"] for c in reb["markets"]] == ["8+", "10+", "12+", "14+"]
    assert 12 < reb["median"] < 14
    assert reb["event_ticker"] == f"KXNBAREB-{KEY}"  # protected variant hidden by default
    assert g["protected_available"] is True
    with factory() as s:
        prot = games.game_detail(s, "KXNBA", KEY, protected=True)
    assert prot["players"][0]["stats"]["REB"]["event_ticker"] == f"KXNBAREBPROT-{KEY}"


def test_game_detail_rejects_bad_keys(factory) -> None:  # type: ignore[no-untyped-def]
    with factory() as s:
        assert games.game_detail(s, "KXNBA", "x%") is None
        assert games.game_detail(s, "nba", KEY) is None
        assert games.game_detail(s, "KXNBA", "26NOV19AAABBB") is None


def test_leg_specs_describe_what_must_happen(factory) -> None:  # type: ignore[no-untyped-def]
    with factory() as s:
        specs = games.market_specs(s, [f"KXNBAREB-{KEY}-NYKKTOWNS32-12", f"KXNBAGAME-{KEY}-MIN",
                                       f"KXNBASPREAD-{KEY}-NYK7", f"KXNBATOTAL-{KEY}-216",
                                       f"KXNBA1Q-{KEY}-NYK"])
    assert specs[f"KXNBAREB-{KEY}-NYKKTOWNS32-12"]["spec"] == {
        "kind": "player_stat", "player": "Karl-Anthony Towns", "team": "NYK", "stat": "REB",
        "at_least": 12}
    assert specs[f"KXNBAGAME-{KEY}-MIN"]["spec"] == {"kind": "team_win", "team": "MIN"}
    assert specs[f"KXNBASPREAD-{KEY}-NYK7"]["spec"] == {"kind": "team_margin", "team": "NYK",
                                                        "over": 6.5}
    assert specs[f"KXNBATOTAL-{KEY}-216"]["spec"] == {"kind": "game_total", "over": 215.5}
    assert specs[f"KXNBA1Q-{KEY}-NYK"]["spec"] is None  # periods: no box-score check yet


# --- parsing & statistics ---------------------------------------------------------------------


def test_parse_gamelog_skips_preseason_and_derives_combos() -> None:
    rows = parse_gamelog(_gamelog(CUR[:3], "2027"), "current")
    assert [r.event_id for r in rows] == ["c2", "c1", "c0"]  # newest first, no preseason
    r = rows[1]  # c1: away game
    assert r.home is False and r.team_score == 115 and r.opp_score == 105 and r.won is True
    assert r.stats["3PT"] == 2 and r.stats["PRA"] == r.stats["PTS"] + r.stats["REB"] + 3
    assert r.stats["2D"] == 1.0  # 22 pts + 13 reb


def test_parse_schedule_keeps_completed_games_only() -> None:
    rows = parse_schedule(_schedule(CUR[:2]), "18", "current")
    assert [r.event_id for r in rows] == ["c1", "c0"]
    assert rows[0].team_score == 115 and rows[0].won is True and rows[0].home is False


def test_wilson_interval_brackets_the_rate() -> None:
    lo, hi = wilson(0.6, 20)
    assert lo < 0.6 < hi and hi - lo < 0.35
    assert wilson(0.5, 0) == (0.0, 1.0)


def _rows(vals: list[float], season: str = "current") -> list[GameRow]:
    return [GameRow(f"{season}{i}", f"2026-11-{30 - i:02d}", season, "TOR", True, v > 10, 110,
                    100, {"REB": v}) for i, v in enumerate(vals)]


def test_leg_summary_windows_estimate_and_verdict() -> None:
    spec = {"kind": "player_stat", "player": "X", "team": "NYK", "stat": "REB", "at_least": 12}
    pred, value = predicate(spec, "yes")
    rows = _rows([14, 13, 9, 15, 12, 11, 16, 13, 12, 10]) + _rows([12, 8] * 10, "previous")
    out = leg_summary(rows, pred, value, market=0.30)
    assert out["windows"]["last5"] == [4, 5] and out["windows"]["season"] == [7, 10]
    assert out["windows"]["last_season"] == [10, 20]
    assert out["interval"][0] < out["estimate"] < out["interval"][1]
    assert out["verdict"] == "market_lower"  # history says likelier than 30%
    assert out["recent"][0] == {"date": "2026-11-30", "opponent": "TOR", "home": True,
                                "value": 14, "hit": True}
    no_pred, _ = predicate(spec, "no")
    assert leg_summary(rows, no_pred, value, market=0.70)["verdict"] == "market_higher"
    assert leg_summary(rows[:3], pred, value, market=0.5)["verdict"] == "thin"


def test_joint_counts_games_where_legs_landed_together() -> None:
    a = _rows([12, 12, 12, 12, 0, 0, 0, 0, 12, 0] * 2)
    b = _rows([12, 12, 12, 12, 0, 0, 0, 0, 0, 12] * 2)
    spec = {"kind": "player_stat", "player": "X", "team": "NYK", "stat": "REB", "at_least": 12}
    p, _ = predicate(spec, "yes")
    j = joint({"A": {r.event_id: r for r in a}, "B": {r.event_id: r for r in b}}, {"A": p, "B": p})
    assert j["games"] == 20 and j["together"] == 8 and j["expected"] == 5.0
    assert 1 < j["lift"] < 1.6  # positively correlated, shrunk toward 1
    # a game seen from opposite benches (different opponents) is not a shared game
    b2 = {r.event_id: GameRow(r.event_id, r.date, r.season, "BOS", r.home, r.won, r.team_score,
                              r.opp_score, r.stats) for r in b}
    assert joint({"A": {r.event_id: r for r in a}, "B": b2}, {"A": p, "B": p})["games"] == 0


def test_adjusted_probability_applies_lift_and_caps_at_weakest_leg() -> None:
    corr = [{"lift": 1.5}]
    assert adjusted_probability(0.2, corr, {"a": 0.5, "b": 0.4}) == 0.3
    assert adjusted_probability(0.3, [{"lift": 2.0}], {"a": 0.5, "b": 0.4}) == 0.4
    assert adjusted_probability(None, corr, {}) is None


# --- API --------------------------------------------------------------------------------------


def test_api_games_list_detail_and_404(api: TestClient) -> None:
    items = api.get("/api/games", params={"league": "NBA"}).json()["items"]
    assert [g["game_key"] for g in items] == [KEY]
    g = api.get(f"/api/games/KXNBA/{KEY}").json()
    assert g["evidence_supported"] is True and g["players"][0]["name"] == "Karl-Anthony Towns"
    assert api.get("/api/games/KXNBA/26NOV19AAABBB").status_code == 404
    assert api.get("/api/games/KXNBA/bad%20key").status_code == 422


def test_api_hides_games_that_already_finished(gset: Settings, factory) -> None:  # type: ignore[no-untyped-def]
    later = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
    with TestClient(create_app(gset, FrozenClock(later)), base_url="http://127.0.0.1") as c:
        assert c.get("/api/games").json()["items"] == []
        assert len(c.get("/api/games", params={"include_past": True}).json()["items"]) == 1


def test_api_evidence_per_leg_and_correlation(api: TestClient) -> None:
    legs = f"KXNBAREB-{KEY}-NYKKTOWNS32-12:yes,KXNBAGAME-{KEY}-NYK:yes,KXNBA1Q-{KEY}-NYK:yes"
    out = api.get("/api/games/evidence", params={"legs": legs}).json()
    reb, win, q1 = out["legs"]
    assert reb["supported"] and reb["subject"]["name"] == "Karl-Anthony Towns"
    assert reb["windows"]["season"] == [8, 12] and reb["windows"]["last_season"] == [6, 12]
    assert reb["line"] == 11.5 and len(reb["recent"]) == 10
    assert reb["subject"]["espn_url"] == "https://www.espn.com/nba/player/_/id/3136195"
    assert win["supported"] and win["subject"]["name"] == "New York Knicks"
    assert q1["supported"] is False and "No box-score check" in q1["reason"]
    (c,) = out["correlation"]
    assert c["team"] == "NYK" and c["games"] == 24 and sorted(c["legs"]) == sorted(
        [f"KXNBAREB-{KEY}-NYKKTOWNS32-12", f"KXNBAGAME-{KEY}-NYK"])
    assert out["independent_probability"] is not None
    assert out["adjusted_probability"] is not None
    # second call is served from cache
    seen = api.app.state.espn_seen  # type: ignore[attr-defined]
    n = len(seen)
    api.get("/api/games/evidence", params={"legs": legs})
    assert len(seen) == n


def test_api_evidence_validates_legs(api: TestClient) -> None:
    assert api.get("/api/games/evidence", params={"legs": "bad leg:yes"}).status_code == 422
    assert api.get("/api/games/evidence", params={"legs": "KXNOPE-1:yes"}).status_code == 404
    many = ",".join([f"KXNBAGAME-{KEY}-NYK:yes"] * 13)
    assert api.get("/api/games/evidence", params={"legs": many}).status_code == 422


def test_api_evidence_can_be_switched_off(gset: Settings, factory) -> None:  # type: ignore[no-untyped-def]
    off = gset.model_copy(update={"sports_evidence_enabled": False})
    with TestClient(create_app(off, FrozenClock(NOW)), base_url="http://127.0.0.1") as c:
        r = c.get("/api/games/evidence", params={"legs": f"KXNBAGAME-{KEY}-NYK:yes"})
        assert r.status_code == 409


def test_api_injuries_by_team(api: TestClient) -> None:
    out = api.get(f"/api/games/KXNBA/{KEY}/injuries").json()
    assert out["supported"] is True
    by = {t["code"]: t for t in out["teams"]}
    assert by["NYK"]["items"] == []
    assert by["MIN"]["items"][0]["player"] == "Jonathan Kuminga"


def test_api_news_is_off_without_a_key(api: TestClient) -> None:
    assert api.post("/api/games/news", json={"q": "Towns injury"},
                    headers={"X-KRT-Request": "research"}).json() == {
        "configured": False, "items": []}


# --- security ---------------------------------------------------------------------------------


def test_espn_client_refuses_paths_outside_the_allowlist() -> None:
    src = EspnSource(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
                     min_interval=0.0, sleep=lambda _: None)
    with pytest.raises(ValueError):
        src._web.get("/apis/common/v3/sports/basketball/nba/athletes/1/../../secret")
    with pytest.raises(ValueError):
        src._site.get("/apis/site/v2/sports/football/nfl/injuries")


def test_news_key_goes_in_a_header_and_results_are_sanitized() -> None:
    seen: list[httpx.Request] = []

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"results": [
            {"title": "Towns questionable", "url": "https://example.com/a",
             "description": "<b>Knee</b> soreness", "meta_url": {"hostname": "example.com"}},
            {"title": "bad", "url": "javascript:alert(1)"}]})

    n = NewsSearch("secret-key-123", transport=httpx.MockTransport(handle))
    items = n.search("Towns injury")
    assert [i["title"] for i in items] == ["Towns questionable"]
    assert items[0]["description"] == "Knee soreness"
    assert seen[0].headers["X-Subscription-Token"] == "secret-key-123"
    assert "secret-key-123" not in str(seen[0].url)


def test_brave_key_is_secret_and_blank_means_unset() -> None:
    s = Settings(_env_file=None, brave_search_api_key="abc123")
    assert "abc123" not in repr(s)
    assert Settings(_env_file=None, brave_search_api_key="  ").brave_search_api_key is None


def test_game_routes_respect_the_paper_safety_words() -> None:
    from app.api.games_routes import router

    for r in router.routes:
        path = getattr(r, "path", "")
        assert not any(w in path for w in ("portfolio", "exchange", "live", "execute"))


# --- AI second opinion ------------------------------------------------------------------------

from pydantic import SecretStr  # noqa: E402

from app.sportsdata import llm  # noqa: E402


def test_parse_review_trims_and_drops_unknowns() -> None:
    text = ('{"summary": "ok", "overall": "yolo", "legs": [{"ticker": "A", "lean": "supports",'
            ' "points": ["p1", "p2", "p3", "p4"], "sources": ["S1", "S9"]},'
            ' {"ticker": "ZZZ", "lean": "against"}], "risks": ["r"], "check_before_betting": 5}')
    out = llm.parse_review(text, ["A", "B"], {"S1"})
    assert out["overall"] == "stretch"  # unknown value -> neutral default
    assert out["legs"][0] == {"ticker": "A", "lean": "supports", "points": ["p1", "p2", "p3"],
                              "sources": ["S1"]}
    assert out["legs"][1]["lean"] == "unclear"  # B missing from reply; ZZZ dropped
    assert out["check_before_betting"] == []
    with pytest.raises(llm.LlmError):
        llm.parse_review("not json", ["A"], set())


def test_reviewer_sends_key_in_header_and_maps_errors() -> None:
    seen: list[httpx.Request] = []

    def ok(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"model": "m", "usage": {"prompt_tokens": 5},
                                         "choices": [{"message": {"content": '{"summary": "s"}'}}]})

    r = llm.ThesisReviewer("sk-secret", "m", transport=httpx.MockTransport(ok))
    out = r.review({"legs": []}, ["A"], set())
    assert out["summary"] == "s" and out["legs"][0]["lean"] == "unclear"
    req = seen[0]
    assert req.method == "POST" and str(req.url) == "https://api.openai.com/v1/chat/completions"
    assert req.headers["Authorization"] == "Bearer sk-secret"
    assert "sk-secret" not in str(req.url) and b"sk-secret" not in req.content
    body = req.read().decode()
    assert "untrusted" in body and "json_object" in body
    bad = llm.ThesisReviewer("k", "m", transport=httpx.MockTransport(
        lambda _: httpx.Response(401, json={})))
    with pytest.raises(llm.LlmError, match="rejected the API key"):
        bad.review({}, [], set())


class FakeReviewer:
    calls: list[dict[str, Any]] = []

    def __init__(self, key: str, model: str) -> None:
        self.key = key

    def review(self, facts: dict[str, Any], tickers: list[str], sources: set[str]) -> dict:
        FakeReviewer.calls.append(facts)
        return {"summary": "fine", "overall": "reasonable",
                "legs": [{"ticker": t, "lean": "supports", "points": [], "sources": []}
                         for t in tickers], "risks": [], "check_before_betting": []}

    def close(self) -> None:
        pass


@pytest.fixture
def rapi(gset: Settings, factory, monkeypatch):  # type: ignore[no-untyped-def]
    import app.api.games_routes as gr

    FakeReviewer.calls = []
    monkeypatch.setattr(gr, "make_reviewer", lambda settings: FakeReviewer("k", "m"))
    s = gset.model_copy(update={"openai_api_key": SecretStr("sk-test"),
                                "llm_max_reviews_per_day": 2})
    app = create_app(s, FrozenClock(NOW))
    app.state.espn = EspnSource(transport=httpx.MockTransport(espn_handler([])),
                                min_interval=0.0, sleep=lambda _: None)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


H = {"X-KRT-Request": "review"}
LEG = {"ticker": f"KXNBAREB-{KEY}-NYKKTOWNS32-12", "side": "yes"}


def test_review_requires_key_and_csrf_header(api: TestClient, rapi: TestClient) -> None:
    assert api.get("/api/games/review/status").json()["configured"] is False
    assert api.post("/api/games/review", json={"legs": [LEG]}, headers=H).status_code == 409
    assert rapi.post("/api/games/review", json={"legs": [LEG]}).status_code == 403
    st = rapi.get("/api/games/review/status").json()
    assert st["configured"] is True and st["daily_cap"] == 2 and "sk-test" not in str(st)


def test_review_sends_grounded_facts_caches_and_caps(rapi: TestClient) -> None:
    win = {"ticker": f"KXNBAGAME-{KEY}-NYK", "side": "no"}
    r = rapi.post("/api/games/review", json={"legs": [LEG, win], "quote_cents": 30}, headers=H)
    assert r.status_code == 200 and r.json()["overall"] == "reasonable"
    facts = FakeReviewer.calls[0]
    reb, nyk = facts["legs"]
    assert reb["windows"]["season"] == [8, 12] and reb["market_probability"] == 0.635
    assert nyk["bet"].startswith("NO on:") and nyk["market_probability"] == 0.495
    assert facts["combo"]["kalshi_quote"] == 0.3 and facts["headlines"] == []
    # identical request: served from cache, no new call
    again = rapi.post("/api/games/review", json={"legs": [LEG, win], "quote_cents": 30}, headers=H)
    assert again.json()["cached"] is True and len(FakeReviewer.calls) == 1
    assert rapi.post("/api/games/review", json={"legs": [LEG]}, headers=H).status_code == 200
    capped = rapi.post("/api/games/review", json={"legs": [win]}, headers=H)
    assert capped.status_code == 429 and "cap" in capped.json()["error"]["message"]
    assert rapi.post("/api/games/review", json={"legs": [{"ticker": "x y", "side": "yes"}]},
                     headers=H).status_code == 422


def test_openai_key_is_secret() -> None:
    s = Settings(_env_file=None, openai_api_key="sk-abc")
    assert "sk-abc" not in repr(s)
    assert Settings(_env_file=None, openai_api_key=" ").openai_api_key is None


# --- Slip check: stake, walk-away price, singles and limit buys -------------------------------

from app.catalog.slipcheck import Fees, walk_away  # noqa: E402


def test_walk_away_keeps_a_relative_edge(factory) -> None:  # type: ignore[no-untyped-def]
    with factory() as s:
        f = Fees(s)
        wa = walk_away(D("0.30"), f, "KXMVECROSSCATEGORY")
        assert wa is not None and D("0.25") <= wa <= D("0.27")  # (q + fee) x 1.1 <= 0.30
        assert walk_away(D("0.005"), f, "KXMVECROSSCATEGORY") is None
        # maker fee is zero on plain quadratic series, a quarter of taker where flagged
        assert f.maker_fee("KXNBAREB", D(100), D("0.5")) == D("0")


def test_slip_check_verdict_sizing_singles_and_trim(api: TestClient) -> None:
    legs = (f"KXNBAREB-{KEY}-NYKKTOWNS32-12:yes,KXNBAGAME-{KEY}-NYK:yes,"
            f"KXNBATOTAL-{KEY}-216:yes,KXNBASPREAD-{KEY}-NYK3:yes")
    out = api.get("/api/games/check", params={"legs": legs, "stake": "8", "quote": "0.20"}).json()
    assert out["verdict"] in ("stretch", "avoid")
    texts = " ".join(r["text"] for r in out["reasons"])
    assert "4 legs" in texts and "over your $5.00 per-idea cap" in texts  # no budget: $5 cap
    assert "above the" in texts and "walk-away" in texts
    c = out["combo"]
    assert c["legs"] == 4 and c["fair"] is not None and c["walk_away"] is not None
    sz = out["sizing"]
    assert sz["cap"] == "5.00" and sz["stake"] == "8.00" and int(sz["contracts"]) > 0
    assert D(sz["expected"]) < 0
    reb = next(x for x in out["singles"] if "rebounds" in x["label"])
    assert reb["history"] is not None and "edge_pts" in reb and reb["limit"]["price"]
    assert out["trim"]["legs_after"] == 3 and out["evidence_used"] is True


def test_slip_check_single_leg_and_validation(api: TestClient) -> None:
    out = api.get("/api/games/check", params={"legs": f"KXNBAGAME-{KEY}-NYK:yes"}).json()
    assert out["verdict"] == "single" and out["combo"]["walk_away"] is None
    assert api.get("/api/games/check", params={"legs": f"KXNBAGAME-{KEY}-NYK:yes",
                                                "quote": "1.5"}).status_code == 422
    assert api.get("/api/games/check", params={"legs": f"KXNBAGAME-{KEY}-NYK:yes",
                                                "stake": "-1"}).status_code == 422



# --- Local model (Ollama) ---------------------------------------------------------------------


def _ollama(reply: str | None, status: int = 200, seen: list | None = None):  # type: ignore[no-untyped-def]
    def handle(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req)
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "gemma4:12b"}]})
        if status != 200:
            return httpx.Response(status, json={"error": "x"})
        return httpx.Response(200, json={"model": "gemma4:12b", "message": {"content": reply},
                                         "prompt_eval_count": 100, "eval_count": 50,
                                         "total_duration": 2_000_000_000})
    return llm.OllamaClient("http://127.0.0.1:11434", "gemma4:12b",
                            transport=httpx.MockTransport(handle))


def test_ollama_client_is_local_structured_and_non_thinking() -> None:
    seen: list[httpx.Request] = []
    c = _ollama('{"summary": "s", "overall": "avoid", "legs": [], "risks": [], '
                '"check_before_betting": []}', seen=seen)
    out = llm.OllamaReviewer(c).review({"legs": []}, ["A"], set())
    assert out["overall"] == "avoid" and out["seconds"] == 2.0 and out["model"] == "gemma4:12b"
    import json as _json
    body = _json.loads(seen[0].content)
    assert seen[0].url.host == "127.0.0.1" and seen[0].url.path == "/api/chat"
    assert body["think"] is False and body["stream"] is False
    assert body["format"]["required"][0] == "summary" and body["options"]["num_ctx"] == 8192
    assert c.ping() == {"reachable": True, "has_model": True, "models": ["gemma4:12b"]}
    with pytest.raises(llm.LlmError, match="loopback"):
        llm.OllamaClient("http://10.0.0.5:11434", "m")


def test_ollama_errors_are_clear() -> None:
    with pytest.raises(llm.LlmError, match="empty answer"):
        _ollama("").chat_json("s", {}, {})
    with pytest.raises(llm.LlmError, match="ollama pull"):
        _ollama(None, status=404).chat_json("s", {}, {})
    unreachable = llm.OllamaClient("http://127.0.0.1:11434", "m", transport=httpx.MockTransport(
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused"))))
    assert unreachable.ping()["reachable"] is False
    with pytest.raises(llm.LlmError, match="Is it running"):
        unreachable.chat_json("s", {}, {})


def test_coach_output_is_trimmed_to_known_positions() -> None:
    out = llm.parse_coach('{"summary": "x", "strengths": [], "leaks": ["a", "b"], '
                          '"rules_for_next_50": ["r1"], "questions": ["q"], "open_positions": '
                          '[{"ticker": "T1", "note": "ok"}, {"ticker": "NOPE", "note": "x"}]}',
                          {"T1"})
    assert out["open_positions"] == [{"ticker": "T1", "note": "ok"}]
    assert out["leaks"] == ["a", "b"] and out["strengths"] == []


def test_ollama_url_must_be_loopback() -> None:
    ok = Settings(_env_file=None, ollama_base_url="http://localhost:11434/")
    assert ok.ollama_base_url == "http://localhost:11434"
    for bad in ("http://192.168.1.4:11434", "https://ollama.example.com", "http://127.0.0.1:1/x"):
        with pytest.raises(ValueError):
            Settings(_env_file=None, ollama_base_url=bad)


def test_model_text_is_cleaned_of_latex_and_markdown() -> None:
    assert llm._s("price $€0.013$, **bold**, $2.50", 200) == "price $0.013, bold, $2.50"


# --- ideas: screened singles, small combos, cheaper entries ----------------------------------

def _eligible(factory) -> None:  # type: ignore[no-untyped-def]
    from app.db.models import CatalogComboEvent
    with factory() as s:
        for series in ("KXNBAGAME", "KXNBASPREAD", "KXNBATOTAL", "KXNBAREB"):
            s.add(CatalogComboEvent(event_ticker=f"{series}-{KEY}", collections="KXMVESPORTS",
                                    refreshed_at=NOW))
        s.commit()


def _src() -> EspnSource:
    return EspnSource(transport=httpx.MockTransport(espn_handler([])), min_interval=0.0,
                      sleep=lambda _: None)


def test_ideas_keep_legs_where_history_beats_the_all_in_price(factory) -> None:  # type: ignore[no-untyped-def]
    from app.sportsdata.ideas import build_ideas
    _eligible(factory)
    with factory() as s:
        out = build_ideas(s, _src(), "KXNBA", KEY, D("50"), D("0.05"), D("2.50"))
    assert out is not None and out["cap"] == "2.50"
    singles = out["singles"]
    assert [x["id"] for x in singles] == [f"S{i}" for i in range(1, len(singles) + 1)]
    assert all(x["edge_pts"] >= 2 for x in singles)
    # one rung per ladder: never two lines of the same market family for the same subject
    keys = [(x["event_ticker"], x["subject"]) for x in singles]
    assert len(keys) == len(set(keys))
    kat = next(x for x in singles if "Towns" in x["bet"])
    # KAT never had 14+ rebounds in 24 games: history says NO, priced at 57c
    assert kat["side"] == "no" and kat["strength"] == "strong" and kat["ask"] == "0.57"
    assert kat["contracts_at_cap"] == 4  # $2.50 at the 56c limit
    # combos: 2-3 legs drawn only from the singles, each from a different market family
    assert out["combos"]
    ids = {x["id"] for x in singles}
    by_id = {x["id"]: x for x in singles}
    for c in out["combos"]:
        assert 2 <= len(c["legs"]) <= 3 and set(c["legs"]) <= ids
        assert len({by_id[i]["event_ticker"] for i in c["legs"]}) == len(c["legs"])
        assert c["walk_away"] is not None and c["history"] > 0
    # entries are priced from the book alone: improve the bid by a cent. 12+ is 61/66c, so
    # NO is 34/39c; NO saves more (bigger taker fee avoided near 50c), one entry per market.
    reb12 = [e for e in out["entries"] if e["ticker"].endswith("NYKKTOWNS32-12")]
    assert len(reb12) == 1 and reb12[0]["side"] == "no" and reb12[0]["limit"] == "0.35"
    assert reb12[0]["saves_per_100"] == "5.67" and reb12[0]["maker_fee_per_100"] == "0.00"


def test_ideas_without_history_offer_entries_only(factory) -> None:  # type: ignore[no-untyped-def]
    from app.sportsdata.ideas import build_ideas
    with factory() as s:
        out = build_ideas(s, None, "KXNBA", KEY, None, D("0.05"), D("2.50"))
        assert build_ideas(s, None, "KXNBA", "26NOV01XXXYYY", None, D("0.05"), D("2")) is None
    assert out is not None
    assert out["singles"] == [] and out["combos"] == [] and out["entries"]
    assert out["evidence_enabled"] is False and out["skipped"]["no_history"] == out["screened"]


def test_parse_ideas_keeps_listed_ids_and_clips_stakes() -> None:
    import json

    from app.sportsdata.llm import parse_ideas
    out = parse_ideas(json.dumps({"summary": "Two picks.", "picks": [
        {"id": "S1", "how": "take_ask", "stake": 9, "why": ["edge 41 pts"], "sources": ["H1", "X"]},
        {"id": "K1", "how": "limit", "stake": 2, "why": ["ratio 1.5"]},
        {"id": "S9", "how": "limit", "stake": 1, "why": ["invented"]},
        {"id": "S1", "how": "limit", "stake": 1, "why": ["dup"]}],
        "skip": [{"id": "S2", "why": "lean"}, {"id": "Z", "why": "x"}]}),
        {"S1", "S2", "K1"}, {"H1"}, 2.5)
    assert [p["id"] for p in out["picks"]] == ["S1", "K1"]
    assert out["picks"][0]["stake"] == 2.5 and out["picks"][0]["sources"] == ["H1"]
    assert out["picks"][1]["how"] == "quote_at_or_below"  # combos are quoted, not limited
    assert out["skip"] == [{"id": "S2", "why": "lean"}]


def test_api_ideas_and_ai_picks(gset: Settings, factory, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import json

    import app.api.games_routes as gr
    from app.sportsdata import llm
    _eligible(factory)
    sent: list[dict] = []

    def handle(req: httpx.Request) -> httpx.Response:
        sent.append(json.loads(req.content))
        return httpx.Response(200, json={"model": "gemma4:12b", "message": {"content": json.dumps({
            "summary": "One single.", "picks": [{"id": "S1", "how": "limit", "stake": 2,
                                                  "why": ["41 pts edge"]}], "skip": []})}})

    monkeypatch.setattr(gr, "local_reviewer", lambda s: llm.OllamaReviewer(llm.OllamaClient(
        "http://127.0.0.1:11434", "gemma4:12b", transport=httpx.MockTransport(handle))))
    app = create_app(gset, FrozenClock(NOW))
    app.state.espn = _src()
    with TestClient(app, base_url="http://127.0.0.1") as c:
        out = c.get(f"/api/games/KXNBA/{KEY}/ideas").json()
        assert out["singles"] and out["generated_at"]
        assert c.get("/api/games/KXNBA/26NOV01XXXYYY/ideas").status_code == 404
        assert c.post(f"/api/games/KXNBA/{KEY}/ideas/ai").status_code == 403
        ai = c.post(f"/api/games/KXNBA/{KEY}/ideas/ai", headers=H).json()
        assert ai["picks"][0]["id"] == "S1" and ai["cached"] is False
        facts = json.loads(sent[0]["messages"][1]["content"])
        assert facts["singles"][0]["id"] == "S1" and "ticker" not in facts["singles"][0]
        assert facts["budget"]["per_idea_cap"] == out["cap"]
        again = c.post(f"/api/games/KXNBA/{KEY}/ideas/ai", headers=H).json()
        assert again["cached"] is True and len(sent) == 1


def test_ideas_never_combine_winner_with_spread(factory) -> None:  # type: ignore[no-untyped-def]
    from app.sportsdata.ideas import build_ideas
    _eligible(factory)
    with factory() as s:
        out = build_ideas(s, _src(), "KXNBA", KEY, D("50"), D("0.05"), D("2.50"))
    assert out is not None
    fam = {x["id"]: x["family"] for x in out["singles"]}
    assert fam and {f for f in fam.values() if f.startswith("outcome:")} == {f"outcome:{KEY}"}
    for c in out["combos"]:
        assert len({fam[i] for i in c["legs"]}) == len(c["legs"])
        # market side carries the same correlation as history, so ratio = leg edges only
        assert c["fair"] <= min(float(next(x["mid"] for x in out["singles"] if x["id"] == i))
                                for i in c["legs"])


def test_role_change_demotes_a_players_props_that_all_lean_one_way() -> None:
    from app.sportsdata.ideas import flag_role_changes

    def leg(event: str, side: str, who: str = "Charles Bassey") -> dict[str, Any]:
        return {"kind": "player_stat", "subject": who, "side": side, "event_ticker": event,
                "strength": "strong", "caution": None}
    unders = [leg("KXNBAAST-G", "no"), leg("KXNBAREB-G", "no"), leg("KXNBABLK-G", "no")]
    rungs = [leg("KXNBAREB-G", "no", "KAT"), leg("KXNBAREB-G", "no", "KAT"),
             leg("KXNBAREB-G", "no", "KAT")]
    mixed = [leg("KXNBAPTS-G", "no", "Grant"), leg("KXNBAAST-G", "yes", "Grant")]
    singles = unders + rungs + mixed
    flag_role_changes(singles)
    assert all(x["strength"] == "lean" and "bigger role" in x["caution"] for x in unders)
    assert all(x["caution"] is None for x in rungs + mixed)  # one ladder / mixed directions


def test_headline_mojibake_is_repaired_and_averages_carry_units() -> None:
    from app.sportsdata.evidence import avg_text
    from app.sportsdata.news import demojibake
    assert demojibake("3-point woes \u00e2\u20ac\u201c NBC") == "3-point woes \u2013 NBC"
    assert demojibake("plain \u2013 text") == "plain \u2013 text"
    assert avg_text({"kind": "team_win", "season_avg": 0.87}) == "+0.9 pts average margin"
    assert avg_text({"kind": "player_stat", "stat": "REB", "season_avg": 11.67}) == \
        "11.7 REB per game"
    assert avg_text({"kind": "team_total", "season_avg": None}) is None


def test_parse_ideas_caps_total_stake_at_three_caps() -> None:
    import json

    from app.sportsdata.llm import parse_ideas
    picks = [{"id": f"S{i}", "how": "limit", "stake": 2.5, "why": []} for i in (1, 2, 3)]
    picks[0]["stake"] = 2.5
    out = parse_ideas(json.dumps({"summary": "", "picks": picks, "skip": []}),
                      {"S1", "S2", "S3"}, set(), 2.0)
    assert [p["stake"] for p in out["picks"]] == [2.0, 2.0, 2.0]
    assert sum(p["stake"] for p in out["picks"]) <= 6.0
