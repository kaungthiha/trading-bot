"""Offline demo: builds a SEPARATE database (data/demo.sqlite3) from deterministic
SYNTHETIC data so every panel can be explored with no network and no API keys.

Everything is labelled: tickers start with MOCK-, evidence source URLs are synthetic://,
mappings are confirmed by actor "demo-seed", and signals use a demo-only fee schedule
version that is never written to fee_schedules.json. Nothing here touches your real data.
"""

from __future__ import annotations

import json
import random
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from alembic import command

from app.core.config import BACKEND_ROOT, Settings
from app.db.models import MarketMapping
from app.db.repositories import MarketRepository
from app.db.session import make_engine, make_session_factory
from app.domain.models import BookLevel, MarketSnapshot, MarketStatus, OrderBook, PriceRange
from app.evidence.models import EvidenceObservation, EvidenceQuality, available_at_for
from app.evidence.repository import EvidenceRepository
from app.evidence.sources import SOURCES
from app.ingest import IngestionSummary
from app.paper.service import OrderRequest, submit_order
from app.research.cpi import history_as_of, next_month
from app.research.models import REGISTRY
from app.research.service import evaluate_and_save, forecast_all, load_first_prints
from app.signals.fees import FeeSchedule, load_schedules
from app.signals.mapping import current_rules
from app.signals.service import generate_signals

DEMO_DB = BACKEND_ROOT / "data" / "demo.sqlite3"
SPEC = SOURCES["fred:CPIAUCSL"]
D = Decimal

DEMO_FEES = FeeSchedule(
    version="demo-synthetic-fees", fee_types=("quadratic_with_maker_fees",),
    taker_rate=D("0.07"), maker_multiplier={"quadratic_with_maker_fees": D("0.25")},
    trade_fee_rounding_step=D("0.000001"), balance_precision=D("0.01"),
    source_url="synthetic://demo", verified=True, verified_by="demo-seed",
    verified_at="2026-11-18",
    provenance={"note": "DEMO ONLY: synthetic stand-in so the demo shows candidate signals"},
)


def synthetic_cpi(start: date, end_month: date, seed: int = 7) -> list[EvidenceObservation]:
    """Monthly index whose MoM % follows a slowly drifting level plus noise; each month is
    first published on the 12th of the next month, and the previous month is revised once
    (in the same release) to exercise vintage handling."""
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic data, not security
    out: list[EvidenceObservation] = []
    level, idx, month = 0.25, D("100.000"), start
    retrieved = datetime(2026, 11, 18, tzinfo=UTC)

    def obs(m: date, v: date, value: D) -> EvidenceObservation:
        return EvidenceObservation(
            source_id=SPEC.id, series_id=SPEC.series_id, observation_date=m, vintage_date=v,
            value=value, quality=EvidenceQuality.OK,
            available_at=available_at_for(v, SPEC.release_time, SPEC.release_tz),
            retrieved_at=retrieved, units="Index (SYNTHETIC)", source_url="synthetic://demo",
            license_notes="SYNTHETIC DEMO DATA - not real CPI",
        )

    prev: tuple[date, D] | None = None
    while month <= end_month:
        level = min(0.8, max(-0.2, level + rng.gauss(0, 0.03)))
        mom = level + rng.gauss(0, 0.12)
        idx = (idx * (1 + D(repr(mom)) / 100)).quantize(D("0.001"), rounding=ROUND_HALF_UP)
        vintage = next_month(month).replace(day=12)
        out.append(obs(month, vintage, idx))
        if prev is not None and rng.random() < 0.3:  # small same-release revision
            pm, pv = prev
            out.append(obs(pm, vintage, (pv + D("0.010")).quantize(D("0.001"))))
        prev = (month, idx)
        month = next_month(month)
    return out


def _book(p: float, skew: float) -> tuple[tuple[BookLevel, ...], tuple[BookLevel, ...]]:
    """Two-sided book centred near p (+skew), 2c wide, three levels each side."""
    mid = min(0.95, max(0.05, p + skew))
    yes_bid = D(repr(round(mid - 0.01, 2)))
    yes_ask = D(repr(round(mid + 0.01, 2)))
    no_bid = D(1) - yes_ask
    yes = tuple(BookLevel(price=yes_bid - D("0.01") * i, quantity=D(200 + 100 * i))
                for i in range(3) if yes_bid - D("0.01") * i > 0)
    no = tuple(BookLevel(price=no_bid - D("0.01") * i, quantity=D(200 + 100 * i))
               for i in range(3) if no_bid - D("0.01") * i > 0)
    return yes, no


