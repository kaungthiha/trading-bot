"""Deterministic investigation of one exact contract (Phase B: no search, no model).

Reuses, never duplicates:
- the catalog quote (ask for the side you'd buy; NO ask = 1 - YES bid when unquoted),
- box-score evidence (app.sportsdata.service.evidence_for),
- the slip check's fee schedule, all-in price and walk-away (app.catalog.slipcheck).

Rules kept here:
- The box-score estimate is a FREQUENCY, labelled as such. A conservative edge (the low end
  of its 80% range minus the all-in price) is only shown when the sample is big enough and
  the quote is fresh; otherwise the reasons are listed and no edge is shown.
- A stale quote is never used for an actionable number.
- Every external-looking claim carries a source id; internal data is cited as such.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import AdapterError
from app.catalog import games
from app.catalog.slipcheck import Fees, _side_prices, price_single, walk_away
from app.catalog.stats import Quote as CatQuote
from app.catalog.stats import implied
from app.db.models import CatalogEvent, CatalogMarket, Investigation
from app.investigate import registry, synth
from app.investigate import schemas as S
from app.investigate.search import Gathered
from app.sportsdata.espn import COLLEGE, LEAGUE_LABEL, LEAGUES
from app.sportsdata.evidence import avg_text
from app.sportsdata.service import evidence_for

# Bump when rules change (cache key). v2 roster check, v3 news search, v4 college leagues,
# v5 NHL + source coverage line, v6 NFL.
POLICY_VERSION = "v6"
QUOTE_FRESH = timedelta(minutes=30)
MIN_GAMES_FOR_EDGE = 15
PROP = re.compile(r"(PTS|REB|AST|3PT|BLK|STL|PRA|STOCK|2D|3D)")
PERIODS = ("1H", "2H", "1Q", "2Q", "3Q", "4Q")
GAME_EVENT = re.compile(r"-\d{2}[A-Z]{3}\d{2}")
KIND_FROM_EVIDENCE = {
    "team_win": "moneyline",
    "team_margin": "spread",
    "game_total": "total",
    "team_total": "team_total",
    "player_stat": "player_prop",
}


OUT = ("out", "doubtful")


def league_of(ticker: str) -> tuple[str, str] | None:
    """(Kalshi prefix, ESPN league slug) for a supported ticker, longest prefix first."""
    p = next((p for p in sorted(LEAGUES, key=len, reverse=True) if ticker.startswith(p)), None)
    return None if p is None else (p, LEAGUES[p])


def roster(session: Session, src: Any, event_ticker: str) -> list[dict[str, Any]]:
    """Tonight's injury report for both teams of the game (the Games strip's data):
    [{code, name, out: [player], questionable: [player], known}]. Empty if unavailable.
    College has no injury report: teams come back with known=False (names still feed the
    news search), and an unknown lineup is never read as a healthy one."""
    lg = league_of(event_ticker)
    if src is None or lg is None or "-" not in event_ticker:
        return []
    prefix, league = lg
    key = event_ticker.split("-", 1)[1]
    names = games.list_games_teams(session, prefix, key)
    known = league not in COLLEGE
    inj = src.injuries(league) if known else []
    out = []
    for code, name in names.items():
        ref = src.team(league, code, name)
        items = [i for i in inj if ref and i["team_id"] == ref["id"]]
        out.append(
            {
                "code": code,
                "name": ref["name"] if ref else name,
                "out": [i["player"] for i in items if i["status"].lower() in OUT],
                "questionable": [i["player"] for i in items if i["status"].lower() not in OUT],
                "known": known,
            }
        )
    return out


def subject_team(ticker: str, kind: str) -> str | None:
    """Team code a team market is about ('...-GSW', '...-MEM4'); None for totals and props."""
    if kind not in ("moneyline", "spread", "team_total"):
        return None
    m = re.match(r"[A-Z]+", ticker.rsplit("-", 1)[-1])
    return m.group(0) if m else None


class Unsupported(ValueError):
    """The selection can't be investigated (with a reason the UI shows)."""


