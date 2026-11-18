"""Proper scoring rules and calibration diagnostics for binary probability forecasts."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass

LOG_LOSS_EPS = 1e-6  # clip so a single 0/1 forecast can't produce infinity; reported


@dataclass(frozen=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int
    mean_p: float | None
    observed_rate: float | None


@dataclass(frozen=True)
class MetricSummary:
    n_predictions: int
    n_events: int  # distinct reference months (predictions within a month are correlated)
    n_abstained: int
    base_rate: float | None
    brier: float | None
    log_loss: float | None
    log_loss_eps: float
    calibration: list[CalibrationBin]

    def to_dict(self) -> dict:
        return asdict(self)


def brier(ps: Sequence[float], ys: Sequence[int]) -> float:
    if not ps or len(ps) != len(ys):
        raise ValueError("need equal-length, non-empty inputs")
    return sum((p - y) ** 2 for p, y in zip(ps, ys, strict=True)) / len(ps)


def log_loss(ps: Sequence[float], ys: Sequence[int], eps: float = LOG_LOSS_EPS) -> float:
    if not ps or len(ps) != len(ys):
        raise ValueError("need equal-length, non-empty inputs")
    total = 0.0
    for p, y in zip(ps, ys, strict=True):
        if not (0.0 <= p <= 1.0) or not math.isfinite(p):
            raise ValueError(f"probability out of range: {p}")
        q = min(max(p, eps), 1 - eps)
        total += -(y * math.log(q) + (1 - y) * math.log(1 - q))
    return total / len(ps)


def calibration_bins(
    ps: Sequence[float], ys: Sequence[int], n_bins: int = 10
) -> list[CalibrationBin]:
    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, y in zip(ps, ys, strict=True):
        bins[min(int(p * n_bins), n_bins - 1)].append((p, y))
    out = []
    for i, b in enumerate(bins):
        out.append(CalibrationBin(
            lower=i / n_bins, upper=(i + 1) / n_bins, count=len(b),
            mean_p=sum(p for p, _ in b) / len(b) if b else None,
            observed_rate=sum(y for _, y in b) / len(b) if b else None,
        ))
    return out


def summarize(ps: Sequence[float], ys: Sequence[int], n_events: int,
              n_abstained: int) -> MetricSummary:
    if not ps:
        return MetricSummary(0, n_events, n_abstained, None, None, None, LOG_LOSS_EPS, [])
    return MetricSummary(
        n_predictions=len(ps),
        n_events=n_events,
        n_abstained=n_abstained,
        base_rate=sum(ys) / len(ys),
        brier=brier(ps, ys),
        log_loss=log_loss(ps, ys),
        log_loss_eps=LOG_LOSS_EPS,
        calibration=calibration_bins(ps, ys),
    )
