"""NFL player props (deterministic, then optional news + local summary).

Evidence: nflverse weekly player stats (its own aggregates, CC BY 4.0; registry entry
nflverse_player_stats), the schedule and team stats already used for NFL games, and this
week's injury report. Brave news only on an explicit run.

Rules kept here:
- Exact mapping: the player and team from the contract, the stat from the series, the line
  from Kalshi's floor_strike ("Matthew Stafford: 200+" is over 199.5). Kalshi settles on the
  player's official stats; if he is active but never plays a live snap, the market settles
  at a fair price. "Protected" contracts also settle at a fair price if he plays in the
  first half but not after it (unless he already reached the line).
- Point in time: only weeks before this game count.
- A player has a row only in games where he recorded a stat. Games his team played without a
  row for him (inactive, or no catch/carry) are counted and shown, and the frequency the
  price lens uses counts them as misses (the cautious reading).
- A frequency over a part-season is context, not a probability: no conservative edge.
"""

from __future__ import annotations

import math
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.adapters.base import AdapterError
from app.catalog import games
from app.db.models import CatalogEvent, CatalogMarket
from app.investigate import common, registry, sources
from app.investigate import schemas as S
from app.investigate.search import Gathered, game_date
from app.sportsdata import nflverse as nv

# Series suffix (after KXNFL, without PROT/PRECISE) -> (stat label, player columns summed,
# the matching team column for "what the opponent allows", its label).
PROP_STATS: dict[str, tuple[str, tuple[str, ...], str | None, str]] = {
    "PASSYDS": ("passing yards", ("passing_yards",), "passing_yards", "passing yards"),
    "RSHYDS": ("rushing yards", ("rushing_yards",), "rushing_yards", "rushing yards"),
    "RECYDS": ("receiving yards", ("receiving_yards",), "passing_yards", "passing yards"),
    "REC": ("receptions", ("receptions",), "completions", "completions"),
    "PASSTDS": ("passing touchdowns", ("passing_tds",), "passing_tds", "passing touchdowns"),
    "TD": (
        "touchdowns scored",
        ("rushing_tds", "receiving_tds", "special_teams_tds", "fumble_recovery_tds", "def_tds"),
        None,
        "",
    ),
    "PASSATT": ("pass attempts", ("attempts",), "attempts", "pass attempts"),
    "PASSCOMP": ("completions", ("completions",), "completions", "completions"),
    "PASSINT": (
        "interceptions thrown",
        ("passing_interceptions",),
        "passing_interceptions",
        "interceptions",
    ),
    "RSHATT": ("carries", ("carries",), "carries", "carries"),
    "RRYDS": ("rushing + receiving yards", ("rushing_yards", "receiving_yards"), None, ""),
}
NO_MODEL = (
    "No validated NFL prop model: the frequency below is a small-sample count from this "
    "season, not a probability, so no edge is calculated."
)
Z80 = 1.2816


def prop_base(rest: str) -> tuple[str, bool] | None:
    """('PASSYDS', protected) for a series suffix, or None if it isn't a covered prop."""
    protected = rest.endswith("PROT")
    base = rest[:-4] if protected else rest[:-7] if rest.endswith("PRECISE") else rest
    return (base, protected) if base in PROP_STATS else None


def settlement(stat: str, protected: bool, td: bool) -> str:
    out = (
        f"Settles on the player's official {stat} (overtime included). If he's active but "
        "never plays a live snap, it settles at a fair price before kickoff; once he plays a "
        "snap (even one wiped out by a penalty), it settles on his actual stats."
    )
    if td:
        out += (
            " Only touchdowns he scores count (rushing, receiving or returns), not ones he throws."
        )
    if protected:
        out += (
            " Protected: if he plays in the first half but not after it, it settles at a fair "
            "price unless he already reached the line."
        )
    return out


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    words = [w for w in re.split(r"[^a-z]+", s) if w and w not in ("jr", "sr", "ii", "iii", "iv")]
    return " ".join(words)


