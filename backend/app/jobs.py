"""In-app background jobs behind the UI buttons: refresh data, refresh FRED, scan, and an
auto-scan timer. One run per job at a time; state is kept in memory for the UI to poll.

Uses the same functions as the CLI/worker. If the separate worker process is running, the
auto-scan timer refuses to start (to avoid double-scanning); manual runs remain allowed.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.base import AdapterError
from app.adapters.kalshi_public import KalshiPublicClient, KalshiPublicMarketAdapter
from app.catalog.combos import run_combo_study
from app.core.clock import Clock
from app.core.config import BACKEND_ROOT, Settings
from app.core.lock import AlreadyRunning, SingleInstanceLock
from app.evidence.ingest import build_evidence_adapter, run_evidence_ingestion
from app.history.client import AccountError, AccountReader
from app.history.sync import sync_account
from app.ingest import run_ingestion
from app.research.service import evaluate_and_save
from app.scanner.service import run_scan
from app.signals.mapping import propose_all
from app.signals.service import generate_signals

log = logging.getLogger("jobs")
JOB_NAMES = ("refresh", "evidence", "scan", "history", "combos")
DEFAULT_WATCHLIST = ["KXCPI"]


@dataclass
class JobState:
    name: str
    running: bool = False
    last_started: datetime | None = None
    last_finished: datetime | None = None
    last_status: str | None = None  # success | partial | failed
    last_message: str | None = None


class JobRunner:
    def __init__(self, settings: Settings, factory: sessionmaker[Session], clock: Clock, *,
                 synchronous: bool = False,
                 client_factory: Callable[[], KalshiPublicClient] | None = None,
                 evidence_factory: Callable | None = None,
                 account_factory: Callable[[], AccountReader] | None = None,
                 worker_lock_path=BACKEND_ROOT / "data" / "worker.lock") -> None:  # type: ignore[no-untyped-def]
        self.settings, self.factory, self.clock = settings, factory, clock
        self.synchronous = synchronous
        self.client_factory = client_factory or (lambda: KalshiPublicClient.from_settings(settings))
        self.evidence_factory = evidence_factory or build_evidence_adapter
        self.account_factory = account_factory or (lambda: AccountReader.from_settings(settings))
        self.worker_lock_path = worker_lock_path
        self.state = {n: JobState(n) for n in JOB_NAMES}
        self._locks = {n: threading.Lock() for n in JOB_NAMES}
        self._auto = threading.Event()
        self._stop = threading.Event()
        self._auto_thread: threading.Thread | None = None
        self.next_auto_scan: datetime | None = None

    # --- status ------------------------------------------------------------------------
    def worker_running(self) -> bool:
        lock = SingleInstanceLock(self.worker_lock_path)
        try:
            lock.acquire()
        except AlreadyRunning:
            return True
        lock.release()
        return False

    def snapshot(self) -> dict:
        return {
            "jobs": {n: {k: (v.isoformat() if isinstance(v, datetime) else v)
                         for k, v in asdict(s).items()} for n, s in self.state.items()},
            "auto_scan": {"enabled": self._auto.is_set(),
                          "interval_seconds": self.settings.scanner_interval_seconds,
                          "next_run_at": self.next_auto_scan.isoformat()
                          if self.next_auto_scan and self._auto.is_set() else None},
            "worker_running": self.worker_running(),
            "watchlist": self.settings.kalshi_series_watchlist or DEFAULT_WATCHLIST,
        }

    # --- running -----------------------------------------------------------------------
    def run(self, name: str) -> bool:
        """Start a job. Returns False if it is already running."""
        if name not in JOB_NAMES:
            raise ValueError(f"Unknown job {name!r}")
        if not self._locks[name].acquire(blocking=False):
            return False
        st = self.state[name]
        st.running, st.last_started = True, self.clock.now()
        if self.synchronous:
            self._execute(name)
        else:
            threading.Thread(target=self._execute, args=(name,), daemon=True,
                             name=f"job-{name}").start()
        return True

    def _execute(self, name: str) -> None:
        st = self.state[name]
        try:
            status, message = getattr(self, f"_job_{name}")()
        except Exception as e:  # noqa: BLE001 - surface to the UI, keep the app alive
            log.exception("job %s crashed", name)
            status, message = "failed", f"{type(e).__name__}: {e}"[:300]
        st.last_status, st.last_message = status, message
        st.last_finished, st.running = self.clock.now(), False
        self._locks[name].release()

    def _job_refresh(self) -> tuple[str, str]:
        watch = self.settings.kalshi_series_watchlist or DEFAULT_WATCHLIST
        client = self.client_factory()
        try:
            adapter = KalshiPublicMarketAdapter(
                client, self.clock, series_watchlist=watch,
                status=self.settings.kalshi_market_status,
                page_limit=self.settings.kalshi_page_limit,
                max_pages=self.settings.kalshi_max_pages,
                orderbook_depth=self.settings.kalshi_orderbook_depth)
            summary = run_ingestion(adapter, self.factory, self.clock)
        finally:
            client.close()
        with self.factory() as s:
            proposals = propose_all(s, self.clock.now())
            signals = generate_signals(s, self.settings, self.clock.now())
            s.commit()
        cands = sum(g.decision != "ABSTAIN" for g in signals)
        return summary.status, (f"{summary.count} markets from {', '.join(watch)}; "
                                f"{len(proposals)} new mapping proposal(s); {len(signals)} "
                                f"signal(s), {cands} candidate(s)")

    def _job_evidence(self) -> tuple[str, str]:
        if self.settings.fred_api_key is None:
            return "failed", "KRT_FRED_API_KEY is not set in .env"
        new, statuses = 0, []
        for sid in self.settings.evidence_sources:
            adapter = self.evidence_factory(sid, self.settings, self.clock)
            try:
                r = run_evidence_ingestion(adapter, self.factory, self.clock)
            finally:
                client = getattr(adapter, "client", None)
                if client is not None:
                    client.close()
            new += r.count
            statuses.append(r.status)
        if new:
            with self.factory() as s:
                evaluate_and_save(s, self.clock.now())
                s.commit()
        status = "failed" if "failed" in statuses else ("partial" if "partial" in statuses
                                                        else "success")
        return status, f"{new} new vintage record(s)" + ("; models re-evaluated" if new else "")

    def _job_history(self) -> tuple[str, str]:
        """Sync YOUR account history (read-only key)."""
        try:
            reader = self.account_factory()
        except AccountError as e:
            return "failed", str(e)
        try:
            r = sync_account(self.factory, reader, self.clock.now())
        finally:
            reader.close()
        if r.status == "success":
            # Legs inside your combos (public data): best effort, never fails the sync.
            from app.history.combo_legs import refresh_combo_legs

            client = self.client_factory()
            try:
                refresh_combo_legs(self.factory, client, self.clock.now())
            except Exception as e:  # noqa: BLE001
                log.warning("combo legs refresh failed: %s", e)
            finally:
                client.close()
        return r.status, r.message

    def _job_combos(self) -> tuple[str, str]:
        """Refresh the settled-combo study (public data)."""
        client = self.client_factory()
        try:
            st = run_combo_study(self.factory, client, self.clock.now())
        except AdapterError as e:
            return "failed", str(e)
        finally:
            client.close()
        o = st["overall"]
        if not o:
            return "partial", "No settled, traded combos found"
        return "success", (f"{o['n']} settled combos: hit {o['hit_rate'] * 100:.1f}% at "
                           f"{o['avg_price'] * 100:.1f}c average; ${o['return_per_dollar']:.2f} "
                           "back per $1")

    def _job_scan(self) -> tuple[str, str]:
        client = self.client_factory()
        try:
            r = run_scan(self.factory, self.settings, client, self.clock)
        except AdapterError as e:
            return "failed", str(e)
        finally:
            client.close()
        msg = (f"{r.events} events / {r.markets} markets; {r.candidates} candidate(s), "
               f"{r.confirmed} confirmed, {len(r.new_cards)} new card(s)")
        if r.budget_note:
            msg += f"; {r.budget_note}"
        return r.status, msg

    # --- auto-scan -----------------------------------------------------------------------
    def set_auto_scan(self, enabled: bool) -> tuple[bool, str | None]:
        if enabled and self.worker_running():
            return False, "The background worker is already scanning; stop it to use auto-scan"
        if enabled:
            self._auto.set()
            self.next_auto_scan = self.clock.now()
            if self._auto_thread is None or not self._auto_thread.is_alive():
                self._auto_thread = threading.Thread(target=self._auto_loop, daemon=True,
                                                     name="auto-scan")
                self._auto_thread.start()
        else:
            self._auto.clear()
        return True, None

    def _auto_loop(self) -> None:
        interval = self.settings.scanner_interval_seconds
        while not self._stop.is_set() and self._auto.is_set():
            self.run("scan")
            self.next_auto_scan = self.clock.now() + timedelta(seconds=interval)
            if self._stop.wait(interval):
                break

    def shutdown(self) -> None:
        self._stop.set()
        self._auto.clear()
