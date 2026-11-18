"""FRED / ALFRED evidence adapter (vintage-aware).

API facts used (fred.stlouisfed.org/docs/api, checked 2026-11-18):
  - Base https://api.stlouisfed.org/fred ; api_key = 32-char lowercase alphanumeric.
  - series/observations with realtime_start=1776-07-04 & realtime_end=9999-12-31 returns
    every real-time period (vintage) of every observation; limit max 100000, page by
    offset. Rows: {realtime_start, realtime_end, date, value}.
  - Rate limit: 120 requests/minute, then HTTP 429 (possible temporary block).
  - Errors: {"error_code": ..., "error_message": ...}. We never echo them (they can
    mention request variables).

Design notes:
  - Always fetch the full real-time window. Narrowing realtime_start risks the API
    clipping older periods to the requested start, which would fabricate vintages.
    Dedupe on insert makes full refreshes idempotent.
  - realtime_end is NOT stored: it changes when a value is superseded, and evidence rows
    are immutable. Supersession is derived from the next vintage instead.
  - "." (and empty) values are recorded as MISSING, never as zero.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.adapters.base import AdapterError, AdapterErrorCode, FetchError
from app.adapters.http import RetryingJsonClient
from app.core.clock import Clock
from app.core.config import Settings
from app.evidence.models import (
    EvidenceFetchResult,
    EvidenceObservation,
    EvidenceQuality,
    SeriesMetadata,
    available_at_for,
)
from app.evidence.sources import SourceSpec

FRED_BASE = "https://api.stlouisfed.org/fred"
_PATHS = re.compile(r"^/series(?:/observations|/vintagedates)?$")
_KEY_RE = re.compile(r"[0-9a-z]{32}")
REALTIME_MIN = "1776-07-04"
REALTIME_MAX = "9999-12-31"
PAGE_LIMIT = 100_000
MAX_PAGES = 20


class FredClient(RetryingJsonClient):
    def __init__(self, api_key: str, **kw: Any) -> None:
        if not _KEY_RE.fullmatch(api_key):
            raise ValueError("FRED API key must be a 32-character lowercase alphanumeric string")
        super().__init__(
            FRED_BASE,
            allowed_bases={FRED_BASE},
            path_pattern=_PATHS,
            default_params={"api_key": api_key, "file_type": "json"},
            **kw,
        )

    @classmethod
    def from_settings(cls, s: Settings, **kw: Any) -> FredClient:
        if s.fred_api_key is None:
            raise AdapterError(
                "KRT_FRED_API_KEY is not set in .env", AdapterErrorCode.SOURCE_UNAVAILABLE
            )
        return cls(
            s.fred_api_key.get_secret_value(),
            timeout=s.http_timeout_seconds,
            min_interval=s.fred_min_request_interval_seconds,
            **kw,
        )


def _parse_date(v: Any, field: str) -> date:
    if not isinstance(v, str):
        raise AdapterError(f"{field}: expected YYYY-MM-DD", AdapterErrorCode.BAD_RESPONSE)
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise AdapterError(f"{field}: invalid date", AdapterErrorCode.BAD_RESPONSE) from None


def parse_value(raw: Any) -> tuple[Decimal | None, EvidenceQuality]:
    if raw is None or (isinstance(raw, str) and raw.strip() in ("", ".")):
        return None, EvidenceQuality.MISSING
    if not isinstance(raw, str):
        raise AdapterError("value: expected string", AdapterErrorCode.BAD_RESPONSE)
    try:
        d = Decimal(raw.strip())
    except InvalidOperation:
        raise AdapterError("value: not a number", AdapterErrorCode.BAD_RESPONSE) from None
    if not d.is_finite():
        raise AdapterError("value: non-finite", AdapterErrorCode.BAD_RESPONSE)
    return d, EvidenceQuality.OK


class FredEvidenceAdapter:
    def __init__(self, spec: SourceSpec, client: FredClient, clock: Clock) -> None:
        if spec.adapter != "fred":
            raise ValueError(f"{spec.id} is not a FRED source")
        self.spec = spec
        self.source_id = spec.id
        self.client = client
        self.clock = clock

    def _friendly(self, e: AdapterError) -> AdapterError:
        if e.status == 400:
            return AdapterError(
                "FRED rejected the request (400): check KRT_FRED_API_KEY and the series id",
                AdapterErrorCode.HTTP_ERROR,
                400,
            )
        return e

    def fetch_metadata(self) -> SeriesMetadata:
        try:
            body = self.client.get("/series", {"series_id": self.spec.series_id})
        except AdapterError as e:
            raise self._friendly(e) from None
        seriess = body.get("seriess")
        if not (isinstance(seriess, list) and seriess and isinstance(seriess[0], dict)):
            raise AdapterError("Missing 'seriess'", AdapterErrorCode.BAD_RESPONSE)
        s = seriess[0]
        notes = s.get("notes") or ""
        return SeriesMetadata(
            series_id=self.spec.series_id,
            title=s.get("title"),
            units=s.get("units"),
            frequency=s.get("frequency"),
            seasonal_adjustment=s.get("seasonal_adjustment"),
            last_updated=s.get("last_updated"),
            copyright_flagged="copyright" in notes.lower(),
        )

    def fetch(self) -> EvidenceFetchResult:
        meta = self.fetch_metadata()
        license_notes = self.spec.license_notes
        if meta.copyright_flagged:
            license_notes += (
                " COPYRIGHTED SERIES (per FRED notes): personal use only; obtain owner "
                "permission for any other use."
            )

        rows: list[dict[str, Any]] = []
        offset = 0
        for _ in range(MAX_PAGES):
            try:
                body = self.client.get(
                    "/series/observations",
                    {
                        "series_id": self.spec.series_id,
                        "realtime_start": REALTIME_MIN,
                        "realtime_end": REALTIME_MAX,
                        "output_type": 1,
                        "limit": PAGE_LIMIT,
                        "offset": offset,
                        "sort_order": "asc",
                    },
                )
            except AdapterError as e:
                raise self._friendly(e) from None
            page = body.get("observations")
            if not isinstance(page, list):
                raise AdapterError("Missing 'observations'", AdapterErrorCode.BAD_RESPONSE)
            rows.extend(page)
            count = body.get("count")
            offset += len(page)
            if not page or not isinstance(count, int) or offset >= count:
                break
        else:
            raise AdapterError(
                f"Stopped after {MAX_PAGES} pages; results truncated", AdapterErrorCode.TRUNCATED
            )

        retrieved = self.clock.now()
        obs: list[EvidenceObservation] = []
        errors: list[FetchError] = []
        for r in rows:
            try:
                vintage = _parse_date(r.get("realtime_start"), "realtime_start")
                period = _parse_date(r.get("date"), "date")
                value, quality = parse_value(r.get("value"))
            except AdapterError as e:
                errors.append(FetchError(f"{self.source_id}:{r.get('date')}", e.code, str(e)))
                continue
            obs.append(
                EvidenceObservation(
                    source_id=self.source_id,
                    series_id=self.spec.series_id,
                    observation_date=period,
                    vintage_date=vintage,
                    value=value,
                    quality=quality,
                    available_at=available_at_for(
                        vintage, self.spec.release_time, self.spec.release_tz
                    ),
                    retrieved_at=retrieved,
                    units=meta.units,
                    source_url=self.spec.source_page_url,
                    license_notes=license_notes,
                )
            )
        return EvidenceFetchResult(observations=obs, errors=errors, metadata=meta)
