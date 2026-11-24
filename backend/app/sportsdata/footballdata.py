"""football-data.org (soccer): fixtures and results for the free-tier competitions.

Rights (app/investigate/sources.py, "football_data_org", reviewed 2026-11-23): the API's
General Terms (June 2018) allow registered use of the free tier under a fair-use policy,
one application per key, with the attribution "Football data provided by the
Football-Data.org API". The key stays private (it's a SecretStr read from .env only and
never written to a repository); team logos are never fetched.

What this adapter does:
- one endpoint, allow-listed: /v4/competitions/{PL|PD|BL1|SA|FL1|CL}/matches?season=Y;
- at most once per 3 hours per competition-season (cached in memory);
- a local throttle under the free plan's 10 requests a minute (refuses rather than waits);
- no redirects followed.

Settlement on Kalshi is the 90-minute score (plus stoppage, no extra time or penalties), so
results are read as 90-minute scores: a match decided in extra time or on penalties uses its
regular-time score when the API gives one, and is left out of the form otherwise.

Nothing here estimates a probability: it reports results for context.
"""

from __future__ import annotations

import re
import threading
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.adapters.base import AdapterError, AdapterErrorCode
from app.investigate import sources

BASE = "https://api.football-data.org"
PATH = re.compile(r"^/v4/competitions/(PL|PD|BL1|SA|FL1|CL)/matches$")
ATTRIBUTION = "Football data provided by the Football-Data.org API"
PAGE = "https://www.football-data.org/"
TTL = timedelta(hours=3)
MAX_BYTES = 3_000_000
RATE = (9, 60.0)  # stay under the free plan's 10 requests a minute

# Kalshi league prefix -> football-data competition code (free tier).
COMPETITIONS = {
    "KXEPL": "PL",
    "KXLALIGA": "PD",
    "KXBUNDESLIGA": "BL1",
    "KXSERIEA": "SA",
    "KXLIGUE1": "FL1",
    "KXUCL": "CL",
}
COMPETITION_NAME = {
    "PL": "Premier League",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "FL1": "Ligue 1",
    "CL": "Champions League",
}
STOP = {
    "fc",
    "cf",
    "afc",
    "ac",
    "as",
    "sc",
    "ssc",
    "ss",
    "us",
    "cd",
    "ud",
    "sd",
    "rc",
    "rcd",
    "club",
    "de",
    "del",
    "la",
    "le",
    "calcio",
    "1",
    "sv",
    "vfl",
    "vfb",
    "tsg",
    "bsc",
    "fk",
    "sk",
    "ogc",
    "osc",
    "losc",
    "the",
    "and",
    "cp",
    "sad",
    "fsv",
    "bv",
    "hsc",
    "aj",
}


def season_of(day: date | datetime) -> int:
    """football-data labels a season by its start year (2026 = 2026/27, from July)."""
    return day.year if day.month >= 7 else day.year - 1


def tokens(name: str) -> set[str]:
    s = name.replace("ø", "o").replace("Ø", "o").replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    # Single letters are fragments (Kalshi writes "M´gladbach"), not words.
    return {t for t in re.split(r"[^a-z0-9]+", s) if len(t) > 1 and t not in STOP}


@dataclass(frozen=True)
class Team:
    id: int
    name: str
    short: str
    tla: str


@dataclass(frozen=True)
class Match:
    id: int
    utc: datetime
    status: str
    matchday: int | None
    stage: str
    home: Team
    away: Team
    home90: int | None  # 90-minute score (None if not finished or not determinable)
    away90: int | None
    duration: str

    @property
    def played(self) -> bool:
        return self.home90 is not None and self.away90 is not None


@dataclass(frozen=True)
class Form:
    games: int
    wins: int
    draws: int
    losses: int
    gf: int
    ga: int
    btts: int
    clean_sheets: int
    failed_to_score: int
    results: tuple[tuple[int, int], ...]  # (goals for, goals against), oldest first
    last: str  # last five, oldest first, e.g. "WDLWW"

    @property
    def gf_pg(self) -> float:
        return self.gf / self.games if self.games else 0.0

    @property
    def ga_pg(self) -> float:
        return self.ga / self.games if self.games else 0.0

    @property
    def ppg(self) -> float:
        return (3 * self.wins + self.draws) / self.games if self.games else 0.0

    def share(self, test: Any) -> tuple[int, int]:
        """(games where test(gf, ga) holds, games)."""
        return sum(1 for gf, ga in self.results if test(gf, ga)), self.games


