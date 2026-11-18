"""CPI month-over-month contract definition and first-print reconstruction.

CONTRACT TYPE (narrow, explicit): "Headline CPI-U, seasonally adjusted, month-over-month
percent change for reference month M, AS FIRST PUBLISHED, rounded to one decimal place,
is strictly greater than threshold T."

This mirrors the general shape of monthly CPI event contracts, but any real market must
be checked against its own official rules (SA vs NSA, rounding, first release vs revised,
strict vs inclusive) before this model is applied to it. That mapping is milestone 05.

FIRST PRINT: the MoM change BLS reports in the release for month M compares M's index with
M-1's index *as published in that same release* (M-1 may itself have been revised).
So: first_vintage(M) = earliest vintage with a value for M; mom = idx_M / idx_{M-1} as of
that vintage. Computed from 3-decimal published indexes, this can differ from BLS's
officially published percentage by 0.1 in rare rounding edge cases (documented limitation).
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.db.models import EvidenceRecord

SOURCE_ID = "fred:CPIAUCSL"
TENTH = Decimal("0.1")
# A true first print for month M appears ~2 weeks after M ends. If the earliest vintage we
# hold is much later (sparse early ALFRED history), it is not a first print: exclude it.
MAX_FIRST_PRINT_LAG = timedelta(days=60)


def next_month(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def prev_month(d: date) -> date:
    return date(d.year - (d.month == 1), (d.month - 2) % 12 + 1, 1)


def round_tenth(x: Decimal) -> Decimal:
    return x.quantize(TENTH, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CpiMomContract:
    reference_month: date  # first of month
    threshold: Decimal  # percent, e.g. Decimal("0.3")

    def __post_init__(self) -> None:
        if self.reference_month.day != 1:
            raise ValueError("reference_month must be the first day of a month")

    @property
    def key(self) -> str:
        return f"CPI_MOM_SA_FIRST>{self.threshold}@{self.reference_month:%Y-%m}"

    def threshold_on_grid(self) -> bool:
        return self.threshold == round_tenth(self.threshold)

    def resolves_yes(self, first_print_mom_rounded: Decimal) -> bool:
        return first_print_mom_rounded > self.threshold


@dataclass(frozen=True)
class FirstPrint:
    month: date
    released_at: datetime  # available_at of the first vintage for this month
    vintage_date: date
    index: Decimal
    prev_index: Decimal
    mom_pct: Decimal  # unrounded, full precision
    mom_rounded: Decimal  # contract resolution value
    evidence_id: str


@dataclass(frozen=True)
class FirstPrintBuild:
    prints: list[FirstPrint]
    excluded: dict[str, int]  # reason -> count


def build_first_prints(records: Iterable[EvidenceRecord]) -> FirstPrintBuild:
    """Reconstruct the first-print MoM series from immutable vintage records."""
    by_month: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for r in records:
        by_month[r.observation_date].append(r)
    for rows in by_month.values():
        rows.sort(key=lambda r: r.vintage_date)

    def value_as_of(month: str, vintage: str) -> Decimal | None:
        best = None
        for r in by_month.get(month, ()):
            if r.vintage_date <= vintage:
                best = r
            else:
                break
        return best.value if best is not None else None

    prints: list[FirstPrint] = []
    excluded: dict[str, int] = defaultdict(int)
    for month_s in sorted(by_month):
        month = date.fromisoformat(month_s)
        first = next((r for r in by_month[month_s] if r.value is not None), None)
        if first is None:
            excluded["no_value_in_any_vintage"] += 1
            continue
        vintage = date.fromisoformat(first.vintage_date)
        if vintage - next_month(month) > MAX_FIRST_PRINT_LAG:
            excluded["earliest_vintage_not_a_first_print"] += 1
            continue
        prev = value_as_of(prev_month(month).isoformat(), first.vintage_date)
        if prev is None or prev == 0:
            excluded["previous_month_missing_in_vintage"] += 1
            continue
        mom = (first.value / prev - 1) * 100
        prints.append(
            FirstPrint(
                month=month,
                released_at=first.available_at,
                vintage_date=vintage,
                index=first.value,
                prev_index=prev,
                mom_pct=mom,
                mom_rounded=round_tenth(mom),
                evidence_id=first.id,
            )
        )
    return FirstPrintBuild(prints, dict(excluded))


class LeakageError(AssertionError):
    """Raised if any input was published after the forecast cutoff."""


def history_as_of(prints: Sequence[FirstPrint], cutoff: datetime) -> list[FirstPrint]:
    """First prints that were public at ``cutoff``. Enforced, not assumed."""
    hist = [p for p in prints if p.released_at <= cutoff]
    if any(p.released_at > cutoff for p in hist):  # defensive; cannot happen
        raise LeakageError("history contains post-cutoff data")
    return hist


def dataset_hash(prints: Sequence[FirstPrint]) -> str:
    payload = [[p.month.isoformat(), p.vintage_date.isoformat(), str(p.index),
                str(p.prev_index)] for p in prints]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()
