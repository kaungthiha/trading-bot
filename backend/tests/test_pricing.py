from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.domain.models import BookLevel, OrderBook, PriceProvenance, PriceRange
from app.domain.pricing import derive_quote, is_on_price_grid, is_stale

T = datetime(2026, 11, 18, 15, 0, tzinfo=UTC)
D = Decimal


def book(yes: list[str], no: list[str]) -> OrderBook:
    return OrderBook(
        observed_at=T,
        yes_bids=tuple(BookLevel(price=D(p), quantity=D("10")) for p in yes),
        no_bids=tuple(BookLevel(price=D(p), quantity=D("10")) for p in no),
    )


def test_spec_case_1_derived_asks() -> None:
    q = derive_quote(book(["0.43"], ["0.55"]))
    assert q.yes_ask == D("0.45")
    assert q.no_ask == D("0.57")
    assert q.yes_ask_provenance is PriceProvenance.DERIVED_FROM_COMPLEMENT
    assert q.spread_yes == D("0.02")


def test_absent_no_bid_means_no_yes_ask() -> None:
    q = derive_quote(book(["0.20"], []))
    assert q.yes_ask is None
    assert q.yes_ask_provenance is None
    assert q.no_ask == D("0.80")
    assert q.spread_yes is None


def test_empty_book_has_no_prices() -> None:
    q = derive_quote(book([], []))
    assert (q.yes_bid, q.no_bid, q.yes_ask, q.no_ask) == (None, None, None, None)


def test_best_bid_is_max_regardless_of_order() -> None:
    q = derive_quote(book(["0.40", "0.43", "0.41"], ["0.50", "0.55"]))
    assert q.yes_bid == D("0.43")
    assert q.no_bid == D("0.55")


def test_sub_cent_precision_preserved() -> None:
    q = derive_quote(book(["0.4325"], ["0.5550"]))
    assert q.yes_ask == D("0.4450")
    assert q.no_ask == D("0.5675")
    assert isinstance(q.yes_ask, Decimal)


def test_price_grid_multi_segment() -> None:
    grid = [
        PriceRange(start=D("0.01"), end=D("0.10"), step=D("0.001")),
        PriceRange(start=D("0.10"), end=D("0.90"), step=D("0.01")),
    ]
    assert is_on_price_grid(D("0.055"), grid)
    assert is_on_price_grid(D("0.55"), grid)
    assert not is_on_price_grid(D("0.555"), grid)  # off-grid in the cent segment
    assert not is_on_price_grid(D("0.95"), grid)  # outside all segments
    assert not is_on_price_grid(D("0.0005"), grid)


def test_staleness() -> None:
    max_age = timedelta(seconds=60)
    assert not is_stale(T, T + timedelta(seconds=60), max_age)
    assert is_stale(T, T + timedelta(seconds=61), max_age)
    assert is_stale(T + timedelta(seconds=5), T, max_age)  # future-dated = untrusted
