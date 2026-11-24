"""Soccer investigation (deterministic, then optional news + local summary).

Leagues: Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Champions League (results
from football-data.org's free tier, keyed) and MLS (no permitted results source yet: price,
rules and news only). ESPN is NOT used (see sources.py).

Safety rules kept here:
- Market mapping is exact. Every Kalshi soccer market here settles after 90 minutes plus
  stoppage time: no extra time, no penalties. Game winner is three-way, and "Tie" is its own
  contract. Own goals count for the team awarded the goal. Halves, corners, correct score
  and first-to-score are unsupported, not approximated.
- Results are read as 90-minute scores; a match decided later is used only when its
  regular-time score is known.
- Point in time: form counts only matches that kicked off before this one.
- No lineup or injury source is connected, so team news is always "unknown", never assumed
  normal.
- Context, not a probability: no model estimate, no conservative edge.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.adapters.base import AdapterError
from app.catalog import games
from app.db.models import CatalogEvent, CatalogMarket
from app.investigate import common, registry, sources
from app.investigate import schemas as S
from app.investigate.search import Gathered, game_date
from app.sportsdata import footballdata as fd

LEAGUES = {
    "KXEPL": "EPL",
    "KXLALIGA": "La Liga",
    "KXBUNDESLIGA": "Bundesliga",
    "KXSERIEA": "Serie A",
    "KXLIGUE1": "Ligue 1",
    "KXUCL": "Champions League",
    "KXMLS": "MLS",
}
KINDS = {
    "GAME": "moneyline",
    "SPREAD": "spread",
    "TOTAL": "total",
    "TEAMTOTAL": "team_total",
    "BTTS": "btts",
}
UNSUPPORTED = (
    (re.compile(r"^(1H|2H)"), "Half markets aren't covered: the data is full-match only."),
    (re.compile(r"CORNERS$"), "Corner markets aren't covered: there's no corner data."),
    (re.compile(r"SCORE$"), "Correct-score markets aren't covered."),
    (re.compile(r"^FTTS$"), "First-team-to-score markets aren't covered."),
)
NINETY = (
    "after 90 minutes plus stoppage time: extra time and penalties don't count, and own goals "
    "count for the team awarded the goal"
)
SETTLEMENT = {
    "moneyline": f"Three-way: a team wins, or the separate “Tie” contract wins, {NINETY}. A "
    "match cancelled or moved more than 48 hours resolves at a fair price.",
    "spread": f"The team must win by more than the line {NINETY}. A draw or a narrower win "
    "is a NO.",
    "total": f"Counts both teams' goals {NINETY}.",
    "team_total": f"Counts the team's goals {NINETY}.",
    "btts": f"YES needs both teams to score {NINETY}.",
}
NO_MODEL = (
    "No validated soccer probability model yet: past results are context, not an estimate, "
    "so no edge is calculated."
)
TEAM_NEWS = (
    "Team news — no permitted lineup or injury source is connected for soccer, so who plays "
    "(injuries, suspensions, rotation) is unknown; check team news before relying on past "
    "results."
)


def league_prefix(ticker: str) -> str | None:
    up = ticker.upper()
    return next((p for p in sorted(LEAGUES, key=len, reverse=True) if up.startswith(p)), None)


def is_soccer(ticker: str) -> bool:
    return league_prefix(ticker) is not None


def suffix(series: str) -> str:
    p = league_prefix(series) or ""
    return series.upper()[len(p) :]


def market_kind(series: str) -> str:
    return KINDS.get(suffix(series), "other")


def unsupported_reason(series: str, event_ticker: str) -> str | None:
    rest = suffix(series)
    if rest in KINDS:
        return (
            None
            if re.search(r"-\d{2}[A-Z]{3}\d{2}", event_ticker)
            else "Only single-match markets can be investigated."
        )
    for pat, why in UNSUPPORTED:
        if pat.search(rest):
            return why
    return "Only soccer match winner, spread, totals and both-teams-to-score can be investigated."


def _pct(k: int, n: int) -> str:
    return f"{k}/{n}" if n else "—"


def build(
    session: Session,
    fd_src: Any,
    ticker: str,
    side: str,
    label: str | None,
    now: datetime,
    cache_hours: float,
    gatherer: Any = None,
    synthesizer: Any = None,
) -> S.Result:
    from app.investigate import service, synth

    m = session.get(CatalogMarket, ticker)
    if m is None:
        raise service.NotFound(f"{ticker} is not in the catalog (run a scan)")
    e = session.get(CatalogEvent, m.event_ticker)
    series = e.series_ticker if e else ticker.split("-")[0]
    why = unsupported_reason(series, m.event_ticker)
    if why:
        raise service.Unsupported(why)
    prefix = league_prefix(series) or ""
    league = LEAGUES[prefix]
    comp = fd.COMPETITIONS.get(prefix)
    kind = market_kind(series)
    errors: list[str] = []
    key = m.event_ticker.split("-", 1)[1]
    names = {c: n for c, n in games.list_games_teams(session, prefix, key).items() if c != "TIE"}
    codes = list(names)
    code = ticker.rsplit("-", 1)[-1]
    draw = kind == "moneyline" and code == "TIE"
    subject = None if draw else service.subject_team(ticker, kind)
    if kind == "btts":
        subject = None
    line = (
        float(m.floor_strike)
        if kind in ("spread", "total", "team_total") and m.floor_strike is not None
        else None
    )

    # --- results (football-data.org, free tier, keyed) -----------------------------------
    day = game_date(m.event_ticker)
    season: fd.SeasonMatches | None = None
    fixture: fd.Match | None = None
    who: dict[str, fd.Team] = {}
    if comp is None:
        pass  # MLS: no permitted results source
    elif fd_src is None or not sources.allows(
        "football_data_org", "read_competition_matches", getattr(fd_src, "settings", None)
    ):
        # The route passes no adapter only when the owner switched the source off.
        errors.append("football-data.org is switched off (KRT_RESEARCH_DISABLED_SOURCES).")
    elif not fd_src.configured():
        errors.append(
            "Soccer results aren't checked: set KRT_FOOTBALL_DATA_API_KEY (free "
            "football-data.org registration) to add them."
        )
    else:
        try:
            season = fd_src.season(comp, fd.season_of(day or now))
        except AdapterError as exc:
            errors.append(f"Soccer results unavailable right now ({exc}).")
    if season is not None and len(codes) == 2:
        found = season.find(
            (codes[0], names[codes[0]]), (codes[1], names[codes[1]]), day.date() if day else None
        )
        if found is None:
            errors.append("This match couldn't be matched to football-data.org's fixtures.")
        else:
            fixture, who = found
    full = {c: (who[c].short or who[c].name) if c in who else names[c] for c in codes}
    teams = [{"code": c, "name": full[c]} for c in codes]
    name = (label or m.yes_sub_title or m.title).strip()[:200]
    if draw:
        name = (
            f"{full[codes[0]]} vs {full[codes[1]]} level after 90 minutes (Kalshi “Tie”)"
            if (len(codes) == 2 and not label)
            else name
        )
    statement = name if side == "yes" else f"NOT: {name} (betting it doesn't happen)"
    phrase = f"“{name}”" if side == "yes" else f"a NO on “{name}”"
    hyp = S.Hypothesis(
        ticker=ticker,
        event_ticker=m.event_ticker,
        side=side,  # type: ignore[arg-type]
        sport="soccer",
        league=league,
        market_type=kind,  # type: ignore[arg-type]
        threshold=line,
        subject=full.get(subject or "") or None,
        label=name,
        statement=statement,
        snapshot_at=service._iso(m.refreshed_at),
        rules_url=f"https://kalshi.com/markets/{series.lower()}",
    )
    kickoff = fixture.utc if fixture else (e.occurs_at if e and e.occurs_at else None)
    before = kickoff or now
    forms: dict[str, fd.Form] = {}
    venue: dict[str, fd.Form] = {}
    if season is not None and fixture is not None:
        for c in codes:
            t = who[c]
            forms[c] = season.form(t.id, before)
            v = "home" if t.id == fixture.home.id else "away"
            venue[c] = season.form(t.id, before, v)
    have = len(forms) == 2 and all(f.games >= 2 for f in forms.values())

    # --- price (slip-check maths; no estimate) -------------------------------------------
    quote = service.quote_for(m, side, now)
    price, all_in = common.price_lens(
        session, m, side, name, series, quote, SETTLEMENT[kind], NO_MODEL
    )

    # --- sources ----------------------------------------------------------------------------
    srcs = [common.kalshi_source(m, hyp.rules_url, now)]
    if season is not None:
        srcs.append(
            S.Source(
                id="D1",
                url=fd.PAGE,
                title=f"{fd.COMPETITION_NAME[season.competition]} {season.season}/"
                f"{str(season.season + 1)[-2:]} fixtures and results. {fd.ATTRIBUTION}"[:200],
                publisher="football-data.org",
                published_at=service._iso(season.retrieved_at),
                retrieved_at=service._iso(season.retrieved_at) or now.isoformat(),
                access="internal",
                line_match="exact",
            )
        )

    # --- news (only on an explicit run; snippets stay in memory) -------------------------
    news: Gathered | None = gatherer(hyp, teams) if gatherer is not None else None
    if news is not None:
        srcs.extend(news.sources)
        errors.extend(news.errors)

    # --- findings ---------------------------------------------------------------------------
    findings: list[S.Finding] = [
        S.Finding(
            text=TEAM_NEWS,
            kind="interpretation",
            stance="neutral",
            source_ids=[],
            verified=True,
        )
    ]
    lean = 0.0
    if have:
        a, b = codes
        fa, fb = forms[a], forms[b]
        mine = subject if subject in forms else a
        other = b if mine == a else a
        fm, fo = forms[mine], forms[other]
        margin = ((fm.gf_pg + fo.ga_pg) - (fo.gf_pg + fm.ga_pg)) / 2
        rec = (
            f"{full[a]} {fa.wins}-{fa.draws}-{fa.losses} ({fa.gf_pg:.1f} scored, "
            f"{fa.ga_pg:.1f} conceded a match, {fa.games} matches); {full[b]} "
            f"{fb.wins}-{fb.draws}-{fb.losses} ({fb.gf_pg:.1f} / {fb.ga_pg:.1f}, {fb.games})"
        )
        if draw:
            text = (
                f"90-minute results before kickoff: {rec}. Draws: {full[a]} "
                f"{_pct(fa.draws, fa.games)}, {full[b]} {_pct(fb.draws, fb.games)}. "
                f"{fd.ATTRIBUTION}."
            )
            stance = "neutral"
        elif kind == "moneyline":
            lean = margin if side == "yes" else -margin
            text = (
                f"90-minute results before kickoff: {rec}. A rough average puts the "
                f"{full[mine]} goal margin near {margin:+.1f} (a win also has to beat the "
                f"draw; not a probability). {fd.ATTRIBUTION}."
            )
            stance = "supports" if lean > 0.4 else "opposes" if lean < -0.4 else "neutral"
        elif kind == "spread":
            gap = margin - (line or 0)
            lean = gap if side == "yes" else -gap
            won, n = fm.share(lambda gf, ga: gf - ga > (line or 0))
            lost, n2 = fo.share(lambda gf, ga: ga - gf > (line or 0))
            text = (
                f"{full[mine]} won by more than {line:g} in {_pct(won, n)} matches; "
                f"{full[other]} lost by more than {line:g} in {_pct(lost, n2)}. A rough "
                f"average puts the {full[mine]} margin near {margin:+.1f} (90-minute results "
                f"before kickoff; not a probability). {fd.ATTRIBUTION}."
            )
            stance = "supports" if lean > 0.4 else "opposes" if lean < -0.4 else "neutral"
        elif kind == "total":
            est = (fa.gf_pg + fb.ga_pg + fb.gf_pg + fa.ga_pg) / 2
            gap = est - (line or est)
            lean = gap if side == "yes" else -gap
            oa, na = fa.share(lambda gf, ga: gf + ga > (line or 0))
            ob, nb = fb.share(lambda gf, ga: gf + ga > (line or 0))
            text = (
                f"Matches with more than {line:g} goals: {full[a]} {_pct(oa, na)}, {full[b]} "
                f"{_pct(ob, nb)}. A rough average puts combined goals near {est:.1f} "
                f"(90-minute results before kickoff; a sanity check, not a probability). "
                f"{fd.ATTRIBUTION}."
            )
            stance = "supports" if lean > 0.3 else "opposes" if lean < -0.3 else "neutral"
        elif kind == "team_total":
            est = (fm.gf_pg + fo.ga_pg) / 2
            gap = est - (line or est)
            lean = gap if side == "yes" else -gap
            sc, n = fm.share(lambda gf, ga: gf > (line or 0))
            cd, n2 = fo.share(lambda gf, ga: ga > (line or 0))
            text = (
                f"{full[mine]} scored more than {line:g} in {_pct(sc, n)} matches; "
                f"{full[other]} conceded more than {line:g} in {_pct(cd, n2)}. A rough "
                f"average puts {full[mine]} goals near {est:.1f} (not a probability). "
                f"{fd.ATTRIBUTION}."
            )
            stance = "supports" if lean > 0.3 else "opposes" if lean < -0.3 else "neutral"
        else:  # btts
            rate = (fa.btts / fa.games + fb.btts / fb.games) / 2
            lean = (rate - 0.5) if side == "yes" else (0.5 - rate)
            text = (
                f"Both teams scored in {_pct(fa.btts, fa.games)} of {full[a]}'s matches and "
                f"{_pct(fb.btts, fb.games)} of {full[b]}'s. {full[a]} failed to score in "
                f"{fa.failed_to_score} and kept {fa.clean_sheets} clean sheets; {full[b]} "
                f"{fb.failed_to_score} and {fb.clean_sheets} (90-minute results before "
                f"kickoff; not a probability). {fd.ATTRIBUTION}."
            )
            stance = "supports" if lean > 0.1 else "opposes" if lean < -0.1 else "neutral"
        findings.append(
            S.Finding(
                text=text[:400],
                kind="statistical",
                stance=stance,  # type: ignore[arg-type]
                source_ids=["D1"],
                verified=True,
            )
        )
        if fixture is not None:
            h = next(c for c in codes if who[c].id == fixture.home.id)
            w = next(c for c in codes if c != h)
            vh, vw = venue[h], venue[w]
            findings.append(
                S.Finding(
                    text=(
                        f"Home and away: {full[h]} at home {vh.wins}-{vh.draws}-{vh.losses} "
                        f"({vh.gf_pg:.1f} scored, {vh.ga_pg:.1f} conceded, {vh.games} "
                        f"matches); {full[w]} away {vw.wins}-{vw.draws}-{vw.losses} "
                        f"({vw.gf_pg:.1f} / {vw.ga_pg:.1f}, {vw.games}). Last five: "
                        f"{full[a]} {fa.last or '—'}, {full[b]} {fb.last or '—'} (oldest "
                        "first)."
                    )[:400],
                    kind="statistical",
                    stance="neutral",
                    source_ids=["D1"],
                    verified=True,
                )
            )
        left_out = sum(season.undetermined(who[c].id, before) for c in codes) if season else 0
        findings.append(
            S.Finding(
                text=(
                    f"Figures cover {fa.games} and {fb.games} {fd.COMPETITION_NAME[comp or 'PL']}"
                    " matches played before this kickoff (later matches excluded). Other "
                    "competitions, opponent strength and fixture congestion aren't counted"
                    + (
                        f"; {left_out} match{'es' if left_out != 1 else ''} decided after "
                        "90 minutes left out (no regular-time score)"
                        if left_out
                        else ""
                    )
                    + "."
                ),
                kind="interpretation",
                stance="neutral",
                source_ids=[],
                verified=True,
            )
        )
    else:
        findings.append(
            S.Finding(
                text=(
                    "No permitted results source covers MLS yet; only the price and rules are "
                    "known."
                    if comp is None
                    else "Past results weren't checked (see the notes); only the price is known."
                    if season is None
                    else "Not enough results for this match before kickoff; only the price "
                    "is known."
                ),
                kind="interpretation",
                stance="neutral",
                source_ids=[],
                verified=True,
            )
        )
    if kickoff is not None and now >= kickoff:
        findings.append(
            S.Finding(
                text="This match has already kicked off: the pre-match view may be out of date.",
                kind="interpretation",
                stance="neutral",
                source_ids=[],
                verified=True,
            )
        )
    if news is not None and news.sources:
        n = len(news.sources)
        indep = sum(1 for x in news.sources if x.duplicate_of is None)
        findings.append(
            S.Finding(
                text=(
                    f"{n} recent article{'s' if n != 1 else ''} found ({indep} independent); "
                    "headlines and snippets only, not yet summarised."
                ),
                kind="interpretation",
                stance="neutral",
                source_ids=[x.id for x in news.sources][:6],
                verified=True,
            )
        )

    # --- takeaway, gaps -----------------------------------------------------------------
    ask_c = f"{all_in * 100:.0f}¢ all-in" if all_in is not None else "current"
    if not have:
        first = (
            f"Past results weren't checked for {phrase}, so only the price is known."
            if season is None
            else f"There are no results to check {phrase} against, so only the price is known."
        )
    elif draw:
        first = (
            f"Past draw rates are context for {phrase}, not a probability, so the {ask_c} "
            "price isn't checked against an estimate."
        )
    elif kind in ("moneyline", "spread"):
        tilt = (
            ("favour" if lean > 0.4 else "cut against" if lean < -0.4 else "are about even for")
            if kind == "moneyline"
            else ("sit above" if lean > 0.4 else "sit below" if lean < -0.4 else "sit close to")
        )
        what = phrase if kind == "moneyline" else f"what {phrase} needs"
        first = (
            f"Past goal margins {tilt} {what}, but there's no validated soccer model, so the "
            f"{ask_c} price isn't checked against an estimate."
        )
    elif kind == "btts":
        tilt = "favour" if lean > 0.1 else "cut against" if lean < -0.1 else "are mixed on"
        first = (
            f"Both teams' scoring records {tilt} {phrase}; that's context, not a probability "
            f"for the {ask_c} price."
        )
    else:
        tilt = "above" if lean > 0.3 else "below" if lean < -0.3 else "close to"
        first = (
            f"Past scoring averages sit {tilt} what {phrase} needs; that's context, not a "
            f"probability for the {ask_c} price."
        )
    takeaway = f"{first} Team news isn't known, so check lineups before relying on it."
    gaps = ["Who's playing tonight: no lineup or injury source is connected for soccer."]
    if comp is None:
        gaps.append("No permitted results source covers MLS yet.")
    elif season is None:
        gaps.append("Past results weren't checked (see the notes).")
    gaps.append("Other competitions, rest, travel and weather aren't checked.")
    if news is None or not news.attempted:
        gaps.append("News and team news were not checked.")
    elif news.sources:
        gaps.append("What the articles say isn't summarised yet: read the sources.")
    if not quote.fresh:
        gaps.insert(0, "The price is stale: run a scan before deciding.")
    against = [f for f in findings if f.stance != "supports"]
    result = S.Result(
        investigation_id=str(uuid.uuid4()),
        status="partial" if errors else "done",
        created_at=now.isoformat(),
        completed_at=now.isoformat(),
        stale_at=(now + timedelta(hours=cache_hours)).isoformat(),
        hypothesis=hyp,
        quote=quote,
        summary=S.Summary(
            takeaway=takeaway,
            findings=findings[:3],
            gaps=gaps,
            stance="insufficient",
            uncertainty="High: no soccer model; past results only, team news unknown.",
        ),
        price_assessment=price,
        details=S.Details(
            supports=[f for f in findings if f.stance == "supports"],
            against=against,
            methodology=[
                "Market mapping: exact Kalshi ticker, side, team and line; " + SETTLEMENT[kind],
                f"Results: football-data.org free tier ({fd.ATTRIBUTION}); 90-minute scores "
                "only; matches before this kickoff only; refreshed at most every 3 hours."
                if comp
                else "Results: none (no permitted source covers MLS yet).",
                "Team news: no source connected; always unknown.",
                "Price: the slip check's fee schedule and all-in price; no estimate or edge.",
                (
                    f"News: Brave News Search, {news.queries} quer"
                    f"{'y' if news.queries == 1 else 'ies'} ({news.searches} sent, "
                    f"{news.cache_hits} from cache); headlines and snippets only, no article pages "
                    "fetched; snippets are not stored."
                    if news is not None
                    else "No external articles were used in this result."
                ),
                f"Source rules: publisher registry {registry.REGISTRY_VERSION}, data sources "
                f"{sources.SOURCES_VERSION}; no publisher licenses full-text processing.",
                "No language model was used in this result.",
            ],
            data_gaps=gaps,
            rules_excerpt=(e.rules_sample[:600] if e and e.rules_sample else None),
        ),
        sources=srcs,
        processing=S.Processing(
            model=None,
            searches=0 if news is None else news.searches,
            cache=(
                "none"
                if news is None or (not news.searches and not news.cache_hits)
                else "hit"
                if not news.searches
                else "miss"
            ),
            errors=errors,
            partial_reasons=["deterministic_only"],
        ),
    )
    result.summary.coverage = service.coverage(
        result, lineup="team news unknown (no lineup source)"
    )
    if synthesizer is not None:
        result = synth.apply(result, news.snippets if news is not None else {}, synthesizer)
    return result
