"""The verified fee schedule must reproduce Kalshi's published General Trading Fees Table
(fee-schedule PDF, effective July 7, 2026) exactly, for 1 and 100 contracts."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.signals.fees import load_schedules, select_schedule, taker_buy_cost

D = Decimal
# price: (fee for 1 contract, fee for 100 contracts) -- transcribed from the PDF table
PDF_TABLE = {
    "0.01": ("0.01", "0.07"), "0.05": ("0.01", "0.34"), "0.10": ("0.01", "0.63"),
    "0.15": ("0.01", "0.90"), "0.20": ("0.02", "1.12"), "0.25": ("0.02", "1.32"),
    "0.30": ("0.02", "1.47"), "0.35": ("0.02", "1.60"), "0.40": ("0.02", "1.68"),
    "0.45": ("0.02", "1.74"), "0.50": ("0.02", "1.75"), "0.55": ("0.02", "1.74"),
    "0.60": ("0.02", "1.68"), "0.65": ("0.02", "1.60"), "0.70": ("0.02", "1.47"),
    "0.75": ("0.02", "1.32"), "0.80": ("0.02", "1.12"), "0.85": ("0.01", "0.90"),
    "0.90": ("0.01", "0.63"), "0.95": ("0.01", "0.34"), "0.99": ("0.01", "0.07"),
}


@pytest.fixture(scope="module")
def schedule():  # type: ignore[no-untyped-def]
    s = select_schedule(load_schedules(), "quadratic_with_maker_fees")
    assert s is not None and s.verified and s.version == "kalshi-fee-schedule-2026-07-07"
    return s


@pytest.mark.parametrize("price,fees", PDF_TABLE.items())
def test_matches_pdf_general_trading_fees_table(schedule, price, fees) -> None:  # type: ignore[no-untyped-def]
    one, hundred = fees
    assert taker_buy_cost(schedule, [(D(1), D(price))]).effective_fee == D(one)
    assert taker_buy_cost(schedule, [(D(100), D(price))]).effective_fee == D(hundred)


def test_maker_multipliers_match_pdf(schedule) -> None:  # type: ignore[no-untyped-def]
    mm = schedule.maker_multiplier
    assert schedule.taker_rate * mm["quadratic_with_maker_fees"] == D("0.0175")
    assert schedule.taker_rate * mm["quadratic_with_combo_maker_fees"] == D("0.035")
    assert schedule.maker_multiplier["quadratic"] == 0


def test_unverified_candidate_kept_for_history() -> None:
    versions = {s.version: s.verified for s in load_schedules()}
    assert versions["kalshi-quadratic-candidate-2026-11"] is False  # old signals reference it
