"""One game, one screen: every Kalshi event that shares a game key (KXNBAGAME-26NOV19NYKMIN,
KXNBAREB-26NOV19NYKMIN, ...) grouped into game lines, periods and per-player props.

Each market also gets a machine-readable *leg spec* ("player X gets 8+ rebounds", "team
wins by over 4.5") so the evidence module can check it against real box scores.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.combos import combo_collections
from app.catalog.stats import Quote, implied, ladder_stats, merge_margin_ladders, spread
from app.db.models import CatalogEvent, CatalogMarket, CatalogSeries

GAME_KEY = re.compile(r"^[A-Z0-9]{4,40}$")
PREFIX = re.compile(r"^KX[A-Z0-9]{2,20}$")
TICKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")

# Player stat series (suffix after the league prefix) -> short label, in display order.
PLAYER_STATS: dict[str, str] = {
    "PTS": "PTS", "REB": "REB", "AST": "AST", "3PT": "3PM", "PRA": "PRA",
    "STL": "STL", "BLK": "BLK", "STOCK": "STL+BLK", "2D": "Dbl-dbl", "3D": "Trp-dbl",
}
PERIODS = ("1H", "2H", "1Q", "2Q", "3Q", "4Q")
PERIOD_NAMES = {"1H": "1st half", "2H": "2nd half", "1Q": "Q1", "2Q": "Q2", "3Q": "Q3", "4Q": "Q4"}
MAX_PICKS = 40
MAIN = {"GAME": "Winner", "SPREAD": "Spread", "TOTAL": "Total points", "TEAMTOTAL": "Team total"}


def _f(d: Decimal | None) -> float | None:
    return None if d is None else float(d)


def _quote(m: CatalogMarket) -> Quote:
    return Quote(m.ticker, m.yes_sub_title or m.title, m.yes_bid, m.yes_ask, m.strike_type,
                 m.floor_strike, m.group_key, m.title)


def _group_key(m: CatalogMarket) -> dict[str, str]:
    try:
        g = json.loads(m.group_key or "{}")
        return g if isinstance(g, dict) else {}
    except ValueError:
        return {}


def _player_id(m: CatalogMarket) -> str | None:
    return next((v for k, v in _group_key(m).items() if k.endswith("_player")), None)


def _team_of(m: CatalogMarket, codes: list[str]) -> str | None:
    """Team code from the ticker's last part: ...-NYKKTOWNS32-8 or ...-MIN27 or ...-NYK."""
    parts = m.ticker.split("-")
    seg = parts[2] if len(parts) >= 3 else ""
    for c in sorted(codes, key=len, reverse=True):
        if seg.startswith(c):
            return c
    return None


def _at_least(m: CatalogMarket) -> int | None:
    """'over 7.5' strikes mean 8+."""
    if m.floor_strike is None or m.strike_type not in ("greater", "greater_or_equal"):
        return None
    k = m.floor_strike
    return int(k + Decimal("0.5")) if m.strike_type == "greater" else int(k)


def leg_spec(suffix: str, m: CatalogMarket, codes: list[str]) -> dict[str, Any] | None:
    """What has to happen for YES, in a form box scores can check. None if unsupported."""
    base = suffix.removesuffix("PROT")
    team = _team_of(m, codes)
    if base in PLAYER_STATS and _player_id(m):
        n = _at_least(m)
        if n is None:
            return None
        return {"kind": "player_stat", "player": (m.title or "").split(":")[0].strip(),
                "team": team, "stat": base, "at_least": n}
    k = _f(m.floor_strike)
    if base == "GAME" and team:
        return {"kind": "team_win", "team": team}
    if base == "SPREAD" and team and k is not None:
        return {"kind": "team_margin", "team": team, "over": k}
    if base == "TOTAL" and k is not None:
        return {"kind": "game_total", "over": k}
    if base == "TEAMTOTAL" and team and k is not None:
        return {"kind": "team_total", "team": team, "over": k}
    return None


def _chip(m: CatalogMarket, label: str, team: str | None = None) -> dict[str, Any]:
    q = _quote(m)
    p, quality = implied(q)
    sp = spread(q)
    return {"ticker": m.ticker, "event_ticker": m.event_ticker, "label": label,
            "title": m.title, "team": team,
            "implied": None if p is None else round(p, 4), "quality": quality,
            "yes_bid": _f(m.yes_bid), "yes_ask": _f(m.yes_ask), "no_ask": _f(m.no_ask),
            "spread": None if sp is None else round(sp, 4),
            "volume_24h": round(_f(m.volume_24h) or 0), "strike": _f(m.floor_strike)}


