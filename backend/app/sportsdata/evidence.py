"""Check combo legs against what actually happened in past games.

For each leg: how often its condition held recently (last 5/10, this season, last season),
a shrunk estimate with an 80% interval, and whether the market price sits inside it.
For legs tied to the same team: how often they landed TOGETHER, versus what independence
predicts. That ratio (the "lift") is the correlation the independent combo price ignores.

This is evidence, not a model: box scores don't know about tonight's matchup, minutes,
or injuries. The UI says so.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import Any

from app.adapters.base import AdapterError
from app.sportsdata.espn import COLLEGE, LEAGUES, EspnSource, GameRow

PRIOR_GAMES = 10   # last season counts as this many games of prior belief
JOINT_PRIOR = 15   # pull the observed together-rate toward independence by this many games
MIN_GAMES = 8
Z80 = 1.2816

Pred = Callable[[GameRow], bool | None]


def wilson(p: float, n: float, z: float = Z80) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def predicate(spec: dict[str, Any], side: str) -> tuple[Pred, Callable[[GameRow], float | None]]:
    """(did YES/NO happen in this game?, the number plotted for it)."""
    kind = spec["kind"]
    if kind == "player_stat":
        stat, n = spec["stat"], spec["at_least"]

        def value(r: GameRow) -> float | None:
            return r.stats.get(stat)

        def yes(r: GameRow) -> bool | None:
            v = value(r)
            return None if v is None else v >= n
    elif kind == "team_win":
        def value(r: GameRow) -> float | None:
            return None if r.team_score is None or r.opp_score is None else \
                float(r.team_score - r.opp_score)

        def yes(r: GameRow) -> bool | None:
            return r.won
    elif kind == "team_margin":
        k = spec["over"]

        def value(r: GameRow) -> float | None:
            return None if r.team_score is None or r.opp_score is None else \
                float(r.team_score - r.opp_score)

        def yes(r: GameRow) -> bool | None:
            v = value(r)
            return None if v is None else v > k
    elif kind == "game_total":
        k = spec["over"]

        def value(r: GameRow) -> float | None:
            return None if r.team_score is None or r.opp_score is None else \
                float(r.team_score + r.opp_score)

        def yes(r: GameRow) -> bool | None:
            v = value(r)
            return None if v is None else v > k
    elif kind == "team_total":
        k = spec["over"]

        def value(r: GameRow) -> float | None:
            return None if r.team_score is None else float(r.team_score)

        def yes(r: GameRow) -> bool | None:
            v = value(r)
            return None if v is None else v > k
    else:  # pragma: no cover - leg_spec only emits the kinds above
        raise ValueError(kind)
    if side == "no":
        return (lambda r: None if (y := yes(r)) is None else not y), value
    return yes, value


def avg_text(leg: dict[str, Any]) -> str | None:
    """The season average with its unit, so a reader (or a model) can't mistake a +0.9 point
    margin for a 0.9 win rate."""
    v, kind = leg.get("season_avg"), leg.get("kind")
    if v is None:
        return None
    if kind == "player_stat":
        return f"{v:.1f} {leg.get('stat') or ''} per game".replace("  ", " ")
    if kind in ("team_win", "team_margin"):
        return f"{v:+.1f} pts average margin"
    if kind == "game_total":
        return f"{v:.1f} total points per game"
    if kind == "team_total":
        return f"{v:.1f} team points per game"
    return f"{v}"


def line_of(spec: dict[str, Any]) -> float | None:
    if spec["kind"] == "player_stat":
        return None if spec["stat"] in ("2D", "3D") else spec["at_least"] - 0.5
    return spec.get("over") if spec["kind"] != "team_win" else 0.0


def _count(rows: Sequence[GameRow], pred: Pred) -> tuple[int, int]:
    res = [x for r in rows if (x := pred(r)) is not None]
    return sum(res), len(res)


def leg_summary(rows: Sequence[GameRow], pred: Pred, value: Callable[[GameRow], float | None],
                market: float | None) -> dict[str, Any]:
    cur = [r for r in rows if r.season == "current"]
    prev = [r for r in rows if r.season == "previous"]
    h5, n5 = _count(rows[:5], pred)
    h10, n10 = _count(rows[:10], pred)
    hc, nc = _count(cur, pred)
    hp, np_ = _count(prev, pred)
    prior = hp / np_ if np_ else 0.5
    m = min(PRIOR_GAMES, np_) if np_ else 2
    est = (hc + m * prior) / (nc + m)
    lo, hi = wilson(est, nc + m)
    if nc + np_ < MIN_GAMES:
        verdict = "thin"
    elif market is None:
        verdict = "no_price"
    elif market > hi:
        verdict = "market_higher"   # price says likelier than history: lean NO / skip
    elif market < lo:
        verdict = "market_lower"    # history says likelier than the price: worth a look
    else:
        verdict = "agrees"
    recent = []
    for r in rows[:10]:
        v = value(r)
        recent.append({"date": r.date, "opponent": r.opponent, "home": r.home,
                       "value": v, "hit": pred(r)})
    vals = [v for r in cur if (v := value(r)) is not None]
    return {
        "windows": {"last5": [h5, n5], "last10": [h10, n10], "season": [hc, nc],
                    "last_season": [hp, np_]},
        "estimate": round(est, 4), "interval": [round(lo, 4), round(hi, 4)],
        "market": None if market is None else round(market, 4),
        "verdict": verdict,
        "season_avg": round(sum(vals) / len(vals), 2) if vals else None,
        "recent": recent,
    }


def joint(rows_by_leg: dict[str, dict[str, GameRow]],
          preds: dict[str, Pred]) -> dict[str, Any] | None:
    """Legs observed in the same past games: how often all landed vs independence."""
    common = set.intersection(*(set(r) for r in rows_by_leg.values())) if rows_by_leg else set()
    hits: dict[str, int] = defaultdict(int)
    together = n = 0
    for eid in common:
        # Same game, same side: a player who switched teams may have faced this team last
        # season; that game is in both logs but from opposite benches.
        if len({rows_by_leg[t][eid].opponent for t in rows_by_leg}) > 1:
            continue
        res = {t: preds[t](rows_by_leg[t][eid]) for t in rows_by_leg}
        if any(v is None for v in res.values()):
            continue
        n += 1
        for t, v in res.items():
            hits[t] += int(bool(v))
        together += int(all(res.values()))
    if n < MIN_GAMES:
        return {"games": n, "together": together, "expected": None, "lift": None}
    prod = math.prod(hits[t] / n for t in rows_by_leg)
    shrunk = (together + JOINT_PRIOR * prod) / (n + JOINT_PRIOR)
    return {"games": n, "together": together, "expected": round(prod * n, 2),
            "lift": round(shrunk / prod, 3) if prod > 0 else None}


class EvidenceService:
    def __init__(self, source: EspnSource) -> None:
        self.source = source

    def _team_ref(self, league: str, code: str, names: dict[str, str]) -> dict[str, str] | None:
        try:
            return self.source.team(league, code, names.get(code))
        except AdapterError:
            return None

    def legs(self, legs: list[dict[str, Any]], team_names: dict[str, dict[str, str]]
             ) -> dict[str, Any]:
        """legs: [{ticker, side, spec, prefix, game_key, implied, label}]."""
        out: list[dict[str, Any]] = []
        groups: dict[tuple[str, str, str], list[tuple[str, dict[str, GameRow], Pred]]] = \
            defaultdict(list)
        injuries: dict[str, list[dict[str, str]]] = {}
        # A game total can be checked from either team's games: use the team the other
        # legs of that game are about, so it joins their correlation check.
        team_votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for lg in legs:
            if lg.get("spec") and lg["spec"].get("team"):
                team_votes[lg["game_key"]][lg["spec"]["team"]] += 1
        for lg in legs:
            spec, prefix = lg.get("spec"), lg.get("prefix")
            base = {"ticker": lg["ticker"], "side": lg["side"], "label": lg["label"]}
            league = LEAGUES.get(prefix or "")
            if spec is None or league is None:
                out.append({**base, "supported": False,
                            "reason": "No box-score check for this market type yet"
                            if league else
                            "Evidence covers NBA, WNBA and college basketball games only"})
                continue
            market = lg["implied"] if lg["side"] == "yes" or lg["implied"] is None \
                else 1 - lg["implied"]
            pred, value = predicate(spec, lg["side"])
            names = team_names.get(lg["game_key"], {})
            try:
                if spec["kind"] == "player_stat":
                    pid = self.source.player_id(league, spec["player"])
                    if pid is None:
                        out.append({**base, "supported": False,
                                    "reason": f"Couldn't find {spec['player']} on ESPN"})
                        continue
                    rows = self.source.player_log(league, pid)
                    subject = {"type": "player", "name": spec["player"], "team": spec["team"],
                               "espn_url": f"https://www.espn.com/{league}/player/_/id/{pid}"}
                    team_code = spec["team"]
                else:
                    votes = team_votes.get(lg["game_key"]) or {}
                    code = spec.get("team") or (max(votes, key=lambda c: votes[c]) if votes
                                                else next(iter(names), None))
                    ref = self._team_ref(league, code, names) if code else None
                    if ref is None:
                        out.append({**base, "supported": False,
                                    "reason": "Couldn't match the team on ESPN"})
                        continue
                    rows = self.source.team_log(league, ref["id"])
                    subject = {"type": "team", "name": ref["name"], "team": code,
                               "espn_url": None}
                    team_code = code
                if league in COLLEGE:
                    injuries[league] = []  # ESPN publishes no college injury report
                elif league not in injuries:
                    try:
                        injuries[league] = self.source.injuries(league)
                    except AdapterError:
                        injuries[league] = []
            except AdapterError as e:
                out.append({**base, "supported": False, "reason": f"ESPN unavailable: {e}"})
                continue
            if not rows:
                out.append({**base, "supported": False, "reason": "No games on record"})
                continue
            inj = None
            if spec["kind"] == "player_stat":
                inj = next((i for i in injuries.get(league, [])
                            if i["player"].lower() == spec["player"].lower()), None)
            out.append({**base, "supported": True, "subject": subject, "kind": spec["kind"],
                        "line": line_of(spec), "stat": spec.get("stat"),
                        "injury": inj, **leg_summary(rows, pred, value, market)})
            if team_code:
                groups[(lg["game_key"], team_code, league)].append(
                    (lg["ticker"], {r.event_id: r for r in rows}, pred))

        correlation = []
        for (gk, team, _), items in groups.items():
            # one entry per ticker (two legs on one market aren't a real combo)
            uniq = {t: (rows, p) for t, rows, p in items}
            if len(uniq) < 2:
                continue
            j = joint({t: r for t, (r, _) in uniq.items()}, {t: p for t, (_, p) in uniq.items()})
            if j:
                correlation.append({"game_key": gk, "team": team, "legs": sorted(uniq), **j})
        return {"legs": out, "correlation": correlation}


def adjusted_probability(independent: float | None, correlation: list[dict[str, Any]],
                         leg_probs: dict[str, float]) -> float | None:
    """Market's independent joint price x each same-team group's historical lift, capped by
    the least likely leg (a combo can't beat its weakest leg)."""
    if independent is None:
        return None
    p = independent
    for c in correlation:
        if c.get("lift"):
            p *= c["lift"]
    cap = min(leg_probs.values()) if leg_probs else 1.0
    return round(max(0.0, min(p, cap)), 4)
