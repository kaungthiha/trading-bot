"""Evidence domain types and the EvidenceAdapter interface."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.adapters.base import FetchError


class EvidenceQuality(StrEnum):
    OK = "ok"
    MISSING = "missing"  # source reported no value for this period/vintage


class EvidenceObservation(BaseModel):
    """One value of one series for one period, AS PUBLISHED in one vintage. Immutable.

    - ``observation_date``: the period the value describes (e.g. 2026-09-01 = Sep 2026).
    - ``vintage_date``: the date this value was published or revised (FRED realtime_start).
    - ``available_at``: earliest instant the value could have been known (vintage date at
      the source's release time). Models may only use rows with available_at <= cutoff.
    - ``retrieved_at``: when we fetched it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    series_id: str
    observation_date: date
    vintage_date: date
    value: Decimal | None
    quality: EvidenceQuality
    available_at: AwareDatetime
    retrieved_at: AwareDatetime
    units: str | None
    source_url: str
    license_notes: str

    def content_hash(self) -> str:
        payload = {
            "source_id": self.source_id,
            "series_id": self.series_id,
            "observation_date": self.observation_date.isoformat(),
            "vintage_date": self.vintage_date.isoformat(),
            "value": None if self.value is None else str(self.value),
            "quality": self.quality.value,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class SeriesMetadata:
    series_id: str
    title: str | None
    units: str | None
    frequency: str | None
    seasonal_adjustment: str | None
    last_updated: str | None
    copyright_flagged: bool


@dataclass(frozen=True)
class EvidenceFetchResult:
    observations: list[EvidenceObservation] = field(default_factory=list)
    errors: list[FetchError] = field(default_factory=list)
    metadata: SeriesMetadata | None = None


class EvidenceAdapter(Protocol):
    """Fetches evidence for one registered source. Raises AdapterError on total failure.

    Adapters return everything they can see; the repository dedupes on insert, so
    repeated fetches are idempotent.
    """

    source_id: str

    def fetch(self) -> EvidenceFetchResult: ...


def available_at_for(vintage: date, release_local_time, tz) -> datetime:  # type: ignore[no-untyped-def]
    """Vintage date at the source's local release time, as an aware datetime (DST-safe)."""
    return datetime.combine(vintage, release_local_time, tzinfo=tz)