def _median(ms: list[CatalogMarket]) -> float | None:
    st = ladder_stats([_quote(m) for m in ms]) if len(ms) >= 3 else None
    return st["median"] if st else None


def _parse_key(key: str) -> tuple[str, str]:
    """'26NOV19NYKMIN' -> ('26NOV19', 'NYKMIN')."""
    m = re.match(r"^(\d{2}[A-Z]{3}\d{2})(.*)$", key)
    return (m.group(1), m.group(2)) if m else ("", key)


def _teams(game_markets: list[CatalogMarket], key: str) -> list[dict[str, Any]]:
    out = []
    for m in game_markets:
        code = m.ticker.rsplit("-", 1)[-1]
        p, _ = implied(_quote(m))
        out.append({"code": code, "name": m.yes_sub_title or code,
                    "win": None if p is None else round(p, 4)})
    # Kalshi keys list the away team first (NYKMIN = New York at Minnesota).
    teams = _parse_key(key)[1]
    out.sort(key=lambda t: (teams.find(t["code"]) if t["code"] in teams else 99, t["code"]))
    return out


# --- Game list -------------------------------------------------------------------------------


def list_games(s: Session, league: str | None = None) -> dict[str, Any]:
    anchors = list(s.scalars(select(CatalogEvent).where(
        CatalogEvent.category == "Sports", CatalogEvent.series_ticker.like("%GAME"))))
    if not anchors:
        return {"items": [], "leagues": []}
    prefixes = {a.series_ticker[:-4] for a in anchors}
    sports = s.execute(select(CatalogEvent.event_ticker, CatalogEvent.series_ticker,
                              CatalogEvent.market_count, CatalogEvent.volume_24h)
                       .where(CatalogEvent.category == "Sports")).all()
    agg: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0, 0, 0.0])
    for et, st, n, vol in sports:
        key = et.split("-", 1)[1] if "-" in et else ""
        pre = next((p for p in prefixes if st.startswith(p)), None)
        if pre and key:
            a = agg[(pre, key)]
            a[0] += 1
            a[1] += n or 0
            a[2] += vol or 0
    gm = defaultdict(list)
    for m in s.scalars(select(CatalogMarket).where(
            CatalogMarket.event_ticker.in_([a.event_ticker for a in anchors]))):
        gm[m.event_ticker].append(m)
    leagues: dict[str, int] = defaultdict(int)
    items = []
    for a in anchors:
        pre = a.series_ticker[:-4]
        lg = pre[2:]
        leagues[lg] += 1
        if league and lg != league:
            continue
        key = a.event_ticker.split("-", 1)[1]
        events_n, markets_n, vol = agg.get((pre, key), [1, a.market_count, a.volume_24h])
        items.append({"game_key": key, "league": lg, "prefix": pre, "title": a.title,
                      "sub_title": a.sub_title, "occurs_at": a.occurs_at, "close_at": a.close_at,
                      "teams": _teams(gm[a.event_ticker], key),
                      "events": int(events_n), "markets": int(markets_n),
                      "volume_24h": round(vol)})
    items.sort(key=lambda g: (g["occurs_at"] is None, g["occurs_at"] or g["close_at"]
                              or "", g["game_key"]))
    return {"items": items,
            "leagues": [{"league": k, "games": v} for k, v in
                        sorted(leagues.items(), key=lambda kv: -kv[1])]}


# --- One game --------------------------------------------------------------------------------


def _short(suffix: str, m: CatalogMarket, team: str | None) -> str:
    base = suffix.removesuffix("PROT")
    n = _at_least(m)
    if base in PLAYER_STATS:
        return "Yes" if base in ("2D", "3D") else f"{n}+"
    if base.endswith("SPREAD") and team and n is not None:
        return f"{team} by {n}+"
    if base.endswith("TOTAL") and m.floor_strike is not None:
        lead = f"{team} " if base.endswith("TEAMTOTAL") and team else ""
        return f"{lead}{n}+"
    return m.yes_sub_title or m.title


def _sort_key(m: CatalogMarket) -> tuple[Any, ...]:
    return (m.floor_strike if m.floor_strike is not None else Decimal(0), m.ticker)


