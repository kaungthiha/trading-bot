"""Pieces every no-model sport investigation (NHL, NFL, soccer) shares: the price lens
(slip-check fees and all-in break-even, never an estimate or edge) and the Kalshi source."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.catalog.slipcheck import Fees, _side_prices, price_single
from app.catalog.stats import Quote as CatQuote
from app.catalog.stats import implied
from app.db.models import CatalogMarket
from app.investigate import schemas as S


def price_lens(
    session: Session,
    m: CatalogMarket,
    side: str,
    name: str,
    series: str,
    quote: S.Quote,
    settlement: str,
    no_model: str,
) -> tuple[S.Price, float | None]:
    """(price assessment, all-in price) with no model: break-even only, reasons listed."""
    from app.investigate import service

    fees = Fees(session)
    y, _ = implied(CatQuote(m.ticker, m.ticker, m.yes_bid, m.yes_ask))
    mid = None if y is None else Decimal(str(y if side == "yes" else 1 - y))
    ask, bid = _side_prices(m, side)
    ps = price_single(
        fees,
        {
            "ticker": m.ticker,
            "side": side,
            "label": name,
            "series": series,
            "mid": mid,
            "ask": ask,
            "bid": bid,
            "history": None,
            "p_est": None,
        },
    )
    all_in = float(ps["all_in"]) if ps.get("all_in") else None
    fee = None if ask is None else float(fees.taker(series, Decimal(100), ask) / 100)
    abstain = [no_model]
    if not quote.fresh:
        abstain.append("The quote is stale: refresh prices before deciding.")
    if ask is None:
        abstain.append("No ask to buy at right now.")
    return (
        S.Price(
            ask=service._f(ask),
            model_p=None,
            model_band=None,
            model_name=None,
            raw_diff=None,
            conservative_edge=None,
            break_even=all_in,
            walk_away=None,
            fee_per_contract=service._f(fee),
            slippage_per_contract=0.0,
            assumptions=[
                f"Ask from the last catalog scan "
                f"({service._iso(m.refreshed_at) or 'unknown time'}).",
                f"Taker fee from Kalshi's {'verified' if fees.verified else 'unverified'} "
                "schedule, one contract.",
                "Break-even = all-in price per $1 payout.",
                f"Settlement: {settlement}",
            ],
            abstain_reasons=abstain,
        ),
        all_in,
    )


def kalshi_source(m: CatalogMarket, rules_url: str | None, now: datetime) -> S.Source:
    from app.investigate import service

    return S.Source(
        id="K1",
        url=rules_url or "https://kalshi.com",
        title=f"Kalshi market: {m.title}"[:200],
        publisher="Kalshi",
        retrieved_at=service._iso(m.refreshed_at) or now.isoformat(),
        access="internal",
        line_match="exact",
    )