# Kalshi short names that share no word with the club's official name (normalised).
ALIASES = {
    "bilbao": "athletic",
    "bayern munich": "bayern munchen",
    "mogladbach": "monchengladbach",  # Kalshi's spelling
    "gladbach": "monchengladbach",
    "psg": "paris saint germain",
    "eindhoven": "psv",
    "bodoe glimt": "bodo glimt",
    "vallecano": "rayo vallecano",
    "inter": "internazionale",
    "city man": "manchester city",  # keys are words in sorted order
    "man united": "manchester united",
    "spurs": "tottenham",
    "cologne": "koln",
}


def team_score(code: str, name: str, t: Team) -> float:
    """How well a Kalshi team (code, short name) matches a football-data team, 0..1.
    Exact words count 1, a 4+ letter prefix 0.75, scaled 0.9-1.0 by how much of the official
    name is covered; the three-letter code alone gives 0.9."""
    kt = tokens(ALIASES.get(" ".join(sorted(tokens(name))), name))
    ft = tokens(t.name) | tokens(t.short)

    def hit(k: str) -> float:
        if k in ft:
            return 1.0
        if any((len(k) >= 4 and f.startswith(k)) or (len(f) >= 4 and k.startswith(f)) for f in ft):
            return 0.75
        return 0.0

    # Tie-break on how much of the official name is explained: "Barcelona" is FC Barcelona,
    # not RCD Espanyol de Barcelona; "Paris FC" is Paris FC, not Paris Saint-Germain.
    covered = (
        sum(1 for f in ft if any(f == k or f.startswith(k) for k in kt)) / len(ft) if ft else 0
    )
    by_name = (sum(hit(k) for k in kt) / len(kt)) * (0.9 + 0.1 * covered) if kt else 0.0
    by_code = 0.9 if t.tla and code.upper() == t.tla.upper() else 0.0
    return max(by_name, by_code)


def _team(raw: Any) -> Team:
    raw = raw if isinstance(raw, dict) else {}
    return Team(
        id=int(raw.get("id") or 0),
        name=str(raw.get("name") or "")[:80],
        short=str(raw.get("shortName") or "")[:60],
        tla=str(raw.get("tla") or "")[:5],
    )


def _pair(x: Any) -> tuple[int | None, int | None]:
    if not isinstance(x, dict):
        return None, None
    h, a = x.get("home"), x.get("away")
    return (h if isinstance(h, int) else None), (a if isinstance(a, int) else None)


def score90(status: str, score: Any) -> tuple[int | None, int | None, str]:
    """The 90-minute score (what Kalshi settles on), or (None, None) if unknown."""
    score = score if isinstance(score, dict) else {}
    duration = str(score.get("duration") or "REGULAR")
    if status != "FINISHED":
        return None, None, duration
    if duration == "REGULAR":
        h, a = _pair(score.get("fullTime"))
    else:
        h, a = _pair(score.get("regularTime"))  # never the extra-time or shoot-out total
    return h, a, duration


