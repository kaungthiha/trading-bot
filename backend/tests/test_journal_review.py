"""Your bet journal, leg post-mortems, warnings from past mistakes, lessons, the day review."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.clock import FrozenClock
from app.core.config import Settings
from app.db.models import AccountFill, AccountSettlement, ComboLeg, LegOutcome, Lesson
from app.db.session import make_engine, make_session_factory
from app.history import postmortem
from app.history.legs import LegRow, Warner, leg_record, parse_leg, warnings_for
from app.history.review_ai import parse_day
from app.main import create_app
from app.sportsdata.espn import GameRow

NOW = datetime(2026, 11, 25, 15, 0, tzinfo=UTC)
NIGHT = datetime(2026, 11, 25, 1, 0, tzinfo=UTC)  # 8pm ET on Nov 24
D = Decimal

CADE = "KXNBAPTS-26NOV24DETORL-DETCCUNNINGHAM2-25"
CADE_OLD = "KXNBAPTS-26NOV20DETBOS-DETCCUNNINGHAM2-25"
DUREN = "KXNBAREB-26NOV24DETORL-DETJDUREN0-10"
BANCH = "KXNBAPTS-26NOV24DETORL-ORLPBANCHERO5-20"
WIN = "KXNBAGAME-26NOV24DETORL-DET"
COMBO = "KXMVECROSSCATEGORY-S2026AAA-1"
OLD_COMBO = "KXMVECROSSCATEGORY-S2026BBB-1"


def test_parse_leg_props_and_team_lines() -> None:
    p = parse_leg(CADE, "Cade Cunningham: 25+ points")
    assert (p["kind"], p["player"], p["stat"], p["line"], p["date"], p["team"], p["teams"]) == (
        "player_stat", "Cade Cunningham", "PTS", 25.0, "2026-11-24", "DET", ["DET", "ORL"])
    s = parse_leg("KXNBASPREAD-26NOV20ORLBKN-ORL3", "Orlando wins by over 2.5 points")
    assert (s["kind"], s["team"], s["team_name"], s["line"]) == ("team_margin", "ORL", "Orlando",
                                                                 2.5)
    t = parse_leg("KXNBATOTAL-26NOV19LACSAS-236", "Full Game: Over 235.5 points scored")
    assert (t["kind"], t["line"], t["team_name"]) == ("game_total", 235.5, None)
    pr = parse_leg("KXNBA3PTPROT-26NOV18ATLOKC-ATLNALEXANDERWALKER7-2",
                   "Nickeil Alexander-Walker: 2+ threes")
    assert (pr["stat"], pr["player"], pr["prefix"]) == ("3PT", "Nickeil Alexander-Walker", "KXNBA")
    assert parse_leg("KXWEIRD-X")["kind"] == "other"


@pytest.fixture
def factory(settings: Settings):  # type: ignore[no-untyped-def]
    engine = make_engine(settings.database_url)
    yield make_session_factory(engine)
    engine.dispose()


def _fill(fid: str, ticker: str, side: str, count: str, price: str, at: datetime) -> AccountFill:
    return AccountFill(fill_id=fid, ticker=ticker, order_id="o" + fid, side=side, action="buy",
                       is_taker=True, count=D(count), price=D(price), yes_price=D(price),
                       fee=D("0.02"), created_at=at, source="live")


def _seed(f: Any) -> None:
    """Two combos: last week's (Cade under 25 lost: he scored 34) and tonight's (Cade under
    25 lost again, Duren and Banchero won)."""
    with f() as s:
        s.add_all([
            _fill("1", OLD_COMBO, "yes", "10", "0.20", NIGHT - timedelta(days=4)),
            _fill("2", COMBO, "yes", "10", "0.15", NIGHT),
            AccountSettlement(ticker=OLD_COMBO, event_ticker="E", market_result="no",
                              yes_count=D(10), yes_cost=D(2), no_count=D(0), no_cost=D(0),
                              revenue=D(0), fee=D(0), settled_at=NIGHT - timedelta(days=3)),
            AccountSettlement(ticker=COMBO, event_ticker="E", market_result="no",
                              yes_count=D(10), yes_cost=D("1.5"), no_count=D(0), no_cost=D(0),
                              revenue=D(0), fee=D(0), settled_at=NOW),
        ])
        for combo, legs in ((OLD_COMBO, [(CADE_OLD, "no", "yes"), (WIN, "yes", "yes")]),
                            (COMBO, [(CADE, "no", "yes"), (DUREN, "yes", "yes"),
                                     (BANCH, "yes", "yes")])):
            for t, side, result in legs:
                title = {CADE: "Cade Cunningham: 25+ points",
                         CADE_OLD: "Cade Cunningham: 25+ points",
                         DUREN: "Jalen Duren: 10+ rebounds",
                         BANCH: "Paolo Banchero: 20+ points", WIN: "Detroit wins"}[t]
                s.add(ComboLeg(combo_ticker=combo, leg_ticker=t, event_ticker=t.rsplit("-", 1)[0],
                               side=side, title=title, result=result, refreshed_at=NOW))
        s.add(LegOutcome(leg_ticker=CADE_OLD, kind="player_stat", subject="Cade Cunningham",
                         stat="PTS", line=25, actual=34, minutes=38, note="vs BOS",
                         checked_at=NOW))
        s.commit()


def test_record_and_warnings_from_past_mistakes(factory) -> None:  # type: ignore[no-untyped-def]
    _seed(factory)
    with factory() as s:
        rec = leg_record(s)
        assert (rec["legs"], rec["won"], rec["lost"]) == (5, 3, 2)
        cade = next(x for x in rec["hurt"] if x["name"] == "Cade Cunningham")
        assert cade["lost"] == 2 and cade["recent_losses"][1]["what_happened"] == \
            "had 34 points vs the 25+ line, 38 min"
        s.add(Lesson(created_at=NOW, day="2026-11-24", text="Stop fading Cade at home.",
                     player="Cade Cunningham", stat="PTS", side="no", author="model",
                     active=True))
        s.add(Lesson(created_at=NOW, day="2026-11-24", text="Keep combos to 3 legs.",
                     author="you", active=True))
        s.commit()
        new = "KXNBAPTS-26NOV28DETMIA-DETCCUNNINGHAM2-25"
        w = warnings_for(s, [{"ticker": new, "side": "no", "title": "Cade Cunningham: 25+ points"},
                             {"ticker": new, "side": "yes",
                              "title": "Cade Cunningham: 25+ points"}])
    under = w["legs"][f"{new}:no"]
    same = next(x for x in under if x["kind"] == "same_bet")
    assert same["level"] == "high" and "0-2" in same["text"]
    assert "had 34 points vs the 25+ line" in same["text"]
    assert any(x["kind"] == "lesson" and "Stop fading Cade" in x["text"] for x in under)
    # The over on the same player isn't the same mistake: no same-bet warning, no lesson.
    assert not any(x["kind"] in ("same_bet", "lesson") for x in w["legs"][f"{new}:yes"])
    assert w["general_lessons"][0]["text"] == "Keep combos to 3 legs."
    # A leg-type lesson (unders on points, any player) flags every such leg, at medium level.
    with factory() as s:
        s.add(Lesson(created_at=NOW, day="2026-11-24", text="Points unders keep losing.",
                     stat="PTS", side="no", author="model", active=True))
        s.commit()
        other = "KXNBAPTS-26NOV28MIABOS-BOSJTATUM0-30"
        w2 = warnings_for(s, [{"ticker": other, "side": "no", "title": "Jayson Tatum: 30+ points"},
                              {"ticker": other, "side": "yes",
                               "title": "Jayson Tatum: 30+ points"}])
    hit = [x for x in w2["legs"][f"{other}:no"] if x["kind"] == "lesson"]
    assert [x["level"] for x in hit] == ["medium"] and "Points unders" in hit[0]["text"]
    assert not any(x["kind"] == "lesson" for x in w2["legs"][f"{other}:yes"])
    assert all(g["text"] != "Points unders keep losing." for g in w2["general_lessons"])


class FakeEspn:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def player_id(self, league: str, name: str) -> str | None:
        self.calls.append(name)
        return "1" if name == "Cade Cunningham" else None

    def player_log(self, league: str, pid: str) -> list[GameRow]:
        return [GameRow("e1", "2026-11-25", "current", "ORL", True, True, 120, 110,
                        {"PTS": 31.0, "MIN": 36.0}, et_date="2026-11-24")]

    def team(self, league: str, code: str, name: str | None = None) -> dict[str, str] | None:
        return {"id": "8", "name": "Detroit Pistons"}

    def team_log(self, league: str, team_id: str) -> list[GameRow]:
        return [GameRow("e1", "2026-11-25", "current", "ORL", True, True, 120, 110, {},
                        et_date="2026-11-24")]


def test_postmortem_fills_actual_stats_once(factory) -> None:  # type: ignore[no-untyped-def]
    legs = [LegRow(CADE, "no", "", "yes", {COMBO}, parse_leg(CADE, "Cade Cunningham: 25+ points")),
            LegRow(BANCH, "yes", "", "yes", {COMBO},
                   parse_leg(BANCH, "Paolo Banchero: 20+ points")),
            LegRow(WIN, "yes", "", "yes", {COMBO}, parse_leg(WIN, "Detroit wins"))]
    src = FakeEspn()
    out = postmortem.fill_outcomes(factory, src, legs, NOW)  # type: ignore[arg-type]
    assert out == {"checked": 3, "pending": 0}
    with factory() as s:
        cade = s.get(LegOutcome, CADE)
        assert (cade.actual, cade.minutes, cade.line) == (31.0, 36.0, 25.0)
        assert "Couldn't find" in s.get(LegOutcome, BANCH).note
        assert s.get(LegOutcome, WIN).note == "Final: DET 120-110 vs ORL"
    # Known results are never fetched again; a miss is retried only after a while.
    src.calls.clear()
    postmortem.fill_outcomes(factory, src, legs, NOW + timedelta(hours=1))  # type: ignore[arg-type]
    assert src.calls == []


def test_day_review_parse_keeps_only_real_tags_and_sources() -> None:
    raw = {"summary": "s", "went_right": ["Rebounds legs hit."],
           "went_wrong": [{"text": "Cade went off for 31.", "kind": "luck",
                           "sources": ["N1", "N7"]},
                          {"text": "Bad kind", "kind": "fate", "sources": []}],
           "lessons": [{"text": "Don't fade Cade at home.", "player": "cade cunningham",
                        "stat": "pts", "side": "no"},
                       {"text": "Made-up player lesson.", "player": "LeBron James",
                        "stat": "PTS", "side": "yes"},
                       {"text": "Fewer legs.", "player": None, "stat": None, "side": None}],
           "next_time": ["Check minutes first."]}
    out = parse_day(json.dumps(raw), {"Cade Cunningham", "Jalen Duren"}, {"N1"})
    assert out["went_wrong"][0]["sources"] == ["N1"] and out["went_wrong"][1]["kind"] == "unclear"
    assert out["lessons"][0] == {"text": "Don't fade Cade at home.", "player": "Cade Cunningham",
                                 "stat": "PTS", "side": "no"}
    # A player who wasn't in the day's legs can't be tagged: it becomes a leg-type lesson.
    assert out["lessons"][1] == {"text": "Made-up player lesson.", "player": None, "stat": "PTS",
                                 "side": "yes"}
    assert out["lessons"][2]["side"] is None and out["lessons"][2]["stat"] is None


@pytest.fixture
def api(settings: Settings):  # type: ignore[no-untyped-def]
    s = settings.model_copy(update={"sports_evidence_enabled": False,
                                    "llm_provider": "ollama"})
    app = create_app(s, FrozenClock(NOW))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c
    app.state.engine.dispose()


J = {"X-KRT-Request": "journal"}


def test_journal_queue_matches_your_kalshi_buy(api: TestClient) -> None:
    legs = [{"ticker": CADE, "side": "no", "label": "Cade Cunningham pts 25+", "price": 0.55},
            {"ticker": DUREN, "side": "yes", "label": "Jalen Duren reb 10+"},
            {"ticker": BANCH, "side": "yes", "label": "Paolo Banchero pts 20+"}]
    body = {"legs": legs, "my_price": "0.15", "stake": "1.50", "note": "Cade cold lately",
            "market_price": "0.1612", "source": "slate"}
    assert api.post("/api/journal", json=body).status_code == 403  # CSRF header required
    e = api.post("/api/journal", json=body, headers=J).json()
    assert e["status"] == "queued" and e["kalshi"] is None and e["note"] == "Cade cold lately"
    assert api.post("/api/journal", json={**body, "my_price": "1.5"}, headers=J).status_code == 422
    # Your history syncs: the same three legs as a combo you bought -> linked, marked placed.
    _seed(make_session_factory(api.app.state.engine))  # type: ignore[attr-defined]
    items = api.get("/api/journal").json()["items"]
    got = next(x for x in items if x["id"] == e["id"])
    assert got["status"] == "placed" and got["kalshi"]["ticker"] == COMBO
    assert got["kalshi"]["avg_price"] == "0.1500" and got["kalshi"]["status"] == "settled"
    assert got["legs_outcome"] == "lost"
    assert {lg["ticker"]: lg["status"] for lg in got["legs"]}[CADE] == "lost"
    up = api.post(f"/api/journal/{e['id']}", json={"note": "Cade went off"}, headers=J).json()
    assert up["note"] == "Cade went off" and up["stake"] == "1.50"
    assert api.post(f"/api/journal/{e['id']}/remove", headers=J).json() == {"removed": e["id"]}
    assert api.post("/api/journal/nope/remove", headers=J).status_code == 404


def test_day_view_warnings_and_lessons_api(api: TestClient) -> None:
    _seed(make_session_factory(api.app.state.engine))  # type: ignore[attr-defined]
    days = api.get("/api/history/days").json()["days"]
    assert [d["date"] for d in days] == ["2026-11-24", "2026-11-20"]
    d = api.get("/api/history/day", params={"date": "2026-11-24"}).json()
    assert d["totals"]["bets"] == 1 and d["totals"]["combos_sunk_by_one"] == 1
    bet = d["bets"][0]
    assert bet["avg_price"] == "0.1500" and bet["max_payout"] == "10.00" and bet["sunk_by_one"]
    assert d["breakers"][0]["title"] == "Cade Cunningham: 25+ points"
    assert api.get("/api/history/day", params={"date": "24-11-2026"}).status_code == 422
    top = api.get("/api/history/top").json()
    assert top["losers"][0]["ticker"] in (COMBO, OLD_COMBO) and top["winners"] == []
    w = api.get("/api/history/warnings", params={"legs": f"{CADE}:no"}).json()
    assert w["history_legs"] == 5
    assert api.get("/api/history/warnings", params={"legs": f"{CADE}:maybe"}).status_code == 422
    L = {"X-KRT-Request": "lesson"}
    assert api.post("/api/history/lessons", json={"text": "No unders on stars"}).status_code == 403
    assert api.post("/api/history/lessons", json={"text": "No unders on Cade",
                                                  "player": "Cade Cunningham", "stat": "pts",
                                                  "side": "no"}, headers=L).json() == {"saved": 1}
    items = api.get("/api/history/lessons").json()["items"]
    assert items[0]["stat"] == "PTS" and items[0]["author"] == "you"
    w = api.get("/api/history/warnings", params={"legs": f"{CADE}:no"}).json()
    assert any(x["kind"] == "lesson" for x in w["legs"][f"{CADE}:no"])
    api.post(f"/api/history/lessons/{items[0]['id']}/remove", headers=L)
    assert api.get("/api/history/lessons").json()["items"] == []
    assert api.get("/api/history/legs").json()["lost"] == 2


class FakeOllama:
    model = "fake:1b"

    def __init__(self) -> None:
        self.facts: dict[str, Any] = {}

    def chat_json(self, system: str, facts: dict[str, Any], schema: dict[str, Any]
                  ) -> tuple[str, dict[str, Any]]:
        self.facts = facts
        return json.dumps({
            "summary": "Cade sank it again.", "went_right": ["Duren and Banchero hit."],
            "went_wrong": [{"text": "Second straight Cade under lost.", "kind": "process",
                            "sources": []}],
            "lessons": [{"text": "Stop fading Cade Cunningham's points.",
                         "player": "Cade Cunningham", "stat": "PTS", "side": "no"}],
            "next_time": ["Check his last 5 before an under."]}), {"model": "fake:1b",
                                                                   "seconds": 1.0}

    def close(self) -> None:
        pass


def test_day_review_saves_lessons_that_warn_next_time(api: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _seed(make_session_factory(api.app.state.engine))  # type: ignore[attr-defined]
    fake = FakeOllama()
    monkeypatch.setattr("app.sportsdata.llm.make_client", lambda settings: fake)
    R = {"X-KRT-Request": "review"}
    assert api.post("/api/history/day/review", json={"date": "2026-11-24"}).status_code == 403
    r = api.post("/api/history/day/review", json={"date": "2026-11-24"}, headers=R).json()
    assert r["lessons_saved"] == 1 and r["news_info"]["status"] == "no_key"
    assert r["went_wrong"][0]["kind"] == "process" and not r["cached"]
    # The model saw the bet, every leg's result and your long-run record.
    assert fake.facts["bets"][0]["legs"][0]["result"] in ("won", "lost")
    assert fake.facts["legs_that_sank_combos"][0]["leg"].startswith("NO · Cade")
    assert fake.facts["long_run_record_by_category"]
    again = api.post("/api/history/day/review", json={"date": "2026-11-24"}, headers=R).json()
    assert again["cached"] is True
    w = api.get("/api/history/warnings", params={"legs": f"{CADE}:no"}).json()
    assert any("Stop fading Cade" in x["text"] for x in w["legs"][f"{CADE}:no"])
    assert api.post("/api/history/day/review", json={"date": "2026-11-01"},
                    headers=R).status_code == 409


def test_warner_without_history_is_quiet(factory) -> None:  # type: ignore[no-untyped-def]
    with factory() as s:
        assert Warner(s).for_leg(CADE, "no", "Cade Cunningham: 25+ points") == []
