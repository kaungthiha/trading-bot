"""Deterministic SYNTHETIC CPI vintages for testing model logic (not real data, not used
for any reported performance). Each month M is first published on the 12th of M+1 at
08:30 ET, with M's index computed from a fixed repeating MoM pattern."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from app.evidence.models import EvidenceObservation, EvidenceQuality, available_at_for
from app.evidence.sources import SOURCES
from app.research.cpi import next_month

SPEC = SOURCES["fred:CPIAUCSL"]
PATTERN = [Decimal(x) for x in ("0.1", "0.2", "0.3", "0.4", "0.2", "0.3")]
RETRIEVED = datetime(2026, 11, 18, tzinfo=UTC)


def obs(month: date, vintage: date, value: Decimal | None) -> EvidenceObservation:
    return EvidenceObservation(
        source_id=SPEC.id, series_id=SPEC.series_id, observation_date=month,
        vintage_date=vintage, value=value,
        quality=EvidenceQuality.OK if value is not None else EvidenceQuality.MISSING,
        available_at=available_at_for(vintage, SPEC.release_time, SPEC.release_tz),
        retrieved_at=RETRIEVED, units="Index", source_url=SPEC.source_page_url,
        license_notes="synthetic",
    )


def synthetic_vintages(start: date = date(2019, 1, 1), months: int = 60,
                       base: Decimal = Decimal("250.000")) -> list[EvidenceObservation]:
    out = []
    idx = base
    m = start
    out.append(obs(m, next_month(m).replace(day=12), idx))
    for i in range(1, months):
        m = next_month(m)
        idx = (idx * (1 + PATTERN[i % len(PATTERN)] / 100)).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP)
        out.append(obs(m, next_month(m).replace(day=12), idx))
    return out


class FakeRecord:
    """Duck-typed EvidenceRecord for pure (no-DB) tests."""

    def __init__(self, o: EvidenceObservation, rid: str) -> None:
        self.id = rid
        self.observation_date = o.observation_date.isoformat()
        self.vintage_date = o.vintage_date.isoformat()
        self.value = o.value
        self.available_at = o.available_at


def as_records(observations: list[EvidenceObservation]) -> list[FakeRecord]:
    return [FakeRecord(o, f"r{i}") for i, o in enumerate(observations)]
