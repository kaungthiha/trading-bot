"""Local scheduled collector.

- Runs each job when due (interval since its last successful run); sleeps until the next
  job is due -- no busy loop.
- Detects collection gaps (worker stopped, laptop asleep): if a job's last success is
  older than interval * gap_factor, a CollectionGap row is recorded. Nothing is invented
  to fill it; ``backfillable`` states whether the source can recover the period.
- Single instance via an OS file lock.

Run: `python -m app.worker`  (Ctrl+C to stop)
"""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.kalshi_public import KalshiPublicMarketAdapter
from app.core.clock import Clock, SystemClock
from app.core.config import BACKEND_ROOT, MarketDataSource, Settings, get_settings
from app.core.lock import AlreadyRunning, SingleInstanceLock
from app.core.logging import configure_logging
from app.db.models import CollectionGap, IngestionRun
from app.db.session import make_engine, make_session_factory
from app.evidence.ingest import build_evidence_adapter, run_evidence_ingestion
from app.ingest import IngestionSummary, run_ingestion

log = logging.getLogger("worker")

MIN_SLEEP_S = 5.0
MAX_SLEEP_S = 300.0  # wake at least every 5 min so suspend/resume is noticed promptly
FAILURE_RETRY = timedelta(minutes=10)


@dataclass(frozen=True)
class Job:
    name: str  # equals IngestionRun.adapter for this job
    interval: timedelta
    backfillable: bool
    gap_reason: str
    run: Callable[[], IngestionSummary]


class Worker:
    def __init__(
        self,
        jobs: list[Job],
        factory: sessionmaker[Session],
        clock: Clock,
        gap_factor: float = 2.0,
    ) -> None:
        self.jobs = jobs
        self.factory = factory
        self.clock = clock
        self.gap_factor = gap_factor

    def last_success(self, job: Job) -> datetime | None:
        with self.factory() as s:
            return s.scalar(
                select(func.max(IngestionRun.finished_at)).where(
                    IngestionRun.adapter == job.name,
                    IngestionRun.status.in_(("success", "partial")),
                )
            )

    def last_attempt(self, job: Job) -> tuple[datetime, str] | None:
        with self.factory() as s:
            row = s.execute(
                select(IngestionRun.started_at, IngestionRun.status)
                .where(IngestionRun.adapter == job.name)
                .order_by(IngestionRun.started_at.desc())
                .limit(1)
            ).first()
        return (row[0], row[1]) if row else None

    def due_at(self, job: Job, now: datetime) -> datetime:
        """When the job should next run. After a failure, wait FAILURE_RETRY (capped at the
        job interval) instead of retrying every tick -- avoids hammering a broken source."""
        last_ok = self.last_success(job)
        due = (last_ok + job.interval) if last_ok else now
        attempt = self.last_attempt(job)
        if attempt and attempt[1] == "failed":
            due = max(due, attempt[0] + min(FAILURE_RETRY, job.interval))
        return due

    def _record_gap_if_any(self, job: Job, last: datetime | None, now: datetime) -> None:
        if last is None:
            return
        if now - last <= job.interval * self.gap_factor:
            return
        gap_start = last + job.interval  # first collection that should have happened
        with self.factory() as s:
            exists = s.scalar(
                select(CollectionGap.id).where(
                    CollectionGap.job == job.name, CollectionGap.gap_start == gap_start
                )
            )
            if exists:
                return
            s.add(
                CollectionGap(
                    job=job.name,
                    gap_start=gap_start,
                    gap_end=now,
                    detected_at=now,
                    backfillable=job.backfillable,
                    reason=job.gap_reason,
                )
            )
            s.commit()
        log.warning("Collection gap for %s: %s -> %s", job.name, gap_start, now)

    def tick(self) -> list[str]:
        """Run every due job once. Returns names of jobs that ran."""
        ran: list[str] = []
        for job in self.jobs:
            now = self.clock.now()
            last = self.last_success(job)
            self._record_gap_if_any(job, last, now)
            if now >= self.due_at(job, now):
                try:
                    summary = job.run()
                    log.info(
                        "%s: %s stored=%d errors=%d",
                        job.name, summary.status, summary.count, len(summary.errors),
                    )
                except Exception as exc:  # noqa: BLE001 - keep the worker alive
                    log.error("%s crashed: %s", job.name, type(exc).__name__)
                ran.append(job.name)
        return ran

    def seconds_until_next(self) -> float:
        now = self.clock.now()
        waits = [(self.due_at(job, now) - now).total_seconds() for job in self.jobs]
        if not waits:
            return MAX_SLEEP_S
        return max(MIN_SLEEP_S, min(MAX_SLEEP_S, min(waits)))

    def run_forever(self, stop: threading.Event) -> None:
        while not stop.is_set():
            self.tick()
            stop.wait(self.seconds_until_next())


