"""Versioned probability models for the CPI MoM contract, with model cards.

Every model is deterministic: same history + contract + cutoff -> same forecast.
Probabilities are floats in [0, 1] (they are not money; Decimal is used for prices).
Models never see data published after the cutoff: callers pass ``history_as_of`` output,
and models re-check it.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from scipy.stats import beta, norm

from app.research.cpi import CpiMomContract, FirstPrint, LeakageError, dataset_hash, next_month

FEATURE_VERSION = "cpi_first_print_mom.v1"


class Decision(StrEnum):
    FORECAST = "FORECAST"
    ABSTAIN = "ABSTAIN"


class AbstainReason(StrEnum):
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    OUTCOME_ALREADY_PUBLISHED = "OUTCOME_ALREADY_PUBLISHED"
    HORIZON_NOT_SUPPORTED = "HORIZON_NOT_SUPPORTED"  # only the next unreleased month
    THRESHOLD_OFF_GRID = "THRESHOLD_OFF_GRID"
    DEGENERATE_INPUTS = "DEGENERATE_INPUTS"


@dataclass(frozen=True)
class Forecast:
    model: str
    version: str
    feature_version: str
    contract_key: str
    as_of: datetime
    decision: Decision
    p_yes: float | None
    lower: float | None
    upper: float | None
    uncertainty_method: str
    reasons: list[str] = field(default_factory=list)
    inputs: dict = field(default_factory=dict)  # months used, input hash, parameters


@dataclass(frozen=True)
class ModelCard:
    name: str
    version: str
    summary: str
    contract_type: str
    features: str
    uncertainty_method: str
    hyperparameters: dict
    limitations: list[str]


class ProbabilityModel(Protocol):
    card: ModelCard

    def predict(
        self, contract: CpiMomContract, history: Sequence[FirstPrint], as_of: datetime
    ) -> Forecast: ...


CONTRACT_TYPE = (
    "Headline CPI-U SA month-over-month % change, first print, rounded to 0.1, > threshold"
)
COMMON_LIMITS = [
    "Forecasts only the NEXT unreleased month; abstains otherwise.",
    "First-print MoM is reconstructed from FRED/ALFRED 3-decimal indexes and can differ "
    "from BLS's published percentage by 0.1 in rare rounding cases.",
    "Uses no information beyond past CPI prints (no energy prices, nowcasts, or consensus "
    "forecasts), so it ignores most of what moves a given month's CPI.",
    "Treats months as exchangeable; regime changes (e.g., 2021-22 inflation) violate this.",
    "Probabilities are not profits; comparison with executable market prices, fees and "
    "slippage happens in the signal engine.",
]


def _common_checks(
    contract: CpiMomContract, history: Sequence[FirstPrint], as_of: datetime, min_history: int
) -> list[str]:
    if any(p.released_at > as_of for p in history):
        raise LeakageError("model received data published after as_of")
    reasons: list[str] = []
    if not contract.threshold_on_grid():
        reasons.append(AbstainReason.THRESHOLD_OFF_GRID)
    if any(p.month == contract.reference_month for p in history):
        reasons.append(AbstainReason.OUTCOME_ALREADY_PUBLISHED)
    elif not history or next_month(history[-1].month) != contract.reference_month:
        reasons.append(AbstainReason.HORIZON_NOT_SUPPORTED)
    if len(history) < min_history:
        reasons.append(AbstainReason.INSUFFICIENT_HISTORY)
    return reasons


def _abstain(card: ModelCard, contract: CpiMomContract, as_of: datetime, reasons: list[str],
             inputs: dict | None = None) -> Forecast:
    return Forecast(card.name, card.version, FEATURE_VERSION, contract.key, as_of,
                    Decision.ABSTAIN, None, None, None, card.uncertainty_method,
                    [str(r) for r in reasons], inputs or {})


class BaseRateModel:
    """Share of past first prints (trailing window) that would have resolved YES at T."""

    def __init__(self, window: int = 120, min_history: int = 36, band: float = 0.90) -> None:
        self.window, self.min_history, self.band = window, min_history, band
        self.card = ModelCard(
            name="base_rate",
            version="1.0.0",
            summary="Historical frequency of first-print MoM > T over the trailing window.",
            contract_type=CONTRACT_TYPE,
            features=f"Last {window} first-print rounded MoM values published before as_of.",
            uncertainty_method=(
                f"Jeffreys Beta(k+0.5, n-k+0.5) posterior; p = posterior mean; "
                f"{int(band * 100)}% equal-tailed credible interval (assumes exchangeable months)"
            ),
            hyperparameters={"window": window, "min_history": min_history, "band": band},
            limitations=[*COMMON_LIMITS, "Ignores recent momentum entirely."],
        )

    def predict(self, contract: CpiMomContract, history: Sequence[FirstPrint],
                as_of: datetime) -> Forecast:
        reasons = _common_checks(contract, history, as_of, self.min_history)
        if reasons:
            return _abstain(self.card, contract, as_of, reasons)
        win = list(history)[-self.window:]
        k = sum(contract.resolves_yes(p.mom_rounded) for p in win)
        n = len(win)
        a, b = k + 0.5, n - k + 0.5
        tail = (1 - self.band) / 2
        inputs = {"n": n, "k": k, "months": [win[0].month.isoformat(), win[-1].month.isoformat()],
                  "input_hash": dataset_hash(win)}
        return Forecast(self.card.name, self.card.version, FEATURE_VERSION, contract.key, as_of,
                        Decision.FORECAST, a / (a + b), float(beta.ppf(tail, a, b)),
                        float(beta.ppf(1 - tail, a, b)), self.card.uncertainty_method, [], inputs)


class GaussianTrailingModel:
    """MoM ~ Normal(mean of last k_mean prints, sd of last k_sd prints).

    Rounding handled exactly: rounded(x) > T  <=>  x >= T + 0.05 (half-up to 0.1).
    """

    def __init__(self, k_mean: int = 12, k_sd: int = 36, min_history: int = 36,
                 sd_floor: float = 0.05) -> None:
        self.k_mean, self.k_sd = k_mean, k_sd
        self.min_history, self.sd_floor = min_history, sd_floor
        self.card = ModelCard(
            name="gaussian_trailing",
            version="1.0.0",
            summary="Normal distribution centred on the recent average first-print MoM.",
            contract_type=CONTRACT_TYPE,
            features=(f"Mean of last {k_mean} and sample SD of last {k_sd} unrounded "
                      "first-print MoM values published before as_of."),
            uncertainty_method=(
                "Heuristic sensitivity band: p recomputed with the mean shifted by +/-1 "
                "standard error (sd/sqrt(k_mean)). NOT a confidence interval."
            ),
            hyperparameters={"k_mean": k_mean, "k_sd": k_sd, "min_history": min_history,
                             "sd_floor": sd_floor},
            limitations=[*COMMON_LIMITS,
                         "Assumes normal, homoskedastic shocks; fat tails are underweighted.",
                         "Window lengths were fixed a priori, not tuned."],
        )

    def predict(self, contract: CpiMomContract, history: Sequence[FirstPrint],
                as_of: datetime) -> Forecast:
        reasons = _common_checks(contract, history, as_of, self.min_history)
        if reasons:
            return _abstain(self.card, contract, as_of, reasons)
        vals_mean = [float(p.mom_pct) for p in list(history)[-self.k_mean:]]
        vals_sd = [float(p.mom_pct) for p in list(history)[-self.k_sd:]]
        mu = statistics.fmean(vals_mean)
        sd = max(statistics.stdev(vals_sd), self.sd_floor)
        if not (math.isfinite(mu) and math.isfinite(sd)):
            return _abstain(self.card, contract, as_of, [AbstainReason.DEGENERATE_INPUTS])
        cut = float(contract.threshold + Decimal("0.05"))
        se = sd / math.sqrt(len(vals_mean))

        def p_at(m: float) -> float:
            return float(norm.sf(cut, loc=m, scale=sd))

        p, lo, hi = p_at(mu), p_at(mu - se), p_at(mu + se)
        win = list(history)[-max(self.k_mean, self.k_sd):]
        inputs = {"mu": round(mu, 6), "sd": round(sd, 6), "se": round(se, 6),
                  "months": [win[0].month.isoformat(), win[-1].month.isoformat()],
                  "input_hash": dataset_hash(win)}
        return Forecast(self.card.name, self.card.version, FEATURE_VERSION, contract.key, as_of,
                        Decision.FORECAST, p, min(lo, hi), max(lo, hi),
                        self.card.uncertainty_method, [], inputs)


REGISTRY: dict[str, ProbabilityModel] = {
    m.card.name: m for m in (BaseRateModel(), GaussianTrailingModel())
}
