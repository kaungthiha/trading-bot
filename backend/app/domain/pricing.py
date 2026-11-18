"""Exact Decimal pricing helpers.

Kalshi's documented order book exposes YES bids and NO bids, not asks. Because YES and NO
are complementary claims paying ``notional_value`` (normally $1), a resting NO bid at
price p is economically an offer to sell YES at ``notional - p``. These helpers derive
asks that way and mark them as derived. If the complementary side is empty, there is no
ask -- we never fabricate a counterparty.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from app.domain.models import BookLevel, DerivedQuote, OrderBook, PriceProvenance, PriceRange


def best_bid(levels: Sequence[BookLevel]) -> Decimal | None:
    return max((lvl.price for lvl in levels), default=None)


def derive_quote(
    book: OrderBook, notional: Decimal = Decimal("1"), *, derivable: bool = True
) -> DerivedQuote:
    """Derive asks from complementary bids.

    ``derivable=False`` (e.g. scalar or unknown market types, whose complement relation
    we have not verified) yields bids only, with no asks.
    """
    yes_bid = best_bid(book.yes_bids)
    no_bid = best_bid(book.no_bids)

    yes_ask = (notional - no_bid) if (derivable and no_bid is not None) else None
    no_ask = (notional - yes_bid) if (derivable and yes_bid is not None) else None

    spread_yes = (yes_ask - yes_bid) if (yes_ask is not None and yes_bid is not None) else None

    return DerivedQuote(
        yes_bid=yes_bid,
        no_bid=no_bid,
        yes_ask=yes_ask,
        no_ask=no_ask,
        yes_ask_provenance=PriceProvenance.DERIVED_FROM_COMPLEMENT if yes_ask is not None else None,
        no_ask_provenance=PriceProvenance.DERIVED_FROM_COMPLEMENT if no_ask is not None else None,
        spread_yes=spread_yes,
    )


def is_on_price_grid(price: Decimal, ranges: Iterable[PriceRange]) -> bool:
    """True if ``price`` lies on any configured segment of the market's price grid."""
    for r in ranges:
        if r.start <= price <= r.end and (price - r.start) % r.step == 0:
            return True
    return False


def quote_age(observed_at: datetime, now: datetime) -> timedelta:
    return now - observed_at


def is_stale(observed_at: datetime, now: datetime, max_age: timedelta) -> bool:
    # A quote timestamped in the future is treated as untrustworthy (stale) too.
    age = quote_age(observed_at, now)
    return age > max_age or age < timedelta(0)
