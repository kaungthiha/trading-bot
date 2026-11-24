"""nflverse release files (NFL): schedule facts, weekly team stats, the weekly injury report.

Rights (see app/investigate/sources.py, reviewed 2026-11-23). The nflverse-data repository
is CC BY 4.0, but one release's licence isn't assumed to cover another, so each file has its
own registry entry and operation:
- nflverse_schedules  -> schedules/games.csv          (game facts only: kickoff, scores, rest,
                                                       roof, stadium, listed QB. The sportsbook
                                                       line and odds columns are never read.)
- nflverse_team_stats -> stats_team/stats_team_week_{season}.csv (nflverse's own aggregates)
- nflverse_injuries   -> injuries/injuries_{season}.csv (the NFL's weekly report, as facts)
FTN charting data (a different licence) is never downloaded.

Only those three exact paths are fetched (allow-list), at most once per 12 hours per season.
GitHub serves release files through one redirect to its asset host; exactly one redirect to
an allow-listed GitHub host is followed, nothing else. Every number shown is credited
"Data: nflverse (CC BY 4.0)".

Point in time: callers ask for form "before kickoff", so later games never leak into a
pre-game view. Nothing here estimates a probability.
"""

from __future__ import annotations

import csv
import io
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from app.adapters.base import AdapterError, AdapterErrorCode
from app.investigate import sources

BASE = "https://github.com"
ROOT = "/nflverse/nflverse-data/releases/download/"
PATHS = {
    "schedules": ("nflverse_schedules", "download_schedule_release"),
    "stats_team": ("nflverse_team_stats", "download_team_stats_release"),
    "injuries": ("nflverse_injuries", "download_injury_report_release"),
}
PATH = re.compile(
    r"^/nflverse/nflverse-data/releases/download/"
    r"(schedules/games\.csv|stats_team/stats_team_week_20\d{2}\.csv|"
    r"injuries/injuries_20\d{2}\.csv)$"
)
ASSET_HOSTS = {"release-assets.githubusercontent.com", "objects.githubusercontent.com"}
TTL = timedelta(hours=12)
MAX_BYTES = 6_000_000
ATTRIBUTION = "Data: nflverse (CC BY 4.0)"
PAGE = "https://github.com/nflverse/nflverse-data/releases"
ET = ZoneInfo("America/New_York")

# Kalshi NFL codes that differ from nflverse's; the other 30 are identical.
KALSHI_TO_NFLVERSE = {"JAC": "JAX", "LAR": "LA"}

NFL_TEAMS = {
    "ARI": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB": "Green Bay Packers",
    "HOU": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAC": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs",
    "LAC": "Los Angeles Chargers",
    "LAR": "Los Angeles Rams",
    "LV": "Las Vegas Raiders",
    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",
    "NE": "New England Patriots",
    "NO": "New Orleans Saints",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
}
OUT = ("out", "doubtful")


def nv_code(kalshi_code: str) -> str:
    return KALSHI_TO_NFLVERSE.get(kalshi_code, kalshi_code)


def season_of(day: datetime | date) -> int:
    """nflverse labels a season by its start year; January/February games are playoffs of
    the season that started the previous September."""
    return day.year if day.month >= 3 else day.year - 1


