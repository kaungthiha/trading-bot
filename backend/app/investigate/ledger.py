"""Durable ledger of Brave Search network attempts, with atomic cap enforcement.

- A row is written BEFORE each network attempt (retries included: each is billed). Cache hits
  never reach here, so they're never counted.
- Research searches are capped daily and monthly (KRT_RESEARCH_BRAVE_*_REQUEST_CAP). Other
  Brave uses in the app (AI-review headlines, the news route) are recorded with their own
  purpose so the totals are visible, but aren't held to the research caps.
- Check-and-insert happens inside one SQLite `BEGIN IMMEDIATE` transaction (a write lock across
  processes, e.g. the app and the worker) plus a process lock (threads), so concurrent clicks
  can never overshoot a cap.
- These counts are this app's own. They are NOT Brave's balance or bill, which the API
  doesn't expose; check the Brave dashboard for those.
"""

from __future__ import annotations

import hashlib
import threading
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

_LOCK = threading.Lock()


class BudgetExhausted(RuntimeError):
    def __init__(self, scope: str, cap: int) -> None:
        super().__init__(f"{scope} search budget ({cap}) is used up")
        self.scope, self.cap = scope, cap


def _bounds(now: datetime) -> tuple[str, str]:
    n = now.astimezone(UTC)
    day = n.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    return day.isoformat(), month.isoformat()


class Ledger:
    def __init__(self, engine: Engine, clock: Any, daily_cap: int | None, monthly_cap: int | None):
        self.engine, self.clock = engine, clock
        self.daily_cap, self.monthly_cap = daily_cap, monthly_cap

    def usage(self, purpose: str = "research") -> dict[str, int]:
        day, month = _bounds(self.clock.now())
        with self.engine.connect() as c:
            d = c.execute(
                text("SELECT COUNT(*) FROM search_ledger WHERE purpose=:p AND at>=:d"),
                {"p": purpose, "d": day},
            ).scalar_one()
            m = c.execute(
                text("SELECT COUNT(*) FROM search_ledger WHERE purpose=:p AND at>=:m"),
                {"p": purpose, "m": month},
            ).scalar_one()
        return {"used_today": int(d), "used_month": int(m)}

    def reserve(self, purpose: str, query: str, capped: bool = True) -> None:
        """Record one network attempt, or raise BudgetExhausted (nothing is sent then)."""
        now = self.clock.now().astimezone(UTC)
        day, month = _bounds(now)
        qh = hashlib.sha256(query.encode("utf-8")).hexdigest()  # never store the raw query
        with _LOCK, self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                if capped:
                    d = c.execute(
                        text("SELECT COUNT(*) FROM search_ledger WHERE purpose=:p AND at>=:d"),
                        {"p": purpose, "d": day},
                    ).scalar_one()
                    if self.daily_cap is not None and d >= self.daily_cap:
                        raise BudgetExhausted("Today's", self.daily_cap)
                    m = c.execute(
                        text("SELECT COUNT(*) FROM search_ledger WHERE purpose=:p AND at>=:m"),
                        {"p": purpose, "m": month},
                    ).scalar_one()
                    if self.monthly_cap is not None and m >= self.monthly_cap:
                        raise BudgetExhausted("This month's", self.monthly_cap)
                c.execute(
                    text(
                        "INSERT INTO search_ledger (at, purpose, query_hash) VALUES (:at, :p, :q)"
                    ),
                    {"at": now.isoformat(), "p": purpose, "q": qh},
                )
                c.exec_driver_sql("COMMIT")
            except BaseException:
                c.exec_driver_sql("ROLLBACK")
                raise

    def attempt_hook(self, purpose: str, query_fn: Any, capped: bool = True) -> Any:
        """A NewsSearch on_attempt callback that reserves before each network attempt."""
        return lambda: self.reserve(purpose, query_fn(), capped)


def record_hook(app_state: Any, purpose: str) -> Any:
    """on_attempt callback for Brave uses outside research: recorded, not capped."""
    return lambda: ledger_for(app_state).reserve(purpose, purpose, capped=False)


def ledger_for(app_state: Any) -> Ledger:
    s = app_state.settings
    return Ledger(
        app_state.engine,
        app_state.clock,
        s.research_brave_daily_request_cap,
        s.research_brave_monthly_request_cap,
    )
