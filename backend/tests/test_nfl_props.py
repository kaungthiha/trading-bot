"""NFL player props: exact player/stat/line mapping, point-in-time frequencies that count
team games without a stat line as misses, status from the injury report and listed QB, and
no edge. Mocked transports only."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.catalog.store import CatalogWriter
from app.core.config import Settings
from app.db.session import make_engine, make_session_factory
from app.investigate import nfl, nfl_props, search, sources
from app.investigate import schemas as S
from app.sportsdata import nflverse as nv
from tests.test_nfl import KEY, PAGE, GitHub, Meteo, _app, _ev, run
from tests.test_nhl import _mk

P_HEAD = (
    "player_id,player_name,player_display_name,position,season,week,season_type,game_id,team,"
    "opponent_team,completions,attempts,passing_yards,passing_tds,passing_interceptions,carries,"
    "rushing_yards,rushing_tds,receptions,targets,receiving_yards,receiving_tds,"
    "special_teams_tds,fumble_recovery_tds,def_tds\n"
)


def _p(
    pid: str,
    short: str,
    name: str,
    pos: str,
    week: int,
    gid: str,
    team: str,
    opp: str,
    **stats: float,
) -> str:
    cols = P_HEAD.strip().split(",")[10:]
    vals = ",".join(str(stats.get(c, 0)) for c in cols)
    return f"{pid},{short},{name},{pos},2026,{week},REG,{gid},{team},{opp},{vals}"


PLAYERS = P_HEAD + "\n".join(
    [
        _p(
            "qb1",
            "J.Allen",
            "Josh Allen",
            "QB",
            2,
            "2026_02_BUF_MIA",
            "BUF",
            "MIA",
            passing_yards=280,
            completions=22,
            attempts=33,
            rushing_tds=1,
        ),
        _p(
            "qb1",
            "J.Allen",
            "Josh Allen",
            "QB",
            3,
            "2026_03_NYJ_BUF",
            "BUF",
            "NYJ",
            passing_yards=240,
            completions=19,
            attempts=30,
        ),
        # After this game (week 12): never counted.
        _p(
            "qb1",
            "J.Allen",
            "Josh Allen",
            "QB",
            13,
            "2026_13_BUF_NE",
            "BUF",
            "NE",
            passing_yards=400,
        ),
        # The other Josh Allen (Jaguars linebacker): same name, different player.
        _p("lb1", "J.Allen", "Josh Allen", "LB", 2, "2026_02_JAX_X", "JAX", "X", def_tds=1),
        _p(
            "qb2",
            "M.Trubisky",
            "Mitchell Trubisky",
            "QB",
            3,
            "2026_03_NYJ_BUF",
            "BUF",
            "NYJ",
            passing_yards=180,
        ),
        # Kelce has a line in week 1 only: week 3 (a Chiefs game) has no row for him.
        _p(
            "te1",
            "T.Kelce",
            "Travis Kelce",
            "TE",
            1,
            "2026_01_KC_DEN",
            "KC",
            "DEN",
            receiving_yards=60,
            receptions=5,
            receiving_tds=1,
        ),
    ]
)
T_HEAD = (
    "season,week,team,season_type,game_id,opponent_team,attempts,sacks_suffered,carries,"
    "passing_epa,rushing_epa,passing_yards,rushing_yards,completions,passing_tds,"
    "rushing_tds,passing_interceptions\n"
)
TEAMS = T_HEAD + "\n".join(
    [
        "2026,1,KC,REG,2026_01_KC_DEN,DEN,35,2,25,4,1,250,100,24,2,1,0",
        "2026,1,DEN,REG,2026_01_KC_DEN,KC,35,2,25,-2,-1,210,80,20,1,0,1",
        "2026,2,BUF,REG,2026_02_BUF_MIA,MIA,35,2,25,9,3,280,120,22,2,1,0",
        "2026,2,MIA,REG,2026_02_BUF_MIA,BUF,35,2,25,-4,-2,190,90,18,0,1,2",
        "2026,3,KC,REG,2026_03_KC_LV,LV,35,2,25,6,2,260,110,25,2,0,0",
        "2026,3,LV,REG,2026_03_KC_LV,KC,35,2,25,1,1,230,70,21,1,0,1",
        "2026,3,BUF,REG,2026_03_NYJ_BUF,NYJ,35,2,25,7,3,240,130,19,1,2,0",
        "2026,3,NYJ,REG,2026_03_NYJ_BUF,BUF,35,2,25,-7,-3,150,60,15,0,0,1",
    ]
)
ALLEN = f"KXNFLPASSYDS-{KEY}-BUFJALLEN17-250"
ALLEN_PROT = f"KXNFLPASSYDSPROT-{KEY}-BUFJALLEN17-200"
KELCE = f"KXNFLRECYDS-{KEY}-KCTKELCE87-50"
TRUB = f"KXNFLPASSYDS-{KEY}-BUFMTRUBISKY10-150"
ALLEN_TD = f"KXNFLTD-{KEY}-BUFJALLEN17-1"
DST = f"KXNFLTD-{KEY}-KCKCDST-1"
LONGREC = f"KXNFLLONGREC-{KEY}-KCTKELCE87-20"
PROPS = PAGE + [
    _ev(
        "KXNFLPASSYDS",
        "Kansas City vs Buffalo: Passing Yards",
        [
            _mk(ALLEN, "Josh Allen: 250+", "0.55", "0.57", strike=249.5, sub="Josh Allen: 250+"),
            _mk(
                TRUB,
                "Mitchell Trubisky: 150+",
                "0.05",
                "0.07",
                strike=149.5,
                sub="Mitchell Trubisky: 150+",
            ),
        ],
    ),
    _ev(
        "KXNFLPASSYDSPROT",
        "Kansas City vs Buffalo: Passing Yards",
        [
            _mk(
                ALLEN_PROT, "Josh Allen: 200+", "0.8", "0.82", strike=199.5, sub="Josh Allen: 200+"
            ),
        ],
    ),
    _ev(
        "KXNFLRECYDS",
        "Kansas City vs Buffalo: Receiving Yards",
        [
            _mk(KELCE, "Travis Kelce: 50+", "0.4", "0.42", strike=49.5, sub="Travis Kelce: 50+"),
        ],
    ),
    _ev(
        "KXNFLTD",
        "Kansas City vs Buffalo: Touchdowns",
        [
            _mk(ALLEN_TD, "Josh Allen: 1+", "0.3", "0.32", strike=0.5, sub="Josh Allen: 1+"),
            _mk(DST, "KC Chiefs D/ST: 1+", "0.1", "0.12", strike=0.5, sub="KC Chiefs D/ST: 1+"),
        ],
    ),
    _ev(
        "KXNFLLONGREC",
        "Kansas City vs Buffalo: Longest Reception",
        [
            _mk(LONGREC, "Travis Kelce: over 19.5 yards", "0.5", "0.52", strike=19.5),
        ],
    ),
]


def _gh(**over: Any) -> GitHub:
    gh = GitHub(**over)
    gh.files["stats_player/stats_player_week_2026.csv"] = PLAYERS
    gh.files["stats_team/stats_team_week_2026.csv"] = TEAMS
    return gh


def _props_app(settings: Settings, gh: GitHub, **over: Any):  # type: ignore[no-untyped-def]
    app = _app(settings, gh, Meteo(), **over)
    engine = make_engine(app.state.settings.database_url)
    from tests.test_nfl import NOW

    CatalogWriter(make_session_factory(engine), NOW).write_page(PROPS)
    engine.dispose()
    return app


def texts(r: dict[str, Any]) -> str:
    return " ".join(
        f["text"]
        for f in r["summary"]["findings"] + r["details"]["against"] + r["details"]["supports"]
    )


# --- mapping ---------------------------------------------------------------------------------


def test_prop_kinds_settlement_and_refusals() -> None:
    assert nfl_props.prop_base("PASSYDS") == ("PASSYDS", False)
    assert nfl_props.prop_base("RECPROT") == ("REC", True)
    assert nfl_props.prop_base("PASSYDSPRECISE") == ("PASSYDS", False)
    assert nfl_props.prop_base("LONGREC") is None and nfl_props.prop_base("FIRSTTD") is None
    for s in ("KXNFLPASSYDS", "KXNFLREC", "KXNFLTD", "KXNFLRRYDS", "KXNFLRSHATT", "KXNFLPASSINT"):
        assert nfl.market_kind(s) == "player_prop", s
    rules = nfl_props.settlement("passing yards", True, False)
    assert "active but never plays a live snap" in rules and "Protected" in rules
    assert "not ones he throws" in nfl_props.settlement("touchdowns scored", False, True)


def test_find_player_never_guesses_between_two_players() -> None:
    rows = nv.parse_players(PLAYERS)
    allen = nfl_props.find_player(rows, "Josh Allen", "BUF")
    assert {r.player_id for r in allen} == {"qb1"} and [r.week for r in allen] == [2, 3, 13]
    assert nfl_props.find_player(rows, "Josh Allen", None) == []  # two Josh Allens: refuse
    assert nfl_props.find_player(rows, "Josh Allen", "KC") == []  # neither is a Chief
    assert [r.player_id for r in nfl_props.find_player(rows, "Travis Kelce Jr.", "KC")] == ["te1"]
    lo, hi = nfl_props.wilson(1, 2)
    assert 0 < lo < 0.5 < hi < 1 and nfl_props.wilson(0, 0) == (0.0, 1.0)


# --- end to end ------------------------------------------------------------------------------


def test_prop_end_to_end_frequency_status_and_no_edge(settings: Settings) -> None:
    gh = _gh()
    with TestClient(_props_app(settings, gh), base_url="http://127.0.0.1") as c:
        r = run(c, ALLEN)
        prot = run(c, ALLEN_PROT, "no")
        td = run(c, ALLEN_TD)
    h, p, sm = r["hypothesis"], r["price_assessment"], r["summary"]
    assert (h["sport"], h["league"], h["market_type"], h["subject"], h["threshold"]) == (
        "football",
        "NFL",
        "player_prop",
        "Josh Allen",
        249.5,
    )
    status = sm["findings"][0]["text"]
    assert status.startswith("Player status — Josh Allen (QB, Buffalo Bills); Questionable (ankle)")
    assert "the schedule lists" not in status  # he is the listed starter
    freq = sm["findings"][1]["text"]
    assert "Josh Allen reached 250+ passing yards in 1 of 2 games with a stat line" in freq
    assert "Last 2: 280, 240" in freq and "400" not in texts(r)  # week 13 never counts
    opp = sm["findings"][2]["text"]
    assert opp.startswith(
        "Kansas City Chiefs allow 220.0 passing yards a game (2 games; league average 226.2)"
    )
    assert p["model_p"] == 0.5 and p["model_band"] is not None and p["conservative_edge"] is None
    assert nfl_props.NO_MODEL in p["abstain_reasons"]
    assert any("2 games is a small sample" in a for a in p["abstain_reasons"])
    assert any("active but never plays a live snap" in a for a in p["assumptions"])
    assert "He's listed Questionable (ankle) this week" in sm["takeaway"]
    assert (
        sm["coverage"] == "1 factual dataset · 0 commentary links · player status: "
        "Questionable (ankle)"
    )
    # Protected NO: the frequency flips for the NO side, and protection is explained.
    assert prot["price_assessment"]["model_p"] == 0.0  # he reached 200+ in both games
    assert any("Protected" in a for a in prot["price_assessment"]["assumptions"])
    assert "Josh Allen scored 1+ touchdowns in 1 of 2 games" in texts(td)
    # The player file is downloaded once for all three props.
    assert sum(1 for x in gh.downloads() if "stats_player" in x) == 1


def test_games_without_a_stat_line_count_as_misses_and_out_opposes(settings: Settings) -> None:
    with TestClient(_props_app(settings, _gh()), base_url="http://127.0.0.1") as c:
        r = run(c, KELCE)
    status = r["summary"]["findings"][0]
    assert "Out (knee)" in status["text"] and status["stance"] == "opposes"
    freq = r["summary"]["findings"][1]["text"]
    assert (
        "Travis Kelce reached 50+ receiving yards in 1 of 1 games with a stat line (1 of 2 "
        "team games, counting 1 without one as misses)"
    ) in freq
    assert r["price_assessment"]["model_p"] == 0.5  # 1 of 2, the cautious reading


def test_listed_qb_mismatch_and_refusals(settings: Settings) -> None:
    with TestClient(_props_app(settings, _gh()), base_url="http://127.0.0.1") as c:
        r = run(c, TRUB)
        dst = c.post(
            "/api/research/investigations",
            json={"ticker": DST, "side": "yes"},
            headers={"X-KRT-Request": "research"},
        )
        lng = c.post(
            "/api/research/investigations",
            json={"ticker": LONGREC, "side": "yes"},
            headers={"X-KRT-Request": "research"},
        )
    assert (
        "the schedule lists Josh Allen as Buffalo Bills's starter"
        in r["summary"]["findings"][0]["text"]
    )
    assert dst.status_code == 422 and "special-teams" in dst.json()["error"]["message"]
    assert lng.status_code == 422 and "prop type isn't covered" in lng.json()["error"]["message"]


def test_player_stats_switch_and_missing_report_week(settings: Settings) -> None:
    gh = _gh()
    app = _props_app(settings, gh, research_disabled_sources="nflverse_player_stats")
    with TestClient(app, base_url="http://127.0.0.1") as c:
        r = run(c, ALLEN)
    assert not any("stats_player" in x for x in gh.downloads())
    assert any("player stats are switched off" in e for e in r["processing"]["errors"])
    assert r["price_assessment"]["model_p"] is None
    assert "No stat lines for Josh Allen" in texts(r)
    late = _gh(injuries_through=11)
    with TestClient(_props_app(settings, late), base_url="http://127.0.0.1") as c:
        r2 = run(c, ALLEN_TD)
    assert "week 12 injury report not out yet" in r2["summary"]["findings"][0]["text"]
    assert r2["summary"]["coverage"].endswith("player status: report not out yet")


def test_prop_news_queries_and_registry() -> None:
    h = S.Hypothesis(
        ticker=ALLEN,
        event_ticker=f"KXNFLPASSYDS-{KEY}",
        side="yes",
        sport="football",
        league="NFL",
        market_type="player_prop",
        threshold=249.5,
        subject="Josh Allen",
        label="x",
        statement="x",
        snapshot_at=None,
        rules_url=None,
    )
    teams = [{"code": "KC", "name": "Kansas City Chiefs"}, {"code": "BUF", "name": "Buffalo Bills"}]
    assert search.plan_queries(h, teams, 5) == [
        "Josh Allen injury status",
        "Kansas City Chiefs vs Buffalo Bills NFL preview",
        "Josh Allen passing yards prop 249.5",
    ]
    assert sources.allows("nflverse_player_stats", "download_player_stats_release")
    assert not sources.allows("nflverse_player_stats", "download_schedule_release")
    assert "never silently skipped" in sources.SOURCES["nflverse_player_stats"].notes
    assert not nv.PATH.match(f"{nv.ROOT}stats_player/stats_player_reg_2026.csv")  # weekly only
    assert nv.PATH.match(f"{nv.ROOT}stats_player/stats_player_week_2026.csv")
