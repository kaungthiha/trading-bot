"""College basketball (men's and women's) in box-score evidence and Investigate.

College differs from the NBA in three ways the app must respect:
- 360+ schools with irregular Kalshi codes: teams are matched by name, never by a bare code;
- no injury report exists: the lineup is "unknown", never "normal", so no edge is shown;
- the same school names cover football and both basketball programs: news is filtered.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.catalog.store import CatalogWriter
from app.core.clock import FrozenClock
from app.core.config import Settings
from app.db.session import make_engine, make_session_factory
from app.investigate import schemas as S
from app.investigate import search, service, synth
from app.main import create_app
from app.sportsdata.espn import EspnSource, college_team
from tests.test_games import NOW, _mk

H = {"X-KRT-Request": "research"}
KEY = "26NOV19TARLUSC"

ESPN_TEAMS = [
    {"id": "30", "abbr": "USC", "location": "USC", "short": "USC", "name": "USC Trojans"},
    {
        "id": "2627",
        "abbr": "TAR",
        "location": "Tarleton State",
        "short": "Tarleton St",
        "name": "Tarleton State Texans",
    },
    {
        "id": "399",
        "abbr": "UALB",
        "location": "UAlbany",
        "short": "UAlbany",
        "name": "UAlbany Great Danes",
    },
    {
        "id": "2599",
        "abbr": "SJU",
        "location": "St. John's",
        "short": "St. John's",
        "name": "St. John's Red Storm",
    },
    {
        "id": "2603",
        "abbr": "SJU",
        "location": "Saint Joseph's",
        "short": "Saint Joseph's",
        "name": "Saint Joseph's Hawks",
    },
    {
        "id": "357",
        "abbr": "AMCC",
        "location": "Texas A&M-Corpus Christi",
        "short": "Texas A&M-CC",
        "name": "Texas A&M-Corpus Christi Islanders",
    },
    {
        "id": "2241",
        "abbr": "CAL",
        "location": "California",
        "short": "California",
        "name": "California Golden Bears",
    },
]


def test_college_teams_match_by_name_not_by_code() -> None:
    def m(code: str, name: str | None) -> str | None:
        t = college_team(ESPN_TEAMS, code, name)
        return None if t is None else t["id"]

    assert m("TARL", "Tarleton St.") == "2627"  # Kalshi code differs; "St." at the end = State
    assert m("AMCC", "Texas A&M-Corpus Christi") == "357"
    assert m("ALBY", "University at Albany") == "399"  # known spelling difference
    assert m("SJU", "St. John's") == "2599"  # leading "St." is Saint: not Saint Joseph's
    assert m("USC", "USC") == "30"
    # Non-Division I opponents and missing names fail closed instead of guessing.
    assert m("AVE", "Averett") is None
    assert m("CAL", None) is None
    # A code that matches some ESPN abbreviation isn't enough when the name disagrees.
    assert m("CAL", "Cal Poly") is None


@pytest.mark.parametrize(
    ("series", "kind"),
    [
        ("KXNCAAMBGAME", "moneyline"),
        ("KXNCAAMBSPREAD", "spread"),
        ("KXNCAAWBTOTAL", "total"),
        ("KXNCAAMB1H", "other"),
        ("KXNCAAMB1HSPREAD", "other"),  # halves can't be checked against full-game scores
        ("KXNCAAMBAPRANK", "other"),
        ("KXNBAREB", "player_prop"),
        ("KXNBAREBPROT", "player_prop"),
        ("KXNBATEAMTOTAL", "team_total"),
        ("KXNBA1QSPREAD", "other"),
    ],
)
def test_market_kind_reads_the_suffix_after_the_league(series: str, kind: str) -> None:
    assert service.market_kind(series) == kind


def test_supported_checks_cover_college_and_wnba() -> None:
    service.check_supported(f"KXNCAAMBGAME-{KEY}-USC", f"KXNCAAMBGAME-{KEY}", "KXNCAAMBGAME")
    service.check_supported(f"KXNCAAWBGAME-{KEY}-USC", f"KXNCAAWBGAME-{KEY}", "KXNCAAWBGAME")
    service.check_supported(
        "KXWNBAGAME-27MAY20LVANYL-LVA", "KXWNBAGAME-27MAY20LVANYL", "KXWNBAGAME"
    )
    with pytest.raises(service.Unsupported):
        service.check_supported(f"KXNCAAMB1H-{KEY}-USC", f"KXNCAAMB1H-{KEY}", "KXNCAAMB1H")
    with pytest.raises(service.Unsupported):
        service.check_supported(
            "KXNCAAFGAME-26NOV21OSUMICH-OSU", "KXNCAAFGAME-26NOV21OSUMICH", "KXNCAAFGAME"
        )


# --- end to end ---------------------------------------------------------------------------


def _ev(series: str, title: str, markets: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "event_ticker": f"{series}-{KEY}",
        "series_ticker": series,
        "category": "Sports",
        "title": title,
        "sub_title": "TARL vs USC (Nov 19)",
        "mutually_exclusive": False,
        "markets": markets,
    }


def _page(lg: str) -> list[dict[str, Any]]:
    return [
        _ev(
            f"KX{lg}GAME",
            "Tarleton St. vs USC",
            [
                _mk(
                    f"KX{lg}GAME-{KEY}-TARL",
                    "Tarleton St. wins",
                    "0.04",
                    "0.05",
                    sub="Tarleton St.",
                ),
                _mk(f"KX{lg}GAME-{KEY}-USC", "USC wins", "0.95", "0.96", sub="USC"),
            ],
        ),
        _ev(
            f"KX{lg}SPREAD",
            "Tarleton St. vs USC: Spread",
            [
                _mk(
                    f"KX{lg}SPREAD-{KEY}-USC28",
                    "USC wins by over 27.5 points",
                    "0.40",
                    "0.42",
                    strike=27.5,
                )
            ],
        ),
    ]


def _schedule(n: int, tid: str) -> dict[str, Any]:
    evs = []
    for i in range(n):
        ts, os_ = 85 + i % 7, 60 + i % 9
        evs.append(
            {
                "id": f"g{i}",
                "date": f"2026-11-{i % 18 + 1:02d}T00:30Z",
                "competitions": [
                    {
                        "status": {"type": {"completed": True}},
                        "competitors": [
                            {
                                "homeAway": "home",
                                "team": {"id": tid, "abbreviation": "USC"},
                                "score": {"value": float(ts)},
                                "winner": True,
                            },
                            {
                                "homeAway": "away",
                                "team": {"id": "9", "abbreviation": "OPP"},
                                "score": {"value": float(os_)},
                                "winner": False,
                            },
                        ],
                    }
                ],
            }
        )
    return {"events": evs, "requestedSeason": {"year": 2027}}


def _college_espn(slug: str, seen: list[str]):  # type: ignore[no-untyped-def]
    def handle(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        seen.append(p + ("?" + str(req.url.params) if req.url.params else ""))
        if p.endswith(f"/{slug}/teams"):
            return httpx.Response(
                200,
                json={
                    "sports": [
                        {
                            "leagues": [
                                {
                                    "teams": [
                                        {
                                            "team": {
                                                "id": t["id"],
                                                "abbreviation": t["abbr"],
                                                "location": t["location"],
                                                "shortDisplayName": t["short"],
                                                "displayName": t["name"],
                                            }
                                        }
                                        for t in ESPN_TEAMS
                                    ]
                                }
                            ]
                        }
                    ]
                },
            )
        if p.endswith(f"/{slug}/teams/30/schedule"):
            # 20 games this season: enough for an edge if the lineup were known
            return httpx.Response(200, json=_schedule(20, "30"))
        return httpx.Response(404)

    return handle


@pytest.fixture
def cset(settings: Settings) -> Settings:
    return Settings(_env_file=None, database_url=settings.database_url, llm_provider="openai")


@pytest.mark.parametrize(
    ("lg", "slug", "label"),
    [
        ("NCAAMB", "mens-college-basketball", "NCAA men's"),
        ("NCAAWB", "womens-college-basketball", "NCAA women's"),
    ],
)
def test_college_investigation_never_shows_an_edge_without_a_lineup(
    cset: Settings, lg: str, slug: str, label: str
) -> None:
    engine = make_engine(cset.database_url)
    CatalogWriter(make_session_factory(engine), NOW).write_page(_page(lg))
    app = create_app(cset, FrozenClock(NOW))
    seen: list[str] = []
    app.state.espn = EspnSource(
        transport=httpx.MockTransport(_college_espn(slug, seen)),
        min_interval=0.0,
        sleep=lambda _: None,
    )
    with TestClient(app, base_url="http://127.0.0.1") as c:
        r = c.post(
            "/api/research/investigations",
            json={"ticker": f"KX{lg}GAME-{KEY}-USC", "side": "yes"},
            headers=H,
        )
        assert r.status_code == 200, r.text
        res = r.json()
        sp = c.post(
            "/api/research/investigations",
            json={"ticker": f"KX{lg}SPREAD-{KEY}-USC28", "side": "yes"},
            headers=H,
        ).json()
        inj = c.get(f"/api/games/KX{lg}/{KEY}/injuries").json()
    engine.dispose()

    h = res["hypothesis"]
    assert h["league"] == label and h["market_type"] == "moneyline"
    p = res["price_assessment"]
    assert p["model_p"] is not None  # box scores were found (team matched by name)
    assert p["conservative_edge"] is None and p["walk_away"] is None
    assert any("no injury report for college" in a for a in p["abstain_reasons"])
    assert res["summary"]["findings"][0]["text"] == synth.LINEUP_UNKNOWN
    assert "E2" not in {s["id"] for s in res["sources"]}
    assert res["summary"]["gaps"][0].startswith("Who's playing tonight")
    assert "no injury report" in res["summary"]["takeaway"]
    assert sp["hypothesis"]["market_type"] == "spread" and sp["hypothesis"]["threshold"] == 27.5
    # The empty college injury feed is never fetched or presented as "everyone healthy".
    assert not any("injuries" in s for s in seen)
    assert inj == {"supported": False, "teams": []}
    assert any("limit=1000" in s for s in seen)  # all 360+ schools, not the first page


# --- news search --------------------------------------------------------------------------


def _hyp(league: str, kind: str = "total", line: float | None = 135.5) -> S.Hypothesis:
    return S.Hypothesis(
        ticker=f"KXNCAAMBTOTAL-{KEY}-136",
        event_ticker=f"KXNCAAMBTOTAL-{KEY}",
        side="yes",
        sport="basketball",
        league=league,
        market_type=kind,
        threshold=line,
        subject=None,
        label="Over 135.5",
        statement="Over 135.5",
        snapshot_at=None,
        rules_url=None,
    )  # type: ignore[arg-type]


TEAMS = [{"code": "TARL", "name": "Tarleton State Texans"}, {"code": "USC", "name": "USC Trojans"}]


def test_college_queries_name_the_sport() -> None:
    men = search.plan_queries(_hyp("NCAA men's"), TEAMS, 3)
    women = search.plan_queries(_hyp("NCAA women's"), TEAMS, 3)
    assert all(" basketball " in q and "women's" not in q for q in men)
    assert all("women's basketball" in q for q in women)


def test_college_news_filters_other_sports_and_programs() -> None:
    men, women = _hyp("NCAA men's"), _hyp("NCAA women's")
    football = "USC Trojans football beat Tarleton"
    assert search.sport_mismatch(men, football) and search.sport_mismatch(women, football)
    wbb = "USC Trojans women's basketball routs Tarleton State"
    assert search.sport_mismatch(men, wbb) and not search.sport_mismatch(women, wbb)
    mbb = "USC basketball: Trojans host Tarleton State"
    assert not search.sport_mismatch(men, mbb) and search.sport_mismatch(women, mbb)
    # The NBA path is unchanged.
    nba = _hyp("NBA")
    assert not search.sport_mismatch(nba, "Knicks beat Wolves")


def test_college_line_ranges_fit_college_scoring() -> None:
    assert search.line_match(_hyp("NCAA men's"), "over/under 135.5 tonight") == "exact"
    assert search.line_match(_hyp("NCAA men's"), "total set at 141.5") == "different_line"
    # The same 135.5 would be outside the NBA's plausible total range: no false "exact".
    assert search.line_match(_hyp("NBA"), "over/under 135.5 tonight") == "unknown"
    big = _hyp("NCAA men's", "spread", 45.5)
    assert search.line_match(big, "USC -45.5 against Tarleton") == "exact"


def test_synth_keeps_the_lineup_unknown_finding() -> None:
    from tests.test_research_synth import base, fake, good

    r = base()
    unknown = S.Finding(
        text=synth.LINEUP_UNKNOWN,
        kind="interpretation",
        stance="neutral",
        source_ids=[],
        verified=True,
    )
    r.summary.findings = [unknown, *r.summary.findings][:3]
    out = synth.apply(r, {}, fake(good()))
    assert out.summary.findings[0].text == synth.LINEUP_UNKNOWN
