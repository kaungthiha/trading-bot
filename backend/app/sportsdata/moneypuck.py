"""MoneyPuck season data (NHL): team and goalie season summaries.

Rights (see app/investigate/sources.py, source "moneypuck", reviewed 2026-11-21): MoneyPuck
offers these files "free to use for non-commercial purposes" and asks to be credited. This
adapter downloads ONLY the two listed season CSVs (teams.csv, goalies.csv) from the exact
listed path, at most once per 12 hours per season (the data updates nightly), and fetches
no other MoneyPuck page. Every number shown from it is credited "Data: MoneyPuck.com".

Nothing here estimates a probability: it reports season facts for context.
"""

from __future__ import annotations

import csv
import io
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.adapters.base import AdapterError, AdapterErrorCode
from app.investigate import sources

BASE = "https://moneypuck.com"
PATH = re.compile(r"^/moneypuck/playerData/seasonSummary/(20\d{2})/regular/(teams|goalies)\.csv$")
TTL = timedelta(hours=12)
MAX_BYTES = 3_000_000
ATTRIBUTION = "Data: MoneyPuck.com"
PAGE = "https://moneypuck.com/data.htm"

# Kalshi NHL codes that differ from MoneyPuck's; the other 28 are identical.
KALSHI_TO_MP = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL"}

NHL_TEAMS = {
    "ANA": "Anaheim Ducks",
    "BOS": "Boston Bruins",
    "BUF": "Buffalo Sabres",
    "CAR": "Carolina Hurricanes",
    "CBJ": "Columbus Blue Jackets",
    "CGY": "Calgary Flames",
    "CHI": "Chicago Blackhawks",
    "COL": "Colorado Avalanche",
    "DAL": "Dallas Stars",
    "DET": "Detroit Red Wings",
    "EDM": "Edmonton Oilers",
    "FLA": "Florida Panthers",
    "LA": "Los Angeles Kings",
    "MIN": "Minnesota Wild",
    "MTL": "Montreal Canadiens",
    "NJ": "New Jersey Devils",
    "NSH": "Nashville Predators",
    "NYI": "New York Islanders",
    "NYR": "New York Rangers",
    "OTT": "Ottawa Senators",
    "PHI": "Philadelphia Flyers",
    "PIT": "Pittsburgh Penguins",
    "SEA": "Seattle Kraken",
    "SJ": "San Jose Sharks",
    "STL": "St. Louis Blues",
    "TB": "Tampa Bay Lightning",
    "TOR": "Toronto Maple Leafs",
    "UTA": "Utah Mammoth",
    "VAN": "Vancouver Canucks",
    "VGK": "Vegas Golden Knights",
    "WPG": "Winnipeg Jets",
    "WSH": "Washington Capitals",
}


def mp_code(kalshi_code: str) -> str:
    return KALSHI_TO_MP.get(kalshi_code, kalshi_code)


def season_of(day: datetime) -> int:
    """MoneyPuck labels a season by its start year (2026 = 2026-27, starting in October)."""
    return day.year if day.month >= 9 else day.year - 1


@dataclass(frozen=True)
class TeamSeason:
    code: str
    games: int
    goals_for: float
    goals_against: float
    xg_for: float
    xg_against: float
    xg_pct_5v5: float | None

    @property
    def gf_pg(self) -> float:
        return self.goals_for / self.games if self.games else 0.0

    @property
    def ga_pg(self) -> float:
        return self.goals_against / self.games if self.games else 0.0


@dataclass(frozen=True)
class GoalieSeason:
    name: str
    team: str
    games: int
    goals: float
    xgoals: float
    shots_on_goal: float

    @property
    def save_pct(self) -> float | None:
        return None if self.shots_on_goal <= 0 else 1 - self.goals / self.shots_on_goal

    @property
    def gsax(self) -> float:
        """Goals saved above expected (positive = better than an average goalie)."""
        return self.xgoals - self.goals


@dataclass
class SeasonData:
    season: int
    teams: dict[str, TeamSeason] = field(default_factory=dict)
    goalies: dict[str, list[GoalieSeason]] = field(default_factory=dict)
    data_as_of: datetime | None = None  # MoneyPuck's Last-Modified (nightly update time)
    retrieved_at: datetime | None = None

    def goalies_for(self, kalshi_code: str) -> list[GoalieSeason]:
        return sorted(self.goalies.get(mp_code(kalshi_code), []), key=lambda g: -g.games)


