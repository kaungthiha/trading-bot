"""NHL investigation (deterministic, then optional news + local summary).

Evidence: MoneyPuck season data (teams, goalies; non-commercial, credited) and, on an explicit
run, Brave news metadata. ESPN and the NHL's own endpoints are NOT used (see sources.py).

Safety rules kept here:
- Market mapping is exact: game winner and puck line settle on Kalshi's "official final result"
  (overtime and shootout included); totals count overtime goals and a shootout as one goal.
  Nothing is treated as a 60-minute regulation bet. Period, overtime and prop markets are
  unsupported rather than approximated.
- Starting goalie status is confirmed / expected / unknown / conflicting / not_applicable.
  It is NEVER "confirmed" from silence, and news reports are "expected (reported)": no
  official lineup source is connected, so nothing is ever marked confirmed today.
- Season stats are context, not a probability: no model estimate, no conservative edge.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.adapters.base import AdapterError
from app.catalog import games
from app.catalog.slipcheck import Fees, _side_prices, price_single
from app.catalog.stats import Quote as CatQuote
from app.catalog.stats import implied
from app.db.models import CatalogEvent, CatalogMarket
from app.investigate import registry, sources
from app.investigate import schemas as S
from app.investigate.search import Gathered
from app.sportsdata import moneypuck as mp

PREFIX = "KXNHL"
KINDS = {"GAME": "moneyline", "SPREAD": "spread", "TOTAL": "total", "TEAMTOTAL": "team_total"}
UNSUPPORTED = {
    "1P": "Period markets aren't covered: the season data is full-game only.",
    "2P": "Period markets aren't covered: the season data is full-game only.",
    "3P": "Period markets aren't covered: the season data is full-game only.",
    "OT": "Overtime markets aren't covered yet.",
    "F10G": "First-10-minutes markets aren't covered yet.",
    "FIRSTGOAL": "First-goal markets aren't covered yet.",
    "GOAL": "Player props aren't covered for the NHL yet.",
    "AST": "Player props aren't covered for the NHL yet.",
    "PTS": "Player props aren't covered for the NHL yet.",
    "SAVE": "Player props aren't covered for the NHL yet.",
}
SETTLEMENT = {
    "moneyline": "Settles on the official final result, so overtime and a shootout count: it is "
    "not a 60-minute regulation bet.",
    "spread": "Settles on the official final result, which includes overtime. Kalshi's rule "
    "doesn't spell out shootouts; the NHL's official score credits the shootout winner one "
    "goal, so a shootout game is a one-goal win.",
    "total": "Overtime goals count; a shootout counts as one goal for the winning team.",
    "team_total": "Overtime goals count; Kalshi's rule doesn't say how a shootout is scored "
    "for a single team's total, so treat shootout games as uncertain.",
}
GOALIE_STATES = ("confirmed", "expected", "unknown", "conflicting", "not_applicable")
NO_MODEL = (
    "No validated NHL probability model yet: the season figures are context, not an estimate, "
    "so no edge is calculated."
)
STARTS = (
    r"(will start|to start|starts|starting|expected to start|projected to start|gets the "
    r"(?:start|nod|call)|in goal|between the pipes|in net|confirmed)"
)


def is_nhl(ticker: str) -> bool:
    return ticker.startswith(PREFIX) and not ticker.startswith("KXNHLSEASON")


def suffix(series: str) -> str:
    return series.upper()[len(PREFIX) :]


def market_kind(series: str) -> str:
    return KINDS.get(suffix(series), "other")


def unsupported_reason(series: str, event_ticker: str) -> str | None:
    rest = suffix(series)
    if rest in KINDS:
        return (
            None
            if re.search(r"-\d{2}[A-Z]{3}\d{2}", event_ticker)
            else ("Only single-game markets can be investigated.")
        )
    for k, why in UNSUPPORTED.items():
        if rest.startswith(k):
            return why
    return "Only NHL game winner, puck line and totals can be investigated."


@dataclass
class GoalieRead:
    team: str
    state: str
    name: str | None = None
    source_ids: list[str] = field(default_factory=list)
    options: list[mp.GoalieSeason] = field(default_factory=list)


def goalie_status(
    codes: list[str], season: mp.SeasonData | None, news: Gathered | None
) -> dict[str, GoalieRead]:
    """Per team: reported starter from news headlines/snippets naming one of the team's
    goalies with a starting phrase. One goalie named -> expected (reported); two different
    goalies -> conflicting; none -> unknown. Never 'confirmed' (no official source)."""
    out: dict[str, GoalieRead] = {}
    texts: list[tuple[str, str]] = []
    if news is not None:
        for s in news.sources:
            if s.duplicate_of:
                continue
            texts.append((s.id, f"{s.title}. {news.snippets.get(s.id, '')}"))
    for code in codes:
        opts = season.goalies_for(code)[:3] if season else []
        named: dict[str, list[str]] = {}
        for g in opts:
            last = g.name.split()[-1] if g.name else ""
            if len(last) < 3:
                continue
            pat = re.compile(
                rf"\b{re.escape(last)}\b[^.]{{0,60}}?\b{STARTS}|\b{STARTS}\b[^.]{{0,40}}?\b{re.escape(last)}\b",
                re.I,
            )
            for sid, t in texts:
                if pat.search(t):
                    named.setdefault(g.name, []).append(sid)
        if len(named) == 1:
            name, ids = next(iter(named.items()))
            out[code] = GoalieRead(code, "expected", name, ids[:3], opts)
        elif len(named) > 1:
            ids = [i for v in named.values() for i in v][:4]
            out[code] = GoalieRead(code, "conflicting", None, ids, opts)
        else:
            out[code] = GoalieRead(code, "unknown", None, [], opts)
    return out


def _pct1(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def _sv(x: float | None) -> str:
    return "—" if x is None else f"{x:.3f}".lstrip("0")


def build(
    session: Session,
    mp_src: Any,
    ticker: str,
    side: str,
    label: str | None,
    now: datetime,
    cache_hours: float,
    gatherer: Any = None,
    synthesizer: Any = None,
) -> S.Result:
    # Shared helpers live in service (imported here to avoid an import cycle).
    from app.investigate import service, synth

    m = session.get(CatalogMarket, ticker)
    if m is None:
        raise service.NotFound(f"{ticker} is not in the catalog (run a scan)")
    e = session.get(CatalogEvent, m.event_ticker)
    series = e.series_ticker if e else ticker.split("-")[0]
    why = unsupported_reason(series, m.event_ticker)
    if why:
        raise service.Unsupported(why)
    kind = market_kind(series)
    errors: list[str] = []
    key = m.event_ticker.split("-", 1)[1]
    names = games.list_games_teams(session, PREFIX, key)
    codes = list(names)
    teams = [{"code": c, "name": mp.NHL_TEAMS.get(c, names[c])} for c in codes]
    full = {t["code"]: t["name"] for t in teams}
    subject = service.subject_team(ticker, kind)
    line = float(m.floor_strike) if kind != "moneyline" and m.floor_strike is not None else None
    name = (label or m.yes_sub_title or m.title).strip()[:200]
    statement = name if side == "yes" else f"NOT: {name} (betting it doesn't happen)"
    phrase = f"“{name}”" if side == "yes" else f"a NO on “{name}”"
    hyp = S.Hypothesis(
        ticker=ticker,
        event_ticker=m.event_ticker,
        side=side,  # type: ignore[arg-type]
        sport="hockey",
        league="NHL",
        market_type=kind,  # type: ignore[arg-type]
        threshold=line,
        subject=full.get(subject or "") or None,
        label=name,
        statement=statement,
        snapshot_at=service._iso(m.refreshed_at),
        rules_url=f"https://kalshi.com/markets/{series.lower()}",
    )

    # --- MoneyPuck season data (free, credited) ------------------------------------------
    start = (e.occurs_at if e and e.occurs_at else None) or now
    season: mp.SeasonData | None = None
    if mp_src is None or not sources.allows(
        "moneypuck", "download_listed_season_csv", getattr(mp_src, "settings", None)
    ):
        errors.append("MoneyPuck season data is switched off (KRT_RESEARCH_DISABLED_SOURCES).")
    else:
        try:
            season = mp_src.season(mp.season_of(start))
        except AdapterError as exc:
            errors.append(f"MoneyPuck season data unavailable right now ({exc}).")
    ts = {c: season.teams.get(mp.mp_code(c)) for c in codes} if season else {}
    have = season is not None and all(ts.get(c) for c in codes) and len(codes) == 2
    if season is not None and not have:
        errors.append("MoneyPuck has no season rows for one of these teams yet.")

    # --- quote and price (existing slip-check maths; no estimate) ------------------------
    quote = service.quote_for(m, side, now)
    fees = Fees(session)
    y, _ = implied(CatQuote(ticker, ticker, m.yes_bid, m.yes_ask))
    mid = None if y is None else Decimal(str(y if side == "yes" else 1 - y))
    ask, bid = _side_prices(m, side)
    ps = price_single(
        fees,
        {
            "ticker": ticker,
            "side": side,
            "label": name,
            "series": series,
            "mid": mid,
            "ask": ask,
            "bid": bid,
            "history": None,
            "p_est": None,
        },
    )
    all_in = float(ps["all_in"]) if ps.get("all_in") else None
    fee = None if ask is None else float(fees.taker(series, Decimal(100), ask) / 100)
    abstain = [NO_MODEL]
    if not quote.fresh:
        abstain.append("The quote is stale: refresh prices before deciding.")
    if ask is None:
        abstain.append("No ask to buy at right now.")
    price = S.Price(
        ask=service._f(ask),
        model_p=None,
        model_band=None,
        model_name=None,
        raw_diff=None,
        conservative_edge=None,
        break_even=all_in,
        walk_away=None,
        fee_per_contract=service._f(fee),
        slippage_per_contract=0.0,
        assumptions=[
            f"Ask from the last catalog scan ({service._iso(m.refreshed_at) or 'unknown time'}).",
            f"Taker fee from Kalshi's {'verified' if fees.verified else 'unverified'} "
            "schedule, one contract.",
            "Break-even = all-in price per $1 payout.",
            f"Settlement: {SETTLEMENT[kind]}",
        ],
        abstain_reasons=abstain,
    )

    # --- sources --------------------------------------------------------------------------
    srcs = [
        S.Source(
            id="K1",
            url=hyp.rules_url or "https://kalshi.com",
            title=f"Kalshi market: {m.title}"[:200],
            publisher="Kalshi",
            retrieved_at=service._iso(m.refreshed_at) or now.isoformat(),
            access="internal",
            line_match="exact",
        )
    ]
    if season is not None:
        srcs.append(
            S.Source(
                id="M1",
                url=mp.PAGE,
                title=f"MoneyPuck {season.season}-{str(season.season + 1)[-2:]} season data "
                f"(teams, goalies). {mp.ATTRIBUTION}",
                publisher="MoneyPuck.com",
                published_at=service._iso(season.data_as_of),
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
    goalies = goalie_status(codes, season, news)

    # --- findings ---------------------------------------------------------------------------
    findings: list[S.Finding] = []

    def gtext(g: GoalieRead) -> str:
        t = full.get(g.team, g.team)
        if g.state == "expected":
            return f"{t}: {g.name} reported as the starter (news, not an official confirmation)"
        if g.state == "conflicting":
            return f"{t}: reports name different starters"
        opts = ", ".join(f"{o.name.split()[-1]} {o.games} GP" for o in g.options[:2])
        return f"{t}: unknown" + (f" (season options: {opts})" if opts else "")

    gstates = {g.state for g in goalies.values()}
    findings.append(
        S.Finding(
            text=(
                "Starting goalies — " + "; ".join(gtext(goalies[c]) for c in codes) + ". "
                "No official lineup source is connected, so neither is confirmed."
            )[:400],
            kind="factual"
            if "expected" in gstates or "conflicting" in gstates
            else "interpretation",
            stance="neutral",
            source_ids=sorted(
                {i for g in goalies.values() for i in g.source_ids} | ({"M1"} if season else set())
            )[:6],
            verified=True,
        )
    )
    lean = 0.0
    if have and len(codes) == 2:
        a, b = codes
        ta, tb = ts[a], ts[b]
        assert ta and tb
        mine = subject or a
        other = b if mine == a else a
        tm, to = ts[mine], ts[other]
        assert tm and to
        if kind in ("moneyline", "spread"):
            diff = (tm.xg_pct_5v5 or 0.5) - (to.xg_pct_5v5 or 0.5)
            lean = diff if side == "yes" else -diff
            findings.append(
                S.Finding(
                    text=(
                        f"5-on-5 expected-goals share this season: {full[mine]} "
                        f"{_pct1(tm.xg_pct_5v5)} ({tm.games} games) vs {full[other]} "
                        f"{_pct1(to.xg_pct_5v5)} ({to.games}). {mp.ATTRIBUTION}."
                    ),
                    kind="statistical",
                    stance="supports" if lean > 0.02 else "opposes" if lean < -0.02 else "neutral",
                    source_ids=["M1"],
                    verified=True,
                )
            )
            gd_m, gd_o = tm.gf_pg - tm.ga_pg, to.gf_pg - to.ga_pg
            margin_text, margin_stance = "", "neutral"
            if kind == "spread" and line is not None:
                # Puck line: being the better team isn't winning by 2+. Compare a rough
                # season margin (own attack vs their defence, and the reverse) with the line.
                margin = (tm.gf_pg + to.ga_pg) / 2 - (to.gf_pg + tm.ga_pg) / 2
                gap = margin - line
                lean = gap if side == "yes" else -gap
                margin_stance = (
                    "supports" if lean > 0.3 else "opposes" if lean < -0.3 else "neutral"
                )
                margin_text = (
                    f" A rough average puts the {full[mine]} margin near {margin:+.1f} vs the "
                    f"{line:g}-goal line."
                )
            findings.append(
                S.Finding(
                    text=(
                        f"Goal difference per game: {full[mine]} {gd_m:+.2f}, {full[other]} "
                        f"{gd_o:+.2f}.{margin_text} (Season averages, not a probability.)"
                    ),
                    kind="statistical",
                    stance=margin_stance,  # type: ignore[arg-type]
                    source_ids=["M1"],
                    verified=True,
                )
            )
            if kind == "spread":
                # The goal-margin check is the relevant one: put it before the xG share.
                findings[-1], findings[-2] = findings[-2], findings[-1]
        else:
            if kind == "total":
                est = (ta.gf_pg + tb.ga_pg + tb.gf_pg + ta.ga_pg) / 2
                what = "combined goals"
            else:
                est = (tm.gf_pg + to.ga_pg) / 2
                what = f"{full[mine]} goals"
            gap = est - (line or est)
            lean = gap if side == "yes" else -gap
            findings.append(
                S.Finding(
                    text=(
                        f"Season scoring: {full[a]} {ta.gf_pg:.2f} for / {ta.ga_pg:.2f} against "
                        f"per game; {full[b]} {tb.gf_pg:.2f} / {tb.ga_pg:.2f}. A rough average "
                        f"puts {what} near {est:.1f} vs the {line:g} line (a sanity check, not a "
                        f"probability). {mp.ATTRIBUTION}."
                    ),
                    kind="statistical",
                    stance="supports" if lean > 0.3 else "opposes" if lean < -0.3 else "neutral",
                    source_ids=["M1"],
                    verified=True,
                )
            )
        tops = []
        for c in codes:
            g = goalies[c].options[0] if goalies[c].options else None
            if g:
                tops.append(
                    f"{g.name} {_sv(g.save_pct)} sv%, {g.gsax:+.1f} goals saved above "
                    f"expected ({g.games} GP)"
                )
        if tops:
            findings.append(
                S.Finding(
                    text=(
                        "Most-used goalies: " + "; ".join(tops) + ". Who starts tonight decides "
                        "how much this matters."
                    )[:400],
                    kind="statistical",
                    stance="neutral",
                    source_ids=["M1"],
                    verified=True,
                )
            )
        findings.append(
            S.Finding(
                text=(
                    f"Season figures cover {ta.games} and {tb.games} games and don't include "
                    "rest, travel or tonight's lineup."
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
                text="No season data for this matchup; only the price is known.",
                kind="interpretation",
                stance="neutral",
                source_ids=[],
                verified=True,
            )
        )
    leak = season is not None and season.data_as_of is not None and season.data_as_of > start
    if leak:
        findings.append(
            S.Finding(
                text="MoneyPuck updated after this game started, so the season figures may "
                "already include it (not a point-in-time view).",
                kind="interpretation",
                stance="neutral",
                source_ids=["M1"],
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

    # --- takeaway, gaps -------------------------------------------------------------------
    ask_c = f"{all_in * 100:.0f}¢ all-in" if all_in is not None else "current"
    if not have:
        first = f"There's no season data to check {phrase} against, so only the price is known."
    elif kind == "spread":
        tilt = "above" if lean > 0.3 else "below" if lean < -0.3 else "close to"
        first = (
            f"Season goal margins sit {tilt} what {phrase} needs, but there's no validated "
            f"NHL model, so the {ask_c} price isn't checked against an estimate."
        )
    elif kind == "moneyline":
        tilt = "favour" if lean > 0.02 else "cut against" if lean < -0.02 else "are about even for"
        first = (
            f"Season expected-goals numbers {tilt} {phrase}, but there's no validated NHL "
            f"model, so the {ask_c} price isn't checked against an estimate."
        )
    else:
        tilt = "above" if lean > 0.3 else "below" if lean < -0.3 else "close to"
        first = (
            f"Season scoring averages sit {tilt} what {phrase} needs; that's context, "
            f"not a probability for the {ask_c} price."
        )
    if gstates == {"unknown"}:
        second = "Neither starting goalie is known yet, so check before relying on it."
    elif "conflicting" in gstates:
        second = "Reports disagree on a starting goalie, so check before relying on it."
    else:
        second = "A reported starter isn't an official confirmation: check before puck drop."
    takeaway = f"{first} {second}"
    gaps = ["Who starts in goal tonight (no official lineup source is connected)."]
    gaps.append(
        "Rest, travel and injuries aren't checked (no permitted NHL schedule or injury source yet)."
    )
    if news is None or not news.attempted:
        gaps.append("News and late lineup changes were not checked.")
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
            uncertainty="High: no NHL model; season averages and unconfirmed goalies only.",
        ),
        price_assessment=price,
        details=S.Details(
            supports=[f for f in findings if f.stance == "supports"],
            against=against,
            methodology=[
                "Market mapping: exact Kalshi ticker, side, team and line; " + SETTLEMENT[kind],
                f"Stats: MoneyPuck season files (teams, goalies), {mp.ATTRIBUTION}; "
                "non-commercial use, credited; refreshed at most twice a day.",
                "Goalie status: from news headlines/snippets only (reported, never confirmed); "
                "unknown when nothing names a starter.",
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
    result.summary.coverage = service.coverage(result, goalies=goalies)
    if synthesizer is not None:
        result = synth.apply(result, news.snippets if news is not None else {}, synthesizer)
    return result
