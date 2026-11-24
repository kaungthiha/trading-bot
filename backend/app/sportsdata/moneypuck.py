"""MoneyPuck season data (NHL): team and goalie season summaries.

Rights (see app/investigate/sources.py, source "moneypuck", reviewed 2026-11-21): MoneyPuck
offers these files "free to use for non-commercial purposes" and asks to be credited. This
adapter downloads ONLY the two listed season CSVs (teams.csv, goalies.csv) from the exact
listed path, at most once per 12 hours per season (the data updates nightly), and fetches
no other MoneyPuck page. Every number shown from it is credited "Data: MoneyPuck.com".

Game logs (added 2026-11-23): the per-season game-by-game goalie and skater files that the
same data page lists (hosted on peter-tanner.com, MoneyPuck's download host), for rest days,
back-to-backs, last night's goalie and which regulars missed recent games. Exactly those two
zips, at most once per 12 hours, size-capped and streamed; same terms and credit.

Nothing here estimates a probability: it reports season facts for context.
"""

from __future__ import annotations

import csv
import io
import re
import threading
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
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
LOG_URL = "https://peter-tanner.com/moneypuck/downloads/seasonPlayersSummary/{kind}/{season}.zip"
LOG = re.compile(
    r"^https://peter-tanner\.com/moneypuck/downloads/seasonPlayersSummary/"
    r"(goalies|skaters)/(20\d{2})\.zip$"
)
MAX_ZIP = 15_000_000
MAX_CSV = 150_000_000  # the skater log is ~50 MB uncompressed; it's streamed, not loaded
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


@dataclass(frozen=True)
class TeamGame:
    game_id: str
    day: date  # MoneyPuck's game date (local)
    opponent: str
    home: bool
    starter: str | None  # the goalie with the most ice time
    starter_seconds: float


@dataclass(frozen=True)
class Rest:
    last_game: date | None
    days_off: int | None  # 0 = back-to-back
    games_last_4_nights: int  # including tonight
    last_starter: str | None
    starter_last_night: bool  # back-to-back and that goalie started last night
    recent_starts: list[tuple[str, int]]  # last 5 games: (goalie, starts)


@dataclass(frozen=True)
class Absence:
    name: str
    position: str
    games: int
    toi_per_game: float  # seconds
    missed: int  # consecutive most recent team games missed


@dataclass
class GameLogs:
    season: int
    games: dict[str, list[TeamGame]] = field(default_factory=dict)  # MoneyPuck team code
    # (team, game_id) -> {player_id: seconds}
    lineups: dict[tuple[str, str], dict[str, float]] = field(default_factory=dict)
    players: dict[str, tuple[str, str]] = field(default_factory=dict)  # id -> (name, position)
    # player id -> [(day, team)] appearances
    seen: dict[str, list[tuple[date, str]]] = field(default_factory=dict)
    data_as_of: datetime | None = None
    retrieved_at: datetime | None = None
    errors: list[str] = field(default_factory=list)

    def prior(self, kalshi_code: str, day: date) -> list[TeamGame]:
        """The team's games before `day` (point in time), oldest first."""
        return [g for g in self.games.get(mp_code(kalshi_code), []) if g.day < day]

    def rest(self, kalshi_code: str, day: date) -> Rest:
        games = self.prior(kalshi_code, day)
        last = games[-1] if games else None
        off = None if last is None else (day - last.day).days - 1
        recent: dict[str, int] = {}
        for g in games[-5:]:
            if g.starter:
                recent[g.starter] = recent.get(g.starter, 0) + 1
        return Rest(
            last_game=last.day if last else None,
            days_off=off,
            games_last_4_nights=1 + sum(1 for g in games if (day - g.day).days <= 3),
            last_starter=last.starter if last else None,
            starter_last_night=bool(last and off == 0 and last.starter),
            recent_starts=sorted(recent.items(), key=lambda kv: -kv[1]),
        )

    def absences(self, kalshi_code: str, day: date, top: int = 12) -> list[Absence]:
        """Regulars (top `top` skaters by ice time, with enough games) who missed the team's
        most recent games before `day`. Players who have since played for another team are
        left out (traded or loaned, not absent)."""
        team = mp_code(kalshi_code)
        games = self.prior(kalshi_code, day)
        if len(games) < 3:
            return []
        totals: dict[str, list[float]] = {}
        for g in games:
            for pid, secs in self.lineups.get((team, g.game_id), {}).items():
                t = totals.setdefault(pid, [0, 0.0])
                t[0] += 1
                t[1] += secs
        need = max(3, int(0.4 * len(games)))
        regulars = sorted(
            (pid for pid, (n, _) in totals.items() if n >= need),
            key=lambda pid: -totals[pid][1],
        )[:top]
        out = []
        for pid in regulars:
            missed = 0
            for g in reversed(games):
                if pid in self.lineups.get((team, g.game_id), {}):
                    break
                missed += 1
            if not missed:
                continue
            last_here = max(d for d, t in self.seen.get(pid, []) if t == team and d < day)
            if any(t != team and last_here < d < day for d, t in self.seen.get(pid, [])):
                continue  # moved to another team
            n, secs = totals[pid]
            name, pos = self.players.get(pid, (pid, ""))
            out.append(Absence(name, pos, int(n), secs / n, missed))
        return sorted(out, key=lambda a: -a.toi_per_game)

    def roster(self, kalshi_code: str, day: date, top: int = 20) -> list[str]:
        """Names of the team's most-used skaters and goalies before `day` (for matching news)."""
        team = mp_code(kalshi_code)
        totals: dict[str, float] = {}
        for g in self.prior(kalshi_code, day):
            for pid, secs in self.lineups.get((team, g.game_id), {}).items():
                totals[pid] = totals.get(pid, 0.0) + secs
            if g.starter:
                totals["G:" + g.starter] = totals.get("G:" + g.starter, 0.0) + g.starter_seconds
        names = []
        for pid in sorted(totals, key=lambda k: -totals[k])[:top]:
            names.append(pid[2:] if pid.startswith("G:") else self.players.get(pid, (pid, ""))[0])
        return names


