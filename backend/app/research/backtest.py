"""Walk-forward evaluation with an enforced chronological development/holdout split.

For each target month M (in order): cutoff = 1 second before M's first print was
published; the model sees only prints public at the cutoff; the outcome is M's first
print. Predictions for every threshold in the grid are scored. Hyperparameters are fixed
a priori, so the holdout is genuinely out-of-sample; dev and holdout are reported
separately and the split is validated (holdout must start after dev ends).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.research.cpi import CpiMomContract, FirstPrint, LeakageError, dataset_hash, history_as_of
from app.research.metrics import MetricSummary, summarize
from app.research.models import Decision, ProbabilityModel

DEFAULT_THRESHOLDS = tuple(Decimal(x) / 10 for x in range(-1, 7))  # -0.1 .. 0.6
DEFAULT_HOLDOUT_START = datetime(2015, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Prediction:
    month: str
    threshold: str
    cutoff: datetime
    p_yes: float | None
    outcome: int
    decision: Decision
    reasons: list[str]


@dataclass(frozen=True)
class EvaluationReport:
    model: str
    version: str
    feature_version: str
    dataset_hash: str
    thresholds: list[str]
    holdout_start: datetime
    dev_range: tuple[str, str] | None
    holdout_range: tuple[str, str] | None
    dev: MetricSummary
    holdout: MetricSummary
    predictions: list[Prediction]


def _range(preds: list[Prediction]) -> tuple[str, str] | None:
    months = sorted({p.month for p in preds})
    return (months[0], months[-1]) if months else None


def _summ(preds: list[Prediction]) -> MetricSummary:
    scored = [p for p in preds if p.decision is Decision.FORECAST]
    return summarize(
        [p.p_yes for p in scored],  # type: ignore[misc]
        [p.outcome for p in scored],
        n_events=len({p.month for p in scored}),
        n_abstained=sum(p.decision is Decision.ABSTAIN for p in preds),
    )


def walk_forward(
    model: ProbabilityModel,
    prints: Sequence[FirstPrint],
    *,
    thresholds: Sequence[Decimal] = DEFAULT_THRESHOLDS,
    holdout_start: datetime = DEFAULT_HOLDOUT_START,
) -> EvaluationReport:
    ordered = sorted(prints, key=lambda p: p.released_at)
    if [p.month for p in ordered] != sorted(p.month for p in ordered):
        raise LeakageError("release order disagrees with month order; data inconsistent")
    preds: list[Prediction] = []
    for target in ordered:
        cutoff = target.released_at - timedelta(seconds=1)
        hist = history_as_of(ordered, cutoff)
        if any(p.month >= target.month for p in hist):
            raise LeakageError(f"target {target.month} visible before its release")
        for t in thresholds:
            c = CpiMomContract(target.month, t)
            f = model.predict(c, hist, cutoff)
            preds.append(Prediction(
                month=target.month.isoformat(), threshold=str(t), cutoff=cutoff,
                p_yes=f.p_yes, outcome=int(c.resolves_yes(target.mom_rounded)),
                decision=f.decision, reasons=f.reasons,
            ))

    dev = [p for p in preds if p.cutoff < holdout_start]
    hold = [p for p in preds if p.cutoff >= holdout_start]
    if dev and hold and max(p.cutoff for p in dev) >= min(p.cutoff for p in hold):
        raise LeakageError("development period overlaps holdout")
    return EvaluationReport(
        model=model.card.name,
        version=model.card.version,
        feature_version="cpi_first_print_mom.v1",
        dataset_hash=dataset_hash(ordered),
        thresholds=[str(t) for t in thresholds],
        holdout_start=holdout_start,
        dev_range=_range(dev),
        holdout_range=_range(hold),
        dev=_summ(dev),
        holdout=_summ(hold),
        predictions=preds,
    )
