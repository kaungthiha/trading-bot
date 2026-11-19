"""Thesis cards, journal and scorecard. Suggestions only -- nothing here trades.

The only write is the journal (what YOU did with a card); it requires the
X-KRT-Request: journal header (CSRF) on top of the Origin allow-list.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Header, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import ApiError, ErrorCode
from app.api.routes import ClockDep, SessionDep, SettingsDep
from app.db.models import AuditEvent, JournalEntry, Opportunity
from app.scanner.service import JournalError, budget_state, record_journal, scorecard

router = APIRouter(prefix="/api")
IdPath = Annotated[str, Path(min_length=1, max_length=36)]


class LegIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=128)
    side: str = Field(pattern=r"^(YES|NO)$")
    quantity: int = Field(ge=1, le=100_000)
    avg_price: str = Field(pattern=r"^0\.\d{1,4}$")
    fee: str = Field(default="0", pattern=r"^\d{1,4}(\.\d{1,6})?$")


class JournalIn(BaseModel):
    action: str = Field(pattern=r"^(EXECUTED|SKIPPED|NOTE)$")
    legs: list[LegIn] = Field(default_factory=list, max_length=40)
    note: str = Field(default="", max_length=500)


def _card(s, o: Opportunity, now) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    journal = s.scalars(select(JournalEntry).where(JournalEntry.opportunity_id == o.id)
                        .order_by(JournalEntry.at)).all()
    decided = next((j.action for j in journal if j.action in ("EXECUTED", "SKIPPED")), None)
    status = decided or ("EXPIRED" if now > o.expires_at else "OPEN")
    return {
        "id": o.id, "detected_at": o.detected_at.isoformat(),
        "expires_at": o.expires_at.isoformat(),
        "status": status, "kind": o.kind, "guaranteed": o.guaranteed, "confirmed": o.confirmed,
        "event_ticker": o.event_ticker, "title": o.title, "legs": json.loads(o.legs_json),
        "quantity": str(o.quantity), "cost": str(o.cost), "fees": str(o.fees),
        "min_payoff": str(o.min_payoff), "profit": str(o.profit),
        "return_pct": str(o.return_pct), "claim": o.claim,
        "checklist": json.loads(o.checklist_json),
        "budget_cap": None if o.budget_cap is None else str(o.budget_cap),
        "fee_schedule_version": o.fee_schedule_version,
        "journal": [{"at": j.at.isoformat(), "action": j.action, "note": j.note,
                     "cost": None if j.cost is None else str(j.cost),
                     "payoff": None if j.payoff is None else str(j.payoff)} for j in journal],
    }


@router.get("/opportunities")
def list_opportunities(session: SessionDep, clock: ClockDep,
                       limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[dict[str, Any]]:
    now = clock.now()
    rows = session.scalars(select(Opportunity).order_by(Opportunity.detected_at.desc())
                           .limit(limit)).all()
    return [_card(session, o, now) for o in rows]


@router.get("/scanner/status")
def scanner_status(session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    last = session.scalar(select(AuditEvent).where(AuditEvent.action == "SCAN_COMPLETED")
                          .order_by(AuditEvent.at.desc()).limit(1))
    b = budget_state(session, settings)
    return {
        "interval_seconds": settings.scanner_interval_seconds,
        "last_scan": None if last is None else {"at": last.at.isoformat(),
                                                **json.loads(last.metadata_json)},
        "budget": None if b.budget is None else str(b.budget),
        "available": None if b.available is None else str(b.available),
        "caps": {"guaranteed": str(b.guaranteed_cap), "conditional": str(b.conditional_cap)},
        "paused": b.paused, "note": b.note,
    }


@router.post("/opportunities/{opportunity_id}/journal", status_code=201)
def journal(opportunity_id: IdPath, body: JournalIn, session: SessionDep, clock: ClockDep,
            x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None
            ) -> dict[str, Any]:
    if x_krt_request != "journal":
        raise ApiError(403, ErrorCode.VALIDATION_ERROR, "Missing X-KRT-Request header")
    try:
        record_journal(session, opportunity_id, body.action, clock.now(),
                       [lg.model_dump() for lg in body.legs], body.note)
    except JournalError as e:
        session.rollback()
        raise ApiError(409, ErrorCode.VALIDATION_ERROR, str(e)) from None
    session.commit()
    return _card(session, session.get(Opportunity, opportunity_id), clock.now())


@router.get("/scorecard")
def get_scorecard(session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    return scorecard(session, settings)
