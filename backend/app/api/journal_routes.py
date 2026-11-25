"""Your bet journal (a queue): bets you plan to place, what you paid, why, and how they
ended. Local only; the app never places orders. Writes need the X-KRT-Request: journal
header (CSRF defence, like every other write route)."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Header
from pydantic import BaseModel, field_validator
from pydantic import Field as PydField

from app.api.errors import ApiError, ErrorCode
from app.api.routes import ClockDep, SessionDep, SettingsDep
from app.db.models import BetJournal
from app.history import journal
from app.history.analysis import report

router = APIRouter(prefix="/api/journal")
_TICKER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")


class LegIn(BaseModel):
    ticker: str = PydField(max_length=160)
    side: str = PydField(pattern="^(yes|no)$")
    label: str = PydField(max_length=300)
    event: str = PydField(default="", max_length=160)
    price: float | None = PydField(default=None, ge=0, le=1)

    @field_validator("ticker")
    @classmethod
    def _ticker(cls, v: str) -> str:
        if not _TICKER.match(v):
            raise ValueError("bad ticker")
        return v


Price = Annotated[Decimal | None, PydField(default=None, ge=0, le=1, decimal_places=4)]
Stake = Annotated[Decimal | None, PydField(default=None, ge=0, le=1000, decimal_places=2)]


class EntryIn(BaseModel):
    legs: list[LegIn] = PydField(min_length=1, max_length=journal.MAX_LEGS)
    status: str = PydField(default="queued", pattern="^(queued|placed|skipped)$")
    source: str = PydField(default="docket", pattern="^(docket|slate|own)$")
    market_price: Price = None
    my_price: Price = None
    stake: Stake = None
    note: str = PydField(default="", max_length=journal.NOTE_MAX)


class EntryUpdate(BaseModel):
    status: str | None = PydField(default=None, pattern="^(queued|placed|skipped)$")
    my_price: Price = None
    stake: Stake = None
    note: str | None = PydField(default=None, max_length=journal.NOTE_MAX)


def _header(x: str | None) -> None:
    if x != "journal":
        raise ApiError(403, ErrorCode.VALIDATION_ERROR, "Missing X-KRT-Request header")


def _rows(session: Any, settings: Any) -> dict[str, dict[str, Any]]:
    rep = report(session, settings.experiment_budget_dollars)
    out = {r["ticker"]: r for r in rep["markets"]}
    out.update({r["ticker"]: r for r in rep["open_positions"]})
    return out


@router.get("")
def journal_list(session: SessionDep, settings: SettingsDep, clock: ClockDep) -> dict[str, Any]:
    items = journal.listing(session, _rows(session, settings), clock.now())
    return {"items": items,
            "queued": sum(1 for x in items if x["status"] == "queued")}


@router.post("")
def journal_add(body: EntryIn, session: SessionDep, settings: SettingsDep, clock: ClockDep,
                x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None
                ) -> dict[str, Any]:
    _header(x_krt_request)
    e = journal.create(session, body.model_dump(), clock.now())
    return journal.entry_json(session, e, _rows(session, settings), journal._buys(session))


def _get(session: Any, entry_id: str) -> BetJournal:
    e = session.get(BetJournal, entry_id) if len(entry_id) <= 36 else None
    if e is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "No such journal entry")
    return e


@router.post("/{entry_id}")
def journal_update(entry_id: str, body: EntryUpdate, session: SessionDep, settings: SettingsDep,
                   clock: ClockDep,
                   x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None
                   ) -> dict[str, Any]:
    _header(x_krt_request)
    e = journal.update(session, _get(session, entry_id), body.model_dump(exclude_unset=True),
                       clock.now())
    return journal.entry_json(session, e, _rows(session, settings), journal._buys(session))


@router.post("/{entry_id}/remove")
def journal_remove(entry_id: str, session: SessionDep,
                   x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None
                   ) -> dict[str, Any]:
    _header(x_krt_request)
    session.delete(_get(session, entry_id))
    session.commit()
    return {"removed": entry_id}
