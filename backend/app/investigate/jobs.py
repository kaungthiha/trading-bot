"""Background research jobs (spec Phase 6): long runs (news search + local model) happen off
the request, and the drawer polls for status.

Rules:
- Only an explicit POST (CSRF header) creates a job. Polling, page loads, opening the drawer
  and new quotes never start one, so nothing searches automatically.
- One worker thread: the local model summarises one result at a time anyway, and queueing
  keeps Brave requests sequential under the app-wide cap.
- The same pick (kind + ticker + side) already queued or running is joined, not repeated,
  so a double click can't spend twice.
- At most MAX_QUEUED jobs wait; more are refused. A queued job can be cancelled; a running
  one can't (a model call can't be interrupted cleanly).
- Jobs live in memory and are forgotten an hour after they finish. Results are saved to the
  database as before, so an app restart loses only the job status, never a finished result.
"""

from __future__ import annotations

import logging
import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.investigate import schemas as S

log = logging.getLogger(__name__)

MAX_QUEUED = 10
KEEP = timedelta(hours=1)
PHASES = ("queued", "starting", "searching", "summarising", "saving")


class QueueFull(RuntimeError):
    pass


@dataclass
class Job:
    id: str
    kind: str
    ticker: str
    side: str
    created_at: datetime
    status: str = "queued"  # queued / running / done / failed / cancelled
    phase: str = "queued"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    result: S.Result | None = None
    work: Callable[[Job], S.Result] | None = field(default=None, repr=False)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.kind, self.ticker, self.side)

    @property
    def active(self) -> bool:
        return self.status in ("queued", "running")


class JobQueue:
    def __init__(self, now: Callable[[], datetime], max_queued: int = MAX_QUEUED) -> None:
        self._now = now
        self._max = max_queued
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []  # queued job ids, oldest first
        self._lock = threading.Lock()
        self._q: queue.Queue[str | None] = queue.Queue()
        self._worker = threading.Thread(target=self._loop, name="research-jobs", daemon=True)
        self._worker.start()

    # --- public -----------------------------------------------------------------------
    def submit(self, kind: str, ticker: str, side: str, work: Callable[[Job], S.Result]) -> Job:
        with self._lock:
            self._prune()
            for j in self._jobs.values():
                if j.active and j.key == (kind, ticker, side):
                    return j  # join the existing job: never run the same pick twice at once
            if len(self._order) >= self._max:
                raise QueueFull(f"{self._max} research jobs are already waiting; try again soon.")
            job = Job(str(uuid.uuid4()), kind, ticker, side, self._now(), work=work)
            self._jobs[job.id] = job
            self._order.append(job.id)
        self._q.put(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            self._prune()
            return self._jobs.get(job_id)

    def active_for(self, ticker: str, side: str) -> Job | None:
        with self._lock:
            return next(
                (
                    j
                    for j in self._jobs.values()
                    if j.active and (j.ticker, j.side) == (ticker, side)
                ),
                None,
            )

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            j = self._jobs.get(job_id)
            if j is None or j.status != "queued":
                return False
            j.status, j.phase, j.finished_at = "cancelled", "cancelled", self._now()
            j.error = "Cancelled before it started."
            if job_id in self._order:
                self._order.remove(job_id)
            return True

    def position(self, job: Job) -> int:
        """Jobs ahead of this one (the running job counts as one)."""
        with self._lock:
            if job.status != "queued" or job.id not in self._order:
                return 0
            running = sum(1 for j in self._jobs.values() if j.status == "running")
            return self._order.index(job.id) + running

    def view(self, job: Job) -> dict[str, Any]:
        return {
            "id": job.id,
            "kind": job.kind,
            "ticker": job.ticker,
            "side": job.side,
            "status": job.status,
            "phase": job.phase,
            "position": self.position(job),
            "created_at": job.created_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "error": job.error,
            "result": job.result.model_dump() if job.status == "done" and job.result else None,
        }

    def shutdown(self) -> None:
        self._q.put(None)
        self._worker.join(timeout=2)

    # --- internals --------------------------------------------------------------------
    def _prune(self) -> None:
        cut = self._now() - KEEP
        for jid in [
            k for k, j in self._jobs.items() if j.finished_at is not None and j.finished_at < cut
        ]:
            del self._jobs[jid]

    def _loop(self) -> None:
        while True:
            jid = self._q.get()
            if jid is None:
                return
            with self._lock:
                job = self._jobs.get(jid)
                if job is None or job.status != "queued":
                    continue  # cancelled or pruned
                self._order.remove(jid)
                job.status, job.phase, job.started_at = "running", "starting", self._now()
            try:
                assert job.work is not None
                result = job.work(job)
            except Exception as e:  # noqa: BLE001 - reported to the user, logged in full
                msg = _message(e)
                if msg is None:
                    log.exception("research job %s failed", jid)
                    msg = "The investigation failed unexpectedly; try again."
                with self._lock:
                    job.status, job.phase, job.error = "failed", "failed", msg
                    job.finished_at, job.work = self._now(), None
                continue
            with self._lock:
                job.status, job.phase, job.result = "done", "done", result
                job.finished_at, job.work = self._now(), None


def _message(e: Exception) -> str | None:
    """User-facing text for expected failures (unsupported market, not found, validation)."""
    from app.api.errors import ApiError
    from app.investigate import service

    if isinstance(e, ApiError):
        return str(getattr(e, "message", None) or e)
    if isinstance(e, service.Unsupported | service.NotFound):
        return str(e)
    return None