def _margin_group(ms: list[CatalogMarket], codes: list[str], suffix: str) -> dict[str, Any]:
    """Spread markets for both teams laid out as one line: away by most ... home by most."""
    by_team: dict[str | None, list[CatalogMarket]] = defaultdict(list)
    for m in ms:
        by_team[_team_of(m, codes)].append(m)
    a, b = (codes + [None, None])[:2]
    ordered = sorted(by_team.get(a, []), key=_sort_key, reverse=True) + \
        sorted(by_team.get(b, []), key=_sort_key)
    median_label = None
    qa = sorted((_quote(m) for m in by_team.get(a, [])), key=lambda q: q.floor_strike or 0)
    qb = sorted((_quote(m) for m in by_team.get(b, [])), key=lambda q: q.floor_strike or 0)
    if a and b and len(qa) >= 3 and len(qb) >= 3:
        # Merged into ONE ladder of a's margin (the first group keeps its sign).
        merged = merge_margin_ladders({"a": qa, "b": qb})
        if len(merged) == 1:
            st = ladder_stats(next(iter(merged.values())))
            med = st["median"] if st else None
            if med is not None:
                median_label = f"{a if med >= 0 else b} by {abs(med):.1f}"
    return {"median_label": median_label,
            "markets": [_chip(m, _short(suffix, m, _team_of(m, codes)), _team_of(m, codes))
                        for m in ordered]}


def game_detail(s: Session, prefix: str, key: str,
                protected: bool = False) -> dict[str, Any] | None:
    if not PREFIX.match(prefix) or not GAME_KEY.match(key):
        return None
    anchor = s.get(CatalogEvent, f"{prefix}GAME-{key}")
    if anchor is None:
        return None
    evs = [e for e in s.scalars(select(CatalogEvent).where(
        CatalogEvent.event_ticker.like(f"%-{key}"), CatalogEvent.series_ticker.like(f"{prefix}%")))]
    by_event = defaultdict(list)
    for m in s.scalars(select(CatalogMarket).where(
            CatalogMarket.event_ticker.in_([e.event_ticker for e in evs]))):
        by_event[m.event_ticker].append(m)
    eligible = combo_collections(s, [e.event_ticker for e in evs])
    titles = dict(s.execute(select(CatalogSeries.ticker, CatalogSeries.title).where(
        CatalogSeries.ticker.in_([e.series_ticker for e in evs]))).all())
    teams = _teams(by_event[anchor.event_ticker], key)
    codes = [t["code"] for t in teams]
    has_protected = any(e.series_ticker.endswith("PROT") for e in evs)

    main: list[dict[str, Any]] = []
    periods: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    players: dict[str, dict[str, Any]] = {}
    stats_seen: set[str] = set()

    for e in sorted(evs, key=lambda e: e.series_ticker):
        suffix = e.series_ticker[len(prefix):]
        ms = by_event[e.event_ticker]
        if not ms:
            continue
        is_prot = suffix.endswith("PROT")
        base = suffix.removesuffix("PROT")
        head = {"event_ticker": e.event_ticker, "eligible": e.event_ticker in eligible,
                "series_title": titles.get(e.series_ticker, e.series_ticker)}
        if base in PLAYER_STATS and any(_player_id(m) for m in ms):
            if is_prot != protected:
                continue
            stats_seen.add(base)
            per: dict[str, list[CatalogMarket]] = defaultdict(list)
            for m in ms:
                pid = _player_id(m)
                if pid:
                    per[pid].append(m)
            for pid, pms in per.items():
                pms.sort(key=_sort_key)
                p = players.setdefault(pid, {
                    "id": pid, "name": (pms[0].title or "").split(":")[0].strip(),
                    "team": _team_of(pms[0], codes), "stats": {}, "volume_24h": 0})
                p["volume_24h"] += sum(round(_f(m.volume_24h) or 0) for m in pms)
                p["stats"][base] = {**head, "label": PLAYER_STATS[base],
                                    "median": _median(pms) if base not in ("2D", "3D") else None,
                                    "markets": [_chip(m, _short(suffix, m, None), p["team"])
                                                for m in pms]}
            continue
        if is_prot:
            continue
        period = next((pp for pp in PERIODS if base.startswith(pp)), None)
        kind = base[len(period):] if period else base
        if period:
            label = f"{PERIOD_NAMES[period]} " + {
                "": "winner", "SPREAD": "spread", "TOTAL": "total",
                "TEAMTOTAL": "team total"}.get(kind, kind.lower())
        else:
            label = MAIN.get(kind, titles.get(e.series_ticker, base))
        if kind == "SPREAD":
            g = {**head, "id": suffix, "label": label, "kind": "ladder",
                 **_margin_group(ms, codes, suffix)}
        elif kind in ("TOTAL", "TEAMTOTAL"):
            if kind == "TEAMTOTAL":
                for code in codes:
                    tms = sorted([m for m in ms if _team_of(m, codes) == code], key=_sort_key)
                    if tms:
                        grp = {**head, "id": f"{suffix}-{code}", "label": f"{label} · {code}",
                               "kind": "ladder", "median_label":
                               f"≈ {md:.1f}" if (md := _median(tms)) is not None else None,
                               "markets": [_chip(m, _short(suffix, m, None), code) for m in tms]}
                        (periods if period else main).append(grp)
                continue
            tms = sorted(ms, key=_sort_key)
            md = _median(tms)
            g = {**head, "id": suffix, "label": label, "kind": "ladder",
                 "median_label": f"≈ {md:.1f}" if md is not None else None,
                 "markets": [_chip(m, _short(suffix, m, None)) for m in tms]}
        else:
            # Most likely outcomes first; long range lists are cut to the top 40.
            pick = sorted(ms, key=lambda m: (-(_f(m.yes_bid) or 0), m.ticker))[:MAX_PICKS]
            g = {**head, "id": suffix, "label": label, "kind": "pick", "median_label": None,
                 "markets": [_chip(m, m.yes_sub_title or m.title, _team_of(m, codes))
                             for m in pick]}
        if base in MAIN:
            main.append(g)
        elif period:
            periods.append(g)
        else:
            other.append(g)

    order = {k: i for i, k in enumerate(["GAME", "SPREAD", "TOTAL"])}
    main.sort(key=lambda g: (order.get(g["id"].split("-")[0], 9), g["id"]))
    pl = sorted(players.values(), key=lambda p: (codes.index(p["team"]) if p["team"] in codes
                                                  else 9, -p["volume_24h"], p["name"]))
    return {
        "game_key": key, "prefix": prefix, "league": prefix[2:], "title": anchor.title,
        "sub_title": anchor.sub_title, "occurs_at": anchor.occurs_at,
        "close_at": anchor.close_at, "refreshed_at": anchor.refreshed_at, "teams": teams,
        "date_code": _parse_key(key)[0],
        "sections": [x for x in (
            {"id": "main", "label": "Game lines", "groups": main},
            {"id": "periods", "label": "Halves & quarters", "groups": periods},
            {"id": "other", "label": "More", "groups": other}) if x["groups"]],
        "players": pl,
        "stats": [k for k in PLAYER_STATS if k in stats_seen],
        "stat_labels": PLAYER_STATS,
        "protected_available": has_protected, "protected": protected,
    }


