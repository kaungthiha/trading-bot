"""Bounded news discovery for one investigation (Brave News Search, metadata only).

- At most `max_searches` targeted queries (matchup, material news, a contrary/specialised
  angle), deduplicated, each served from an in-memory cache when possible. The cache lives in
  process memory only and expires (Brave's terms allow only transient storage).
- Every network attempt is reserved in the ledger first; a full budget stops the search.
- Results are kept only if they name this game's teams (or the prop's player). Each is checked
  for a past matchup (published well before this game) and for a different line than the one
  being investigated. Syndicated copies are marked duplicates, never extra confirmation.
- Only Brave's headline/snippet is used; no publisher page is fetched. Snippets stay in memory
  for the summary and are never persisted.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from app.adapters.base import AdapterError, AdapterErrorCode
from app.investigate import registry
from app.investigate import schemas as S
from app.investigate.ledger import BudgetExhausted, Ledger

PAST_MATCHUP = timedelta(days=3)
HALF = re.compile(r"(?<![\d.])(\d{1,3}\.5)(?![\d])")
PLAUSIBLE = {
    "total": (150, 320),
    "team_total": (70, 170),
    "spread": (0.5, 30),
    "player_prop": (0.5, 75),
}
# Scoring differs by league: a 135.5 college total is ordinary, a 45.5 college spread happens.
PLAUSIBLE_BY_LEAGUE = {
    "WNBA": {**PLAUSIBLE, "total": (120, 210), "team_total": (50, 120)},
    "NCAA men's": {**PLAUSIBLE, "total": (100, 200), "team_total": (40, 120), "spread": (0.5, 55)},
    "NCAA women's": {**PLAUSIBLE, "total": (90, 190), "team_total": (35, 120), "spread": (0.5, 60)},
    # Hockey: totals around 5.5-6.5, puck lines 1.5-3.5.
    "NHL": {"total": (3.5, 10.5), "team_total": (0.5, 6.5), "spread": (0.5, 4.5),
            "player_prop": (0.5, 6.5)},
}
COLLEGE = {"NCAA men's": "basketball", "NCAA women's": "women's basketball"}
BASKETBALL = re.compile(r"basketball|hoops|\bmbb\b|\bwbb\b|\bcbb\b|ncaab|ncaaw|march madness", re.I)
WOMEN = re.compile(r"\bwomen|\bwbb\b|\blady\b|ncaaw", re.I)
# NHL nicknames are shared with other leagues (Rangers, Kings, Jets, Panthers, Senators...):
# an NHL result must actually be about hockey.
HOCKEY = re.compile(
    r"\bnhl\b|hockey|goalie|goaltender|netminder|\bpuck|power play|power-play|shutout|"
    r"\bin goal\b|between the pipes|\bcrease\b|stanley cup",
    re.I,
)


def _plausible(h: S.Hypothesis) -> dict[str, tuple[float, float]]:
    return PLAUSIBLE_BY_LEAGUE.get(h.league, PLAUSIBLE)


def sport_mismatch(h: S.Hypothesis, text: str) -> bool:
    """College: the same school names cover football and both basketball programs. NHL: the
    nicknames are shared with MLB/NFL/NBA teams, so the text must be about hockey."""
    if h.league == "NHL":
        return not HOCKEY.search(text)
    if h.league not in COLLEGE:
        return False
    if not BASKETBALL.search(text):
        return True
    women = bool(WOMEN.search(text))
    return women if h.league == "NCAA men's" else not women


STAT_WORD = {
    "PTS": "points",
    "REB": "rebounds",
    "AST": "assists",
    "3PT": "threes",
    "BLK": "blocks",
    "STL": "steals",
    "PRA": "points rebounds assists",
}
MONTHS = {
    m: i
    for i, m in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1
    )
}


@dataclass
class Gathered:
    sources: list[S.Source] = field(default_factory=list)
    snippets: dict[str, str] = field(default_factory=dict)  # transient, never persisted
    searches: int = 0  # network attempts actually made (each reserved in the ledger)
    cache_hits: int = 0
    queries: int = 0
    attempted: bool = False  # a search was actually planned (key set, query built)
    errors: list[str] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)


def game_date(event_ticker: str) -> datetime | None:
    m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})", event_ticker)
    if not m or m.group(2) not in MONTHS:
        return None
    from datetime import UTC

    return datetime(2000 + int(m.group(1)), MONTHS[m.group(2)], int(m.group(3)), tzinfo=UTC)


def nickname(team_name: str) -> str:
    return team_name.split()[-1].lower() if team_name else ""


def plan_queries(h: S.Hypothesis, teams: list[dict[str, Any]], max_n: int) -> list[str]:
    names = [t["name"] for t in teams][:2]
    if len(names) < 2 or max_n <= 0:
        return []
    a, b = names
    own = next((t["name"] for t in teams if h.ticker.rsplit("-", 1)[-1].startswith(t["code"])), a)
    stat = next((w for k, w in STAT_WORD.items() if k in h.ticker.split("-")[0]), "")
    line = "" if h.threshold is None else f" {h.threshold:g}"
    if h.league == "NHL":
        # Goalie first: who starts is the biggest unknown in a hockey game.
        qs = [f"{a} {b} NHL starting goalie confirmed", f"{a} vs {b} NHL preview",
              f"{own} NHL injury update"]
        if h.market_type in ("total", "team_total"):
            qs.append(f"{a} {b} NHL over under{line}")
        elif h.market_type == "spread":
            qs.append(f"{a} {b} NHL puck line{line}")
        else:
            qs.append(f"{a} vs {b} NHL prediction")
        return list(dict.fromkeys(q.strip() for q in qs))[:max_n]
    if h.league in COLLEGE:
        sport = COLLEGE[h.league]
        if h.market_type in ("total", "team_total"):
            qs = [
                f"{a} vs {b} {sport} preview",
                f"{a} {b} {sport} injury news",
                f"{a} {b} {sport} over under{line}",
            ]
        elif h.market_type == "spread":
            qs = [
                f"{a} vs {b} {sport} preview",
                f"{own} {sport} injury news",
                f"{a} {b} {sport} spread pick{line}",
            ]
        elif h.market_type == "player_prop" and h.subject:
            qs = [
                f"{a} vs {b} {sport} preview",
                f"{h.subject} injury status",
                f"{h.subject} {stat} prop{line}",
            ]
        else:
            qs = [
                f"{a} vs {b} {sport} preview",
                f"{own} {sport} injury news",
                f"{a} vs {b} {sport} prediction",
            ]
        return list(dict.fromkeys(q.strip() for q in qs))[:max_n]
    if h.market_type == "player_prop" and h.subject:
        qs = [f"{a} vs {b} preview", f"{h.subject} injury status", f"{h.subject} {stat} prop{line}"]
    elif h.market_type in ("total", "team_total"):
        qs = [f"{a} vs {b} preview", f"{a} {b} injury report", f"{a} {b} over under{line}"]
    elif h.market_type == "spread":
        qs = [f"{a} vs {b} preview", f"{own} injury report", f"{a} {b} spread pick{line}"]
    else:
        qs = [f"{a} vs {b} preview", f"{own} injury report", f"{a} vs {b} prediction"]
    return list(dict.fromkeys(q.strip() for q in qs))[:max_n]


def canonical(url: str) -> str:
    u = urlparse(url)
    host = re.sub(r"^(www|m|amp)\.", "", u.netloc.lower())
    path = re.sub(r"/amp/?$", "", u.path).rstrip("/")
    return f"{host}{path}"


def _words(t: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", t.lower())) - {"the", "a", "vs", "and", "of", "to", "in"}


def line_match(h: S.Hypothesis, text: str) -> str:
    ranges = _plausible(h)
    if h.threshold is None or h.market_type not in ranges:
        return "unknown"
    lo, hi = ranges[h.market_type]
    nums = {float(x) for x in HALF.findall(text) if lo <= float(x) <= hi}
    if not nums:
        return "unknown"
    return "exact" if any(abs(n - h.threshold) < 0.01 for n in nums) else "different_line"


def _published(r: dict[str, Any]) -> datetime | None:
    raw = (r.get("page_age") or "").strip()
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    from datetime import UTC

    return d if d.tzinfo else d.replace(tzinfo=UTC)


def gather(
    h: S.Hypothesis,
    teams: list[dict[str, Any]],
    *,
    configured: bool,
    client_factory: Callable[[Callable[[], None]], Any],
    ledger: Ledger,
    cache: dict[str, tuple[datetime, list[dict[str, Any]]]],
    cache_ttl: timedelta,
    now: datetime,
    max_searches: int,
    max_sources: int,
) -> Gathered:
    g = Gathered()
    if not configured:
        g.errors.append(
            "Brave Search isn't set up, so no news was checked (set KRT_BRAVE_SEARCH_API_KEY)."
        )
        return g
    queries = plan_queries(h, teams, max_searches)
    g.queries = len(queries)
    g.attempted = bool(queries)
    if not queries:
        g.errors.append("Couldn't build a news query for this game (team names unavailable).")
        return g
    current: dict[str, str] = {}

    def reserve() -> None:
        ledger.reserve("research", current["q"])
        g.searches += 1

    raw: list[dict[str, Any]] = []
    client = None
    try:
        for q in queries:
            key = q.lower()
            hit = cache.get(key)
            if hit and now - hit[0] < cache_ttl:
                g.cache_hits += 1
                raw.extend(hit[1])
                continue
            if client is None:
                client = client_factory(reserve)
            current["q"] = q
            try:
                items = client.search(q, count=8)
            except BudgetExhausted as e:
                g.errors.append(f"{e}: no further searches until it resets.")
                break
            except AdapterError as e:
                if e.code == AdapterErrorCode.RATE_LIMITED:
                    g.errors.append("Brave rate-limited the request (429); not retried.")
                    break
                g.errors.append(f"A news search failed ({e}).")
                continue
            cache[key] = (now, items)
            raw.extend(items)
    finally:
        if client is not None:
            client.close()

    # --- relevance, past matchups, lines, duplicates -----------------------------------------
    gd = game_date(h.event_ticker)
    must = [nickname(t["name"]) for t in teams if t.get("name")]
    if h.market_type == "player_prop" and h.subject:
        must = [h.subject.split()[-1].lower()]
    seen_urls: set[str] = set()
    kept: list[tuple[tuple[int, int, float], S.Source, str, S.Source | None]] = []
    titles: list[tuple[set[str], S.Source]] = []
    for r in raw:
        text = f"{r.get('title', '')} {r.get('description', '')}"
        low = text.lower()
        if must and not any(m and m in low for m in must):
            g.dropped["off_topic"] = g.dropped.get("off_topic", 0) + 1
            continue
        if sport_mismatch(h, text):
            g.dropped["other_sport"] = g.dropped.get("other_sport", 0) + 1
            continue
        cu = canonical(r.get("url", ""))
        if not cu or cu in seen_urls:
            g.dropped["duplicate_url"] = g.dropped.get("duplicate_url", 0) + 1
            continue
        seen_urls.add(cu)
        dom, pub = registry.lookup(urlparse(r.get("url", "")).hostname or "")
        if not pub.enabled:
            g.dropped["disabled_publisher"] = g.dropped.get("disabled_publisher", 0) + 1
            continue
        pub_at = _published(r)
        lm = line_match(h, text)
        if gd is not None and pub_at is not None and pub_at < gd - PAST_MATCHUP:
            lm = "past_matchup"
        src = S.Source(
            id="?",
            url=r["url"],
            title=r.get("title", "")[:200],
            publisher=pub.name if pub is not registry.UNKNOWN else dom,
            published_at=None if pub_at is None else pub_at.isoformat(),
            retrieved_at=now.isoformat(),
            access="snippet" if r.get("description") else "headline",
            line_match=lm,
        )  # type: ignore[arg-type]
        ws = _words(r.get("title", ""))
        dup = next(
            (o for tws, o in titles if ws and len(ws & tws) / max(1, len(ws | tws)) >= 0.75), None
        )
        titles.append((ws, src))
        age = (now - pub_at).total_seconds() if pub_at else 9e9
        rank = (0 if lm == "exact" else 1 if lm == "unknown" else 2, pub.priority, age)
        kept.append((rank, src, r.get("description", "")[:400], dup))
    kept.sort(key=lambda x: x[0])
    final = kept[:max_sources]
    for i, (_, src, snip, _) in enumerate(final, 1):
        src.id = f"N{i}"
        if snip:
            g.snippets[src.id] = snip
    chosen = {id(src) for _, src, _, _ in final}
    for _, src, _, dup in final:
        # A copy of a report we kept is "not independent"; a copy of a trimmed one is a source.
        src.duplicate_of = dup.id if dup is not None and id(dup) in chosen else None
        g.sources.append(src)
    if not g.sources and not g.errors:
        g.errors.append("No relevant articles were found for this game.")
    return g
