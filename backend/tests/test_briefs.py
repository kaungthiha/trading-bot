"""Qualitative leg briefs and tonight's slate combos (no probability, no edge)."""

from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi.testclient import TestClient

from app.catalog.store import CatalogWriter
from app.core.clock import FrozenClock
from app.core.config import Settings
from app.db.session import make_engine, make_session_factory
from app.main import create_app
from app.sportsdata import slate
from app.sportsdata.briefs import Ctx, brief, game_date
from app.sportsdata.espn import EspnSource, GameRow, et_date, parse_opponents
from app.sportsdata.evidence import leg_summary, predicate
from tests.test_games import BYTEAM, KEY, NOW, PAGE, espn_handler

TABLE = parse_opponents(BYTEAM)
NAMES = {"NYK": "New York", "MIN": "Minnesota"}


def _rows(vals: list[float], mins: list[float] | None = None, opp: str = "TOR",
          start: str = "2026-11-18", home: bool = True) -> list[GameRow]:
    """Newest first, one game a day going back from `start`."""
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    out = []
    for i, v in enumerate(vals):
        d = (d0 - timedelta(days=i)).isoformat()
        out.append(GameRow(event_id=f"e{i}", date=d, et_date=d, season="current", opponent=opp,
                           home=home if i % 2 == 0 else not home, won=v > 10, team_score=110,
                           opp_score=100, stats={"REB": v, "MIN": (mins or [34] * 40)[i]}))
    return out


def _ctx(side: str = "yes", injuries: list[dict[str, str]] | None = None, **kw: Any) -> Ctx:
    base: dict[str, Any] = {"league": "nba", "side": side, "team": "NYK", "opp": "MIN",
                            "home": False, "game_date": "2026-11-20", "names": NAMES,
                            "table": TABLE, "injuries": [] if injuries is None else injuries,
                            "team_ids": {"NYK": "18", "MIN": "16"}}
    return Ctx(**{**base, **kw})


SPEC = {"kind": "player_stat", "player": "Karl-Anthony Towns", "team": "NYK", "stat": "REB",
        "at_least": 12}


def _brief(rows: list[GameRow], market_yes: float, side: str = "yes", **kw: Any
           ) -> dict[str, Any]:
    pred, value = predicate(SPEC, side)
    m = market_yes if side == "yes" else 1 - market_yes
    return brief(SPEC, rows, leg_summary(rows, pred, value, m), m, _ctx(side, **kw))


def _texts(b: dict[str, Any], key: str) -> str:
    return " | ".join(p["text"] for p in b[key])


# --- parsing --------------------------------------------------------------------------------


def test_team_table_reads_own_and_opponent_rows_by_label() -> None:
    assert TABLE["MIN"]["allow_REB"] == 47.5 and TABLE["MIN"]["own_PTS"] == 112
    assert TABLE["MIA"]["allow_PTS"] == 119.4 and TABLE["MIA"]["gp"] == 16
    # A team with no games played is left out rather than zero-filled.
    body = {**BYTEAM, "teams": BYTEAM["teams"] + [{"team": {"abbreviation": "XX"},
                                                   "categories": []}]}
    assert "XX" not in parse_opponents(body)


def test_dates_are_us_eastern() -> None:
    assert et_date("2026-11-24T00:30:00.000+00:00") == "2026-11-23"  # 7:30pm ET
    assert et_date("2026-11-23T18:00Z") == "2026-11-23" and et_date("junk") == ""
    assert game_date("26NOV24NYKMIN") == "2026-11-24" and game_date("bad") == ""


# --- player briefs ----------------------------------------------------------------------------


def test_form_counts_only_against_the_price() -> None:
    rows = _rows([13] * 9 + [9] * 3)
    # 9 of last 10 at a 90% price is just why it costs 90%: context, not a reason.
    rich = _brief(rows, 0.90)
    assert "9 of his last 10" in _texts(rich, "context")
    # The same record at 50% runs well ahead of the price.
    cheap = _brief(rows, 0.50)
    assert "9 of his last 10" in _texts(cheap, "for")
    assert "below his history" in _texts(cheap, "for")


def test_matchup_minutes_and_rest_points() -> None:
    mins = [38] * 5 + [31] * 10
    rows = _rows([12] * 15, mins=mins, start="2026-11-19")  # played last night
    b = _brief(rows, 0.5)
    pro, con = _texts(b, "for"), _texts(b, "against")
    assert "Minnesota allow 47.5 rebounds a game, 1st most of 4" in pro
    assert "Minutes up: 38.0" in pro
    assert "back-to-back" in con
    # Betting NO turns the same facts around.
    nb = _brief(rows, 0.5, side="no")
    assert "Minnesota allow" in _texts(nb, "against") and "back-to-back" in _texts(nb, "for")


def test_injuries_own_status_and_teammates() -> None:
    rows = _rows([12] * 15)
    out = [{"team_id": "18", "player": "Karl-Anthony Towns", "status": "Out", "detail": "knee"}]
    b = _brief(rows, 0.5, injuries=out)
    assert b["lean"] == "avoid" and "fair price" in b["headline"]
    probable = [{"team_id": "18", "player": "Karl-Anthony Towns", "status": "Day-To-Day",
                 "detail": "Towns is probable for Thursday"}]
    assert "probable" in _texts(_brief(rows, 0.5, injuries=probable), "context")
    mates = [{"team_id": "18", "player": "Jalen Brunson", "status": "Out", "detail": ""},
             {"team_id": "16", "player": "Rudy Gobert", "status": "Out", "detail": ""}]
    ctx = _texts(_brief(rows, 0.5, injuries=mates), "context")
    assert "Out for his team: Jalen Brunson" in ctx and "Gobert" not in ctx
    ctx_college = _ctx()
    ctx_college.injuries = None  # no report published (college)
    college = brief(SPEC, rows, leg_summary(rows, *predicate(SPEC, "yes"), 0.5), 0.5,
                    ctx_college)
    assert "No injury report" in _texts(college, "context")