def anchor_for(s: Session, e: CatalogEvent) -> CatalogEvent | None:
    """The {league}GAME event this event belongs to (KXNBAREB-X -> KXNBAGAME-X), if any."""
    key = e.event_ticker.split("-", 1)[1] if "-" in e.event_ticker else ""
    if not GAME_KEY.match(key):
        return None
    candidates = s.scalars(select(CatalogEvent).where(
        CatalogEvent.event_ticker.like(f"%GAME-{key}"))).all()
    return next((a for a in candidates if a.series_ticker.endswith("GAME")
                 and e.series_ticker.startswith(a.series_ticker[:-4])), None)


def game_ref(s: Session, e: CatalogEvent) -> dict[str, str] | None:
    a = anchor_for(s, e)
    return None if a is None else {"prefix": a.series_ticker[:-4],
                                   "game_key": a.event_ticker.split("-", 1)[1]}


def market_specs(s: Session, tickers: list[str]) -> dict[str, dict[str, Any]]:
    """ticker -> {spec, event_ticker, game_key, prefix, implied} for evidence lookups."""
    out: dict[str, dict[str, Any]] = {}
    for t in tickers:
        m = s.get(CatalogMarket, t)
        if m is None:
            continue
        e = s.get(CatalogEvent, m.event_ticker)
        if e is None:
            continue
        key = m.event_ticker.split("-", 1)[1] if "-" in m.event_ticker else ""
        anchor = anchor_for(s, e)
        spec = None
        prefix = None
        if anchor is not None:
            prefix = anchor.series_ticker[:-4]
            codes = [mm.ticker.rsplit("-", 1)[-1] for mm in s.scalars(select(CatalogMarket).where(
                CatalogMarket.event_ticker == anchor.event_ticker))]
            spec = leg_spec(e.series_ticker[len(prefix):], m, codes)
        p, _ = implied(_quote(m))
        out[t] = {"spec": spec, "event_ticker": m.event_ticker, "game_key": key,
                  "prefix": prefix, "implied": p, "label": m.title}
    return out


def list_games_teams(s: Session, prefix: str, key: str) -> dict[str, str]:
    """{team code: display name} for one game, away team first."""
    ms = list(s.scalars(select(CatalogMarket).where(
        CatalogMarket.event_ticker == f"{prefix}GAME-{key}")))
    return {t["code"]: t["name"] for t in _teams(ms, key)}