def find_player(rows: list[nv.PlayerWeek], name: str, team: str | None) -> list[nv.PlayerWeek]:
    """All weekly rows for the named player (one player id), preferring his current team."""
    target = _norm(name)
    hits = [r for r in rows if _norm(r.name) == target]
    if not hits and target:
        first, last = target.split()[0], target.split()[-1]
        hits = [r for r in rows if _norm(r.short).replace(" ", "") == f"{first[0]}{last}"]
    ids: dict[str, list[nv.PlayerWeek]] = {}
    for r in hits:
        ids.setdefault(r.player_id, []).append(r)
    if not ids:
        return []
    if len(ids) > 1 and team:
        on_team = {k: v for k, v in ids.items() if max(v, key=lambda r: r.week).team == team}
        if len(on_team) == 1:
            ids = on_team
    if len(ids) != 1:
        return []  # ambiguous: never guess between two players
    return sorted(next(iter(ids.values())), key=lambda r: r.week)


def wilson(k: int, n: int, z: float = Z80) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


@dataclass
class Freq:
    values: list[float]  # stat per game with a row, oldest first
    hits: int
    games: int  # games with a stat line
    team_games: int  # games his team played (in his weeks with the team)
    avg: float


def frequency(
    rows: list[nv.PlayerWeek], cols: tuple[str, ...], line: float, team_games: int
) -> Freq:
    vals = [sum(r.stats.get(c, 0.0) for c in cols) for r in rows]
    return Freq(
        values=vals,
        hits=sum(1 for v in vals if v > line),
        games=len(vals),
        team_games=max(team_games, len(vals)),
        avg=sum(vals) / len(vals) if vals else 0.0,
    )


