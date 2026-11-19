"""Scan -> confirm -> persist thesis cards; budget rules; journal; scorecard.

Suggestions only. The user executes trades on Kalshi themselves and records them in the
journal; settlement uses FINALIZED exchange results only.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.base import AdapterError
from app.adapters.kalshi_public import KalshiPublicClient
from app.catalog.combos import refresh_combo_eligibility
from app.catalog.store import CatalogWriter, refresh_series
from app.core.clock import Clock
from app.core.config import Settings
from app.db.models import AuditEvent, IngestionRun, JournalEntry
from app.db.models import Opportunity as OpportunityRow
from app.history.positions import safe_record_marks
from app.scanner.detectors import (
    Opportunity,
    SizingRules,
    coverage,
    near_misses,
    scan_events,
)
from app.scanner.detectors_resize import resize
from app.scanner.kalshi_scan import confirm_legs, fetch_open_events
from app.signals.fees import FeeSchedule, load_schedules, select_schedule

log = logging.getLogger("scanner")
DEDUPE_WINDOW = timedelta(minutes=30)
DRAWDOWN_PAUSE = Decimal("0.30")  # pause new cards after losing 30% of the budget


# --- Budget ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetState:
    budget: Decimal | None
    open_cost: Decimal
    realized_pnl: Decimal
    available: Decimal | None
    paused: bool
    guaranteed_cap: Decimal
    conditional_cap: Decimal
    note: str | None


def _entries(s: Session) -> list[JournalEntry]:
    return list(s.scalars(select(JournalEntry).order_by(JournalEntry.at)).all())


def budget_state(s: Session, settings: Settings) -> BudgetState:
    entries = _entries(s)
    settled = {e.opportunity_id: e for e in entries if e.action == "SETTLED"}
    executed = [e for e in entries if e.action == "EXECUTED"]
    open_cost = sum((e.cost or Decimal(0) for e in executed
                     if e.opportunity_id not in settled), Decimal(0))
    realized = sum(((settled[e.opportunity_id].payoff or Decimal(0)) - (e.cost or Decimal(0))
                    for e in executed if e.opportunity_id in settled), Decimal(0))
    b = settings.experiment_budget_dollars
    if b is None:
        cap = settings.scanner_unset_budget_cap
        return BudgetState(None, open_cost, realized, None, False, cap,
                           min(cap, settings.scanner_unset_budget_cap * Decimal("0.25")),
                           "Budget not set (KRT_EXPERIMENT_BUDGET_DOLLARS); using a small cap")
    available = b + realized - open_cost
    paused = realized <= -(b * DRAWDOWN_PAUSE)
    g = max(Decimal(0), min(b * settings.scanner_guaranteed_fraction, available))
    c = max(Decimal(0), min(b * settings.scanner_conditional_fraction, available))
    note = None
    if paused:
        note = f"Paused: realized loss reached {int(DRAWDOWN_PAUSE * 100)}% of the budget"
    elif available <= 0:
        note = "Budget fully committed to open trades"
    return BudgetState(b, open_cost, realized, available, paused, g, c, note)


# --- Scan -----------------------------------------------------------------------------------


def fingerprint(o: Opportunity) -> str:
    parts = [o.kind] + sorted(f"{lg.ticker}:{lg.side}:{lg.limit_price}" for lg in o.legs)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


@dataclass
class ScanResult:
    run_id: str
    status: str
    events: int = 0
    markets: int = 0
    candidates: int = 0
    confirmed: int = 0
    new_cards: list[str] = field(default_factory=list)
    budget_note: str | None = None
    error: str | None = None
    coverage: dict = field(default_factory=dict)
    near_misses: list[dict] = field(default_factory=list)


Notifier = Callable[[str, str], None]


def _rules(cap: Decimal, settings: Settings) -> SizingRules:
    return SizingRules(max_cost=cap, min_profit=settings.scanner_min_profit_dollars,
                       min_return=settings.scanner_min_return, max_legs=settings.scanner_max_legs)


def run_scan(factory: sessionmaker[Session], settings: Settings, client: KalshiPublicClient,
             clock: Clock, schedules: list[FeeSchedule] | None = None,
             notifier: Notifier | None = None) -> ScanResult:
    now = clock.now()
    with factory() as s:
        run = IngestionRun(adapter="scanner", started_at=now, status="running")
        s.add(run)
        s.commit()
        result = ScanResult(run.id, "running")
        budget = budget_state(s, settings)
    result.budget_note = budget.note
    schedules = schedules if schedules is not None else load_schedules()
    schedule = select_schedule(schedules, "quadratic_with_maker_fees")
    errors: list[dict] = []
    try:
        if schedule is None or not schedule.verified:
            raise AdapterError("No verified fee schedule; refusing to size trades")
        catalog = CatalogWriter(factory, now)
        events, truncated = fetch_open_events(client, on_page=catalog.write_page)
        catalog.finish(complete=not truncated)
        safe_record_marks(factory, now, "scan")  # price trail for your open positions
        try:
            refresh_series(factory, client, now)
        except AdapterError as e:  # titles/fee multipliers are a nice-to-have
            log.warning("series refresh failed: %s", e)
        try:
            refresh_combo_eligibility(factory, client, now)
        except AdapterError as e:  # combo eligibility is a nice-to-have too
            log.warning("combo eligibility refresh failed: %s", e)
        if truncated:
            errors.append({"scope": "scanner", "code": "TRUNCATED",
                           "message": "Page limit reached; some open events were not scanned"})
        result.events = len(events)
        result.markets = sum(len(e.markets) for e in events)
        result.coverage = coverage(events)
        result.near_misses = [{k: str(v) if isinstance(v, Decimal) else v
                               for k, v in asdict(nm).items()} for nm in near_misses(events)]
        if budget.paused or (budget.available is not None and budget.available <= 0):
            found: list[Opportunity] = []
        else:
            g_rules = _rules(budget.guaranteed_cap, settings)
            c_rules = _rules(budget.conditional_cap, settings)
            found = [o for o in scan_events(events, schedule, g_rules) if o.guaranteed]
            found += [o for o in scan_events(events, schedule, c_rules) if not o.guaranteed]
        result.candidates = len(found)
        confirmed: list[Opportunity] = []
        for o in found[: settings.scanner_confirm_top]:
            try:
                fresh = confirm_legs(client, o)
            except AdapterError as e:
                errors.append({"scope": o.event_ticker, "code": e.code, "message": str(e)})
                continue
            rules = _rules(budget.guaranteed_cap if o.guaranteed else budget.conditional_cap,
                           settings)
            again = resize(o, fresh, schedule, rules) if fresh else None
            if again is not None:
                confirmed.append(again)
        result.confirmed = len(confirmed)
        with factory() as s:
            for o in confirmed:
                fp = fingerprint(o)
                seen = s.scalar(select(OpportunityRow.id).where(
                    OpportunityRow.fingerprint == fp,
                    OpportunityRow.detected_at >= now - DEDUPE_WINDOW))
                if seen:
                    continue
                row = OpportunityRow(
                    detected_at=now,
                    expires_at=now + timedelta(seconds=settings.scanner_card_ttl_seconds),
                    kind=o.kind, guaranteed=o.guaranteed, confirmed=True,
                    event_ticker=o.event_ticker, title=o.title,
                    legs_json=json.dumps([{k: str(v) if isinstance(v, Decimal) else v
                                           for k, v in asdict(lg).items()} for lg in o.legs]),
                    quantity=o.quantity, cost=o.cost, fees=o.fees, min_payoff=o.min_payoff,
                    profit=o.profit, return_pct=o.return_pct, claim=o.claim,
                    checklist_json=json.dumps(o.checklist),
                    budget_cap=budget.guaranteed_cap if o.guaranteed else budget.conditional_cap,
                    fee_schedule_version=schedule.version, fingerprint=fp)
                s.add(row)
                s.flush()
                result.new_cards.append(row.id)
            s.add(AuditEvent(at=now, actor="scanner", action="SCAN_COMPLETED",
                             object_type="scan", object_id=result.run_id,
                             metadata_json=json.dumps({
                                 "events": result.events, "markets": result.markets,
                                 "candidates": result.candidates,
                                 "confirmed": result.confirmed,
                                 "new_cards": len(result.new_cards),
                                 "budget_note": budget.note,
                                 "coverage": result.coverage,
                                 "near_misses": result.near_misses})))
            s.commit()
        result.status = "success" if not errors else "partial"
    except AdapterError as e:
        result.status, result.error = "failed", str(e)
        errors.append({"scope": "scanner", "code": e.code, "message": str(e)})
    with factory() as s:
        run = s.get(IngestionRun, result.run_id)
        run.finished_at = clock.now()
        run.status = result.status
        run.count = len(result.new_cards)
        run.errors_json = json.dumps(errors)
        s.commit()
    if notifier and result.new_cards:
        try:
            notifier("Kalshi scanner", f"{len(result.new_cards)} new idea(s) to review")
        except Exception:  # noqa: BLE001 - alerts are best-effort
            log.warning("desktop alert failed")
    return result


# --- Journal & scorecard ---------------------------------------------------------------------


class JournalError(ValueError):
    pass


def record_journal(s: Session, opportunity_id: str, action: str, now: datetime,
                   legs: list[dict[str, Any]] | None = None, note: str = "") -> JournalEntry:
    opp = s.get(OpportunityRow, opportunity_id)
    if opp is None:
        raise JournalError("Unknown opportunity")
    if action not in ("EXECUTED", "SKIPPED", "NOTE"):
        raise JournalError("action must be EXECUTED, SKIPPED or NOTE")
    prior = {e.action for e in s.scalars(select(JournalEntry).where(
        JournalEntry.opportunity_id == opportunity_id)).all()}
    if action in ("EXECUTED", "SKIPPED") and prior & {"EXECUTED", "SKIPPED"}:
        raise JournalError("This card already has a decision recorded")
    cost = None
    if action == "EXECUTED":
        if not legs:
            raise JournalError("Record the legs you actually filled")
        cost = Decimal(0)
        clean = []
        for lg in legs:
            qty, px = Decimal(str(lg["quantity"])), Decimal(str(lg["avg_price"]))
            fee = Decimal(str(lg.get("fee") or "0"))
            if qty <= 0 or not (Decimal(0) < px < Decimal(1)) or fee < 0:
                raise JournalError("Invalid leg (quantity > 0, 0 < price < 1, fee >= 0)")
            if lg.get("side") not in ("YES", "NO") or not lg.get("ticker"):
                raise JournalError("Each leg needs ticker and side YES/NO")
            cost += qty * px + fee
            clean.append({"ticker": lg["ticker"], "side": lg["side"], "quantity": str(qty),
                          "avg_price": str(px), "fee": str(fee)})
        legs = clean
    e = JournalEntry(at=now, opportunity_id=opportunity_id, action=action,
                     legs_json=json.dumps(legs or []), cost=cost, note=note[:500])
    s.add(e)
    s.flush()
    return e


def settle_journal(s: Session, results: dict[str, str], now: datetime) -> list[JournalEntry]:
    """``results``: ticker -> 'yes'|'no' for FINALIZED markets only. Settles executed cards
    whose every leg has a final result."""
    out = []
    entries = _entries(s)
    settled = {e.opportunity_id for e in entries if e.action == "SETTLED"}
    for e in entries:
        if e.action != "EXECUTED" or e.opportunity_id in settled:
            continue
        legs = json.loads(e.legs_json)
        if not all(lg["ticker"] in results for lg in legs):
            continue
        payoff = sum((Decimal(lg["quantity"]) for lg in legs
                      if (results[lg["ticker"]] == "yes") == (lg["side"] == "YES")), Decimal(0))
        row = JournalEntry(at=now, opportunity_id=e.opportunity_id, action="SETTLED",
                           payoff=payoff, legs_json="[]",
                           note="Settled on finalized Kalshi results")
        s.add(row)
        out.append(row)
    s.flush()
    return out


def scorecard(s: Session, settings: Settings) -> dict[str, Any]:
    entries = _entries(s)
    executed = {e.opportunity_id: e for e in entries if e.action == "EXECUTED"}
    settled = {e.opportunity_id: e for e in entries if e.action == "SETTLED"}
    rows = []
    for oid, ex in executed.items():
        opp = s.get(OpportunityRow, oid)
        st = settled.get(oid)
        rows.append({"opportunity_id": oid, "kind": opp.kind, "guaranteed": opp.guaranteed,
                     "title": opp.title, "cost": str(ex.cost),
                     "expected_min_payoff": str(opp.min_payoff),
                     "payoff": None if st is None else str(st.payoff),
                     "pnl": None if st is None else str((st.payoff or 0) - (ex.cost or 0))})
    b = budget_state(s, settings)

    def total(kind_guaranteed: bool | None) -> dict[str, Any]:
        sel = [r for r in rows if kind_guaranteed is None or r["guaranteed"] == kind_guaranteed]
        done = [r for r in sel if r["pnl"] is not None]
        return {"executed": len(sel), "settled": len(done),
                "pnl": str(sum((Decimal(r["pnl"]) for r in done), Decimal(0))),
                "wins": sum(Decimal(r["pnl"]) > 0 for r in done)}

    return {
        "budget": None if b.budget is None else str(b.budget),
        "available": None if b.available is None else str(b.available),
        "open_cost": str(b.open_cost), "realized_pnl": str(b.realized_pnl),
        "paused": b.paused, "note": b.note,
        "caps": {"guaranteed": str(b.guaranteed_cap), "conditional": str(b.conditional_cap)},
        "all": total(None), "guaranteed": total(True), "conditional": total(False),
        "skipped": sum(1 for e in entries if e.action == "SKIPPED"),
        "rows": rows,
    }
