"""Durable ledger of Brave Search network attempts, with ONE atomic cap for the whole app.

- A row is written BEFORE each network attempt (retries included: each is billed). Cache hits
  never reach here, so they're never counted.
- Every Brave caller (research investigations, the "Headlines here" button, the AI reviews'
  headlines, and anything added later) reserves through `Ledger.reserve`, and the daily and
  monthly caps (KRT_RESEARCH_BRAVE_*_REQUEST_CAP) apply to the TOTAL across all of them. The
  purpose tag is kept only so usage can be broken down; it never selects a separate budget.
- Check-and-insert happens inside one SQLite `BEGIN IMMEDIATE` transaction (a write lock across
  processes, e.g. the app and the worker) plus a process lock (threads), so concurrent clicks
  on different features can never overshoot the cap together.
- Only a hash of the query is stored, never the query text or any Brave response.
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

# Purpose tags (breakdown only). Unknown tags are allowed but still count toward the total.
PURPOSES = ("research", "news", "headlines")


class BudgetExhausted(RuntimeError):
    def __init__(self, scope: str, cap: int) -> None:
        super().__init__(f"{scope} Brave request budget ({cap}) is used up")
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

    def usage(self, purpose: str | None = None) -> dict[str, Any]:
        """Totals across every purpose (what the caps apply to), plus a per-purpose breakdown.
        With `purpose`, used_today/used_month are that purpose's own counts (legacy callers)."""
        day, month = _bounds(self.clock.now())
        with self.engine.connect() as c:
            rows = c.execute(
                text(
                    "SELECT purpose, SUM(CASE WHEN at>=:d THEN 1 ELSE 0 END), COUNT(*) "
                    "FROM search_ledger WHERE at>=:m GROUP BY purpose"
                ),
                {"d": day, "m": month},
            ).all()
        by = {str(p): {"today": int(d or 0), "month": int(m)} for p, d, m in rows}
        total_d = sum(v["today"] for v in by.values())
        total_m = sum(v["month"] for v in by.values())
        mine = by.get(purpose or "", {"today": 0, "month": 0}) if purpose else None
        return {
            "used_today": mine["today"] if mine is not None else total_d,
            "used_month": mine["month"] if mine is not None else total_m,
            "total_today": total_d,
            "total_month": total_m,
            "by_purpose": {p: by.get(p, {"today": 0, "month": 0}) for p in PURPOSES}
            | {p: v for p, v in by.items() if p not in PURPOSES},
        }

    def reserve(self, purpose: str, query: str) -> None:
        """Record one network attempt against the app-wide caps, or raise BudgetExhausted
        (nothing is sent then)."""
        now = self.clock.now().astimezone(UTC)
        day, month = _bounds(now)
        qh = hashlib.sha256(query.encode("utf-8")).hexdigest()  # never store the raw query
        with _LOCK, self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                # All purposes together: no caller has a budget of its own.
                d = c.execute(
                    text("SELECT COUNT(*) FROM search_ledger WHERE at>=:d"), {"d": day}
                ).scalar_one()
                if self.daily_cap is not None and d >= self.daily_cap:
                    raise BudgetExhausted("Today's", self.daily_cap)
                m = c.execute(
                    text("SELECT COUNT(*) FROM search_ledger WHERE at>=:m"), {"m": month}
                ).scalar_one()
                if self.monthly_cap is not None and m >= self.monthly_cap:
                    raise BudgetExhausted("This month's", self.monthly_cap)
                c.execute(
                    text(
                        "INSERT INTO search_ledger (at, purpose, query_hash) VALUES (:at, :p, :q)"
                    ),
                    {"at": now.isoformat(), "p": purpose[:16], "q": qh},
                )
                c.exec_driver_sql("COMMIT")
            except BaseException:
                c.exec_driver_sql("ROLLBACK")
                raise

    def attempt_hook(self, purpose: str, query_fn: Any) -> Any:
        """A NewsSearch on_attempt callback that reserves before each network attempt."""
        return lambda: self.reserve(purpose, query_fn())


def record_hook(app_state: Any, purpose: str, query: str | None = None) -> Any:
    """on_attempt callback for Brave uses outside research. Held to the same app-wide caps:
    raises BudgetExhausted before anything is sent once they're reached."""
    return lambda: ledger_for(app_state).reserve(purpose, query or purpose)


def ledger_for(app_state: Any) -> Ledger:
    s = app_state.settings
    return Ledger(
        app_state.engine,
        app_state.clock,
        s.research_brave_daily_request_cap,
        s.research_brave_monthly_request_cap,
    )