def _day(x: str) -> date | None:
    try:
        return datetime.strptime(x.strip(), "%Y%m%d").date()
    except (ValueError, AttributeError):
        return None


def _rows(blob: bytes) -> Any:
    """Stream the single CSV inside a size-checked zip (no member paths are used)."""
    if len(blob) > MAX_ZIP:
        raise AdapterError("MoneyPuck game log unexpectedly large", AdapterErrorCode.TRUNCATED)
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as e:
        raise AdapterError("MoneyPuck game log isn't a zip", AdapterErrorCode.BAD_RESPONSE) from e
    members = [i for i in z.infolist() if i.filename.endswith(".csv")]
    if len(members) != 1 or members[0].file_size > MAX_CSV:
        raise AdapterError(
            "MoneyPuck game log has an unexpected layout", AdapterErrorCode.BAD_RESPONSE
        )
    with z.open(members[0]) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"))


def parse_goalie_log(blob: bytes) -> dict[str, list[TeamGame]]:
    per: dict[tuple[str, str], dict[str, Any]] = {}
    for r in _rows(blob):
        if r.get("situation") != "all":
            continue
        d = _day(r.get("gameDate", ""))
        team, gid = r.get("playerTeam", ""), r.get("gameId", "")
        if d is None or not team or not gid:
            continue
        g = per.setdefault(
            (team, gid),
            {
                "day": d,
                "opp": r.get("opposingTeam", ""),
                "home": r.get("home_or_away") == "HOME",
                "starter": None,
                "secs": -1.0,
            },
        )
        secs = _num(r.get("icetime"))
        if secs > g["secs"]:
            g["starter"], g["secs"] = str(r.get("name", ""))[:80] or None, secs
    out: dict[str, list[TeamGame]] = {}
    for (team, gid), g in per.items():
        out.setdefault(team, []).append(
            TeamGame(gid, g["day"], g["opp"], g["home"], g["starter"], max(g["secs"], 0.0))
        )
    for v in out.values():
        v.sort(key=lambda x: (x.day, x.game_id))
    return out


def parse_skater_log(blob: bytes, logs: GameLogs) -> None:
    for r in _rows(blob):
        if r.get("situation") != "all":
            continue
        d = _day(r.get("gameDate", ""))
        team, gid, pid = r.get("playerTeam", ""), r.get("gameId", ""), r.get("playerId", "")
        if d is None or not team or not gid or not pid:
            continue
        logs.lineups.setdefault((team, gid), {})[pid] = _num(r.get("icetime"))
        logs.players.setdefault(pid, (str(r.get("name", ""))[:80], str(r.get("position", ""))[:3]))
        logs.seen.setdefault(pid, []).append((d, team))


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
        self._logs: dict[int, GameLogs] = {}
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

    def logs_enabled(self) -> bool:
        return sources.allows("moneypuck", "download_listed_game_logs", self.settings)

    def _get_log(self, kind: str, season: int) -> tuple[bytes, datetime | None]:
        url = LOG_URL.format(kind=kind, season=season)
        if not LOG.match(url):  # allow-list: the two listed game-log zips only
            raise AdapterError("MoneyPuck game-log URL not allowed", AdapterErrorCode.BAD_RESPONSE)
        try:
            r = self._http.get(url)
        except httpx.HTTPError as e:
            raise AdapterError(f"MoneyPuck game logs unreachable ({type(e).__name__})") from e
        if r.status_code != 200:
            raise AdapterError(
                f"MoneyPuck game logs returned HTTP {r.status_code}",
                AdapterErrorCode.NOT_FOUND if r.status_code == 404 else AdapterErrorCode.HTTP_ERROR,
                r.status_code,
            )
        try:
            lm = parsedate_to_datetime(r.headers.get("last-modified", ""))
        except (TypeError, ValueError):
            lm = None
        return r.content, lm

    def game_logs(self, season: int) -> GameLogs:
        """Goalie and skater game logs for one season (cached 12 h). The skater file failing
        leaves rest and goalie info intact (absences then say they weren't checked)."""
        if not self.logs_enabled():
            raise AdapterError("MoneyPuck game logs are switched off or not permitted")
        now = self._now()
        with self._lock:
            hit = self._logs.get(season)
            if hit and hit.retrieved_at and now - hit.retrieved_at < TTL:
                return hit
            blob, lm1 = self._get_log("goalies", season)
            logs = GameLogs(season=season, games=parse_goalie_log(blob), retrieved_at=now)
            if not logs.games:
                raise AdapterError(
                    "MoneyPuck goalie log had no games", AdapterErrorCode.BAD_RESPONSE
                )
            lm2 = None
            try:
                blob, lm2 = self._get_log("skaters", season)
                parse_skater_log(blob, logs)
            except AdapterError as e:
                logs.errors.append(f"MoneyPuck skater game log unavailable ({e})")
            logs.data_as_of = max((d for d in (lm1, lm2) if d), default=None)
            self._logs[season] = logs
            return logs

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
