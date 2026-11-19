"""Approval-gated execution API (mock / Kalshi demo only; production is not implemented).

Every state-changing route requires the X-KRT-Request: execution header (CSRF defence,
on top of the Origin allow-list). Approval additionally requires the user's PIN. The kill
switch can be ENGAGED over HTTP but only RELEASED from the CLI.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Header, Path, Request
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import literal_column, select

from app.api.errors import ApiError, ErrorCode
from app.api.routes import ClockDep, SessionDep, SettingsDep
from app.db.models import ExchangeOrder, ExecutionEvent, ExecutionIntent, Market
from app.execution.factory import build_gateway
from app.execution.service import (
    ExecutionError,
    IntentRequest,
    approve_and_submit,
    create_intent,
    kill_switch_engaged,
    reconcile,
    set_kill_switch,
    summary,
)

router = APIRouter(prefix="/api/execution")
# Insertion order breaks ties between events recorded in the same instant.
EVENT_ORDER = literal_column("execution_events.rowid")
IdPath = Annotated[str, Path(min_length=1, max_length=36)]


def _csrf(value: str | None) -> None:
    if value != "execution":
        raise ApiError(403, ErrorCode.VALIDATION_ERROR, "Missing X-KRT-Request header")


def _err(e: ExecutionError) -> ApiError:
    return ApiError(e.status, e.code, e.message)  # type: ignore[arg-type]


class IntentIn(BaseModel):
    market_id: str = Field(min_length=1, max_length=36)
    side: str = Field(pattern=r"^(YES|NO)$")
    quantity: int = Field(ge=1, le=10_000)
    limit_price: Decimal = Field(gt=0, lt=1, max_digits=6, decimal_places=4)
    signal_id: str | None = Field(default=None, max_length=36)


class ApproveIn(BaseModel):
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    pin: str = Field(min_length=1, max_length=128)


class KillIn(BaseModel):
    reason: str = Field(default="", max_length=200)


class IntentOut(BaseModel):
    id: str
    created_at: AwareDatetime
    expires_at: AwareDatetime
    env: str
    market_ticker: str
    side: str
    quantity: Decimal
    limit_price: Decimal
    approved_ask: Decimal
    est_fee: Decimal
    max_cost: Decimal
    fee_schedule_version: str
    status: str
    block_reason: str | None
    summary: str
    payload: dict[str, Any]
    payload_hash: str
    exchange_order: dict[str, Any] | None
    events: list[dict[str, Any]]


def _out(s, i: ExecutionIntent, with_events: bool = True) -> IntentOut:  # type: ignore[no-untyped-def]
    m = s.get(Market, i.market_id)
    eo = s.scalar(select(ExchangeOrder).where(ExchangeOrder.intent_id == i.id))
    events = s.scalars(select(ExecutionEvent).where(ExecutionEvent.intent_id == i.id)
                       .order_by(ExecutionEvent.at, EVENT_ORDER)).all() if with_events else []
    return IntentOut(
        id=i.id, created_at=i.created_at, expires_at=i.expires_at, env=i.env,
        market_ticker=m.external_ticker, side=i.side, quantity=i.quantity,
        limit_price=i.limit_price, approved_ask=i.approved_ask, est_fee=i.est_fee,
        max_cost=i.max_cost, fee_schedule_version=i.fee_schedule_version, status=i.status,
        block_reason=i.block_reason, summary=summary(i, m), payload=json.loads(i.payload_json),
        payload_hash=i.payload_hash,
        exchange_order={"exchange_order_id": eo.exchange_order_id, "source": eo.source,
                        "fill_count": str(eo.fill_count),
                        "average_fill_price": str(eo.average_fill_price)
                        if eo.average_fill_price is not None else None,
                        "average_fee_paid": str(eo.average_fee_paid)
                        if eo.average_fee_paid is not None else None} if eo else None,
        events=[{"at": e.at.isoformat(), "kind": e.kind, "detail": json.loads(e.detail_json)}
                for e in events],
    )


def _gateway(request: Request, settings, session):  # type: ignore[no-untyped-def]
    try:
        return build_gateway(settings, session, request.app.state.mock_exchange)
    except ExecutionError as e:
        raise _err(e) from None


@router.get("/status")
def status(session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    return {
        "execution_enabled": settings.execution_enabled,
        "env": settings.execution_env.value,
        "production": "not implemented (disabled in code)",
        "kill_switch_engaged": kill_switch_engaged(session),
        "pin_configured": settings.execution_approval_pin_hash is not None,
        "demo_credentials_configured": settings.kalshi_demo_api_key_id is not None
        and settings.kalshi_demo_private_key_path is not None,
        "caps": {
            "max_contracts_per_order": settings.execution_max_contracts_per_order,
            "max_cost_per_order": str(settings.execution_max_cost_per_order),
            "max_position_contracts": settings.execution_max_position_contracts,
            "max_daily_cost": str(settings.execution_max_daily_cost),
            "intent_ttl_seconds": settings.execution_intent_ttl_seconds,
            "quote_max_age_seconds": settings.execution_quote_max_age_seconds,
        },
    }


@router.post("/intents", response_model=IntentOut, status_code=201)
def propose(body: IntentIn, session: SessionDep, settings: SettingsDep, clock: ClockDep,
            x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None
            ) -> IntentOut:
    _csrf(x_krt_request)
    try:
        intent = create_intent(session, settings, IntentRequest(
            body.market_id, body.side, Decimal(body.quantity), body.limit_price, body.signal_id),
            clock.now())
    except ExecutionError as e:
        session.rollback()
        raise _err(e) from None
    session.commit()
    return _out(session, intent)


@router.get("/intents", response_model=list[IntentOut])
def list_intents(session: SessionDep) -> list[IntentOut]:
    rows = session.scalars(select(ExecutionIntent).order_by(ExecutionIntent.created_at.desc())
                           .limit(50)).all()
    return [_out(session, i, with_events=False) for i in rows]


@router.get("/intents/{intent_id}", response_model=IntentOut)
def get_intent(intent_id: IdPath, session: SessionDep) -> IntentOut:
    i = session.get(ExecutionIntent, intent_id)
    if i is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Intent not found")
    return _out(session, i)


@router.post("/intents/{intent_id}/approve", response_model=IntentOut)
def approve(intent_id: IdPath, body: ApproveIn, request: Request, session: SessionDep,
            settings: SettingsDep, clock: ClockDep,
            x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None
            ) -> IntentOut:
    _csrf(x_krt_request)
    gw = _gateway(request, settings, session)
    try:
        intent = approve_and_submit(session, settings, intent_id, body.payload_hash, body.pin,
                                    gw, clock.now())
    except ExecutionError as e:
        raise _err(e) from None
    finally:
        if hasattr(gw, "close"):
            gw.close()
    return _out(session, intent)


@router.post("/intents/{intent_id}/reconcile", response_model=IntentOut)
def reconcile_intent(intent_id: IdPath, request: Request, session: SessionDep,
                     settings: SettingsDep, clock: ClockDep,
                     x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None
                     ) -> IntentOut:
    _csrf(x_krt_request)
    gw = _gateway(request, settings, session)
    try:
        intent = reconcile(session, intent_id, gw, clock.now())
    except ExecutionError as e:
        raise _err(e) from None
    finally:
        if hasattr(gw, "close"):
            gw.close()
    return _out(session, intent)


@router.post("/kill-switch")
def engage_kill_switch(body: KillIn, session: SessionDep, clock: ClockDep,
                       x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None
                       ) -> dict[str, Any]:
    """ENGAGE only. Releasing requires the CLI (deliberately not exposed over HTTP)."""
    _csrf(x_krt_request)
    set_kill_switch(session, clock.now(), engage=True, actor="ui", reason=body.reason)
    session.commit()
    return {"kill_switch_engaged": True}