def build_jobs(settings: Settings, factory: sessionmaker[Session], clock: Clock) -> list[Job]:
    jobs: list[Job] = []
    if (
        settings.market_data_source is MarketDataSource.KALSHI_PUBLIC
        and settings.kalshi_series_watchlist
    ):

        def kalshi() -> IngestionSummary:
            adapter = KalshiPublicMarketAdapter.from_settings(settings, clock)
            try:
                return run_ingestion(adapter, factory, clock)
            finally:
                adapter.client.close()

        jobs.append(
            Job(
                name=KalshiPublicMarketAdapter.name,
                interval=timedelta(seconds=settings.worker_kalshi_interval_seconds),
                backfillable=False,
                gap_reason=(
                    "Quote snapshots were not collected (worker stopped or machine asleep). "
                    "Public REST orderbooks are point-in-time; this period cannot be "
                    "reconstructed by this app."
                ),
                run=kalshi,
            )
        )
    if settings.market_data_source is MarketDataSource.KALSHI_PUBLIC:
        from app.adapters.kalshi_public import KalshiPublicClient
        from app.scanner.alerts import desktop_notify
        from app.scanner.service import run_scan

        def scanner() -> IngestionSummary:
            with KalshiPublicClient.from_settings(settings) as client:
                r = run_scan(factory, settings, client, clock,
                             notifier=desktop_notify if settings.alerts_desktop else None)
            return IngestionSummary(r.run_id, "scanner", r.status, len(r.new_cards), [])

        jobs.append(Job(
            name="scanner", interval=timedelta(seconds=settings.scanner_interval_seconds),
            backfillable=False,
            gap_reason="Scans did not run; short-lived mispricings in that window were missed.",
            run=scanner))
    if settings.evidence_sources and settings.fred_api_key is None:
        log.warning("Evidence sources configured but KRT_FRED_API_KEY is not set; skipping")
    else:
        for source_id in settings.evidence_sources:

            def evidence(sid: str = source_id) -> IngestionSummary:
                adapter = build_evidence_adapter(sid, settings, clock)
                try:
                    return run_evidence_ingestion(adapter, factory, clock)
                finally:
                    adapter.client.close()  # type: ignore[attr-defined]

            jobs.append(
                Job(
                    name=source_id,
                    interval=timedelta(seconds=settings.worker_evidence_interval_seconds),
                    backfillable=True,
                    gap_reason=(
                        "Evidence refresh did not run. Vintage history is re-fetched in "
                        "full on the next run, so values are recoverable; only detection "
                        "latency was affected."
                    ),
                    run=evidence,
                )
            )
    return jobs


def main() -> int:
    configure_logging()
    settings = get_settings()
    lock = SingleInstanceLock(BACKEND_ROOT / "data" / "worker.lock")
    try:
        lock.acquire()
    except AlreadyRunning as e:
        log.error("%s", e)
        return 1
    engine = make_engine(settings.database_url)
    clock = SystemClock()
    factory = make_session_factory(engine)
    jobs = build_jobs(settings, factory, clock)
    if not jobs:
        log.error(
            "No jobs configured. Set KRT_FRED_API_KEY and/or KRT_MARKET_DATA_SOURCE="
            "kalshi_public with KRT_KALSHI_SERIES_WATCHLIST in .env."
        )
        lock.release()
        return 1
    log.info("Worker started with jobs: %s", ", ".join(j.name for j in jobs))
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        Worker(jobs, factory, clock, settings.worker_gap_factor).run_forever(stop)
    finally:
        engine.dispose()
        lock.release()
        log.info("Worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
