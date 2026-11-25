"""What actually happened on the legs you traded: the player's stat line (or the final score)
against the leg's line, from ESPN game logs. Stored in leg_outcomes and never re-fetched once
known, so each player costs ESPN requests once.

Basketball (NBA, WNBA, college) only for now: that's where the app has box scores."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.base import AdapterError
from app.db.models import LegOutcome
from app.history.legs import STAT_WORD, LegRow, outcomes
from app.sportsdata.espn import LEAGUES, EspnSource, GameRow

log = logging.getLogger(__name__)
RETRY_AFTER = timedelta(hours=6)  # an unknown result (game not logged yet) is retried later


def _league(prefix: str) -> str | None:
    return LEAGUES.get(prefix)


def _row_on(rows: list[GameRow], day: str) -> GameRow | None:
    return next((r for r in rows if (r.et_date or r.date) == day), None)


def check_leg(src: EspnSource, p: dict[str, Any], cache: dict[tuple[str, str], Any]
              ) -> dict[str, Any] | None:
    """One leg -> {kind, subject, stat, line, actual, minutes, note}, or None if unsupported."""
    league = _league(p["prefix"])
    if league is None or not p.get("date"):
        return None
    if p["kind"] == "player_stat":
        if not p.get("player") or p["stat"] not in STAT_WORD:
            return None
        key = ("p", p["player"].lower())
        if key not in cache:
            pid = src.player_id(league, p["player"])
            cache[key] = src.player_log(league, pid) if pid else None
        rows = cache[key]
        base = {"kind": "player_stat", "subject": p["player"], "stat": p["stat"],
                "line": p.get("line")}
        if rows is None:
            return {**base, "actual": None, "minutes": None,
                    "note": f"Couldn't find {p['player']} on ESPN"}
        r = _row_on(rows, p["date"])
        if r is None:
            return {**base, "actual": None, "minutes": None,
                    "note": "No game on his log that day (didn't play, or not logged yet)"}
        return {**base, "actual": r.stats.get(p["stat"]), "minutes": r.stats.get("MIN"),
                "note": f"vs {r.opponent}" if r.opponent else ""}
    code = p.get("team") or (p["teams"][0] if p.get("teams") else None)
    if not code or p["kind"] not in ("team_win", "team_margin", "game_total", "team_total"):
        return None
    key = ("t", code)
    if key not in cache:
        ref = src.team(league, code, p.get("team_name"))
        cache[key] = src.team_log(league, ref["id"]) if ref else None
    rows = cache[key]
    base = {"kind": p["kind"], "subject": code, "stat": None, "line": p.get("line")}
    if rows is None:
        return {**base, "actual": None, "minutes": None, "note": f"Couldn't match {code} on ESPN"}
    r = _row_on(rows, p["date"])
    if r is None or r.team_score is None or r.opp_score is None:
        return {**base, "actual": None, "minutes": None, "note": "Final score not found"}
    score = f"{code} {r.team_score}-{r.opp_score} vs {r.opponent}"
    actual = {"team_win": float(r.team_score - r.opp_score),
              "team_margin": float(r.team_score - r.opp_score),
              "game_total": float(r.team_score + r.opp_score),
              "team_total": float(r.team_score)}[p["kind"]]
    return {**base, "actual": actual, "minutes": None, "note": f"Final: {score}"}


def fill_outcomes(factory: sessionmaker[Session], src: EspnSource, legs: list[LegRow],
                  now: datetime, max_subjects: int = 15) -> dict[str, int]:
    """Look up outcomes for resolved legs that don't have one yet. Bounded by distinct
    players/teams (each costs a few ESPN requests); the rest fill in on the next call."""
    with factory() as s:
        have = outcomes(s, [r.ticker for r in legs])
    todo = []
    for r in legs:
        o = have.get(r.ticker)
        if r.won is None or (o is not None and (o.actual is not None
                                                or now - o.checked_at < RETRY_AFTER)):
            continue
        todo.append(r)
    todo.sort(key=lambda r: (r.won is not False, len(r.combos) * -1))  # losses first
    cache: dict[tuple[str, str], Any] = {}
    rows, skipped = [], 0
    for r in todo:
        p = r.parsed
        who = (p.get("player") or p.get("team") or "").lower()
        if len(cache) >= max_subjects and not any(k[1] == who for k in cache):
            skipped += 1
            continue
        try:
            res = check_leg(src, p, cache)
        except AdapterError as e:
            log.info("outcome %s: %s", r.ticker, e)
            skipped += 1
            continue
        if res is None:
            continue
        rows.append({"leg_ticker": r.ticker, **res, "subject": res["subject"][:120],
                     "note": (res["note"] or "")[:300], "checked_at": now})
    if rows:
        with factory() as s:
            stmt = sqlite_insert(LegOutcome.__table__).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["leg_ticker"],
                set_={k: stmt.excluded[k] for k in ("actual", "minutes", "note", "line",
                                                     "checked_at")})
            s.execute(stmt)
            s.commit()
    return {"checked": len(rows), "pending": skipped}