class NotFound(LookupError):
    pass


def market_kind(series: str) -> str:
    """Kind from the series suffix after the league prefix. Halves and quarters (1H, 2Q...)
    are 'other': full-game box scores can't check them."""
    s = series.upper()
    lg = league_of(s)
    rest = s[len(lg[0]) :] if lg else s
    if rest.startswith(PERIODS):
        return "other"
    if rest.endswith("TEAMTOTAL"):
        return "team_total"
    if rest.endswith("SPREAD"):
        return "spread"
    if rest.endswith("TOTAL"):
        return "total"
    if rest == "GAME":
        return "moneyline"
    if PROP.match(rest):
        return "player_prop"
    return "other"


def check_supported(ticker: str, event_ticker: str, series: str) -> None:
    from app.investigate import nfl, nhl

    sport = nhl if nhl.is_nhl(ticker) else nfl if nfl.is_nfl(ticker) else None
    if sport is not None:
        why = sport.unsupported_reason(series, event_ticker)
        if why:
            raise Unsupported(why)
        return
    if league_of(ticker) is None:
        raise Unsupported(
            "Investigation covers NBA, WNBA, college basketball, NHL and NFL game markets for now."
        )
    if market_kind(series) == "other":
        raise Unsupported("Only game winner, spread, totals and player props can be investigated.")
    if not GAME_EVENT.search(event_ticker):
        raise Unsupported("Only single-game markets can be investigated.")


def _iso(d: datetime | None) -> str | None:
    return None if d is None else d.isoformat()


def _f(x: Decimal | float | None) -> float | None:
    return None if x is None else round(float(x), 4)


def _pct(p: float | None) -> str:
    return "—" if p is None else f"{p * 100:.0f}%"


def quote_for(m: CatalogMarket, side: str, now: datetime) -> S.Quote:
    ask, _ = _side_prices(m, side)
    fresh = m.refreshed_at is not None and now - m.refreshed_at <= QUOTE_FRESH
    return S.Quote(
        ask=_f(ask),
        side=side,
        observed_at=_iso(m.refreshed_at),
        fresh=fresh,  # type: ignore[arg-type]
        snapshot_ref=f"catalog:{m.ticker}@{_iso(m.refreshed_at)}",
    )


def cache_key(ticker: str, side: str, m: CatalogMarket, model: str = "none") -> str:
    return (
        f"{ticker}|{side}|{_iso(m.refreshed_at)}|{POLICY_VERSION}|"
        f"{registry.REGISTRY_VERSION}|{model}"
    )


def coverage(r: S.Result, goalies: Any = None, quarterbacks: Any = None) -> str:
    """One line on what the result rests on: structured datasets (not counting the Kalshi
    quote), commentary links, and the lineup/goalie state. Ordered by impact, not count."""
    data = [s for s in r.sources if s.access == "internal" and s.id != "K1"]
    links = [s for s in r.sources if s.access != "internal" and s.duplicate_of is None]
    parts = [
        f"{len(data)} factual dataset{'s' if len(data) != 1 else ''}",
        f"{len(links)} commentary link{'s' if len(links) != 1 else ''}",
    ]
    if goalies is not None:
        states = {g.state for g in goalies.values()}
        parts.append(
            "goalie status unknown" if states == {"unknown"}
            else "goalie reports conflict" if "conflicting" in states
            else "goalie status unconfirmed"
        )
    elif quarterbacks is not None:
        states = {q.state for q in quarterbacks.values()}
        parts.append(
            "QB reports conflict" if "conflicting" in states
            else "starting QB unknown" if "unknown" in states
            else "starting QBs unconfirmed"
        )
    elif any(f.text == synth.LINEUP_UNKNOWN for f in r.summary.findings):
        parts.append("lineup unknown (no injury report)")
    elif any("E2" in f.source_ids for f in r.summary.findings + r.details.against):
        parts.append("injury report checked")
    return " · ".join(parts)


