from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.lock import AlreadyRunning, SingleInstanceLock
from app.db.models import CollectionGap, IngestionRun
from app.db.session import make_engine, make_session_factory
from app.ingest import IngestionSummary
from app.worker import FAILURE_RETRY, MAX_SLEEP_S, MIN_SLEEP_S, Job, Worker, build_jobs

T0 = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


class MutableClock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at


@pytest.fixture
def factory(settings: Settings):  # type: ignore[no-untyped-def]
    engine = make_engine(settings.database_url)
    yield make_session_factory(engine)
    engine.dispose()


def fake_job(name: str, factory, clock, status: str = "success", interval_min: int = 15,  # type: ignore[no-untyped-def]
             backfillable: bool = False) -> tuple[Job, list[datetime]]:
    runs: list[datetime] = []

    def run() -> IngestionSummary:
        runs.append(clock.now())
        with factory() as s:
            r = IngestionRun(adapter=name, started_at=clock.now(), finished_at=clock.now(),
                             status=status, count=1, errors_json=json.dumps([]))
            s.add(r)
            s.commit()
            return IngestionSummary(r.id, name, status, 1, [])

    return Job(name, timedelta(minutes=interval_min), backfillable, "test gap", run), runs


def test_runs_when_due_and_sleeps_until_next(factory) -> None:  # type: ignore[no-untyped-def]
    clock = MutableClock(T0)
    job, runs = fake_job("j", factory, clock)
    w = Worker([job], factory, clock)
    assert w.tick() == ["j"]  # never run -> due immediately
    assert w.tick() == []  # just ran
    assert w.seconds_until_next() == MAX_SLEEP_S  # 15 min away, capped at 5 min
    clock.at = T0 + timedelta(minutes=14, seconds=58)
    assert w.seconds_until_next() == MIN_SLEEP_S  # never busy-loops below the floor
    clock.at = T0 + timedelta(minutes=15)
    assert w.tick() == ["j"]
    assert len(runs) == 2


def test_gap_recorded_once_after_sleep(factory) -> None:  # type: ignore[no-untyped-def]
    clock = MutableClock(T0)
    job, _ = fake_job("kalshi_public", factory, clock, backfillable=False)
    w = Worker([job], factory, clock, gap_factor=2.0)
    w.tick()
    clock.at = T0 + timedelta(minutes=29)  # within 2x interval: no gap
    w.tick()
    with factory() as s:
        assert s.scalars(select(CollectionGap)).all() == []

    clock.at = T0 + timedelta(minutes=15, hours=3)  # laptop slept ~3h
    with factory() as s:
        last = s.scalar(select(IngestionRun.finished_at).order_by(IngestionRun.finished_at.desc()))
    w2 = Worker([job], factory, clock, gap_factor=2.0)
    w2._record_gap_if_any(job, last, clock.now())
    w2._record_gap_if_any(job, last, clock.now())  # idempotent
    with factory() as s:
        gaps = s.scalars(select(CollectionGap)).all()
    assert len(gaps) == 1
    g = gaps[0]
    assert g.job == "kalshi_public" and g.backfillable is False
    assert g.gap_start == last + timedelta(minutes=15) and g.gap_end == clock.now()


def test_failed_job_waits_before_retry(factory) -> None:  # type: ignore[no-untyped-def]
    clock = MutableClock(T0)
    job, runs = fake_job("bad", factory, clock, status="failed", interval_min=60)
    w = Worker([job], factory, clock)
    w.tick()
    clock.at = T0 + timedelta(minutes=1)
    w.tick()
    assert len(runs) == 1  # not hammering a failing source
    clock.at = T0 + FAILURE_RETRY
    w.tick()
    assert len(runs) == 2


def test_crashing_job_does_not_kill_worker(factory) -> None:  # type: ignore[no-untyped-def]
    clock = MutableClock(T0)

    def boom() -> IngestionSummary:
        raise RuntimeError("x")

    ok, runs = fake_job("ok", factory, clock)
    w = Worker([Job("boom", timedelta(minutes=5), True, "r", boom), ok], factory, clock)
    assert w.tick() == ["boom", "ok"]
    assert len(runs) == 1


def test_single_instance_lock(tmp_path: Path) -> None:
    path = tmp_path / "worker.lock"
    with SingleInstanceLock(path):
        with pytest.raises(AlreadyRunning):
            SingleInstanceLock(path).acquire()
    with SingleInstanceLock(path):  # released -> can reacquire
        pass


def test_build_jobs_respects_config(factory, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    clock = MutableClock(T0)
    assert build_jobs(settings, factory, clock) == []  # no FRED key, fixture source
    s2 = Settings(_env_file=None, database_url=settings.database_url,
                  fred_api_key="x" * 32, market_data_source="kalshi_public",
                  kalshi_series_watchlist=["KXFED"])
    names = [j.name for j in build_jobs(s2, factory, clock)]
    assert names == ["kalshi_public", "scanner", "fred:CPIAUCSL"]
