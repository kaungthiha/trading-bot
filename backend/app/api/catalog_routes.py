"""Markets page: browse every open Kalshi market (from the last scan's snapshot), with
research statistics. All read-only GETs; the live endpoint calls Kalshi's PUBLIC API."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request

from app.adapters.base import AdapterError
from app.api.errors import ApiError, ErrorCode
from app.api.routes import SessionDep, SettingsDep
from app.catalog import service

router = APIRouter(prefix="/api/catalog")

SORT = r"^(volume_24h|open_interest|volume|closing)$"
TICKER = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$"
Ticker = Annotated[str, Path(pattern=TICKER, max_length=160)]
Text = Annotated[str | None, Query(min_length=1, max_length=100)]
Category = Annotated[str | None, Query(min_length=1, max_length=64)]
Series = Annotated[str | None, Query(pattern=TICKER, max_length=128)]
Prob = Annotated[Decimal, Query(gt=0, lt=1, max_digits=6, decimal_places=4)]
Price = Annotated[Decimal | None, Query(gt=0, lt=1, max_digits=5, decimal_places=4)]


@router.get("/status")
def catalog_status(session: SessionDep) -> dict[str, Any]:
    return service.status(session)


@router.get("/categories")
def catalog_categories(session: SessionDep) -> dict[str, Any]:
    return {"items": service.categories(session)}


@router.get("/series")
def catalog_series(session: SessionDep, category: Category = None,
                   q: Text = None) -> dict[str, Any]:
    return {"items": service.series_list(session, category, q)}


@router.get("/events")
def catalog_events(session: SessionDep, category: Category = None, series: Series = None,
                   q: Text = None,
                   sort: Annotated[str, Query(pattern=SORT)] = "volume_24h",
                   limit: Annotated[int, Query(ge=1, le=200)] = 50,
                   offset: Annotated[int, Query(ge=0, le=100_000)] = 0) -> dict[str, Any]:
    return service.events(session, category=category, series=series, q=q, sort=sort,
                          limit=limit, offset=offset)


@router.get("/events/{event_ticker}")
def catalog_event(event_ticker: Ticker, session: SessionDep) -> dict[str, Any]:
    out = service.event_detail(session, event_ticker)
    if out is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Event not in the catalog (closed, or not "
                       "scanned yet)")
    return out


@router.get("/combo-study")
def catalog_combo_study(session: SessionDep) -> dict[str, Any]:
    from app.catalog.combos import latest_study

    return {"study": latest_study(session)}


@router.get("/markets/{ticker}/ev")
def catalog_ev(ticker: Ticker, session: SessionDep, settings: SettingsDep, prob: Prob,
               side: Annotated[str, Query(pattern=r"^(yes|no)$")] = "yes",
               contracts: Annotated[int, Query(ge=1, le=10_000)] = 10,
               price: Price = None) -> dict[str, Any]:
    try:
        return service.market_ev(session, settings, ticker, side, contracts, prob, price)
    except service.CatalogError as e:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, str(e)) from e


@router.get("/combo")
def catalog_combo(session: SessionDep,
                  legs: Annotated[str, Query(min_length=3, max_length=2000,
                                             description="TICKER:yes,TICKER:no,...")]
                  ) -> dict[str, Any]:
    parsed: list[tuple[str, str]] = []
    for part in legs.split(","):
        t, _, side = part.strip().rpartition(":")
        if not re.match(TICKER, t) or side not in ("yes", "no"):
            raise ApiError(422, ErrorCode.VALIDATION_ERROR, f"Bad leg {part[:60]!r}")
        parsed.append((t, side))
    if not 1 <= len(parsed) <= 12:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, "Use 1 to 12 legs")
    try:
        return service.combo(session, parsed)
    except service.CatalogError as e:
        raise ApiError(404, ErrorCode.NOT_FOUND, str(e)) from e


@router.get("/markets/{ticker}/book")
def catalog_book(ticker: Ticker, request: Request) -> dict[str, Any]:
    """Fresh market + orderbook straight from Kalshi's public API (on demand)."""
    client = request.app.state.jobs.client_factory()
    try:
        m = client.get_market(ticker)
        book = client.get_orderbook(ticker, depth=10).get("orderbook_fp") or {}
    except AdapterError as e:
        raise ApiError(502, ErrorCode.SOURCE_FAILURE, f"Kalshi: {e}") from e
    finally:
        client.close()

    def levels(key: str) -> list[dict[str, str]]:
        rows = sorted(((Decimal(p), Decimal(c)) for p, c in book.get(key) or []), reverse=True)
        return [{"price": str(p), "quantity": str(c)} for p, c in rows]

    keep = ("ticker", "title", "yes_sub_title", "no_sub_title", "status", "yes_bid_dollars",
            "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars", "last_price_dollars",
            "volume_24h_fp", "open_interest_fp", "close_time", "rules_primary",
            "rules_secondary", "early_close_condition")
    return {"market": {k: m.get(k) for k in keep},
            "yes_bids": levels("yes_dollars"), "no_bids": levels("no_dollars"),
            "custom_strike": json.dumps(m.get("custom_strike")) if m.get("custom_strike") else None}