def build(
    session: Session,
    src: Any,
    ticker: str,
    side: str,
    label: str | None,
    now: datetime,
    cache_hours: float,
    gatherer: Any = None,
    synthesizer: Any = None,
    mp_src: Any = None,
    nv_src: Any = None,
    wx_src: Any = None,
) -> S.Result:
    from app.investigate import nfl, nhl

    if nhl.is_nhl(ticker):
        return nhl.build(session, mp_src, ticker, side, label, now, cache_hours,
                         gatherer=gatherer, synthesizer=synthesizer)
    if nfl.is_nfl(ticker):
        return nfl.build(session, nv_src, wx_src, ticker, side, label, now, cache_hours,
                         gatherer=gatherer, synthesizer=synthesizer)
    m = session.get(CatalogMarket, ticker)
    if m is None:
        raise NotFound(f"{ticker} is not in the catalog (run a scan)")
    e = session.get(CatalogEvent, m.event_ticker)
    series = e.series_ticker if e else ticker.split("-")[0]
    check_supported(ticker, m.event_ticker, series)
    _, league = league_of(ticker)  # type: ignore[misc]
    league_label = LEAGUE_LABEL.get(league, league)
    college = league in COLLEGE
    errors: list[str] = []

    # --- box-score evidence (free, ESPN) -----------------------------------------------------
    ev: dict[str, Any] | None = None
    if src is None:
        errors.append("Box-score evidence is switched off (KRT_SPORTS_EVIDENCE_ENABLED=false).")
    else:
        try:
            out, _, _ = evidence_for(session, src, [(ticker, side)])
            ev = next((lg for lg in out.get("legs", []) if lg["ticker"] == ticker), None)
        except AdapterError as exc:
            errors.append(f"Box scores unavailable right now ({exc}).")
    supported = bool(ev and ev.get("supported"))
    teams: list[dict[str, Any]] = []
    try:
        teams = roster(session, src, m.event_ticker)
    except AdapterError as exc:
        errors.append(f"Injury report unavailable right now ({exc}).")

    # --- hypothesis ---------------------------------------------------------------------------
    kind = KIND_FROM_EVIDENCE.get((ev or {}).get("kind") or "", market_kind(series))
    line = None if kind == "moneyline" else (ev or {}).get("line")
    name = (label or m.yes_sub_title or m.title).strip()[:200]
    subject = ((ev or {}).get("subject") or {}).get("name")
    statement = name if side == "yes" else f"NOT: {name} (betting it doesn't happen)"
    phrase = f"“{name}”" if side == "yes" else f"a NO on “{name}”"
    hyp = S.Hypothesis(
        ticker=ticker,
        event_ticker=m.event_ticker,
        side=side,
        sport="basketball",  # type: ignore[arg-type]
        league=league_label,
        market_type=kind,
        threshold=line,
        subject=subject,
        label=name,  # type: ignore[arg-type]
        statement=statement,
        snapshot_at=_iso(m.refreshed_at),
        rules_url=f"https://kalshi.com/markets/{series.lower()}",
    )

    # --- quote and price (existing slip-check maths) --------------------------------------------
    quote = quote_for(m, side, now)
    fees = Fees(session)
    y, _ = implied(CatQuote(ticker, ticker, m.yes_bid, m.yes_ask))
    mid = None if y is None else Decimal(str(y if side == "yes" else 1 - y))
    ask, bid = _side_prices(m, side)
    est = (ev or {}).get("estimate") if supported else None
    interval = (ev or {}).get("interval") if supported else None
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
            "history": None if est is None else Decimal(str(round(est, 4))),
            "p_est": None if est is None else Decimal(str(round(est, 4))),
        },
    )
    all_in = float(ps["all_in"]) if ps.get("all_in") else None
    fee = None if ask is None else float(fees.taker(series, Decimal(100), ask) / 100)
    windows = (ev or {}).get("windows") or {}
    season_games = (windows.get("season") or [0, 0])[1] if windows else 0
    abstain: list[str] = []
    if not supported:
        abstain.append(
            "No box-score estimate for this market"
            + (f": {ev.get('reason')}" if ev and ev.get("reason") else ".")
        )
    if est is not None:
        abstain.append(
            "Box-score history is a frequency from past games, not a calibrated probability."
        )
    if est is not None and season_games < MIN_GAMES_FOR_EDGE:
        abstain.append(
            f"Only {season_games} games this season "
            f"(needs {MIN_GAMES_FOR_EDGE}+ to estimate an edge)."
        )
    if (ev or {}).get("verdict") == "thin":
        abstain.append("Too few games on record.")
    if not quote.fresh:
        abstain.append("The quote is stale: refresh prices before using any edge.")
    if ask is None:
        abstain.append("No ask to buy at right now.")
    # Past games assume a normal lineup: if tonight's isn't, history can't price it.
    own_team = subject_team(ticker, kind)
    roster_issue = None
    if kind != "player_prop":
        hit = [t for t in teams if t["out"]]
        if hit:
            roster_issue = "; ".join(f"{t['name']} has {len(t['out'])} out" for t in hit)
    else:
        inj = (ev or {}).get("injury") or {}
        if inj and inj.get("player") == subject:
            roster_issue = f"{subject} is listed {inj.get('status', '').lower()}"
    if roster_issue:
        abstain.append(
            f"Tonight's lineup isn't normal ({roster_issue}); past games don't "
            "reflect it, so no edge is estimated."
        )
    # No injury report means no idea who's playing: never treat that as a normal lineup.
    lineup_unknown = college
    if lineup_unknown:
        abstain.append(
            "There's no injury report for college games, so tonight's lineup is unknown and "
            "no edge is estimated."
        )
    edge_ok = (
        roster_issue is None
        and not lineup_unknown
        and est is not None
        and interval
        and all_in is not None
        and quote.fresh
        and season_games >= MIN_GAMES_FOR_EDGE
        and (ev or {}).get("verdict") != "thin"
    )
    cons = round(interval[0] - all_in, 4) if edge_ok else None  # type: ignore[index]
    wa = walk_away(Decimal(str(est)), fees, series) if edge_ok else None
    price = S.Price(
        ask=_f(ask),
        model_p=_f(est),
        model_band=(_f(interval[0]), _f(interval[1])) if interval else None,  # type: ignore[arg-type]
        model_name="Box-score history (frequency, not calibrated)" if est is not None else None,
        raw_diff=None if est is None or all_in is None else round(est - all_in, 4),
        conservative_edge=cons,
        break_even=all_in,
        walk_away=_f(wa),
        fee_per_contract=_f(fee),
        slippage_per_contract=0.0,
        assumptions=[
            f"Ask from the last catalog scan ({_iso(m.refreshed_at) or 'unknown time'}).",
            f"Taker fee from Kalshi's {'verified' if fees.verified else 'unverified'} "
            "schedule, one contract.",
            "No slippage allowance: assumes the top of the book has size for a small order"
            + (
                f" ({m.yes_ask_size} contracts shown)." if side == "yes" and m.yes_ask_size else "."
            ),
            "Break-even = all-in price per $1 payout.",
        ]
        + (
            ["Conservative edge = low end of the history range minus the all-in price."]
            if cons is not None
            else []
        ),
        abstain_reasons=abstain,
    )

    # --- findings (deterministic, sourced) ------------------------------------------
    sources = [
        S.Source(
            id="K1",
            url=hyp.rules_url or "https://kalshi.com",
            title=f"Kalshi market: {m.title}"[:200],
            publisher="Kalshi",
            retrieved_at=_iso(m.refreshed_at) or now.isoformat(),
            access="internal",
            line_match="exact",
        )
    ]
    findings: list[S.Finding] = []
    if supported:
        espn = ((ev or {}).get("subject") or {}).get("espn_url") or (
            f"https://www.espn.com/{league}/"
        )
        sources.append(
            S.Source(
                id="E1",
                url=espn,
                title=f"ESPN box scores: {subject or name}",
                publisher="ESPN",
                retrieved_at=now.isoformat(),
                access="internal",
                line_match="exact",
            )
        )
        l10, sea = windows.get("last10") or [0, 0], windows.get("season") or [0, 0]
        favours = est is not None and all_in is not None and est > all_in
        findings.append(
            S.Finding(
                text=(
                    f"Past games: last 10 {l10[0]}/{l10[1]}, "
                    f"season {sea[0]}/{sea[1]} for this side "
                    f"(history {_pct(est)}, range {_pct(interval[0]) if interval else '—'}–"
                    f"{_pct(interval[1]) if interval else '—'}) "
                    f"vs an all-in price of {_pct(all_in)}."
                ),
                kind="statistical",
                stance="supports" if favours else "opposes",
                source_ids=["E1", "K1"],
                verified=True,
            )
        )
        avg = avg_text(ev or {})
        if avg and line is not None:
            findings.append(
                S.Finding(
                    text=f"Season average {avg} against a line of {line}.",
                    kind="statistical",
                    stance="neutral",
                    source_ids=["E1"],
                    verified=True,
                )
            )
        inj = (ev or {}).get("injury")
        if inj:
            own = subject and inj.get("player") == subject and kind == "player_prop"
            findings.insert(
                0 if own else len(findings),
                S.Finding(
                    text=f"{inj['player']}: {inj['status']}. {inj.get('detail') or ''}".strip()[
                        :300
                    ],
                    kind="factual",
                    stance=("opposes" if side == "yes" else "supports") if own else "neutral",
                    source_ids=["E1"],
                    verified=True,
                ),
            )
        findings.append(
            S.Finding(
                text=(
                    f"History covers {season_games} games this season against opponents of "
                    "very different strength, so it says little about tonight's matchup."
                    if college
                    else f"History covers {season_games} games this season and ignores "
                    "tonight's matchup, minutes and role."
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
                text="No box-score check is available for this market; only the price is known.",
                kind="interpretation",
                stance="neutral",
                source_ids=[],
                verified=True,
            )
        )

    # Roster findings go first: they decide whether history means anything tonight.
    roster_findings: list[S.Finding] = []
    if lineup_unknown:
        roster_findings.append(
            S.Finding(
                text=synth.LINEUP_UNKNOWN,
                kind="interpretation",
                stance="neutral",
                source_ids=[],
                verified=True,
            )
        )
    elif teams:
        sources.append(
            S.Source(
                id="E2",
                url=f"https://www.espn.com/{league}/injuries",
                title=f"ESPN {league_label} injury report",
                publisher="ESPN",
                retrieved_at=now.isoformat(),
                access="internal",
                line_match="exact",
            )
        )
        for t in teams:
            if not t["out"] and not t["questionable"]:
                continue
            names = ", ".join(t["out"][:4]) + (
                f" and {len(t['out']) - 4} more" if len(t["out"]) > 4 else ""
            )
            text = (
                f"{t['name']}: {len(t['out'])} out"
                + (f" ({names})" if t["out"] else "")
                + (f", {len(t['questionable'])} questionable" if t["questionable"] else "")
                + "."
            )
            if own_team is None or not t["out"]:
                lean = "neutral"
            else:
                mine = t["code"] == own_team
                lean = (
                    ("opposes" if mine else "supports")
                    if side == "yes"
                    else ("supports" if mine else "opposes")
                )
            roster_findings.append(
                S.Finding(
                    text=text[:400],
                    kind="factual",
                    stance=lean,  # type: ignore[arg-type]
                    source_ids=["E2"],
                    verified=True,
                )
            )
    roster_findings.sort(key=lambda f: 0 if f.stance == "opposes" else 1)
    findings = roster_findings + findings

    # --- news (only on an explicit run; snippets stay in memory) -------------------------
    news: Gathered | None = gatherer(hyp, teams) if gatherer is not None else None
    if news is not None:
        sources.extend(news.sources)
        errors.extend(news.errors)
        if news.sources:
            n = len(news.sources)
            indep = sum(1 for x in news.sources if x.duplicate_of is None)
            news_finding = S.Finding(
                text=(
                    f"{n} recent article{'s' if n != 1 else ''} found ({indep} independent); "
                    "headlines and snippets only, not yet summarised."
                ),
                kind="interpretation",
                stance="neutral",
                source_ids=[x.id for x in news.sources][:6],
                verified=True,
            )
            findings.append(news_finding)

    # --- takeaway --------------------------------------------------------------------------------
    verdict = (ev or {}).get("verdict")
    past = "Past games (against mixed opponents)" if college else "Past games"
    ask_c = f"{all_in * 100:.0f}¢ all-in" if all_in is not None else "current"
    if not supported:
        first = f"No box-score check is available for {phrase}, so only the market price is known."
    elif verdict == "thin":
        first = f"There are too few games on record to judge {phrase} from history."
    elif verdict == "market_lower":
        first = f"{past} suggest {phrase} is likelier than the {ask_c} price implies."
    elif verdict == "market_higher":
        first = f"{past} suggest {phrase} is less likely than the {ask_c} price implies."
    else:
        first = f"{past} put {phrase} about where the {ask_c} price does."
    if roster_issue:
        second = (
            f"But tonight's lineup isn't normal ({roster_issue}), which past games don't reflect."
        )
    elif lineup_unknown and (news is None or not news.sources):
        second = "College games have no injury report, so check who's playing before relying on it."
    elif news is None or not news.attempted:
        second = "No news or analyst views were checked yet."
    elif news.sources:
        second = (
            f"{len(news.sources)} recent article(s) were found but aren't summarised; "
            "read the sources before relying on them."
        )
    else:
        second = "No relevant news was found for this game."
    takeaway = f"{first} {second}"
    stance = (
        "supports"
        if cons is not None and cons > 0
        else "challenges"
        if price.raw_diff is not None and price.raw_diff < -0.02
        else "insufficient"
    )
    if news is None or not news.attempted:
        gaps = ["News and late lineup changes were not checked."]
    elif news.sources:
        gaps = ["What the articles say isn't summarised yet: read the sources."]
    else:
        gaps = ["No relevant articles found; late lineup news may still be missing."]
    if lineup_unknown:
        gaps.insert(0, "Who's playing tonight (no college injury report exists).")
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
            takeaway=takeaway,
            findings=findings[:3],
            gaps=gaps,
            stance=stance,  # type: ignore[arg-type]
            uncertainty="Box-score frequency only; no news, lineup or model input.",
        ),
        price_assessment=price,
        details=S.Details(
            supports=[f for f in findings if f.stance == "supports"],
            against=[f for f in findings if f.stance != "supports"],
            methodology=[
                "Quote: Kalshi catalog snapshot for the exact contract and side.",
                "Evidence: ESPN box scores for the subject, the same check as the Docket.",
                "Price: the slip check's fee schedule, all-in price and walk-away rule.",
                (
                    f"News: Brave News Search, {news.queries} quer"
                    f"{'y' if news.queries == 1 else 'ies'} ({news.searches} sent, "
                    f"{news.cache_hits} from cache); headlines and snippets only, no article "
                    "pages fetched; snippets are not stored."
                    if news is not None
                    else "No external articles were used in this result."
                ),
                f"Source rules: publisher registry {registry.REGISTRY_VERSION}; no publisher "
                "currently licenses full-text processing.",
                "No language model was used in this result.",
            ],
            data_gaps=gaps,
            rules_excerpt=(e.rules_sample[:600] if e and e.rules_sample else None),
        ),
        sources=sources,
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
    result.summary.coverage = coverage(result)
    if synthesizer is not None:
        result = synth.apply(result, news.snippets if news is not None else {}, synthesizer)
    return result