def build(
    session: Session,
    nv_src: Any,
    m: CatalogMarket,
    e: CatalogEvent | None,
    series: str,
    side: str,
    label: str | None,
    now: datetime,
    cache_hours: float,
    gatherer: Any = None,
    synthesizer: Any = None,
) -> S.Result:
    from app.investigate import nfl, service, synth

    rest = nfl.suffix(series)
    base = prop_base(rest)
    if base is None:
        raise service.Unsupported("This NFL prop type isn't covered.")
    stat_key, protected = base
    stat, cols, team_col, team_label = PROP_STATS[stat_key]
    parts = m.ticker.split("-")
    who_code = parts[2] if len(parts) >= 4 else ""
    if who_code.endswith("DST"):
        raise service.Unsupported("Defense/special-teams touchdown markets aren't covered.")
    key = m.event_ticker.split("-", 1)[1]
    names = games.list_games_teams(session, nfl.PREFIX, key)
    codes = list(names)
    team = next((c for c in sorted(codes, key=len, reverse=True) if who_code.startswith(c)), None)
    other = next((c for c in codes if c != team), None)
    player = (m.yes_sub_title or "").split(":")[0].strip()[:60]
    if not player or team is None:
        raise service.Unsupported("Couldn't tell which player this market is about.")
    line = float(m.floor_strike) if m.floor_strike is not None else None
    if line is None:
        raise service.Unsupported("This market has no line to check.")
    full = {c: nv.NFL_TEAMS.get(c, names[c]) for c in codes}
    name = (label or m.yes_sub_title or m.title).strip()[:200]
    statement = name if side == "yes" else f"NOT: {name} (betting it doesn't happen)"
    phrase = f"“{name}”" if side == "yes" else f"a NO on “{name}”"
    rules = settlement(stat, protected, stat_key == "TD")
    hyp = S.Hypothesis(
        ticker=m.ticker,
        event_ticker=m.event_ticker,
        side=side,  # type: ignore[arg-type]
        sport="football",
        league="NFL",
        market_type="player_prop",
        threshold=line,
        subject=player,
        label=name,
        statement=statement,
        snapshot_at=service._iso(m.refreshed_at),
        rules_url=f"https://kalshi.com/markets/{series.lower()}",
    )
    errors: list[str] = []

    # --- data ------------------------------------------------------------------------------
    day = game_date(m.event_ticker)
    season: nv.SeasonData | None = None
    rows_all: list[nv.PlayerWeek] = []
    players_as_of = None
    settings = getattr(nv_src, "settings", None)
    if nv_src is None or not sources.allows(
        "nflverse_schedules", "download_schedule_release", settings
    ):
        errors.append("nflverse data is switched off (KRT_RESEARCH_DISABLED_SOURCES).")
    else:
        yr = nv.season_of(day or now)
        try:
            season = nv_src.season(yr)
            errors.extend(season.errors)
        except AdapterError as exc:
            errors.append(f"nflverse data unavailable right now ({exc}).")
        if not sources.allows("nflverse_player_stats", "download_player_stats_release", settings):
            errors.append("nflverse player stats are switched off (KRT_RESEARCH_DISABLED_SOURCES).")
        else:
            try:
                rows_all, players_as_of = nv_src.players(yr)
            except AdapterError as exc:
                errors.append(f"nflverse player stats unavailable right now ({exc}).")
    game = (
        season.find_game(codes[0], codes[1], day.date() if day else None)
        if season and len(codes) == 2
        else None
    )
    kickoff = (game.kickoff if game else None) or (
        e.occurs_at - timedelta(hours=3) if e and e.occurs_at else None
    )
    week = game.week if game else None
    rows = find_player(rows_all, player, nv.nv_code(team)) if rows_all else []
    prior = [r for r in rows if week is None or r.week < week]
    team_games = 0
    if season and game and game.kickoff:
        mine = {r.team for r in prior} or {nv.nv_code(team)}
        team_games = sum(
            1
            for g in season.games
            if g.played
            and g.kickoff
            and g.kickoff < game.kickoff
            and (g.away in mine or g.home in mine)
            and (not prior or g.week >= prior[0].week)
        )
    if rows_all and not rows:
        errors.append(f"{player} couldn't be matched to one player in nflverse's stats.")
    freq = frequency(prior, cols, line, team_games) if prior else None
    position = prior[-1].position if prior else (rows[-1].position if rows else "")

    # Injury status this week, and the listed QB (for quarterback props).
    latest = season.latest_injury_week() if season else None
    report_week = bool(game and latest is not None and latest >= game.week)
    injuries_on = sources.allows("nflverse_injuries", "download_injury_report_release", settings)
    status = None
    if season and game and report_week and injuries_on:
        row = next(
            (i for i in season.injuries_for(team, game.week) if _norm(i.name) == _norm(player)),
            None,
        )
        status = (
            "not on the injury report"
            if row is None or not row.status
            else f"{row.status}" + (f" ({row.injury.lower()})" if row.injury else "")
        )
    listed_qb = None
    if game and position == "QB":
        t = nv.nv_code(team)
        listed_qb = game.away_qb if game.away == t else game.home_qb if game.home == t else None

    # --- price (frequency shown as history; never an edge) ---------------------------------
    quote = service.quote_for(m, side, now)
    price, all_in = common.price_lens(session, m, side, name, series, quote, rules, NO_MODEL)
    if freq and freq.team_games:
        # Cautious: team games without a stat line count as misses.
        k, n = freq.hits, freq.team_games
        p_yes = k / n
        lo, hi = wilson(k, n)
        p = p_yes if side == "yes" else 1 - p_yes
        band = (lo, hi) if side == "yes" else (1 - hi, 1 - lo)
        price.model_p = round(p, 4)
        price.model_band = (round(band[0], 4), round(band[1], 4))
        price.model_name = (
            f"Frequency in {n} team games this season (games without a stat line count as "
            "misses; not calibrated)"
        )
        price.raw_diff = None if all_in is None else round(p - all_in, 4)
        price.abstain_reasons.append(
            f"{n} games is a small sample; usage, matchup and game script vary week to week."
        )

    # --- sources ---------------------------------------------------------------------------
    srcs = [common.kalshi_source(m, hyp.rules_url, now)]
    if season is not None or rows_all:
        srcs.append(
            S.Source(
                id="F1",
                url=nv.PAGE,
                title=f"nflverse {nv.season_of(day or now)} season (player stats, schedule, team "
                f"stats, injury report). {nv.ATTRIBUTION}"[:200],
                publisher="nflverse",
                published_at=service._iso(players_as_of or (season.data_as_of if season else None)),
                retrieved_at=service._iso(season.retrieved_at if season else None)
                or now.isoformat(),
                access="internal",
                line_match="exact",
            )
        )
    news: Gathered | None = (
        gatherer(hyp, [{"code": c, "name": full[c]} for c in codes]) if gatherer else None
    )
    if news is not None:
        srcs.extend(news.sources)
        errors.extend(news.errors)

    # --- findings ---------------------------------------------------------------------------
    findings: list[S.Finding] = []
    bits = [f"{player} ({position or 'position unknown'}, {full[team]})"]
    if status:
        bits.append(status)
    elif game and not report_week:
        bits.append(f"week {game.week} injury report not out yet")
    elif not injuries_on:
        bits.append("injury report switched off")
    if listed_qb and _norm(listed_qb) != _norm(player):
        bits.append(f"the schedule lists {listed_qb} as {full[team]}'s starter")
    findings.append(
        S.Finding(
            text=(
                "Player status — " + "; ".join(bits) + ". Inactives come about 90 minutes "
                "before kickoff; if he's active but doesn't play a snap, Kalshi settles at a "
                "fair price."
            )[:400],
            kind="factual" if status or listed_qb else "interpretation",
            stance="opposes"
            if status and nv.is_out(status.split(" ")[0]) and side == "yes"
            else "neutral",
            source_ids=["F1"] if season else [],
            verified=True,
        )
    )
    lean = 0.0
    if freq:
        k, n, mt = freq.hits, freq.games, freq.team_games
        p_side = (k / mt) if side == "yes" else 1 - k / mt
        lean = p_side - 0.5
        missing = mt - n
        last5 = ", ".join(f"{v:g}" for v in freq.values[-5:])
        findings.append(
            S.Finding(
                text=(
                    f"{player} {'scored' if stat_key == 'TD' else 'reached'} {line + 0.5:g}+ "
                    f"{stat.removesuffix(' scored')} in {k} of {n} games with a stat line"
                    + (
                        f" ({k} of {mt} team games, counting {missing} without one as misses)"
                        if missing
                        else ""
                    )
                    + f"; average {freq.avg:.1f}. Last {min(5, n)}: {last5} (oldest first). "
                    f"{nv.ATTRIBUTION}."
                )[:400],
                kind="statistical",
                stance="supports" if lean > 0.1 else "opposes" if lean < -0.1 else "neutral",
                source_ids=["F1"],
                verified=True,
            )
        )
    else:
        findings.append(
            S.Finding(
                text=f"No stat lines for {player} this season before kickoff; only the price "
                "is known.",
                kind="interpretation",
                stance="neutral",
                source_ids=[],
                verified=True,
            )
        )
    if team_col and season and game and other:
        opp = nv.nv_code(other)
        prev = [w for w in season.weeks if w.week < game.week]
        vs = [w.stats.get(team_col, 0.0) for w in prev if w.opponent == opp]
        league = [w.stats.get(team_col, 0.0) for w in prev]
        if len(vs) >= 2 and league:
            findings.append(
                S.Finding(
                    text=(
                        f"{full[other]} allow {sum(vs) / len(vs):.1f} {team_label} a game "
                        f"({len(vs)} games; league average {sum(league) / len(league):.1f}). "
                        "Team totals, not this player's role."
                    ),
                    kind="statistical",
                    stance="neutral",
                    source_ids=["F1"],
                    verified=True,
                )
            )
    if kickoff is not None and now >= kickoff:
        findings.append(
            S.Finding(
                text="This game has already kicked off: the pre-game view may be out of date.",
                kind="interpretation",
                stance="neutral",
                source_ids=[],
                verified=True,
            )
        )
    if news is not None and news.sources:
        n_src = len(news.sources)
        findings.append(
            S.Finding(
                text=(
                    f"{n_src} recent article{'s' if n_src != 1 else ''} found; headlines and "
                    "snippets only, not yet summarised."
                ),
                kind="interpretation",
                stance="neutral",
                source_ids=[x.id for x in news.sources][:6],
                verified=True,
            )
        )

    # --- takeaway, gaps -----------------------------------------------------------------
    ask_c = f"{all_in * 100:.0f}¢ all-in" if all_in is not None else "current"
    if freq:
        first = (
            f"{player} cleared this line in {freq.hits} of {freq.team_games} team games this "
            f"season: a small-sample count, not a probability for {phrase} at the {ask_c} price."
        )
    else:
        first = f"There are no stat lines to check {phrase} against, so only the price is known."
    second = (
        f"He's listed {status} this week, so check inactives before kickoff."
        if status and status != "not on the injury report"
        else "Check inactives about 90 minutes before kickoff."
    )
    gaps = ["Who's active and his snap share aren't known until inactives are posted."]
    if game and not report_week:
        gaps.append(f"This week's injury report (week {game.week}) isn't available yet.")
    gaps.append("Game script, weather and his role in this matchup aren't modelled.")
    if news is None or not news.attempted:
        gaps.append("News and late injury updates were not checked.")
    elif news.sources:
        gaps.append("What the articles say isn't summarised yet: read the sources.")
    if not quote.fresh:
        gaps.insert(0, "The price is stale: run a scan before deciding.")
    result = S.Result(
        investigation_id=str(uuid.uuid4()),
        status="partial" if errors else "done",
        created_at=now.isoformat(),
        completed_at=now.isoformat(),
        stale_at=(now + timedelta(hours=cache_hours)).isoformat(),
        hypothesis=hyp,
        quote=quote,
        summary=S.Summary(
            takeaway=f"{first} {second}",
            findings=findings[:3],
            gaps=gaps,
            stance="insufficient",
            uncertainty="High: a part-season frequency for one player; no validated model.",
        ),
        price_assessment=price,
        details=S.Details(
            supports=[f for f in findings if f.stance == "supports"],
            against=[f for f in findings if f.stance != "supports"],
            methodology=[
                f"Market mapping: {player} ({full[team]}), {stat} over {line:g}; " + rules,
                f"Stats: nflverse weekly player stats ({nv.ATTRIBUTION}); weeks before this "
                "game only. Team games without a stat line for him are shown, and count as "
                "misses in the price lens's frequency (80% Wilson range).",
                "Opponent context: what the opponent allowed per game from nflverse team stats.",
                "Status: this week's nflverse injury report and the schedule's listed QB; "
                "never confirmed.",
                "Price: the slip check's fee schedule and all-in price; no edge is calculated.",
                (
                    f"News: Brave News Search, {news.queries} quer"
                    f"{'y' if news.queries == 1 else 'ies'} ({news.searches} sent); headlines "
                    "and snippets only; snippets are not stored."
                    if news is not None
                    else "No external articles were used in this result."
                ),
                f"Source rules: publisher registry {registry.REGISTRY_VERSION}, data sources "
                f"{sources.SOURCES_VERSION}.",
                "No language model was used in this result.",
            ],
            data_gaps=gaps,
            rules_excerpt=(e.rules_sample[:600] if e and e.rules_sample else None),
        ),
        sources=srcs,
        processing=S.Processing(
            model=None,
            searches=0 if news is None else news.searches,
            cache="none" if news is None or not news.searches else "miss",
            errors=errors,
            partial_reasons=["deterministic_only"],
        ),
    )
    result.summary.coverage = service.coverage(
        result,
        lineup=f"player status: {status}"
        if status
        else "player status: report not out yet"
        if game and not report_week
        else "player status unknown",
    )
    if synthesizer is not None:
        result = synth.apply(result, news.snippets if news is not None else {}, synthesizer)
    return result
