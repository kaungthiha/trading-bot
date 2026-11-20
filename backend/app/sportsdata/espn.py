"""ESPN's public JSON (the data behind espn.com pages): player game logs, team schedules,
injuries. No key. Unofficial and undocumented, so every parse is defensive and a failure
is reported as "no evidence", never guessed.

Hardening: two allowlisted hosts, path regexes per host, GET only, no redirects, request
spacing and retries (shared RetryingJsonClient), and an in-memory TTL cache so one combo
check costs a handful of requests.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.adapters.base import AdapterError
from app.adapters.http import RetryingJsonClient

WEB = "https://site.web.api.espn.com"
SITE = "https://site.api.espn.com"
_LEAGUE = r"(?:nba|wnba|mens-college-basketball|womens-college-basketball)"
WEB_PATHS = re.compile(
    rf"/apis/common/v3/(?:search|sports/basketball/{_LEAGUE}/athletes/\d{{1,12}}/gamelog)")
SITE_PATHS = re.compile(
    rf"/apis/site/v2/sports/basketball/{_LEAGUE}/(?:injuries|teams|teams/\d{{1,6}}/schedule)")

# Kalshi league prefix -> ESPN league slug. Only leagues whose box scores we parse.
LEAGUES = {"KXNBA": "nba", "KXWNBA": "wnba", "KXNCAAMB": "mens-college-basketball",
           "KXNCAAWB": "womens-college-basketball"}
# ESPN publishes no injury report for college; those leagues are "lineup unknown".
COLLEGE = {"mens-college-basketball", "womens-college-basketball"}
LEAGUE_LABEL = {"nba": "NBA", "wnba": "WNBA", "mens-college-basketball": "NCAA men's",
                "womens-college-basketball": "NCAA women's"}
# Kalshi team codes that differ from ESPN abbreviations.
ALIASES = {"nba": {"NYK": "NY", "GSW": "GS", "SAS": "SA", "NOP": "NO", "UTA": "UTAH",
                   "WAS": "WSH", "PHO": "PHX", "BRK": "BKN"}}

TTL_LOG = 30 * 60
TTL_INJ = 15 * 60
TTL_TEAMS = 24 * 3600


@dataclass
class GameRow:
    event_id: str
    date: str
    season: str  # "current" | "previous"
    opponent: str
    home: bool
    won: bool | None
    team_score: int | None
    opp_score: int | None
    stats: dict[str, float] = field(default_factory=dict)


def _num(x: Any) -> float | None:
    try:
        return float(str(x).split("-")[0])
    except (TypeError, ValueError):
        return None


def _int(x: Any) -> int | None:
    v = _num(x)
    return None if v is None else int(v)


LABELS = {"PTS": "PTS", "REB": "REB", "AST": "AST", "BLK": "BLK", "STL": "STL", "3PT": "3PT",
          "MIN": "MIN", "TO": "TO"}


def parse_gamelog(body: dict[str, Any], season: str) -> list[GameRow]:
    labels = body.get("labels") or []
    idx = {lab: i for i, lab in enumerate(labels) if lab in LABELS}
    meta = body.get("events") or {}
    rows: list[GameRow] = []
    for st in body.get("seasonTypes") or []:
        name = str(st.get("displayName") or "")
        if "Preseason" in name:
            continue
        for cat in st.get("categories") or []:
            for ev in cat.get("events") or []:
                eid = str(ev.get("eventId") or "")
                vals = ev.get("stats") or []
                m = meta.get(eid) or {}
                if not eid or not vals or not m:
                    continue
                stats = {k: v for k in idx
                         if (v := _num(vals[idx[k]] if idx[k] < len(vals) else None)) is not None}
                if "PTS" in stats and "REB" in stats and "AST" in stats:
                    stats["PRA"] = stats["PTS"] + stats["REB"] + stats["AST"]
                if "STL" in stats and "BLK" in stats:
                    stats["STOCK"] = stats["STL"] + stats["BLK"]
                tens = sum(1 for k in ("PTS", "REB", "AST", "STL", "BLK") if stats.get(k, 0) >= 10)
                stats["2D"] = 1.0 if tens >= 2 else 0.0
                stats["3D"] = 1.0 if tens >= 3 else 0.0
                away = m.get("atVs") == "@"
                ts = _int(m.get("awayTeamScore") if away else m.get("homeTeamScore"))
                os_ = _int(m.get("homeTeamScore") if away else m.get("awayTeamScore"))
                res = m.get("gameResult")
                rows.append(GameRow(
                    event_id=eid, date=str(m.get("gameDate") or "")[:10], season=season,
                    opponent=str((m.get("opponent") or {}).get("abbreviation") or ""),
                    home=not away, won=True if res == "W" else False if res == "L" else None,
                    team_score=ts, opp_score=os_, stats=stats))
    rows.sort(key=lambda r: r.date, reverse=True)
    return rows


def parse_schedule(body: dict[str, Any], team_id: str, season: str) -> list[GameRow]:
    rows: list[GameRow] = []
    for ev in body.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        if not ((comp.get("status") or {}).get("type") or {}).get("completed"):
            continue
        me = opp = None
        for c in comp.get("competitors") or []:
            if str((c.get("team") or {}).get("id")) == team_id:
                me = c
            else:
                opp = c
        if me is None or opp is None:
            continue

        def score(c: dict[str, Any]) -> int | None:
            s = c.get("score")
            return _int(s.get("value") if isinstance(s, dict) else s)

        ts, os_ = score(me), score(opp)
        rows.append(GameRow(
            event_id=str(ev.get("id") or ""), date=str(ev.get("date") or "")[:10],
            season=season, opponent=str((opp.get("team") or {}).get("abbreviation") or ""),
            home=me.get("homeAway") == "home",
            won=bool(me.get("winner")) if me.get("winner") is not None else
            (None if ts is None or os_ is None else ts > os_),
            team_score=ts, opp_score=os_))
    rows.sort(key=lambda r: r.date, reverse=True)
    return rows


def _norm(s: str) -> str:
    """'Texas A&M-Corpus Christi' -> 'texas a and m corpus christi'; 'Wichita St.' and
    'Wichita State' -> 'wichita state'; 'St. John's' -> 'st johns'."""
    s = s.lower().replace("&", " and ").replace("'", "").replace("\u2019", "")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(r"\bst$", "state", s)  # a trailing "St." is State; a leading one is Saint
    return re.sub(r"\s+", " ", s)


