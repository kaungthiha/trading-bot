"""Paper-trading API. The only state-changing route in the app is POST /api/paper/orders,
which SIMULATES an order locally -- no exchange is ever contacted.

CSRF defence for the POST (localhost is not authentication):
  - OriginGuardMiddleware already rejects non-allow-listed Origins on unsafe methods;
  - this route additionally requires a custom header (X-KRT-Request) and a JSON body.
    Browsers cannot send custom headers cross-origin without a CORS preflight, which our
    exact-origin CORS policy denies, so a hostile page cannot forge the request.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select

from app.api.errors import ApiError, ErrorCode
from app.api.routes import ClockDep, SessionDep, SettingsDep
from app.db.models import Market, PaperFill, PaperOrder, PaperSettlement
from app.paper.replay import replay
from app.paper.service import OrderRequest, account_summary, submit_order
from app.paper.simulator import SCENARIOS
from app.signals.fees import load_schedules

router = APIRouter(prefix="/api/paper")

CSRF_HEADER = "X-KRT-Request"


class OrderIn(BaseModel):
    client_order_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    market_id: str = Field(min_length=1, max_length=36)
    side: str = Field(pattern=r"^(YES|NO)$")
    action: str = Field(pattern=r"^(BUY|SELL)$")
    quantity: int = Field(ge=1, le=100_000)
    limit_price: Decimal = Field(gt=0, lt=1, max_digits=8, decimal_places=6)
    scenario: str | None = Field(default=None, max_length=32)
    signal_id: str | None = Field(default=None, max_length=36)


class FillOut(BaseModel):
    quantity: Decimal
    price: Decimal
    displayed_price: Decimal
    fee: Decimal
    filled_at: AwareDatetime
    assumption_code: str


class OrderOut(BaseModel):
    id: str
    client_order_id: str
    submitted_at: AwareDatetime
    market_id: str
    market_ticker: str
    side: str
    action: str
    quantity: Decimal
    limit_price: Decimal
    status: str
    filled_quantity: Decimal
    reject_reason: str | None
    scenario: str
    simulation_version: str
    fee_schedule_version: str | None
    fee_schedule_verified: bool
    quote_id: str | None
    signal_id: str | None
    source: str
    fills: list[FillOut]
    duplicate: bool = False


class PositionOut(BaseModel):
    market_id: str
    market_ticker: str
    side: str
    open_qty: Decimal
    avg_cost: Decimal
    realized: Decimal
    unrealized: Decimal
    mark_value: Decimal
    mark_note: str | None
    settled: bool
    held: bool


class AccountOut(BaseModel):
    as_of: AwareDatetime
    cash: Decimal
    deposits: Decimal
    open_value: Decimal
    equity: Decimal
    realized: Decimal
    unrealized: Decimal
    fee_schedule_verified: bool
    notes: list[str]
    positions: list[PositionOut]


class SettlementOut(BaseModel):
    id: str
    created_at: AwareDatetime
    market_ticker: str
    exchange_status: str
    exchange_result: str
    evidence_check: str
    status: str
    notes: list[str]


Q6 = Decimal("0.000001")


def _order_out(session, o: PaperOrder, duplicate: bool = False) -> OrderOut:  # type: ignore[no-untyped-def]
    fills = session.scalars(select(PaperFill).where(PaperFill.paper_order_id == o.id)).all()
    return OrderOut(
        id=o.id, client_order_id=o.client_order_id, submitted_at=o.submitted_at,
        market_id=o.market_id, market_ticker=session.get(Market, o.market_id).external_ticker,
        side=o.side, action=o.action, quantity=o.quantity, limit_price=o.limit_price,
        status=o.status, filled_quantity=o.filled_quantity, reject_reason=o.reject_reason,
        scenario=o.scenario, simulation_version=o.simulation_version,
        fee_schedule_version=o.fee_schedule_version,
        fee_schedule_verified=o.fee_schedule_verified, quote_id=o.quote_id,
        signal_id=o.signal_id, source=o.source, duplicate=duplicate,
        fills=[FillOut(quantity=f.quantity, price=f.price, displayed_price=f.displayed_price,
                       fee=f.fee, filled_at=f.filled_at, assumption_code=f.assumption_code)
               for f in fills],
    )


@router.post("/orders", response_model=OrderOut, status_code=201)
def create_order(
    body: OrderIn,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
    x_krt_request: Annotated[str | None, Header(alias=CSRF_HEADER)] = None,
) -> OrderOut:
    if x_krt_request != "paper":
        raise ApiError(403, ErrorCode.VALIDATION_ERROR, f"Missing {CSRF_HEADER} header")
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise ApiError(415, ErrorCode.VALIDATION_ERROR, "JSON body required")
    if session.get(Market, body.market_id) is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Market not found")
    scenario = body.scenario or settings.paper_default_scenario
    res = submit_order(session, settings, OrderRequest(
        client_order_id=body.client_order_id, market_id=body.market_id, side=body.side,
        action=body.action, quantity=Decimal(body.quantity), limit_price=body.limit_price,
        scenario=scenario, signal_id=body.signal_id), clock.now())
    session.commit()
    if res.duplicate:
        response.status_code = 200
    return _order_out(session, res.order, res.duplicate)


@router.get("/orders", response_model=list[OrderOut])
def list_orders(session: SessionDep,
                limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[OrderOut]:
    rows = session.scalars(select(PaperOrder).order_by(PaperOrder.submitted_at.desc())
                           .limit(limit)).all()
    return [_order_out(session, o) for o in rows]


@router.get("/account", response_model=AccountOut)
def account(session: SessionDep, clock: ClockDep) -> AccountOut:
    now = clock.now()
    summ, rows = account_summary(session, now)
    return AccountOut(
        as_of=now, cash=summ.cash, deposits=summ.deposits, open_value=summ.open_value,
        equity=summ.equity, realized=summ.realized.quantize(Q6),
        unrealized=summ.unrealized.quantize(Q6), fee_schedule_verified=summ.fee_schedule_verified,
        notes=summ.notes,
        positions=[PositionOut(
            market_id=p.market_id, market_ticker=session.get(Market, p.market_id).external_ticker,
            side=p.side, open_qty=p.open_qty, avg_cost=p.avg_cost.quantize(Q6),
            realized=p.realized.quantize(Q6), unrealized=unr.quantize(Q6),
            mark_value=mk.value, mark_note=mk.note, settled=p.settled, held=p.held,
        ) for p, mk, unr in rows],
    )


@router.get("/settlements", response_model=list[SettlementOut])
def settlements(session: SessionDep) -> list[SettlementOut]:
    rows = session.scalars(select(PaperSettlement).order_by(PaperSettlement.created_at.desc()))
    return [SettlementOut(id=st.id, created_at=st.created_at,
                          market_ticker=session.get(Market, st.market_id).external_ticker,
                          exchange_status=st.exchange_status, exchange_result=st.exchange_result,
                          evidence_check=st.evidence_check, status=st.status,
                          notes=json.loads(st.notes_json)) for st in rows]


@router.get("/replay")
def replay_signals(session: SessionDep, clock: ClockDep, settings: SettingsDep,
                   scenario: str | None = None,
                   as_of: AwareDatetime | None = None) -> dict[str, Any]:
    sc = SCENARIOS.get(scenario or settings.paper_default_scenario)
    if sc is None:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR,
                       f"scenario must be one of {list(SCENARIOS)}")
    cutoff: datetime = as_of or clock.now()
    rep = replay(session, sc, cutoff, load_schedules())

    def d(x: Decimal | None) -> str | None:
        return None if x is None else str(x)

    return {
        "as_of": rep.as_of.isoformat(), "scenario": rep.scenario, "n_signals": rep.n_signals,
        "n_resolved": rep.n_resolved, "total_cost": d(rep.total_cost),
        "realized_pnl": d(rep.realized_pnl), "unresolved_cost": d(rep.unresolved_cost),
        "resolved_brier": rep.resolved_brier,
        "trades": [{**t.__dict__, "requested": d(t.requested), "filled": d(t.filled),
                    "avg_price": d(t.avg_price), "cost": d(t.cost), "payout": d(t.payout)}
                   for t in rep.trades],
        "caveat": "Simulated replay of research signals under stated fill assumptions; not "
                  "evidence of real-world returns.",
    }