def test_strong_needs_several_points_and_thin_data_says_so() -> None:
    mins = [38] * 5 + [31] * 10
    b = _brief(_rows([13] * 15, mins=mins), 0.45)
    assert b["lean"] == "strong" and b["score"] >= 2 and b["headline"].startswith("Strong")
    thin = _brief(_rows([13] * 3), 0.45)
    assert thin["lean"] == "thin"


def test_team_line_matchup_counts_only_while_the_price_is_open() -> None:
    spec = {"kind": "team_win", "team": "MIN"}
    rows = _rows([12] * 12)
    # Minnesota -2.0 a game vs New York +8.0: against a Minnesota win while the price is open,
    # only context once the price is lopsided (it already says who's better).
    for price, where in ((0.5, "against"), (0.9, "context")):
        pred, value = predicate(spec, "yes")
        b = brief(spec, rows, leg_summary(rows, pred, value, price), price,
                  _ctx(team="MIN", opp="NYK", home=True))
        assert "Point differential this season: Minnesota -2.0 a game, New York +8.0" in \
            _texts(b, where)


# --- slate ------------------------------------------------------------------------------------


def _leg(ticker: str, game: str, score: int, price: float, subject: str | None = None,
         family: str | None = None, kind: str = "player_stat", against: int = 0
         ) -> dict[str, Any]:
    pro = [{"text": f"p{i}", "kind": "form"} for i in range(score + against)]
    con = [{"text": f"c{i}", "kind": "form"} for i in range(against)]
    return {"ticker": ticker, "side": "yes", "label": ticker, "bet": f"YES · {ticker}",
            "event_ticker": f"EV-{ticker}", "game_key": game, "game": game,
            "subject": subject or ticker, "kind": kind, "price": price, "eligible": True,
            "family": family or f"EV-{ticker}",
            "brief": {"lean": "strong" if score >= 2 else "mixed", "score": score,
                      "headline": "h", "for": pro, "against": con, "context": []}}


def test_pool_keeps_clear_cases_one_per_player() -> None:
    legs = [_leg("A", "g1", 3, 0.6), _leg("B", "g1", 1, 0.6),          # not clear enough
            _leg("C", "g2", 3, 0.95),                                    # near-lock
            _leg("D", "g2", 3, 0.6, against=2),                          # too much against
            _leg("E", "g3", 2, 0.5, subject="Same"), _leg("F", "g3", 3, 0.5, subject="Same")]
    legs[0]["eligible"] = True
    pool = slate.pick_pool(legs)
    assert [x["ticker"] for x in pool] == ["A", "F"]


def test_combos_respect_game_and_family_limits() -> None:
    pool = [_leg("A", "g1", 4, 0.6), _leg("B", "g1", 3, 0.6), _leg("C", "g1", 3, 0.6),
            _leg("W", "g2", 3, 0.55, family="outcome:g2"),
            _leg("S", "g2", 3, 0.55, family="outcome:g2"), _leg("T", "g3", 2, 0.5)]
    combos = slate.combos_from(pool)
    assert combos and len(combos) <= slate.MAX_COMBOS
    for c in combos:
        assert 3 <= len(c) <= 4
        per = [x["game_key"] for x in c]
        assert max(per.count(g) for g in per) <= slate.MAX_PER_GAME
        assert not {"W", "S"} <= {x["ticker"] for x in c}   # winner + spread of one game
    # Suggestions differ by more than one swapped leg.
    a, b = ({x["ticker"] for x in c} for c in combos[:2])
    assert len(a & b) < min(len(a), len(b)) - 1


def test_slate_api_builds_in_the_background(settings: Settings) -> None:
    gset = Settings(_env_file=None, database_url=settings.database_url, llm_provider="openai")
    engine = make_engine(gset.database_url)
    CatalogWriter(make_session_factory(engine), NOW).write_page(PAGE)
    engine.dispose()
    app = create_app(gset, FrozenClock(NOW))
    app.state.espn = EspnSource(transport=httpx.MockTransport(espn_handler([])),
                                min_interval=0.0, sleep=lambda _: None)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.get("/api/games/slate/KXNBA").json()["status"] == "idle"
        assert c.post("/api/games/slate/KXNBA").status_code == 403       # no CSRF header
        assert c.get("/api/games/slate/KXNHL").status_code == 404
        H = {"X-KRT-Request": "slate"}
        assert c.post("/api/games/slate/KXNBA", headers=H).json()["status"] == "building"
        for _ in range(200):
            st = c.get("/api/games/slate/KXNBA").json()
            if st["status"] != "building":
                break
            time.sleep(0.05)
        assert st["status"] == "ready", st
        res = st["result"]
        assert [g["game_key"] for g in res["games"]] == [KEY]
        assert res["briefed"] > 0 and sum(res["leans"].values()) == res["briefed"]
        for x in res["pool"]:
            assert slate.LEG_MIN <= x["price"] <= slate.LEG_MAX
            assert x["brief"]["lean"] in ("strong", "mixed")
        # Each docket evidence leg carries its brief too.
        ev = c.get("/api/games/evidence",
                   params={"legs": f"KXNBAREB-{KEY}-NYKKTOWNS32-12:yes"}).json()
        assert ev["legs"][0]["brief"]["lean"] in ("strong", "mixed", "weak", "thin", "avoid")