def parse_matches(payload: Any) -> list[Match]:
    out = []
    for m in (payload or {}).get("matches") or []:
        if not isinstance(m, dict):
            continue
        try:
            utc = datetime.fromisoformat(str(m.get("utcDate", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        status = str(m.get("status") or "")
        h, a, duration = score90(status, m.get("score"))
        md = m.get("matchday")
        out.append(
            Match(
                id=int(m.get("id") or 0),
                utc=utc.astimezone(UTC),
                status=status,
                matchday=md if isinstance(md, int) else None,
                stage=str(m.get("stage") or "")[:40],
                home=_team(m.get("homeTeam")),
                away=_team(m.get("awayTeam")),
                home90=h,
                away90=a,
                duration=duration,
            )
        )
    return out


@dataclass
class SeasonMatches:
    competition: str
    season: int
    matches: list[Match] = field(default_factory=list)
    retrieved_at: datetime | None = None

    def find(
        self, a: tuple[str, str], b: tuple[str, str], day: date | None
    ) -> tuple[Match, dict[str, Team]] | None:
        """The fixture for two Kalshi teams (code, name) within a day of `day`, and which
        football-data team each Kalshi code is. None when nothing matches clearly."""
        rows = [m for m in self.matches if day is None or abs((m.utc.date() - day).days) <= 1]
        best: tuple[float, Match, dict[str, Team]] | None = None
        for m in rows:
            for x, y in ((m.home, m.away), (m.away, m.home)):
                s = min(team_score(a[0], a[1], x), team_score(b[0], b[1], y))
                if s >= 0.5 and (best is None or s > best[0]):
                    best = (s, m, {a[0]: x, b[0]: y})
        return None if best is None else (best[1], best[2])

    def form(self, team_id: int, before: datetime, venue: str | None = None) -> Form:
        """90-minute results for one team, kicked off BEFORE `before` (point in time).
        venue: "home" / "away" to split, None for all."""
        rows = sorted(
            (
                m
                for m in self.matches
                if m.played
                and m.utc < before
                and (
                    (venue in (None, "home") and m.home.id == team_id)
                    or (venue in (None, "away") and m.away.id == team_id)
                )
            ),
            key=lambda m: m.utc,
        )
        res = []
        for m in rows:
            assert m.home90 is not None and m.away90 is not None
            res.append((m.home90, m.away90) if m.home.id == team_id else (m.away90, m.home90))
        w = sum(1 for gf, ga in res if gf > ga)
        d = sum(1 for gf, ga in res if gf == ga)
        return Form(
            games=len(res),
            wins=w,
            draws=d,
            losses=len(res) - w - d,
            gf=sum(gf for gf, _ in res),
            ga=sum(ga for _, ga in res),
            btts=sum(1 for gf, ga in res if gf and ga),
            clean_sheets=sum(1 for _, ga in res if ga == 0),
            failed_to_score=sum(1 for gf, _ in res if gf == 0),
            results=tuple(res),
            last="".join("W" if gf > ga else "D" if gf == ga else "L" for gf, ga in res[-5:]),
        )

    def undetermined(self, team_id: int, before: datetime) -> int:
        """Finished matches left out because the 90-minute score isn't known."""
        return sum(
            1
            for m in self.matches
            if m.status == "FINISHED"
            and not m.played
            and m.utc < before
            and team_id in (m.home.id, m.away.id)
        )


class FootballData:
    def __init__(
        self,
        settings: Any = None,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
        now: Any = None,
        clock: Any = None,
    ) -> None:
        self.settings = settings
        self._key = api_key
        self._now = now or (lambda: datetime.now(UTC))
        self._clock = clock  # monotonic seconds, for the throttle (tests inject one)
        self._http = httpx.Client(
            base_url=BASE,
            transport=transport,
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": "kalshi-research-terminal (local, non-commercial)"},
        )
        self._cache: dict[tuple[str, int], SeasonMatches] = {}
        self._lock = threading.Lock()
        self._sent: deque[float] = deque()

    def close(self) -> None:
        self._http.close()

    def configured(self) -> bool:
        return bool(self._key)

    def enabled(self) -> bool:
        return self.configured() and sources.allows(
            "football_data_org", "read_competition_matches", self.settings
        )

    def _tick(self) -> None:
        import time

        now = self._clock() if self._clock else time.monotonic()
        n, window = RATE
        while self._sent and now - self._sent[0] > window:
            self._sent.popleft()
        if len(self._sent) >= n:
            raise AdapterError(
                "football-data.org's free plan allows 10 requests a minute; try again shortly",
                AdapterErrorCode.HTTP_ERROR,
                429,
            )
        self._sent.append(now)

    def season(self, competition: str, season: int) -> SeasonMatches:
        if not self.enabled():
            raise AdapterError("football-data.org isn't configured or is switched off")
        path = f"/v4/competitions/{competition}/matches"
        if not PATH.match(path):  # allow-list: the free-tier competitions only
            raise AdapterError("football-data.org path not allowed", AdapterErrorCode.BAD_RESPONSE)
        now = self._now()
        with self._lock:
            hit = self._cache.get((competition, season))
            if hit and hit.retrieved_at and now - hit.retrieved_at < TTL:
                return hit
            self._tick()
            try:
                r = self._http.get(
                    path,
                    params={"season": str(season)},
                    headers={"X-Auth-Token": self._key or ""},
                )
            except httpx.HTTPError as e:
                raise AdapterError(f"football-data.org unreachable ({type(e).__name__})") from e
            if r.status_code in (401, 403):
                raise AdapterError(
                    "football-data.org refused the key for this competition (check "
                    "KRT_FOOTBALL_DATA_API_KEY and your plan)",
                    AdapterErrorCode.HTTP_ERROR,
                    r.status_code,
                )
            if r.status_code == 429:
                raise AdapterError(
                    "football-data.org rate limit reached; try again in a minute",
                    AdapterErrorCode.HTTP_ERROR,
                    429,
                )
            if r.status_code != 200:
                raise AdapterError(
                    f"football-data.org returned HTTP {r.status_code}",
                    AdapterErrorCode.HTTP_ERROR,
                    r.status_code,
                )
            if len(r.content) > MAX_BYTES:
                raise AdapterError(
                    "football-data.org reply unexpectedly large", AdapterErrorCode.TRUNCATED
                )
            try:
                payload = r.json()
            except ValueError as e:
                raise AdapterError(
                    "football-data.org sent invalid JSON", AdapterErrorCode.BAD_RESPONSE
                ) from e
            data = SeasonMatches(competition, season, parse_matches(payload), now)
            if not data.matches:
                raise AdapterError(
                    "football-data.org had no matches for this season",
                    AdapterErrorCode.BAD_RESPONSE,
                )
            self._cache[(competition, season)] = data
            return data
