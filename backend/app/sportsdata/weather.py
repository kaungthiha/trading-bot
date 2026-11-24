"""Kickoff weather from Open-Meteo, for open-air NFL stadiums only.

Rights (app/investigate/sources.py, "open_meteo", reviewed 2026-11-21): the free API is for
non-commercial use, under 10,000 calls a day, CC BY 4.0, credited "Weather data by
Open-Meteo.com". No key is needed. One request per game (cached an hour), only for games
in the next 7 days at a home team's own open-air stadium; domes, closed roofs, retractable
roofs of unknown state and neutral sites are never looked up.

The forecast is a forecast: each reading carries the time it was retrieved.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.adapters.base import AdapterError, AdapterErrorCode
from app.investigate import sources

BASE = "https://api.open-meteo.com"
PATH = "/v1/forecast"
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"
PAGE = "https://open-meteo.com/"
CACHE = timedelta(hours=1)
HORIZON = timedelta(days=7)
MAX_BYTES = 200_000

# nflverse stadium_id -> (lat, lon) for open-air home stadiums (2026 season). Neutral-site
# and international games are skipped even when the schedule reuses a home id.
STADIUMS: dict[str, tuple[float, float]] = {
    "BAL00": (39.278, -76.623),  # M&T Bank Stadium
    "BOS00": (42.091, -71.264),  # Gillette Stadium
    "BUF00": (42.774, -78.787),  # Highmark Stadium
    "CAR00": (35.226, -80.853),  # Bank of America Stadium
    "CHI98": (41.862, -87.617),  # Soldier Field
    "CIN00": (39.095, -84.516),  # Paycor Stadium
    "CLE00": (41.506, -81.700),  # Huntington Bank Field
    "DEN00": (39.744, -105.020),  # Empower Field at Mile High
    "GNB00": (44.501, -88.062),  # Lambeau Field
    "JAX00": (30.324, -81.637),  # EverBank Stadium
    "KAN00": (39.049, -94.484),  # Arrowhead Stadium
    "MIA00": (25.958, -80.239),  # Hard Rock Stadium
    "NAS00": (36.166, -86.771),  # Nissan Stadium
    "NYC01": (40.814, -74.074),  # MetLife Stadium
    "PHI00": (39.901, -75.168),  # Lincoln Financial Field
    "PIT00": (40.447, -80.016),  # Acrisure Stadium
    "SEA00": (47.595, -122.332),  # Lumen Field
    "SFO01": (37.403, -121.970),  # Levi's Stadium
    "TAM00": (27.976, -82.503),  # Raymond James Stadium
    "WAS00": (38.908, -76.865),  # Northwest Stadium
}


@dataclass(frozen=True)
class Forecast:
    at: datetime  # the forecast hour (UTC)
    temp_f: float | None
    wind_mph: float | None
    gust_mph: float | None
    precip_prob: float | None  # %
    retrieved_at: datetime


def skip_reason(
    stadium_id: str, roof: str, location: str, kickoff: datetime | None, now: datetime
) -> str | None:
    """Why weather isn't looked up for this game, or None if it should be."""
    if roof in ("dome", "closed"):
        return "indoors"
    if location != "Home":
        return "neutral site"
    if roof != "outdoors":
        return "retractable roof, open or closed not known"
    if stadium_id not in STADIUMS:
        return "stadium not in the app's table"
    if kickoff is None:
        return "kickoff time unknown"
    if kickoff < now - timedelta(hours=4):
        return "game already played"
    if kickoff - now > HORIZON:
        return "more than 7 days out"
    return None


class OpenMeteo:
    def __init__(
        self,
        settings: Any = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
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
        self._cache: dict[tuple[str, str], Forecast] = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        self._http.close()

    def enabled(self) -> bool:
        return sources.allows("open_meteo", "forecast_lookup_noncommercial", self.settings)

    def kickoff(self, stadium_id: str, kickoff: datetime) -> Forecast:
        if not self.enabled():
            raise AdapterError("Open-Meteo is switched off or not permitted")
        if stadium_id not in STADIUMS:
            raise AdapterError("Stadium not in the table", AdapterErrorCode.NOT_FOUND)
        hour = kickoff.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        key = (stadium_id, hour.isoformat())
        now = self._now()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit.retrieved_at < CACHE:
                return hit
            lat, lon = STADIUMS[stadium_id]
            params = {
                "latitude": f"{lat:.3f}",
                "longitude": f"{lon:.3f}",
                "hourly": "temperature_2m,precipitation_probability,wind_speed_10m,wind_gusts_10m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": "UTC",
                "start_date": hour.date().isoformat(),
                "end_date": hour.date().isoformat(),
            }
            try:
                r = self._http.get(PATH, params=params)
            except httpx.HTTPError as e:
                raise AdapterError(f"Open-Meteo unreachable ({type(e).__name__})") from e
            if r.status_code != 200:
                raise AdapterError(
                    f"Open-Meteo returned HTTP {r.status_code}",
                    AdapterErrorCode.HTTP_ERROR,
                    r.status_code,
                )
            if len(r.content) > MAX_BYTES:
                raise AdapterError(
                    "Open-Meteo reply unexpectedly large", AdapterErrorCode.TRUNCATED
                )
            try:
                h = r.json()["hourly"]
                i = h["time"].index(hour.strftime("%Y-%m-%dT%H:%M"))
            except (ValueError, KeyError, TypeError) as e:
                raise AdapterError(
                    "Open-Meteo had no reading for kickoff", AdapterErrorCode.BAD_RESPONSE
                ) from e

            def at(k: str) -> float | None:
                try:
                    v = h[k][i]
                    return None if v is None else float(v)
                except (KeyError, IndexError, TypeError, ValueError):
                    return None

            f = Forecast(
                at=hour,
                temp_f=at("temperature_2m"),
                wind_mph=at("wind_speed_10m"),
                gust_mph=at("wind_gusts_10m"),
                precip_prob=at("precipitation_probability"),
                retrieved_at=now,
            )
            self._cache[key] = f
            return f