def build_demo(path: Path = DEMO_DB, cfg_factory=None) -> dict:  # type: ignore[no-untyped-def]
    """(Re)create the demo database. Returns a summary dict."""
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            p.unlink()
    url = f"sqlite:///{path.as_posix()}"
    command.upgrade(cfg_factory(url), "head")
    settings = Settings(_env_file=None, database_url=url, env="demo",
                        quote_max_age_seconds=31_536_000)
    engine = make_engine(url)
    factory = make_session_factory(engine)
    now = datetime.now(UTC).replace(microsecond=0)
    try:
        with factory() as s:
            # Evidence through the month before last so "next month" is forecastable.
            last = date(now.year, now.month, 1)
            last = date(last.year - (last.month <= 2), (last.month - 3) % 12 + 1, 1)
            EvidenceRepository(s).insert_new(SPEC.id, synthetic_cpi(date(1990, 1, 1), last))
            s.commit()
            evaluate_and_save(s, now)
            s.commit()

            hist = history_as_of(load_first_prints(s).prints, now)
            ref = next_month(hist[-1].month)
            repo = MarketRepository(s, _Clock(now))
            skews = {D("-0.1"): 0.0, D("0.0"): 0.0, D("0.1"): -0.12, D("0.2"): 0.02,
                     D("0.3"): 0.15, D("0.4"): 0.0, D("0.5"): -0.03}
            model = REGISTRY["gaussian_trailing"]
            for thr, skew in skews.items():
                contract, fs, _ = forecast_all(s, thr, now, ref)
                p = next(f.p_yes for f in fs if f.model == model.card.name) or 0.5
                yes, no = _book(p, skew)
                ticker = f"MOCK-KXCPI-{ref:%y%b}-T{thr}".upper()
                rules = (f"[DEMO] If the Consumer Price Index (CPI) increases by more than {thr}% "
                         f"(single-decimal) in {ref:%B %Y}, then the market resolves to Yes. "
                         "SYNTHETIC MARKET FOR THE OFFLINE DEMO.")
                snap = MarketSnapshot(
                    exchange="kalshi", external_ticker=ticker,
                    event_ticker=f"MOCK-KXCPI-{ref:%y%b}".upper(), series_ticker="MOCK-KXCPI",
                    title=f"[DEMO] Will CPI rise more than {thr}% in {ref:%B %Y}?",
                    category="economics", status=MarketStatus.ACTIVE, status_raw="active",
                    close_at=datetime.combine(next_month(ref).replace(day=12), datetime.min.time(),
                                              tzinfo=UTC),
                    rules_text=rules, official_source_url=None, notional_value=D("1.0000"),
                    price_ranges=(PriceRange(start=D("0"), end=D("1"), step=D("0.01")),),
                    orderbook=OrderBook(observed_at=now - timedelta(seconds=5), yes_bids=yes,
                                        no_bids=no),
                    is_mock=True, fee_type="quadratic_with_maker_fees", fee_multiplier=D("1"),
                )
                m = repo.upsert_snapshot(snap, "demo")
                s.add(MarketMapping(
                    created_at=now, market_id=m.id, contract_type="CPI_MOM_SA_FIRST",
                    reference_month=ref.isoformat(), threshold=thr,
                    rules_hash=current_rules(s, m.id).hash, status="confirmed",
                    actor="demo-seed",
                    notes_json=json.dumps(["DEMO: synthetic market, auto-confirmed"])))
            s.commit()
            sigs = generate_signals(s, settings, now, schedules=[DEMO_FEES])
            s.commit()
            orders = 0
            for g in sigs:
                if g.decision != "ABSTAIN" and g.entry is not None and orders < 2:
                    limit = (g.entry + D("0.02")).quantize(D("0.01"))
                    submit_order(s, settings, OrderRequest(
                        client_order_id=f"demo-{g.id[:12]}", market_id=g.market_id,
                        side=g.side or "YES", action="BUY", quantity=D(10),
                        limit_price=min(limit, D("0.99")), scenario="conservative",
                        signal_id=g.id, source="manual"), now,
                        schedules=[replace(DEMO_FEES, fee_types=DEMO_FEES.fee_types)])
                    orders += 1
            s.commit()
            return {"path": str(path), "first_prints": len(hist), "markets": len(skews),
                    "signals": len(sigs),
                    "candidates": sum(g.decision != "ABSTAIN" for g in sigs),
                    "paper_orders": orders, "reference_month": ref.isoformat()}
    finally:
        engine.dispose()


class _Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at


__all__ = ["DEMO_DB", "DEMO_FEES", "IngestionSummary", "build_demo", "load_schedules",
           "synthetic_cpi"]