# --- storage -----------------------------------------------------------------------


def save(session: Session, key: str, r: S.Result) -> None:
    session.add(
        Investigation(
            id=r.investigation_id,
            cache_key=key,
            ticker=r.hypothesis.ticker,
            side=r.hypothesis.side,
            status=r.status,
            created_at=datetime.fromisoformat(r.created_at),
            stale_at=datetime.fromisoformat(r.stale_at) if r.stale_at else None,
            result_json=r.model_dump_json(),
        )
    )
    session.commit()


def load(session: Session, inv_id: str) -> S.Result | None:
    row = session.get(Investigation, inv_id)
    return None if row is None else S.Result.model_validate(json.loads(row.result_json))


# Brave's terms allow only transient storage of results. Once an investigation is older than
# the search cache window (its stale_at), everything that came from news is removed from the
# stored copy: the sources and any text the app or the model wrote from them.
NEWS_EXPIRED = (
    "News articles behind this result were removed after the search cache window "
    "(Brave's storage terms). Refresh to see a current summary."
)
_EXTERNAL_MARKERS = ('"access":"headline"', '"access":"snippet"', '"access":"full_text"')


def strip_news(r: S.Result) -> S.Result:
    """A copy of r with no external sources and nothing written from them. Internal data
    (box scores, injury report, price assessment) is kept."""
    out = r.model_copy(deep=True)
    internal = {s.id for s in out.sources if s.access == "internal"}
    if len(internal) == len(out.sources):
        return out
    out.sources = [s for s in out.sources if s.id in internal]
    used_model = out.processing.model is not None

    def keep(f: S.Finding) -> bool:
        if f.text == synth.LINEUP_UNKNOWN:
            return True
        # A model-written finding with no source may still paraphrase a headline.
        return all(i in internal for i in f.source_ids) and not (used_model and not f.source_ids)

    top = [f for f in out.summary.findings if keep(f)]
    out.details.supports = [f for f in out.details.supports if keep(f)]
    out.details.against = [f for f in out.details.against if keep(f)]
    # The app's own roster fact (from the injury report) must stay in the summary.
    roster = next((f for f in out.details.against if "E2" in f.source_ids), None)
    if roster is not None and not any("E2" in f.source_ids for f in top):
        top.insert(0, roster)
    if not top:
        top = (out.details.against + out.details.supports)[:3]
    out.summary.findings = top[:3]
    out.summary.takeaway = NEWS_EXPIRED
    out.summary.gaps = [
        g for g in out.summary.gaps if g.startswith(("The price is stale", "Who's playing tonight"))
    ] + ["News wasn't kept: refresh to check again."]
    if used_model:
        out.summary.stance = "insufficient"
    out.details.methodology = [
        m for m in out.details.methodology if not m.startswith("Summary: local model")
    ] + [NEWS_EXPIRED]
    if "news_expired" not in out.processing.partial_reasons:
        out.processing.partial_reasons.append("news_expired")
    if out.summary.coverage:
        # Recount: the commentary links are gone; the lineup/goalie note stays as it was.
        tail = out.summary.coverage.split(" · ")[2:]
        out.summary.coverage = " · ".join(coverage(out).split(" · ")[:2] + tail)
    return out


def purge_expired_news(session: Session, now: datetime) -> int:
    """Rewrite every stored investigation past its stale_at that still holds news. Returns
    how many were rewritten."""
    rows = session.scalars(
        select(Investigation).where(
            (Investigation.stale_at.is_(None)) | (Investigation.stale_at <= now),
            Investigation.result_json.contains(_EXTERNAL_MARKERS[0])
            | Investigation.result_json.contains(_EXTERNAL_MARKERS[1])
            | Investigation.result_json.contains(_EXTERNAL_MARKERS[2]),
        )
    ).all()
    for row in rows:
        r = strip_news(S.Result.model_validate(json.loads(row.result_json)))
        row.result_json = r.model_dump_json()
    if rows:
        session.commit()
    return len(rows)


def cached(session: Session, key: str, now: datetime) -> S.Result | None:
    row = session.scalars(
        select(Investigation)
        .where(Investigation.cache_key == key)
        .order_by(Investigation.created_at.desc())
        .limit(1)
    ).first()
    if row is None or (row.stale_at is not None and row.stale_at <= now):
        return None
    r = S.Result.model_validate(json.loads(row.result_json))
    r.processing.cache = "hit"
    return r