# Kalshi school names that ESPN spells differently (normalized on both sides). Checked
# against every college game in the catalog on 2026-11-19.
COLLEGE_NAMES = {
    "university at albany": "ualbany",
    "appalachian state": "app state",
    "liu": "long island university",
    "usc upstate": "south carolina upstate",
    "southeastern louisiana": "se louisiana",
    "new orleans": "lsu new orleans",
    "tennessee martin": "ut martin",
    "north carolina state": "nc state",
}


def college_team(ts: list[dict[str, str]], code: str, name: str | None
                 ) -> dict[str, str] | None:
    """College codes are too many and too irregular for an alias table, and an abbreviation
    match alone can land on a different school. Match on the name Kalshi shows; the code only
    breaks ties. No confident match -> None (the caller says it couldn't match)."""
    if not name:
        return None
    want = _norm(name)
    want = COLLEGE_NAMES.get(want, want)
    hits = [t for t in ts
            if want in {_norm(t.get(k, "")) for k in ("location", "short", "name")}]
    if len(hits) > 1:
        hits = [t for t in hits if t["abbr"].upper() == code.upper()]
    if len(hits) == 1:
        return hits[0]
    # Fallback: same abbreviation AND the name's first word in ESPN's location.
    first = want.split(" ")[0] if want else ""
    abbr = [t for t in ts if t["abbr"].upper() == code.upper()
            and first and first in _norm(t["location"]).split(" ")]
    return abbr[0] if len(abbr) == 1 else None