def _num(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def parse_teams(text: str) -> dict[str, TeamSeason]:
    rows = list(csv.DictReader(io.StringIO(text)))
    by: dict[str, dict[str, dict[str, str]]] = {}
    for r in rows:
        by.setdefault(r.get("team", ""), {})[r.get("situation", "")] = r
    out = {}
    for code, sit in by.items():
        a = sit.get("all")
        if not code or a is None:
            continue
        five = sit.get("5on5")
        out[code] = TeamSeason(
            code=code,
            games=int(_num(a.get("games_played"))),
            goals_for=_num(a.get("goalsFor")),
            goals_against=_num(a.get("goalsAgainst")),
            xg_for=_num(a.get("xGoalsFor")),
            xg_against=_num(a.get("xGoalsAgainst")),
            xg_pct_5v5=_num(five.get("xGoalsPercentage")) if five else None,
        )
    return out


def parse_goalies(text: str) -> dict[str, list[GoalieSeason]]:
    out: dict[str, list[GoalieSeason]] = {}
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("situation") != "all" or not r.get("team"):
            continue
        out.setdefault(r["team"], []).append(
            GoalieSeason(
                name=str(r.get("name", ""))[:80],
                team=r["team"],
                games=int(_num(r.get("games_played"))),
                goals=_num(r.get("goals")),
                xgoals=_num(r.get("xGoals")),
                shots_on_goal=_num(r.get("ongoal")),
            )
        )
    return out


class MoneyPuck:
    def __init__(
        self,
        settings: Any = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
        now: Any = None,
    ) -> None:
        self.settings = settings
        self._now = now or (lambda: datetime.now(UTC))
        self._http = httpx.Client(
            base_url=BASE,
            transport=transport,
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": "kalshi-research-terminal (local, non-commercial)"},
        )
        self._cache: dict[int, SeasonData] = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        self._http.close()

    def enabled(self) -> bool:
        return sources.allows("moneypuck", "download_listed_season_csv", self.settings)

    def _get(self, season: int, kind: str) -> tuple[str, datetime | None]:
        path = f"/moneypuck/playerData/seasonSummary/{season}/regular/{kind}.csv"
        if not PATH.match(path):  # allow-list: only the two listed season files
            raise AdapterError("MoneyPuck path not allowed", AdapterErrorCode.BAD_RESPONSE)
        try:
            r = self._http.get(path)
        except httpx.HTTPError as e:
            raise AdapterError(f"MoneyPuck unreachable ({type(e).__name__})") from e
        if r.status_code == 404:
            raise AdapterError(
                "MoneyPuck has no file for this season yet", AdapterErrorCode.NOT_FOUND, 404
            )
        if r.status_code != 200:
            raise AdapterError(
                f"MoneyPuck returned HTTP {r.status_code}",
                AdapterErrorCode.HTTP_ERROR,
                r.status_code,
            )
        if len(r.content) > MAX_BYTES:
            raise AdapterError("MoneyPuck file unexpectedly large", AdapterErrorCode.TRUNCATED)
        try:
            lm = parsedate_to_datetime(r.headers.get("last-modified", ""))
        except (TypeError, ValueError):
            lm = None
        return r.text, lm

    def season(self, season: int) -> SeasonData:
        if not self.enabled():
            raise AdapterError("MoneyPuck is switched off or not permitted for this use")
        now = self._now()
        with self._lock:
            hit = self._cache.get(season)
            if hit and hit.retrieved_at and now - hit.retrieved_at < TTL:
                return hit
            teams_csv, lm1 = self._get(season, "teams")
            goalies_csv, lm2 = self._get(season, "goalies")
            data = SeasonData(
                season=season,
                teams=parse_teams(teams_csv),
                goalies=parse_goalies(goalies_csv),
                data_as_of=max((d for d in (lm1, lm2) if d), default=None),
                retrieved_at=now,
            )
            if not data.teams:
                raise AdapterError(
                    "MoneyPuck teams file had no rows", AdapterErrorCode.BAD_RESPONSE
                )
            self._cache[season] = data
            return data
