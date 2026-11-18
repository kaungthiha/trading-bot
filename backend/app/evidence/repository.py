"""Evidence persistence: insert-only with dedupe, and point-in-time (as-of) reads."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.adapters.base import FetchError
from app.db.models import EvidenceRecord
from app.evidence.models import EvidenceObservation
from app.evidence.sources import SourceSpec


@dataclass(frozen=True)
class InsertResult:
    inserted: int
    duplicates: int
    conflicts: list[FetchError]


class EvidenceRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def insert_new(
        self, source_id: str, observations: Sequence[EvidenceObservation]
    ) -> InsertResult:
        """Insert observations not seen before. Same identity + same content = duplicate
        (skipped). Same identity + DIFFERENT content = conflict: the stored record is kept
        (immutability) and the discrepancy is reported, never silently overwritten."""
        existing: dict[str, str] = {
            f"{od}|{vd}": h
            for od, vd, h in self.s.execute(
                select(
                    EvidenceRecord.observation_date,
                    EvidenceRecord.vintage_date,
                    EvidenceRecord.hash,
                ).where(EvidenceRecord.source_id == source_id)
            ).all()
        }
        inserted = duplicates = 0
        conflicts: list[FetchError] = []
        batch: list[EvidenceRecord] = []
        seen_in_batch: set[str] = set()
        for o in observations:
            key = f"{o.observation_date.isoformat()}|{o.vintage_date.isoformat()}"
            h = o.content_hash()
            if key in existing or key in seen_in_batch:
                if key in existing and existing[key] != h:
                    conflicts.append(
                        FetchError(
                            f"{source_id}:{key}",
                            "VINTAGE_CONTENT_CHANGED",
                            "Upstream value for an already-stored vintage differs; kept original",
                        )
                    )
                else:
                    duplicates += 1
                continue
            seen_in_batch.add(key)
            batch.append(
                EvidenceRecord(
                    source_id=o.source_id,
                    series_id=o.series_id,
                    observation_date=o.observation_date.isoformat(),
                    vintage_date=o.vintage_date.isoformat(),
                    value=o.value,
                    quality=o.quality.value,
                    available_at=o.available_at,
                    retrieved_at=o.retrieved_at,
                    units=o.units,
                    source_url=o.source_url,
                    license_notes=o.license_notes,
                    hash=h,
                )
            )
            inserted += 1
        self.s.add_all(batch)
        self.s.flush()
        return InsertResult(inserted, duplicates, conflicts)

    def as_of(self, source_id: str, cutoff: datetime, limit: int) -> Sequence[EvidenceRecord]:
        """Point-in-time view: for each period, the latest vintage with available_at <=
        cutoff. Anything published after the cutoff is invisible."""
        latest = (
            select(
                EvidenceRecord.observation_date.label("od"),
                func.max(EvidenceRecord.vintage_date).label("vd"),
            )
            .where(EvidenceRecord.source_id == source_id, EvidenceRecord.available_at <= cutoff)
            .group_by(EvidenceRecord.observation_date)
            .subquery()
        )
        stmt = (
            select(EvidenceRecord)
            .join(
                latest,
                and_(
                    EvidenceRecord.observation_date == latest.c.od,
                    EvidenceRecord.vintage_date == latest.c.vd,
                ),
            )
            .where(EvidenceRecord.source_id == source_id)
            .order_by(EvidenceRecord.observation_date.desc())
            .limit(limit)
        )
        return self.s.scalars(stmt).all()

    def vintages_of(self, source_id: str, observation_date: str) -> Sequence[EvidenceRecord]:
        return self.s.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.source_id == source_id,
                EvidenceRecord.observation_date == observation_date,
            )
            .order_by(EvidenceRecord.vintage_date)
        ).all()

    def stats(self, source_id: str) -> tuple[int, datetime | None, str | None]:
        count, latest_avail, latest_vintage = self.s.execute(
            select(
                func.count(),
                func.max(EvidenceRecord.available_at),
                func.max(EvidenceRecord.vintage_date),
            ).where(EvidenceRecord.source_id == source_id)
        ).one()
        # Depending on dialect, max() may or may not apply the column's type processor.
        avail = latest_avail
        if isinstance(avail, str):
            avail = datetime.fromisoformat(avail)
        if avail is not None and avail.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")
        return int(count), avail, latest_vintage


def is_fresh(spec: SourceSpec, latest_available: datetime | None, now: datetime) -> bool:
    if latest_available is None:
        return False
    return now - latest_available <= timedelta(days=spec.freshness_max_age_days)