class EspnSource:
    """Thread-safe cached facade. `transport` lets tests replay fixtures."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None,
                 min_interval: float = 0.3, timeout: float = 10.0,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        kw: dict[str, Any] = {"transport": transport, "min_interval": min_interval,
                              "timeout": timeout, "max_retries": 2, "sleep": sleep}
        self._web = RetryingJsonClient(WEB, allowed_bases={WEB}, path_pattern=WEB_PATHS, **kw)
        self._site = RetryingJsonClient(SITE, allowed_bases={SITE}, path_pattern=SITE_PATHS, **kw)
        self._cache: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def close(self) -> None:
        self._web.close()
        self._site.close()

    def _cached(self, key: tuple[Any, ...], ttl: float, fetch: Callable[[], Any]) -> Any:
        now = self._clock()
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] > now:
                return hit[1]
        val = fetch()
        with self._lock:
            self._cache[key] = (now + ttl, val)
        return val

    # --- lookups ---------------------------------------------------------------------------

    def player_id(self, league: str, name: str) -> str | None:
        def fetch() -> str | None:
            body = self._web.get("/apis/common/v3/search", {
                "query": name, "type": "player", "sport": "basketball", "league": league,
                "limit": 5})
            for it in body.get("items") or []:
                if it.get("league") == league and str(it.get("id", "")).isdigit():
                    return str(it["id"])
            return None
        return self._cached(("pid", league, name.lower()), TTL_TEAMS, fetch)

    def player_log(self, league: str, pid: str) -> list[GameRow]:
        def fetch() -> list[GameRow]:
            path = f"/apis/common/v3/sports/basketball/{league}/athletes/{pid}/gamelog"
            cur = self._web.get(path)
            rows = parse_gamelog(cur, "current")
            season = next((f.get("value") for f in cur.get("filters") or []
                           if f.get("name") == "season"), None)
            if season and str(season).isdigit():
                try:
                    rows += parse_gamelog(self._web.get(path, {"season": int(season) - 1}),
                                          "previous")
                except AdapterError:
                    pass  # last season is a bonus; this season alone still counts
            return rows
        return self._cached(("log", league, pid), TTL_LOG, fetch)

    def teams(self, league: str) -> list[dict[str, str]]:
        def fetch() -> list[dict[str, str]]:
            # College lists 360+ teams; the default page is much shorter.
            body = self._site.get(f"/apis/site/v2/sports/basketball/{league}/teams",
                                  {"limit": 1000})
            out = []
            for sp in body.get("sports") or []:
                for lg in sp.get("leagues") or []:
                    for t in lg.get("teams") or []:
                        t = t.get("team") or {}
                        out.append({"id": str(t.get("id", "")),
                                    "abbr": str(t.get("abbreviation", "")),
                                    "location": str(t.get("location", "")),
                                    "short": str(t.get("shortDisplayName", "")),
                                    "name": str(t.get("displayName", ""))})
            return out
        return self._cached(("teams", league), TTL_TEAMS, fetch)

    def team(self, league: str, code: str, name: str | None = None) -> dict[str, str] | None:
        """Kalshi code (+ display name like 'Los Angeles C') -> ESPN team."""
        ts = self.teams(league)
        if league in COLLEGE:
            return college_team(ts, code, name)
        want = ALIASES.get(league, {}).get(code, code)
        hit = next((t for t in ts if t["abbr"].upper() == want.upper()), None)
        if hit or not name:
            return hit
        loc = name.lower()
        return next((t for t in ts if t["location"].lower() == loc or
                     t["name"].lower().startswith(loc)), None)

    def team_log(self, league: str, team_id: str) -> list[GameRow]:
        def fetch() -> list[GameRow]:
            path = f"/apis/site/v2/sports/basketball/{league}/teams/{team_id}/schedule"
            cur = self._site.get(path)
            rows = parse_schedule(cur, team_id, "current")
            yr = (cur.get("requestedSeason") or cur.get("season") or {}).get("year")
            if isinstance(yr, int):
                try:
                    rows += parse_schedule(self._site.get(path, {"season": yr - 1}), team_id,
                                           "previous")
                except AdapterError:
                    pass
            return rows
        return self._cached(("tlog", league, team_id), TTL_LOG, fetch)

    def injuries(self, league: str) -> list[dict[str, str]]:
        def fetch() -> list[dict[str, str]]:
            body = self._site.get(f"/apis/site/v2/sports/basketball/{league}/injuries")
            out = []
            for team in body.get("injuries") or []:
                for inj in team.get("injuries") or []:
                    a = inj.get("athlete") or {}
                    out.append({"team_id": str(team.get("id", "")),
                                "team": str(team.get("displayName", "")),
                                "player": str(a.get("displayName", "")),
                                "status": str(inj.get("status", "")),
                                "detail": str(inj.get("shortComment", ""))[:300],
                                "date": str(inj.get("date", ""))[:10]})
            return out
        return self._cached(("inj", league), TTL_INJ, fetch)
