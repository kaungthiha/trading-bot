"""Your record leg by leg: every leg inside the combos you traded, how it resolved, what the
player actually did (leg_outcomes), and warnings when a new bet repeats a past mistake.

Local data only. A leg that sat in several of your combos counts once in the record (it was
one outcome), with the number of combos it was in kept for the warning text."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CatalogMarket, ComboLeg, LegOutcome, Lesson

SUFFIXES = ("TEAMTOTAL", "GAME", "SPREAD", "TOTAL", "PTS", "REB", "AST", "3PT", "PRA", "STL",
            "BLK", "STOCK", "2D", "3D", "TD", "RECYDS", "RSHYDS", "PASSYDS", "REC", "SOG", "GOAL")
_SERIES = re.compile(r"^(KX[A-Z0-9]+?)(" + "|".join(SUFFIXES) + r")(PROT)?$")
_KEY = re.compile(r"^(\d{2})([A-Z]{3})(\d{2})")
_MONTHS = {m: i for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
_PROP = re.compile(r"^(?P<player>.+?):\s*(?P<n>\d+(?:\.\d+)?)\+\s*(?P<what>.+?)\??$")
_NUM = re.compile(r"(\d+(?:\.\d+)?)")
PLAYER = {"PTS", "REB", "AST", "3PT", "PRA", "STL", "BLK", "STOCK", "2D", "3D", "TD", "RECYDS",
          "RSHYDS", "PASSYDS", "REC", "SOG", "GOAL"}
STAT_WORD = {"PTS": "points", "REB": "rebounds", "AST": "assists", "3PT": "threes",
             "PRA": "points+rebounds+assists", "STL": "steals", "BLK": "blocks",
             "STOCK": "steals+blocks", "2D": "double-double", "3D": "triple-double",
             "TD": "touchdowns", "RECYDS": "receiving yards", "RSHYDS": "rushing yards",
             "PASSYDS": "passing yards", "REC": "receptions", "SOG": "shots on goal",
             "GOAL": "goals"}
TEAM_WORD = {"GAME": "winner", "SPREAD": "spread", "TOTAL": "game total",
             "TEAMTOTAL": "team total"}
# A category needs this many resolved legs before its loss rate is quoted as a pattern.
MIN_PATTERN = 10
PATTERN_GAP = 0.10


def parse_leg(ticker: str, title: str = "") -> dict[str, Any]:
    """KXNBAPTS-26NOV24DETORL-DETCCUNNINGHAM2-25 + 'Cade Cunningham: 25+ points' ->
    {prefix, suffix, kind, player, stat, line, team, teams, date}. Unknown parts are None."""
    parts = ticker.split("-")
    m = _SERIES.match(parts[0])
    prefix, suffix = (m.group(1), m.group(2)) if m else (parts[0], "")
    out: dict[str, Any] = {"ticker": ticker, "prefix": prefix, "suffix": suffix,
                           "kind": "other", "player": None, "stat": None, "line": None,
                           "team": None, "teams": None, "date": None,
                           "game_key": parts[1] if len(parts) > 1 else None}
    if len(parts) > 1 and (k := _KEY.match(parts[1])) and k.group(2) in _MONTHS:
        try:
            out["date"] = date(2000 + int(k.group(1)), _MONTHS[k.group(2)],
                               int(k.group(3))).isoformat()
        except ValueError:
            pass
        codes = parts[1][7:]
        if re.fullmatch(r"\d{4}", codes[:4] or ""):  # esports keys carry a start time
            codes = codes[4:]
        if len(codes) == 6:
            out["teams"] = [codes[:3], codes[3:]]
    seg = parts[2] if len(parts) > 2 else ""
    if suffix in PLAYER:
        out["kind"] = "player_stat"
        out["stat"] = suffix
        p = _PROP.match(title.strip())
        if p:
            out["player"] = p.group("player").strip()
            out["line"] = float(p.group("n"))
        elif len(parts) > 3 and _NUM.fullmatch(parts[3]):
            out["line"] = float(parts[3])
        if out["teams"]:
            out["team"] = next((t for t in out["teams"] if seg.startswith(t)), None)
    elif suffix in TEAM_WORD:
        out["kind"] = {"GAME": "team_win", "SPREAD": "team_margin", "TOTAL": "game_total",
                       "TEAMTOTAL": "team_total"}[suffix]
        code = re.sub(r"\d+$", "", seg)
        out["team"] = code or None
        name = re.split(r" wins(?: |$|\?)| over \d", title.removeprefix("Full Game: "))[0]
        name = name.strip().rstrip("?")
        out["team_name"] = name if name and suffix != "TOTAL" else None
        n = _NUM.search(title) if suffix != "GAME" else None
        out["line"] = float(n.group(1)) if n else None
    return out


def subject(p: dict[str, Any]) -> str:
    return p["player"] or p.get("team_name") or p["team"] or p["ticker"]


def category(p: dict[str, Any], side: str) -> str:
    """'Unders on points', 'Overs on rebounds', 'Winners', 'Game total unders'..."""
    yes = side == "yes"
    if p["kind"] == "player_stat":
        return f"{'Overs' if yes else 'Unders'} on {STAT_WORD.get(p['stat'], p['stat'])}"
    if p["kind"] == "team_win":
        return "Picking winners" if yes else "Fading a team (NO on winner)"
    if p["kind"] == "team_margin":
        return "Spreads, to cover" if yes else "Spreads, not to cover"
    if p["kind"] == "game_total":
        return "Game total overs" if yes else "Game total unders"
    if p["kind"] == "team_total":
        return "Team total overs" if yes else "Team total unders"
    return f"{p['prefix']}{p['suffix']} {side.upper()}"


def _short_date(iso: str | None) -> str:
    if not iso:
        return ""
    d = date.fromisoformat(iso)
    return f"{d.strftime('%b')} {d.day}"


def outcome_text(p: dict[str, Any], side: str, o: LegOutcome | None) -> str | None:
    """'had 34 points vs the 25+ line (31 min)' from a stored outcome."""
    if o is None:
        return None
    if o.actual is None:
        return o.note or None
    mins = f", {o.minutes:g} min" if o.minutes is not None else ""
    if o.kind == "player_stat":
        word = STAT_WORD.get(o.stat or "", o.stat or "")
        if o.stat in ("2D", "3D"):
            return f"{'got' if o.actual else 'no'} {word}{mins}"
        line = f" vs the {o.line:g}+ line" if o.line is not None else ""
        return f"had {o.actual:g} {word}{line}{mins}"
    return o.note or f"{o.actual:g}"


@dataclass
class LegRow:
    ticker: str
    side: str
    title: str
    result: str | None       # market result yes/no, None = unresolved
    combos: set[str] = field(default_factory=set)
    parsed: dict[str, Any] = field(default_factory=dict)

    @property
    def won(self) -> bool | None:
        return None if self.result not in ("yes", "no") else self.result == self.side


def leg_rows(s: Session, combos: set[str] | None = None) -> list[LegRow]:
    """Distinct (leg, side) across the combos you traded, optionally only these combos."""
    q = select(ComboLeg)
    if combos is not None:
        q = q.where(ComboLeg.combo_ticker.in_(combos))
    by: dict[tuple[str, str], LegRow] = {}
    for lg in s.scalars(q):
        r = by.get((lg.leg_ticker, lg.side))
        if r is None:
            r = by[(lg.leg_ticker, lg.side)] = LegRow(lg.leg_ticker, lg.side, lg.title,
                                                       lg.result)
            r.parsed = parse_leg(lg.leg_ticker, lg.title)
        r.result = r.result or lg.result
        r.combos.add(lg.combo_ticker)
    return list(by.values())


def outcomes(s: Session, tickers: list[str]) -> dict[str, LegOutcome]:
    if not tickers:
        return {}
    out: dict[str, LegOutcome] = {}
    for i in range(0, len(tickers), 500):
        out.update({o.leg_ticker: o for o in s.scalars(select(LegOutcome).where(
            LegOutcome.leg_ticker.in_(tickers[i:i + 500])))})
    return out


def _tally(rows: list[LegRow]) -> dict[str, int]:
    won = sum(1 for r in rows if r.won is True)
    lost = sum(1 for r in rows if r.won is False)
    return {"n": won + lost, "won": won, "lost": lost}


def leg_record(s: Session, limit: int = 12) -> dict[str, Any]:
    """Who and what has carried or sunk your combos: by player/team and by category."""
    rows = [r for r in leg_rows(s) if r.won is not None]
    if not rows:
        return {"legs": 0, "by_subject": [], "by_category": [], "overall_loss_rate": None}
    outs = outcomes(s, [r.ticker for r in rows])
    by_subject: dict[str, list[LegRow]] = defaultdict(list)
    by_cat: dict[str, list[LegRow]] = defaultdict(list)
    for r in rows:
        by_subject[subject(r.parsed)].append(r)
        by_cat[category(r.parsed, r.side)].append(r)
    total = _tally(rows)
    overall = total["lost"] / total["n"]

    def subj(name: str, rs: list[LegRow]) -> dict[str, Any]:
        lost = [r for r in rs if r.won is False]
        lost.sort(key=lambda r: r.parsed.get("date") or "", reverse=True)
        return {"name": name, **_tally(rs),
                "combos_hurt": len({c for r in lost for c in r.combos}),
                "recent_losses": [{"bet": f"{r.side.upper()} · {r.title}",
                                   "date": r.parsed.get("date"),
                                   "what_happened": outcome_text(r.parsed, r.side,
                                                                 outs.get(r.ticker))}
                                  for r in lost[:3]]}

    subjects = [subj(k, v) for k, v in by_subject.items()]
    hurt = sorted((x for x in subjects if x["lost"] >= 2),
                  key=lambda x: (-x["lost"], x["won"]))[:limit]
    carried = sorted((x for x in subjects if x["won"] >= 3 and x["lost"] == 0),
                     key=lambda x: -x["won"])[:limit]
    cats = []
    for k, v in by_cat.items():
        t = _tally(v)
        rate = t["lost"] / t["n"] if t["n"] else None
        cats.append({"name": k, **t, "loss_rate": None if rate is None else round(rate, 3),
                     "pattern": t["n"] >= MIN_PATTERN and rate is not None
                     and rate >= overall + PATTERN_GAP})
    cats.sort(key=lambda x: (-x["lost"], -x["n"]))
    return {"legs": total["n"], "won": total["won"], "lost": total["lost"],
            "overall_loss_rate": round(overall, 3), "hurt": hurt, "carried": carried,
            "by_category": cats[:limit], "min_pattern": MIN_PATTERN}


# --- warnings for new bets ----------------------------------------------------------------------


def _titles(s: Session, tickers: list[str]) -> dict[str, str]:
    have = dict(s.execute(select(CatalogMarket.ticker, CatalogMarket.title)
                          .where(CatalogMarket.ticker.in_(tickers))).all())
    missing = [t for t in tickers if t not in have]
    if missing:
        have.update(dict(s.execute(select(ComboLeg.leg_ticker, ComboLeg.title)
                                   .where(ComboLeg.leg_ticker.in_(missing))).all()))
    return have


def active_lessons(s: Session, limit: int = 40) -> list[Lesson]:
    return list(s.scalars(select(Lesson).where(Lesson.active.is_(True))
                          .order_by(Lesson.created_at.desc()).limit(limit)))


def lesson_matches(lesson: Lesson, p: dict[str, Any], side: str) -> bool:
    """A player lesson matches that player (and its stat/side if set). A leg-type lesson (no
    player, a stat and usually a side, e.g. unders on points) matches every such leg. Team leg
    types use their series code as the stat (TOTAL, SPREAD, GAME, TEAMTOTAL)."""
    code = p.get("stat") or p.get("suffix")
    side_ok = lesson.side in (None, "", side)
    if not lesson.player:
        return bool(lesson.stat) and lesson.stat == code and side_ok
    who = {(p.get(k) or "").lower() for k in ("player", "team_name", "team")} - {""}
    if lesson.player.lower() not in who:
        return False
    return lesson.stat in (None, "", code) and side_ok


LESSON_CODES = set(STAT_WORD) | set(TEAM_WORD)


class Warner:
    """Built once per request from your history; answers for any number of legs."""

    def __init__(self, s: Session) -> None:
        rows = [r for r in leg_rows(s) if r.won is not None]
        self.rows = rows
        self.outs = outcomes(s, [r.ticker for r in rows])
        self.lessons = active_lessons(s)
        self.by_subject: dict[str, list[LegRow]] = defaultdict(list)
        self.by_cat: dict[str, list[LegRow]] = defaultdict(list)
        breakers: dict[str, int] = defaultdict(int)
        by_combo: dict[str, list[LegRow]] = defaultdict(list)
        for r in rows:
            self.by_subject[subject(r.parsed).lower()].append(r)
            self.by_cat[category(r.parsed, r.side)].append(r)
            for c in r.combos:
                by_combo[c].append(r)
        for legs in by_combo.values():
            misses = [r for r in legs if r.won is False]
            if len(misses) == 1:
                breakers[category(misses[0].parsed, misses[0].side)] += 1
        self.breakers = dict(breakers)
        t = _tally(rows)
        self.overall = t["lost"] / t["n"] if t["n"] else None

    def for_leg(self, ticker: str, side: str, title: str) -> list[dict[str, str]]:
        p = parse_leg(ticker, title)
        out: list[dict[str, str]] = []
        who = subject(p)
        same = [r for r in self.by_subject.get(who.lower(), []) if r.ticker != ticker
                or r.side != side]
        exact = [r for r in same if r.parsed.get("stat") == p.get("stat")
                 and r.parsed["kind"] == p["kind"] and r.side == side]
        # 1. The same bet type on the same player/team, lost before.
        lost = [r for r in exact if r.won is False]
        if lost:
            lost.sort(key=lambda r: r.parsed.get("date") or "", reverse=True)
            t = _tally(exact)
            seen = "; ".join(
                f"{_short_date(r.parsed.get('date'))}: {r.side.upper()} {r.title}"
                + (f" ({w})" if (w := outcome_text(r.parsed, r.side, self.outs.get(r.ticker)))
                   else "")
                for r in lost[:2])
            level = "high" if t["lost"] >= 2 and t["lost"] >= t["won"] else "medium"
            out.append({"level": level, "kind": "same_bet",
                        "text": f"{category(p, side)} for {who}: you're {t['won']}-{t['lost']} "
                                f"on this before. Lost: {seen}."})
        # 2. This player/team has sunk your legs more often than not.
        others = [r for r in same if r not in exact]
        t = _tally(others)
        if t["lost"] >= 2 and t["lost"] >= t["won"]:
            out.append({"level": "medium", "kind": "subject",
                        "text": f"{who} legs (other bets) went {t['won']}-{t['lost']} in your "
                                "combos."})
        # 3. A category that loses noticeably more often than your legs overall.
        cat = category(p, side)
        crs = self.by_cat.get(cat, [])
        ct = _tally(crs)
        if self.overall is not None and ct["n"] >= MIN_PATTERN:
            rate = ct["lost"] / ct["n"]
            if rate >= self.overall + PATTERN_GAP:
                out.append({"level": "medium", "kind": "category",
                            "text": f"{cat} lose {rate:.0%} of the time in your combos "
                                    f"({ct['lost']} of {ct['n']}), vs {self.overall:.0%} for "
                                    "all your legs."})
        top = max(self.breakers.items(), key=lambda kv: kv[1], default=None)
        if top and top[0] == cat and top[1] >= 3:
            out.append({"level": "info", "kind": "breaker",
                        "text": f"{cat} is the leg type that most often sank a combo by itself "
                                f"for you ({top[1]} combos lost by that one leg)."})
        # 4. Lessons you (or the model) wrote about this player and bet.
        for ls in self.lessons:
            if lesson_matches(ls, p, side):
                out.append({"level": "high" if ls.player else "medium", "kind": "lesson",
                            "text": f"Lesson from {_short_date(ls.day)}: {ls.text}"})
        return out


def warnings_for(s: Session, legs: list[dict[str, str]]) -> dict[str, Any]:
    """legs: [{ticker, side, title?}] -> {"legs": {"TICKER:side": [warning...]}, lessons}."""
    titles = _titles(s, [lg["ticker"] for lg in legs if not lg.get("title")])
    w = Warner(s)
    by: dict[str, list[dict[str, str]]] = {}
    for lg in legs:
        title = lg.get("title") or titles.get(lg["ticker"], "")
        by[f"{lg['ticker']}:{lg['side']}"] = w.for_leg(lg["ticker"], lg["side"], title)
    general = [{"day": ls.day, "text": ls.text, "id": ls.id} for ls in w.lessons
               if not ls.player and not ls.stat][:5]
    return {"legs": by, "general_lessons": general, "history_legs": len(w.rows)}