def _num(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _int(x: Any) -> int | None:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Game:
    game_id: str
    season: int
    week: int
    game_type: str
    gameday: date
    kickoff: datetime | None  # UTC, from the schedule's Eastern date and time
    away: str
    home: str
    away_score: int | None
    home_score: int | None
    location: str  # "Home" or "Neutral"
    roof: str  # outdoors / dome / closed / open / "" (retractable, state unknown)
    stadium_id: str
    stadium: str
    away_rest: int | None
    home_rest: int | None
    away_qb: str
    home_qb: str
    div_game: bool

    @property
    def played(self) -> bool:
        return self.away_score is not None and self.home_score is not None

    def side_of(self, team: str) -> str | None:
        return "away" if team == self.away else "home" if team == self.home else None


@dataclass(frozen=True)
class TeamWeek:
    team: str
    week: int
    game_id: str
    opponent: str
    epa: float  # passing + rushing EPA (offense)
    plays: float  # dropbacks (attempts + sacks) + carries


@dataclass(frozen=True)
class Injury:
    team: str
    week: int
    name: str
    position: str
    status: str  # Out / Doubtful / Questionable / "" (practised, no game status)
    practice: str
    injury: str


@dataclass(frozen=True)
class Form:
    team: str
    games: int
    points_for: int
    points_against: int
    off_epa_play: float | None
    def_epa_play: float | None  # EPA per play allowed (lower is better)
    last_game: date | None

    @property
    def pf_pg(self) -> float:
        return self.points_for / self.games if self.games else 0.0

    @property
    def pa_pg(self) -> float:
        return self.points_against / self.games if self.games else 0.0


@dataclass
class SeasonData:
    season: int
    games: list[Game] = field(default_factory=list)
    weeks: list[TeamWeek] = field(default_factory=list)
    injuries: list[Injury] = field(default_factory=list)
    as_of: dict[str, datetime | None] = field(default_factory=dict)  # per file Last-Modified
    retrieved_at: datetime | None = None
    errors: list[str] = field(default_factory=list)  # files that couldn't be read

    @property
    def data_as_of(self) -> datetime | None:
        return max((d for d in self.as_of.values() if d), default=None)

    def find_game(self, a: str, b: str, day: date | None) -> Game | None:
        """The schedule row for two Kalshi codes on (or a day either side of) the ticker's
        date. Either order: Kalshi lists away first, but neutral sites can differ."""
        pair = {nv_code(a), nv_code(b)}
        rows = [g for g in self.games if {g.away, g.home} == pair]
        if day is None:
            return rows[0] if len(rows) == 1 else None
        rows = [g for g in rows if abs((g.gameday - day).days) <= 1]
        return min(rows, key=lambda g: abs((g.gameday - day).days)) if rows else None

    def form(self, kalshi_code: str, before: datetime) -> Form:
        """Season form from games that kicked off BEFORE `before` (point in time)."""
        t = nv_code(kalshi_code)
        prior = [
            g
            for g in self.games
            if g.played and t in (g.away, g.home) and g.kickoff is not None and g.kickoff < before
        ]
        pf = pa = 0
        for g in prior:
            mine, theirs = (
                (g.away_score, g.home_score) if g.away == t else (g.home_score, g.away_score)
            )
            pf += mine or 0
            pa += theirs or 0
        ids = {g.game_id for g in prior}
        off = [w for w in self.weeks if w.team == t and w.game_id in ids]
        dfn = [w for w in self.weeks if w.opponent == t and w.game_id in ids]

        def rate(ws: list[TeamWeek]) -> float | None:
            plays = sum(w.plays for w in ws)
            return sum(w.epa for w in ws) / plays if plays >= 100 else None

        return Form(
            team=kalshi_code,
            games=len(prior),
            points_for=pf,
            points_against=pa,
            off_epa_play=rate(off),
            def_epa_play=rate(dfn),
            last_game=max((g.gameday for g in prior), default=None),
        )

    def prior_starters(self, kalshi_code: str, before: datetime) -> list[tuple[str, int]]:
        """QBs who started for the team this season before `before`: (name, starts), most
        recent starter first."""
        t = nv_code(kalshi_code)
        seen: dict[str, int] = {}
        order: list[str] = []
        prior = sorted(
            (
                g
                for g in self.games
                if g.played
                and g.kickoff is not None
                and g.kickoff < before
                and t in (g.away, g.home)
            ),
            key=lambda g: g.kickoff or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        for g in prior:
            name = g.away_qb if g.away == t else g.home_qb
            if not name:
                continue
            if name not in seen:
                order.append(name)
            seen[name] = seen.get(name, 0) + 1
        return [(n, seen[n]) for n in order]

    def injuries_for(self, kalshi_code: str, week: int) -> list[Injury]:
        t = nv_code(kalshi_code)
        return [i for i in self.injuries if i.team == t and i.week == week]

    def latest_injury_week(self) -> int | None:
        return max((i.week for i in self.injuries), default=None)

    def qbs_on_report(self, kalshi_code: str) -> list[str]:
        t = nv_code(kalshi_code)
        return list(
            dict.fromkeys(i.name for i in self.injuries if i.team == t and i.position == "QB")
        )


def _kickoff(day: str, hhmm: str) -> datetime | None:
    try:
        d = date.fromisoformat(day)
        h, m = (int(x) for x in hhmm.split(":"))
        return datetime(d.year, d.month, d.day, h, m, tzinfo=ET).astimezone(UTC)
    except (ValueError, TypeError):
        return None


def parse_games(text: str, season: int) -> list[Game]:
    """Schedule rows for one season. Only factual columns are read; the sportsbook columns
    (moneylines, spread_line, total_line, odds) are deliberately ignored."""
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        if _int(r.get("season")) != season:
            continue
        try:
            day = date.fromisoformat(str(r.get("gameday", "")))
        except ValueError:
            continue
        out.append(
            Game(
                game_id=str(r.get("game_id", ""))[:40],
                season=season,
                week=_int(r.get("week")) or 0,
                game_type=str(r.get("game_type", ""))[:8],
                gameday=day,
                kickoff=_kickoff(str(r.get("gameday", "")), str(r.get("gametime", ""))),
                away=str(r.get("away_team", ""))[:4],
                home=str(r.get("home_team", ""))[:4],
                away_score=_int(r.get("away_score")),
                home_score=_int(r.get("home_score")),
                location=str(r.get("location", ""))[:10],
                roof=str(r.get("roof", ""))[:10],
                stadium_id=str(r.get("stadium_id", ""))[:8],
                stadium=str(r.get("stadium", ""))[:80],
                away_rest=_int(r.get("away_rest")),
                home_rest=_int(r.get("home_rest")),
                away_qb=str(r.get("away_qb_name", ""))[:60],
                home_qb=str(r.get("home_qb_name", ""))[:60],
                div_game=str(r.get("div_game", "")) == "1",
            )
        )
    return out


def parse_weeks(text: str) -> list[TeamWeek]:
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        if not r.get("team") or not r.get("game_id"):
            continue
        out.append(
            TeamWeek(
                team=str(r["team"])[:4],
                week=_int(r.get("week")) or 0,
                game_id=str(r["game_id"])[:40],
                opponent=str(r.get("opponent_team", ""))[:4],
                epa=_num(r.get("passing_epa")) + _num(r.get("rushing_epa")),
                plays=_num(r.get("attempts"))
                + _num(r.get("sacks_suffered"))
                + _num(r.get("carries")),
            )
        )
    return out


def parse_injuries(text: str) -> list[Injury]:
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        if not r.get("team") or not r.get("full_name"):
            continue
        out.append(
            Injury(
                team=str(r["team"])[:4],
                week=_int(r.get("week")) or 0,
                name=str(r["full_name"])[:60],
                position=str(r.get("position", ""))[:6],
                status=str(r.get("report_status", ""))[:20],
                practice=str(r.get("practice_status", ""))[:60],
                injury=str(r.get("report_primary_injury", ""))[:40],
            )
        )
    return out


class Nflverse:
    def __init__(
        self,
        settings: Any = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
        now: Any = None,
    ) -> None:
        self.settings = settings
        self._now = now or (lambda: datetime.now(UTC))
        self._http = httpx.Client(
            transport=transport,
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": "kalshi-research-terminal (local, non-commercial)"},
        )
        self._cache: dict[int, SeasonData] = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        self._http.close()

    def allowed(self, release: str) -> bool:
        sid, op = PATHS[release]
        return sources.allows(sid, op, self.settings)

    def enabled(self) -> bool:
        """The schedule is required (kickoff, teams); the other two are optional extras."""
        return self.allowed("schedules")

    def _get(self, path: str) -> tuple[str, datetime | None]:
        if not PATH.match(path):  # allow-list: only the three listed release files
            raise AdapterError("nflverse path not allowed", AdapterErrorCode.BAD_RESPONSE)
        try:
            r = self._http.get(BASE + path)
            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("location", "")
                u = urlparse(loc)
                if u.scheme != "https" or u.hostname not in ASSET_HOSTS:
                    raise AdapterError(
                        "nflverse redirected somewhere unexpected", AdapterErrorCode.BAD_RESPONSE
                    )
                r = self._http.get(loc)  # one hop only; a further redirect is refused below
        except httpx.HTTPError as e:
            raise AdapterError(f"nflverse unreachable ({type(e).__name__})") from e
        if r.status_code == 404:
            raise AdapterError("nflverse has no file for this yet", AdapterErrorCode.NOT_FOUND, 404)
        if r.status_code != 200:
            raise AdapterError(
                f"nflverse returned HTTP {r.status_code}",
                AdapterErrorCode.HTTP_ERROR,
                r.status_code,
            )
        if len(r.content) > MAX_BYTES:
            raise AdapterError("nflverse file unexpectedly large", AdapterErrorCode.TRUNCATED)
        try:
            lm = parsedate_to_datetime(r.headers.get("last-modified", ""))
        except (TypeError, ValueError):
            lm = None
        return r.text, lm

    def season(self, season: int) -> SeasonData:
        if not self.enabled():
            raise AdapterError("nflverse schedules are switched off or not permitted")
        now = self._now()
        with self._lock:
            hit = self._cache.get(season)
            if hit and hit.retrieved_at and now - hit.retrieved_at < TTL:
                return hit
            text, lm = self._get(ROOT + "schedules/games.csv")
            data = SeasonData(season=season, games=parse_games(text, season), retrieved_at=now)
            data.as_of["schedules"] = lm
            if not data.games:
                raise AdapterError(
                    "nflverse schedule had no games for this season", AdapterErrorCode.BAD_RESPONSE
                )
            if self.allowed("stats_team"):
                try:
                    text, lm = self._get(f"{ROOT}stats_team/stats_team_week_{season}.csv")
                    data.weeks, data.as_of["stats_team"] = parse_weeks(text), lm
                except AdapterError as e:
                    data.errors.append(f"nflverse team stats unavailable ({e})")
            if self.allowed("injuries"):
                try:
                    text, lm = self._get(f"{ROOT}injuries/injuries_{season}.csv")
                    data.injuries, data.as_of["injuries"] = parse_injuries(text), lm
                except AdapterError as e:
                    data.errors.append(f"nflverse injury report unavailable ({e})")
            self._cache[season] = data
            return data


def is_out(status: str) -> bool:
    return status.lower() in OUT
