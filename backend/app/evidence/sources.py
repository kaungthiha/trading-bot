"""Controlled registry of evidence sources.

Only sources listed here can be configured. Each entry documents provenance, licensing
and the timing rule used to compute ``available_at`` (when a value could first have been
known), which is what keeps backtests free of look-ahead bias.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

FRED_NOTICE = (
    "This product uses the FRED® API but is not endorsed or certified by the "
    "Federal Reserve Bank of St. Louis."
)
FRED_TERMS_URL = "https://fred.stlouisfed.org/docs/api/terms_of_use.html"

EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class SourceSpec:
    id: str
    adapter: str  # "fred"
    series_id: str
    title: str
    category: str
    frequency: str
    # available_at = vintage date at this local time. FRED vintage dates carry no time of
    # day; we use the originating agency's published release time. Unknown -> end of day.
    release_time: time
    release_tz: ZoneInfo
    release_time_source: str
    freshness_max_age_days: int
    source_page_url: str
    upstream_agency: str
    license_notes: str


_BLS_CPI_TIMING = (
    "BLS CPI release schedule lists 08:30 AM (https://www.bls.gov/schedule/news_release/"
    "cpi.htm, checked 2026-11-18). Timezone not stated on page; assumed US Eastern."
)
_BLS_EMP_TIMING = (
    "BLS Employment Situation releases at 08:30 AM (assumed US Eastern; reverify at "
    "https://www.bls.gov/schedule/news_release/empsit.htm)."
)
_FRED_LICENSE = (
    "Retrieved via FRED API under its Terms of Use (" + FRED_TERMS_URL + "); attribution "
    "notice required. Underlying data published by {agency}. Personal research use."
)

SOURCES: dict[str, SourceSpec] = {
    s.id: s
    for s in [
        SourceSpec(
            id="fred:CPIAUCSL",
            adapter="fred",
            series_id="CPIAUCSL",
            title="CPI for All Urban Consumers: All Items, SA (index 1982-84=100)",
            category="economics",
            frequency="monthly",
            release_time=time(8, 30),
            release_tz=EASTERN,
            release_time_source=_BLS_CPI_TIMING,
            freshness_max_age_days=45,
            source_page_url="https://alfred.stlouisfed.org/series?seid=CPIAUCSL",
            upstream_agency="U.S. Bureau of Labor Statistics",
            license_notes=_FRED_LICENSE.format(agency="U.S. Bureau of Labor Statistics"),
        ),
        SourceSpec(
            id="fred:CPILFESL",
            adapter="fred",
            series_id="CPILFESL",
            title="CPI: All Items Less Food and Energy, SA (core CPI)",
            category="economics",
            frequency="monthly",
            release_time=time(8, 30),
            release_tz=EASTERN,
            release_time_source=_BLS_CPI_TIMING,
            freshness_max_age_days=45,
            source_page_url="https://alfred.stlouisfed.org/series?seid=CPILFESL",
            upstream_agency="U.S. Bureau of Labor Statistics",
            license_notes=_FRED_LICENSE.format(agency="U.S. Bureau of Labor Statistics"),
        ),
        SourceSpec(
            id="fred:UNRATE",
            adapter="fred",
            series_id="UNRATE",
            title="Unemployment Rate, SA (percent)",
            category="economics",
            frequency="monthly",
            release_time=time(8, 30),
            release_tz=EASTERN,
            release_time_source=_BLS_EMP_TIMING,
            freshness_max_age_days=45,
            source_page_url="https://alfred.stlouisfed.org/series?seid=UNRATE",
            upstream_agency="U.S. Bureau of Labor Statistics",
            license_notes=_FRED_LICENSE.format(agency="U.S. Bureau of Labor Statistics"),
        ),
    ]
}
