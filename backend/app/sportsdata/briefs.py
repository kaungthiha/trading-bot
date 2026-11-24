"""Qualitative leg briefs: the case for and against one leg, from free box-score data.

No probability and no edge. Each point is one checkable fact with its numbers, sorted into
"for", "against" or "context" for the side being bet:
- form: how often the line was reached lately, with averages;
- minutes: a role getting bigger or smaller than the season says;
- matchup: what tonight's opponent allows in that stat, ranked league-wide (ESPN team table);
- head-to-head: results against this opponent since last season;
- rest and venue: back-to-backs, a clear home/away split;
- injuries: his own status, and teammates out (a bigger role history can't show);
- price: where the market sits against his own history.

A point counts for or against only if it could disagree with the price: recent form and
head-to-head are compared with what the price implies (a 10-of-10 record on an 85% leg is
just why it costs 85%), and game-line matchups count only while the price is still open.
Minutes, rest, injuries, venue splits and the opponent's rank are things a price may not
fully reflect, so they count as they are. Thresholds are deliberately blunt, and every point
keeps its numbers, so a reader can disagree with the sorting. A "strong case" means several
facts point the same way: it is a reason to research the leg, not a forecast.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.sportsdata.espn import ALIASES, GameRow
from app.sportsdata.evidence import line_of, predicate

STAT_WORD = {"PTS": "points", "REB": "rebounds", "AST": "assists", "3PT": "threes",
             "BLK": "blocks", "STL": "steals", "PRA": "points + rebounds + assists",
             "STOCK": "steals + blocks", "2D": "double-double", "3D": "triple-double"}
# Prop stat -> fields of the ESPN team table that describe the opponent for it.
MATCHUP = {"PTS": ("allow_PTS",), "REB": ("allow_REB",), "AST": ("allow_AST",),
           "3PT": ("allow_3PT",), "PRA": ("allow_PTS", "allow_REB", "allow_AST"),
           "STL": ("own_TO",)}
OUT = ("out", "doubtful")
SHAKY = ("questionable", "day-to-day", "day to day", "game time")
FORM_GAP = 0.15          # recent hit rate vs the price, before it counts for or against
H2H_GAP = 0.25           # head-to-head hit rate vs the price (3+ meetings)
OPEN_PRICE = (0.25, 0.75)  # game-line matchup points count only while the price is open
MIN_SWING = 3.0           # minutes per game, last 5 vs season
SPLIT_GAP = 0.2           # home/away hit-rate gap worth mentioning
PRICE_GAP = 0.10          # market vs history
EARLY_GAMES = 8           # team-table sample below this is flagged


@dataclass
class Ctx:
    league: str                      # ESPN slug
    side: str                        # "yes" | "no"
    team: str | None                 # Kalshi code the leg is about
    opp: str | None                  # Kalshi code of tonight's opponent
    home: bool | None
    game_date: str                   # US Eastern date of tonight's game, yyyy-mm-dd
    names: dict[str, str] = field(default_factory=dict)        # Kalshi code -> display name
    table: dict[str, dict[str, float]] = field(default_factory=dict)  # ESPN team table
    injuries: list[dict[str, str]] | None = None   # None = no report for this league
    team_ids: dict[str, str] = field(default_factory=dict)     # Kalshi code -> ESPN team id
    opp_rows: list[GameRow] | None = None


def game_date(game_key: str) -> str:
    """'26NOV24NYKMIN' -> '2026-11-24' ('' if it doesn't parse)."""
    months = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
    try:
        return date(2000 + int(game_key[:2]), months.index(game_key[2:5]) + 1,
                    int(game_key[5:7])).isoformat()
    except (ValueError, IndexError):
        return ""


def espn_code(league: str, code: str | None) -> str | None:
    return None if code is None else ALIASES.get(league, {}).get(code, code)


def _ord(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _pt(text: str, kind: str, lean: int, no_side: str | None = None) -> dict[str, Any]:
    """lean is for the YES side (+1 for, -1 against, 0 context). no_side='context' keeps a
    point neutral when betting NO (e.g. an injury: a benching settles at a fair price)."""
    return {"text": text, "kind": kind, "lean": lean, "no_side": no_side}


def _vs_price(rate: float, m_yes: float | None, gap: float) -> int:
    """+1 if the record runs well above what the YES price implies, -1 well below."""
    if m_yes is None:
        return 0
    return 1 if rate >= m_yes + gap else -1 if rate <= m_yes - gap else 0


def _open(m_yes: float | None) -> bool:
    return m_yes is not None and OPEN_PRICE[0] <= m_yes <= OPEN_PRICE[1]


def _mean(xs: Sequence[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _before(rows: Sequence[GameRow], gdate: str) -> list[GameRow]:
    return [r for r in rows if not gdate or (r.et_date or r.date) < gdate]


def _rank(table: dict[str, dict[str, float]], keys: Sequence[str], team: str
          ) -> tuple[float, int, int, float, int] | None:
    """(value, rank where 1 = most, teams ranked, league average, games) or None."""
    vals = {t: sum(v[k] for k in keys) for t, v in table.items() if all(k in v for k in keys)}
    if team not in vals or len(vals) < 4:
        return None
    order = sorted(vals, key=lambda t: -vals[t])
    return (vals[team], order.index(team) + 1, len(vals), sum(vals.values()) / len(vals),
            int(table[team].get("gp", 0)))


def _band(rank: int, n: int) -> int:
    """+1 top quarter (allows the most), -1 bottom quarter, 0 between."""
    top = max(2, round(n * 0.27))
    return 1 if rank <= top else -1 if rank > n - top else 0


def _early(gp: int) -> str:
    return f" (only {gp} games in)" if gp and gp < EARLY_GAMES else ""


def _rest(prior: list[GameRow], gdate: str, who: str) -> dict[str, Any] | None:
    """who: 'He' or a team name."""
    last = (prior[0].et_date or prior[0].date) if prior else ""
    if not last or not gdate:
        return None
    try:
        days = (date.fromisoformat(gdate) - date.fromisoformat(last)).days
    except ValueError:
        return None
    if days == 1:
        verb = "is" if who == "He" else "are"
        return _pt(f"{who} {verb} on the second night of a back-to-back (played {last})",
                   "rest", -1)
    if days >= 3:
        return _pt(f"{who} {'has' if who == 'He' else 'have'} had {days - 1} days of rest",
                   "rest", 0)
    return None


def _injury(ctx: Ctx, player: str) -> dict[str, str] | None:
    return next((i for i in ctx.injuries or [] if i["player"].lower() == player.lower()), None)


def _outs(ctx: Ctx, code: str | None, skip: str = "") -> list[str]:
    tid = ctx.team_ids.get(code or "")
    if not tid or ctx.injuries is None:
        return []
    return [i["player"] for i in ctx.injuries
            if i["team_id"] == tid and any(w in i["status"].lower() for w in OUT)
            and i["player"].lower() != skip.lower()]


def _price(summary: dict[str, Any], market: float | None, whose: str) -> dict[str, Any] | None:
    """Side-relative already (the summary and market are for the side being bet)."""
    est = summary.get("estimate")
    if est is None or market is None:
        return None
    if market <= est - PRICE_GAP:
        return {"text": f"The price ({market:.0%}) is below {whose} history ({est:.0%})",
                "kind": "price", "side_lean": 1}
    if market >= est + PRICE_GAP:
        return {"text": f"The price ({market:.0%}) already expects more than {whose} history "
                        f"({est:.0%})", "kind": "price", "side_lean": -1}
    return {"text": f"Price and history roughly agree ({market:.0%} vs {est:.0%})",
            "kind": "price", "side_lean": 0}


def _finish(points: list[dict[str, Any]], price: dict[str, Any] | None, ctx: Ctx,
            thin: bool, avoid: str | None) -> dict[str, Any]:
    pro: list[dict[str, str]] = []
    con: list[dict[str, str]] = []
    info: list[dict[str, str]] = []
    for p in points:
        lean = p["lean"] if ctx.side == "yes" else (0 if p["no_side"] == "context"
                                                    else -p["lean"])
        (pro if lean > 0 else con if lean < 0 else info).append(
            {"text": p["text"], "kind": p["kind"]})
    if price:
        (pro if price["side_lean"] > 0 else con if price["side_lean"] < 0 else info).append(
            {"text": price["text"], "kind": "price"})
    if avoid:
        lean = "avoid"
    elif thin:
        lean = "thin"
    elif len(pro) >= 3 and len(con) <= 1 and len(pro) - len(con) >= 2:
        lean = "strong"
    elif len(con) >= 2 and len(con) > len(pro):
        lean = "weak"
    else:
        lean = "mixed"
    head = {"avoid": avoid or "Avoid", "thin": "Too few games on record to judge",
            "strong": f"Strong case: {len(pro)} for, {len(con)} against",
            "weak": f"Weak case: {len(con)} against, {len(pro)} for",
            "mixed": f"Mixed: {len(pro)} for, {len(con)} against"}[lean]
    return {"lean": lean, "headline": head, "for": pro, "against": con, "context": info,
            "score": len(pro) - len(con)}


# --- player props ------------------------------------------------------------------------------


def player_brief(spec: dict[str, Any], rows: Sequence[GameRow], summary: dict[str, Any],
                 market: float | None, ctx: Ctx) -> dict[str, Any]:
    stat, need, player = spec["stat"], spec["at_least"], spec["player"]
    word = STAT_WORD.get(stat, stat.lower())
    flag = stat in ("2D", "3D")
    target = f"a {word}" if flag else f"{need}+ {word}"
    yes, value = predicate(spec, "yes")
    prior = _before(rows, ctx.game_date)
    cur = [r for r in prior if r.season == "current"]
    line = line_of(spec)
    m_yes = None if market is None else (market if ctx.side == "yes" else 1 - market)
    pts: list[dict[str, Any]] = []

    res = [h for r in prior[:10] if (h := yes(r)) is not None]
    if len(res) >= 5:
        h, n = sum(res), len(res)
        text = f"Had {target} in {h} of his last {n} games"
        if not flag:
            v5 = _mean([v for r in prior[:5] if (v := value(r)) is not None])
            vs = _mean([v for r in cur if (v := value(r)) is not None])
            if v5 is not None:
                text += f": {v5:.1f} a game over the last 5"
                text += f", {vs:.1f} this season" if vs is not None else ""
                text += f" (line {line})"
        pts.append(_pt(text, "form", _vs_price(h / n, m_yes, FORM_GAP)))

    mins = [r.stats["MIN"] for r in cur if r.stats.get("MIN")]
    if len(mins) >= 6:
        m5, ms = sum(mins[:5]) / 5, sum(mins) / len(mins)
        if abs(m5 - ms) >= MIN_SWING:
            up = m5 > ms
            pts.append(_pt(f"Minutes {'up' if up else 'down'}: {m5:.1f} a game over his last 5 "
                           f"vs {ms:.1f} this season", "minutes", 1 if up else -1))

    opp_e = espn_code(ctx.league, ctx.opp)
    opp_name = ctx.names.get(ctx.opp or "", ctx.opp or "the opponent")
    keys = MATCHUP.get(stat)
    if keys and opp_e:
        rk = _rank(ctx.table, keys, opp_e)
        if rk:
            v, r_, n, avg, gp = rk
            if stat == "STL":
                text = (f"{opp_name} turn it over {v:.1f} times a game, {_ord(r_)} most of {n} "
                        f"(league average {avg:.1f}){_early(gp)}")
            else:
                text = (f"{opp_name} allow {v:.1f} {word} a game, {_ord(r_)} most of {n} "
                        f"(league average {avg:.1f}){_early(gp)}")
            pts.append(_pt(text, "matchup", _band(r_, n)))
    elif not keys:
        pts.append(_pt(f"No opponent stat covers {word} props", "matchup", 0))

    if opp_e:
        h2h = [r for r in prior if r.opponent == opp_e]
        hits = [h for r in h2h if (h := yes(r)) is not None]
        if hits:
            vals = ", ".join(f"{v:g}" for r in h2h[:5] if (v := value(r)) is not None)
            h, n = sum(hits), len(hits)
            text = (f"Against {opp_name} since last season: had {target} in {h} of {n}"
                    + ("" if flag else f" ({vals})"))
            lean = _vs_price(h / n, m_yes, H2H_GAP) if n >= 3 else 0
            pts.append(_pt(text, "h2h", lean))

    if r := _rest(prior, ctx.game_date, "He"):
        pts.append(r)

    if ctx.home is not None:
        recent = prior[:40]
        home = [h for r in recent if r.home and (h := yes(r)) is not None]
        away = [h for r in recent if not r.home and (h := yes(r)) is not None]
        if len(home) >= 5 and len(away) >= 5:
            rh, ra = sum(home) / len(home), sum(away) / len(away)
            if abs(rh - ra) >= SPLIT_GAP:
                tonight = rh if ctx.home else ra
                pts.append(_pt(f"Had {target} in {rh:.0%} of home games vs {ra:.0%} away; "
                               f"tonight he's {'home' if ctx.home else 'away'}", "venue",
                               1 if tonight == max(rh, ra) else -1))

    avoid = None
    if ctx.injuries is None:
        pts.append(_pt("No injury report is published for this league: check team news",
                       "injury", 0))
    elif inj := _injury(ctx, player):
        st = inj["status"]
        detail = f" ({inj['detail'][:120]})" if inj.get("detail") else ""
        if any(w in st.lower() for w in OUT):
            avoid = (f"Listed {st}: if he doesn't play, Kalshi settles at a fair price; "
                     "if he plays hurt, history overstates him")
            pts.append(_pt(f"Listed {st}{detail}", "injury", -1, no_side="context"))
        elif any(w in st.lower() for w in SHAKY):
            # ESPN's note often says "probable" under a Day-To-Day status: that's context.
            probable = "probable" in inj.get("detail", "").lower()
            pts.append(_pt(f"Listed {st}{detail}" + ("" if probable else ": minutes risk"),
                           "injury", 0 if probable else -1, no_side="context"))
    outs = _outs(ctx, ctx.team, skip=player)
    if outs:
        pts.append(_pt(f"Out for his team: {', '.join(outs[:4])}. His role may be bigger than "
                       "his history shows", "teammates", 0))

    thin = summary.get("verdict") == "thin" or len(res) < 5
    return _finish(pts, _price(summary, market, "his"), ctx, thin, avoid)


# --- game lines --------------------------------------------------------------------------------


def team_brief(spec: dict[str, Any], rows: Sequence[GameRow], summary: dict[str, Any],
               market: float | None, ctx: Ctx) -> dict[str, Any]:
    kind = spec["kind"]
    yes, value = predicate(spec, "yes")
    prior = _before(rows, ctx.game_date)
    me = ctx.names.get(ctx.team or "", ctx.team or "The team")
    opp = ctx.names.get(ctx.opp or "", ctx.opp or "the opponent")
    over = spec.get("over")
    m_yes = None if market is None else (market if ctx.side == "yes" else 1 - market)
    pts: list[dict[str, Any]] = []

    res = [h for r in prior[:10] if (h := yes(r)) is not None]
    vals = [v for r in prior[:10] if (v := value(r)) is not None]
    if len(res) >= 5 and vals:
        h, n, avg = sum(res), len(res), sum(vals) / len(vals)
        text = {
            "team_win": f"{me} won {h} of their last {n} (average margin {avg:+.1f})",
            "team_margin": f"{me} won by more than {over} in {h} of their last {n} "
                           f"(average margin {avg:+.1f})",
            "team_total": f"{me} scored more than {over} in {h} of their last {n} "
                          f"(averaging {avg:.1f})",
            "game_total": f"{me} games went over {over} in {h} of their last {n} "
                          f"(averaging {avg:.1f} total)",
        }[kind]
        pts.append(_pt(text, "form", _vs_price(h / n, m_yes, FORM_GAP)))

    me_e, opp_e = espn_code(ctx.league, ctx.team), espn_code(ctx.league, ctx.opp)
    t = ctx.table
    if me_e in t and opp_e in t:
        a, b = t[me_e], t[opp_e]
        if kind == "team_total" and (rk := _rank(t, ("allow_PTS",), opp_e)):
            v, r_, n, avg, gp = rk
            pts.append(_pt(f"{opp} allow {v:.1f} points a game, {_ord(r_)} most of {n} "
                           f"(league average {avg:.1f}){_early(gp)}", "matchup",
                           _band(r_, n) if _open(m_yes) else 0))
        elif kind == "game_total" and all(k in x for x in (a, b) for k in ("own_PTS",
                                                                          "allow_PTS")):
            ta, tb = a["own_PTS"] + a["allow_PTS"], b["own_PTS"] + b["allow_PTS"]
            lean = (1 if min(ta, tb) > over else -1 if max(ta, tb) < over else 0
                    ) if _open(m_yes) else 0
            pts.append(_pt(f"{me} games average {ta:.1f} total points, {opp} games {tb:.1f} "
                           f"(line {over})", "matchup", lean))
        elif kind in ("team_win", "team_margin") and all(
                k in x for x in (a, b) for k in ("own_PTS", "allow_PTS")):
            da, db = a["own_PTS"] - a["allow_PTS"], b["own_PTS"] - b["allow_PTS"]
            gap = da - db
            if not _open(m_yes):
                lean = 0  # a lopsided price already says who's better
            elif kind == "team_win":
                lean = 1 if gap >= 3 else -1 if gap <= -3 else 0
            else:
                lean = 1 if gap >= 2 * over else -1 if gap <= 0 else 0
            pts.append(_pt(f"Point differential this season: {me} {da:+.1f} a game, "
                           f"{opp} {db:+.1f}", "matchup", lean))

    if opp_e:
        h2h = [r for r in prior if r.opponent == opp_e]
        hits = [h for r in h2h if (h := yes(r)) is not None]
        if hits:
            h, n = sum(hits), len(hits)
            scores = ", ".join(f"{r.team_score}-{r.opp_score}" for r in h2h[:4]
                               if r.team_score is not None)
            lean = _vs_price(h / n, m_yes, H2H_GAP) if n >= 3 else 0
            pts.append(_pt(f"Against {opp} since last season: {h} of {n} ({scores})", "h2h",
                           lean))

    own_rest = _rest(prior, ctx.game_date, me)
    opp_rest = _rest(_before(ctx.opp_rows or [], ctx.game_date), ctx.game_date, opp)
    tired = 0 if kind == "game_total" else 1
    if own_rest:
        own_rest["lean"] = own_rest["lean"] * tired
        pts.append(own_rest)
    if opp_rest:
        # The opponent tired helps a team win or cover; for a team total it's minor context.
        opp_rest["lean"] = -opp_rest["lean"] if kind in ("team_win", "team_margin") else 0
        pts.append(opp_rest)

    if ctx.injuries is None:
        pts.append(_pt("No injury report is published for this league: check team news",
                       "injury", 0))
    else:
        mine, theirs = _outs(ctx, ctx.team), _outs(ctx, ctx.opp)
        if mine or theirs:
            parts = [f"{nm}: {', '.join(xs[:4])}" for nm, xs in ((me, mine), (opp, theirs)) if xs]
            pts.append(_pt("Out tonight: " + "; ".join(parts), "injury", 0))

    thin = summary.get("verdict") == "thin" or len(res) < 5
    return _finish(pts, _price(summary, market, f"{me}'s" if kind != "game_total" else "the"),
                   ctx, thin, None)


def brief(spec: dict[str, Any], rows: Sequence[GameRow], summary: dict[str, Any],
          market: float | None, ctx: Ctx) -> dict[str, Any]:
    if spec["kind"] == "player_stat":
        return player_brief(spec, rows, summary, market, ctx)
    return team_brief(spec, rows, summary, market, ctx)
