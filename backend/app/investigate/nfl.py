"""NFL investigation (deterministic, then optional news + local summary).

Evidence: nflverse release files (schedule facts, weekly team stats, the weekly injury
report; each its own registry entry), Open-Meteo kickoff weather for open-air stadiums, and,
on an explicit run, Brave news metadata. ESPN and NFL.com are NOT used (see sources.py).

Safety rules kept here:
- Market mapping is exact. Game winner settles on the official final result (overtime
  counts) and a tie pays $0.50 per team; spreads and totals use the official final score,
  overtime included. Half, quarter and prop markets are unsupported, not approximated.
- Starting QB status is confirmed / expected / unknown / conflicting / not_applicable. It
  is NEVER "confirmed": the schedule's listed QB is a projection and news is a report.
  A listed QB who is Out or Doubtful on this week's report makes the state unknown, and a
  missing week of the injury report is shown as unknown, never as healthy.
- Point in time: season form counts only games that kicked off before this one.
- Context, not a probability: no model estimate, no conservative edge.
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
from app.investigate.search import Gathered, game_date
from app.sportsdata import nflverse as nv
from app.sportsdata import weather as wx

PREFIX = "KXNFL"
KINDS = {"GAME": "moneyline", "SPREAD": "spread", "TOTAL": "total", "TEAMTOTAL": "team_total"}
PERIODS = ("1H", "2H", "1Q", "2Q", "3Q", "4Q", "Q1", "Q2", "Q3", "Q4")
PROPS = re.compile(
    r"^(PASS|RSH|RUSH|REC|RR|TD|FIRSTTD|ANYTD|LONG|FG|SACK|INT|LADDER|ESCALATOR|FF|DSTTD)"
)
SETTLEMENT = {
    "moneyline": "Settles on the official final result, so overtime counts. If the game ends "
    "in a tie, each team's market pays $0.50. A game postponed more than 48 hours resolves "
    "at a fair price.",
    "spread": "Settles on the official final score, which includes overtime (Kalshi's rule "
    "doesn't mention overtime separately). A tie isn't a win, so a winning-margin YES loses.",
    "total": "Counts every point in the official final score, overtime included (Kalshi's "
    "rule doesn't mention overtime separately).",
    "team_total": "Counts the team's points in the official final score, overtime included "
    "(Kalshi's rule doesn't mention overtime separately).",
}
NO_MODEL = (
    "No validated NFL probability model yet: the season figures are context, not an estimate, "
    "so no edge is calculated."
)
STARTS = (
    r"(will start|to start|starts|starting|expected to start|projected to start|gets the "
    r"(?:start|nod|call)|under center|named (?:the )?starter|QB1|confirmed)"
)


def is_nfl(ticker: str) -> bool:
    return ticker.startswith(PREFIX)


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
            else "Only single-game markets can be investigated."
        )
    if rest.startswith(PERIODS):
        return "Half and quarter markets aren't covered: the data is full-game only."
    if PROPS.match(rest):
        return "Player props aren't covered for the NFL yet."
    return "Only NFL game winner, spread and totals can be investigated."


@dataclass
class QbRead:
    team: str
    state: str  # confirmed (never set) / expected / unknown / conflicting / not_applicable
    name: str | None = None
    basis: str = ""
    injury: str | None = None  # "Questionable (ankle)" etc. from this week's report
    source_ids: list[str] = field(default_factory=list)
    options: list[tuple[str, int]] = field(default_factory=list)  # prior starters, starts


def _last(name: str) -> str:
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    while parts and parts[-1].rstrip(".").lower() in ("jr", "sr", "ii", "iii", "iv", "v"):
        parts.pop()
    return parts[-1] if parts else ""


def qb_status(
    codes: list[str],
    game: nv.Game | None,
    season: nv.SeasonData | None,
    news: Gathered | None,
    report_week: bool,
) -> dict[str, QbRead]:
    """Per team: the schedule's listed QB, checked against this week's injury report and
    news headlines/snippets. Never 'confirmed' (no official lineup source)."""
    out: dict[str, QbRead] = {}
    texts: list[tuple[str, str]] = []
    if news is not None:
        for s in news.sources:
            if not s.duplicate_of:
                texts.append((s.id, f"{s.title}. {news.snippets.get(s.id, '')}"))
    for code in codes:
        t = nv.nv_code(code)
        listed = ""
        if game is not None:
            listed = game.away_qb if game.away == t else game.home_qb if game.home == t else ""
        opts = season.prior_starters(code, game.kickoff) if season and game and game.kickoff else []
        cands = list(
            dict.fromkeys(
                [n for n in [listed] if n]
                + [n for n, _ in opts]
                + (season.qbs_on_report(code) if season else [])
            )
        )
        named: dict[str, list[str]] = {}
        for n in cands:
            last = _last(n)
            if len(last) < 3:
                continue
            pat = re.compile(
                rf"\b{re.escape(last)}\b[^.]{{0,60}}?\b{STARTS}|\b{STARTS}\b[^.]{{0,40}}?"
                rf"\b{re.escape(last)}\b",
                re.I,
            )
            for sid, txt in texts:
                if pat.search(txt):
                    named.setdefault(n, []).append(sid)
        inj = None
        if season and game and report_week:
            row = next(
                (i for i in season.injuries_for(code, game.week) if listed and i.name == listed),
                None,
            )
            if row and row.status:
                inj = f"{row.status}" + (f" ({row.injury.lower()})" if row.injury else "")
        injured_out = bool(inj and nv.is_out(inj.split(" ")[0]))
        if len(named) > 1 or (len(named) == 1 and listed and next(iter(named)) != listed):
            ids = [i for v in named.values() for i in v][:4]
            out[code] = QbRead(code, "conflicting", None, "reports differ", inj, ids, opts)
        elif len(named) == 1:
            n, ids = next(iter(named.items()))
            state = "unknown" if injured_out else "expected"
            out[code] = QbRead(code, state, n, "news report", inj, ids[:3], opts)
        elif listed and not injured_out:
            out[code] = QbRead(code, "expected", listed, "listed", inj, [], opts)
        elif listed:
            out[code] = QbRead(code, "unknown", listed, "listed but on the report", inj, [], opts)
        else:
            out[code] = QbRead(code, "unknown", None, "not listed", None, [], opts)
    return out


def build(
    session: Session,
    nv_src: Any,
    wx_src: Any,
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
    kind = market_kind(series)
    errors: list[str] = []
    key = m.event_ticker.split("-", 1)[1]
    names = games.list_games_teams(session, PREFIX, key)
    codes = list(names)
    teams = [{"code": c, "name": nv.NFL_TEAMS.get(c, names[c])} for c in codes]
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
        sport="football",
        league="NFL",
        market_type=kind,  # type: ignore[arg-type]
        threshold=line,
        subject=full.get(subject or "") or None,
        label=name,
        statement=statement,
        snapshot_at=service._iso(m.refreshed_at),
        rules_url=f"https://kalshi.com/markets/{series.lower()}",
    )

    # --- nflverse (free, credited) -------------------------------------------------------
    day = game_date(m.event_ticker)
    season: nv.SeasonData | None = None
    if nv_src is None or not sources.allows(
        "nflverse_schedules", "download_schedule_release", getattr(nv_src, "settings", None)
    ):
        errors.append("nflverse data is switched off (KRT_RESEARCH_DISABLED_SOURCES).")
    else:
        try:
            season = nv_src.season(nv.season_of(day or now))
            errors.extend(season.errors)
        except AdapterError as exc:
            errors.append(f"nflverse data unavailable right now ({exc}).")
    game = (
        season.find_game(codes[0], codes[1], day.date() if day else None)
        if (season and len(codes) == 2)
        else None
    )
    if season is not None and game is None:
        errors.append("This game isn't in the nflverse schedule.")
    kickoff = (game.kickoff if game else None) or (
        e.occurs_at - timedelta(hours=3) if e and e.occurs_at else None
    )
    before = kickoff or now
    forms = {c: season.form(c, before) for c in codes} if season and game else {}
    have = len(codes) == 2 and all(f.games >= 1 for f in forms.values()) and len(forms) == 2
    latest = season.latest_injury_week() if season else None
    report_week = bool(game and latest is not None and latest >= game.week)
    injuries_on = sources.allows(
        "nflverse_injuries", "download_injury_report_release", getattr(nv_src, "settings", None)
    )

    # --- weather (open-air stadiums only) ------------------------------------------------
    forecast: wx.Forecast | None = None
    wx_note = None
    if game is not None:
        wx_note = wx.skip_reason(game.stadium_id, game.roof, game.location, kickoff, now)
        if wx_note is None:
            if wx_src is None or not sources.allows(
                "open_meteo", "forecast_lookup_noncommercial", getattr(wx_src, "settings", None)
            ):
                wx_note = "weather lookup switched off"
            else:
                try:
                    forecast = wx_src.kickoff(game.stadium_id, kickoff)
                except AdapterError as exc:
                    wx_note = "forecast unavailable"
                    errors.append(f"Open-Meteo forecast unavailable right now ({exc}).")

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

    # --- sources ------------------------------------------------------------------------
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
        files = (
            ["schedule"]
            + (["team stats"] if season.weeks else [])
            + (["injury report"] if season.injuries else [])
        )
        srcs.append(
            S.Source(
                id="F1",
                url=nv.PAGE,
                title=f"nflverse {season.season} season ({', '.join(files)}). {nv.ATTRIBUTION}"[
                    :200
                ],
                publisher="nflverse",
                published_at=service._iso(season.data_as_of),
                retrieved_at=service._iso(season.retrieved_at) or now.isoformat(),
                access="internal",
                line_match="exact",
            )
        )
    if forecast is not None:
        srcs.append(
            S.Source(
                id="W1",
                url=wx.PAGE,
                title=f"Kickoff forecast for {game.stadium if game else 'the stadium'}. "
                f"{wx.ATTRIBUTION}"[:200],
                publisher="Open-Meteo",
                published_at=service._iso(forecast.retrieved_at),
                retrieved_at=service._iso(forecast.retrieved_at) or now.isoformat(),
                access="internal",
                line_match="exact",
            )
        )

    # --- news (only on an explicit run; snippets stay in memory) -------------------------
    news: Gathered | None = gatherer(hyp, teams) if gatherer is not None else None
    if news is not None:
        srcs.extend(news.sources)
        errors.extend(news.errors)
    qbs = qb_status(codes, game, season, news, report_week and injuries_on)

    # --- findings -----------------------------------------------------------------------
    findings: list[S.Finding] = []

    def qtext(q: QbRead) -> str:
        t = full.get(q.team, q.team)
        inj = f", {q.injury} on the report" if q.injury else ""
        if q.state == "conflicting":
            return f"{t}: reports name different starters"
        if q.state == "expected" and q.basis == "news report":
            return f"{t}: {q.name} reported as the starter{inj}"
        if q.state == "expected":
            return f"{t}: {q.name} listed (a projection){inj}"
        if q.name:
            return f"{t}: unknown ({q.name} listed{inj})"
        opts = ", ".join(f"{_last(n)} {k} start{'s' if k != 1 else ''}" for n, k in q.options[:2])
        return f"{t}: unknown" + (f" (this season: {opts})" if opts else "")

    qstates = {q.state for q in qbs.values()}
    findings.append(
        S.Finding(
            text=(
                "Starting quarterbacks — " + "; ".join(qtext(qbs[c]) for c in codes) + ". "
                "No official lineup source is connected, so neither is confirmed."
            )[:400],
            kind="factual" if season is not None else "interpretation",
            stance="neutral",
            source_ids=sorted(
                {i for q in qbs.values() for i in q.source_ids} | ({"F1"} if season else set())
            )[:6],
            verified=True,
        )
    )

    lean = 0.0
    main: S.Finding | None = None
    extra: list[S.Finding] = []
    if have:
        a, b = codes
        fa, fb = forms[a], forms[b]
        mine = subject or a
        other = b if mine == a else a
        fm, fo = forms[mine], forms[other]
        margin = (fm.pf_pg + fo.pa_pg) / 2 - (fo.pf_pg + fm.pa_pg) / 2
        if kind == "moneyline":
            lean = margin if side == "yes" else -margin
            main = S.Finding(
                text=(
                    f"Points per game before kickoff: {full[mine]} {fm.pf_pg:.1f} for / "
                    f"{fm.pa_pg:.1f} against ({fm.games} games), {full[other]} {fo.pf_pg:.1f} / "
                    f"{fo.pa_pg:.1f} ({fo.games}). A rough average puts the {full[mine]} "
                    f"margin near {margin:+.1f} (no home-field or QB adjustment; not a "
                    f"probability). {nv.ATTRIBUTION}."
                ),
                kind="statistical",
                stance="supports" if lean > 2 else "opposes" if lean < -2 else "neutral",
                source_ids=["F1"],
                verified=True,
            )
        elif kind == "spread":
            gap = margin - (line or 0)
            lean = gap if side == "yes" else -gap
            main = S.Finding(
                text=(
                    f"Points per game before kickoff: {full[mine]} {fm.pf_pg:.1f} for / "
                    f"{fm.pa_pg:.1f} against, {full[other]} {fo.pf_pg:.1f} / {fo.pa_pg:.1f}. "
                    f"A rough average puts the {full[mine]} margin near {margin:+.1f} vs the "
                    f"{line:g}-point line (season averages, not a probability). "
                    f"{nv.ATTRIBUTION}."
                ),
                kind="statistical",
                stance="supports" if lean > 2 else "opposes" if lean < -2 else "neutral",
                source_ids=["F1"],
                verified=True,
            )
        else:
            if kind == "total":
                est = (fa.pf_pg + fb.pa_pg + fb.pf_pg + fa.pa_pg) / 2
                what = "combined points"
            else:
                est = (fm.pf_pg + fo.pa_pg) / 2
                what = f"{full[mine]} points"
            gap = est - (line if line is not None else est)
            lean = gap if side == "yes" else -gap
            main = S.Finding(
                text=(
                    f"Scoring before kickoff: {full[a]} {fa.pf_pg:.1f} for / {fa.pa_pg:.1f} "
                    f"against per game; {full[b]} {fb.pf_pg:.1f} / {fb.pa_pg:.1f}. A rough "
                    f"average puts {what} near {est:.1f} vs the {line:g} line (a sanity check, "
                    f"not a probability). {nv.ATTRIBUTION}."
                ),
                kind="statistical",
                stance="supports" if lean > 3 else "opposes" if lean < -3 else "neutral",
                source_ids=["F1"],
                verified=True,
            )
        if all(f.off_epa_play is not None and f.def_epa_play is not None for f in (fa, fb)):

            def epa(f: nv.Form) -> str:
                return (
                    f"{full[f.team]} offense {f.off_epa_play:+.2f}, defense allows "
                    f"{f.def_epa_play:+.2f}"
                )

            extra.append(
                S.Finding(
                    text=(
                        f"EPA per play before kickoff (passing and rushing): {epa(fa)}; "
                        f"{epa(fb)}. Higher offense and lower defense numbers are better. "
                        f"{nv.ATTRIBUTION}."
                    ),
                    kind="statistical",
                    stance="neutral",
                    source_ids=["F1"],
                    verified=True,
                )
            )
    else:
        main = S.Finding(
            text="No season data for this matchup before kickoff; only the price is known.",
            kind="interpretation",
            stance="neutral",
            source_ids=[],
            verified=True,
        )

    # Injury report (this week's, or say plainly that it isn't out yet).
    inj_finding: S.Finding | None = None
    if season is not None and game is not None and injuries_on and season.injuries:
        if report_week:
            parts = []
            for c in codes:
                rows = [
                    i
                    for i in season.injuries_for(c, game.week)
                    if i.status.lower() in ("out", "doubtful")
                ]
                q = sum(
                    1
                    for i in season.injuries_for(c, game.week)
                    if i.status.lower() == "questionable"
                )
                named = ", ".join(f"{i.name} ({i.position}, {i.status})" for i in rows[:4])
                more = f" +{len(rows) - 4} more" if len(rows) > 4 else ""
                parts.append(
                    f"{full[c]}: "
                    + (named + more if rows else "nobody out or doubtful")
                    + (f"; {q} questionable" if q else "")
                )
            inj_finding = S.Finding(
                text=(f"Week {game.week} injury report — " + "; ".join(parts) + ".")[:400],
                kind="factual",
                stance="neutral",
                source_ids=["F1"],
                verified=True,
            )
        else:
            inj_finding = S.Finding(
                text=(
                    f"This week's injury report (week {game.week}) isn't in the nflverse file "
                    f"yet (latest: week {latest}), so player availability is unknown."
                ),
                kind="interpretation",
                stance="neutral",
                source_ids=["F1"],
                verified=True,
            )

    # Rest, venue and weather.
    if game is not None:
        rest = []
        for c in codes:
            s = game.side_of(nv.nv_code(c))
            r = game.away_rest if s == "away" else game.home_rest if s == "home" else None
            if r is not None:
                rest.append(f"{full[c]} {r} days")
        venue = {
            "dome": "indoors (dome)",
            "closed": "indoors (roof closed)",
            "outdoors": "open-air",
            "open": "roof open",
        }.get(game.roof, "retractable roof, open or closed not known")
        wtxt = ""
        if forecast is not None:
            bits = []
            if forecast.temp_f is not None:
                bits.append(f"{forecast.temp_f:.0f}°F")
            if forecast.wind_mph is not None:
                g = f" (gusts {forecast.gust_mph:.0f})" if forecast.gust_mph is not None else ""
                bits.append(f"wind {forecast.wind_mph:.0f} mph{g}")
            if forecast.precip_prob is not None:
                bits.append(f"{forecast.precip_prob:.0f}% chance of precipitation")
            wtxt = (
                f" Forecast for kickoff ({forecast.at:%b %d %H:00} UTC), retrieved "
                f"{forecast.retrieved_at:%b %d %H:%M} UTC: "
                + ", ".join(bits)
                + f". {wx.ATTRIBUTION}."
            )
        elif wx_note and wx_note != "indoors" and not wx_note.startswith("retractable"):
            wtxt = f" Weather not checked: {wx_note}."
        extra.append(
            S.Finding(
                text=(
                    f"Rest: {', '.join(rest) or 'unknown'}. {game.stadium or 'Venue'}: {venue}"
                    + (" (neutral site)" if game.location == "Neutral" else "")
                    + (", division game" if game.div_game else "")
                    + f".{wtxt}"
                )[:400],
                kind="factual",
                stance="neutral",
                source_ids=["F1"] + (["W1"] if forecast is not None else []),
                verified=True,
            )
        )
    if have:
        fa, fb = forms[codes[0]], forms[codes[1]]
        extra.append(
            S.Finding(
                text=(
                    f"Season figures cover {fa.games} and {fb.games} games played before this "
                    "kickoff (later games excluded) and don't adjust for opponents, travel or "
                    "who plays quarterback."
                ),
                kind="interpretation",
                stance="neutral",
                source_ids=[],
                verified=True,
            )
        )
    started = kickoff is not None and now >= kickoff
    if started:
        extra.append(
            S.Finding(
                text="This game has already kicked off: the pre-game view may be out of date.",
                kind="interpretation",
                stance="neutral",
                source_ids=[],
                verified=True,
            )
        )
    if news is not None and news.sources:
        n = len(news.sources)
        indep = sum(1 for x in news.sources if x.duplicate_of is None)
        extra.append(
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
    if main is not None:
        findings.append(main)
    if inj_finding is not None:
        findings.append(inj_finding)
    findings.extend(extra)

    # --- takeaway, gaps -----------------------------------------------------------------
    ask_c = f"{all_in * 100:.0f}¢ all-in" if all_in is not None else "current"
    if not have:
        first = f"There's no season data to check {phrase} against, so only the price is known."
    elif kind in ("moneyline", "spread"):
        if kind == "spread":
            tilt = "above" if lean > 2 else "below" if lean < -2 else "close to"
            what = f"Season scoring margins sit {tilt} what {phrase} needs"
        else:
            tilt = "favour" if lean > 2 else "cut against" if lean < -2 else "are about even for"
            what = f"Season scoring margins {tilt} {phrase}"
        first = (
            f"{what}, but there's no validated NFL model, so the {ask_c} price isn't checked "
            "against an estimate."
        )
    else:
        tilt = "above" if lean > 3 else "below" if lean < -3 else "close to"
        first = (
            f"Season scoring averages sit {tilt} what {phrase} needs; that's context, not a "
            f"probability for the {ask_c} price."
        )
    if "conflicting" in qstates:
        second = "Reports disagree on a starting quarterback, so check before relying on it."
    elif "unknown" in qstates:
        second = "A starting quarterback isn't known, so check before relying on it."
    else:
        second = "Listed or reported quarterbacks aren't official: check before kickoff."
    takeaway = f"{first} {second}"
    gaps = ["Who starts at quarterback (no official lineup source is connected)."]
    if not injuries_on:
        gaps.append("The injury report is switched off (KRT_RESEARCH_DISABLED_SOURCES).")
    elif game is not None and not report_week:
        gaps.append(f"This week's injury report (week {game.week}) isn't available yet.")
    if game is not None and forecast is None and wx_note not in (None, "indoors"):
        gaps.append(f"Weather not checked ({wx_note}).")
    gaps.append("Travel, coaching and late scratches aren't checked.")
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
            uncertainty="High: no NFL model; season averages and unconfirmed quarterbacks only.",
        ),
        price_assessment=price,
        details=S.Details(
            supports=[f for f in findings if f.stance == "supports"],
            against=against,
            methodology=[
                "Market mapping: exact Kalshi ticker, side, team and line; " + SETTLEMENT[kind],
                f"Stats: nflverse schedule, weekly team stats and injury report ({nv.ATTRIBUTION}"
                "); only games that kicked off before this one; sportsbook columns ignored; "
                "refreshed at most twice a day.",
                "Quarterbacks: the schedule's listed QB (a projection), this week's injury "
                "report and news headlines/snippets; never confirmed.",
                "Weather: Open-Meteo forecast at kickoff for open-air home stadiums only "
                f"({wx.ATTRIBUTION}).",
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
    result.summary.coverage = service.coverage(result, quarterbacks=qbs)
    if synthesizer is not None:
        result = synth.apply(result, news.snippets if news is not None else {}, synthesizer)
    return result
