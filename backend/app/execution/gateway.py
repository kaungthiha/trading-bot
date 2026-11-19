"""Execution gateways. Every gateway implements the same small interface; the service
decides WHETHER to send, gateways only know HOW.

Outcome contract for create_order (from Kalshi order_errors docs):
  - returns dict           -> exchange accepted (201); fill_count/remaining_count are final
                              for immediate-or-cancel orders
  - DefinitiveReject       -> 4xx with a known code: nothing was placed; never retried
  - UnknownOutcome         -> timeout / connection drop / 408 / 5xx / duplicate id: the
                              order MAY exist. Never resubmit; reconcile by client_order_id.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

import httpx

from app.execution.signing import API_PREFIX, Signer

KALSHI_DEMO_BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
# Only demo hosts may ever be contacted with credentials. Production hosts are refused.
_ALLOWED_HOSTS = {"external-api.demo.kalshi.co", "demo-api.kalshi.co"}
_FORBIDDEN_HOSTS = {"external-api.kalshi.com", "api.elections.kalshi.com", "kalshi.com"}


class DefinitiveReject(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(f"{status} {code}")
        self.status, self.code = status, code


class UnknownOutcome(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class GatewayError(Exception):
    """A read failed (market/orderbook/balance); the preflight must block."""


def rules_hash_from_market(m: dict[str, Any]) -> str:
    rules = "\n\n".join(r for r in (m.get("rules_primary"), m.get("rules_secondary")) if r)
    return hashlib.sha256(rules.encode("utf-8")).hexdigest()


class ExecutionGateway(Protocol):
    env: str

    def get_market(self, ticker: str) -> dict[str, Any]: ...
    def get_orderbook(self, ticker: str) -> dict[str, Any]: ...
    def get_balance_dollars(self) -> Decimal: ...
    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def find_order(
        self, ticker: str, client_order_id: str, min_ts: int
    ) -> dict[str, Any] | None: ...


# --- Mock exchange ----------------------------------------------------------------------


@dataclass
class MockExchange:
    """Deterministic in-process exchange for testing the full approval flow.

    ``markets`` maps ticker -> market dict (Kalshi shape, incl. rules_primary/secondary,
    status); ``books`` maps ticker -> {"orderbook_fp": {"yes_dollars": [...], "no_dollars": [...]}}.
    ``faults`` is a queue of injected failures consumed by create_order, e.g.
    "timeout_before_accept", "timeout_after_accept", "http_500", "duplicate",
    "insufficient_balance", "market_inactive".
    """

    markets: dict[str, dict[str, Any]] = field(default_factory=dict)
    books: dict[str, dict[str, Any]] = field(default_factory=dict)
    balance: Decimal = Decimal("1000")
    taker_rate: Decimal = Decimal("0.07")
    faults: list[str] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    create_calls: int = 0
    env: str = "mock"
    clock_ms: Callable[[], int] = field(default=lambda: int(time.time() * 1000))

    def get_market(self, ticker: str) -> dict[str, Any]:
        if ticker not in self.markets:
            raise GatewayError("market_not_found")
        return self.markets[ticker]

    def get_orderbook(self, ticker: str) -> dict[str, Any]:
        return self.books.get(ticker, {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}})

    def get_balance_dollars(self) -> Decimal:
        return self.balance

    def _fill(self, payload: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal]:
        """IOC fill against the book. Returns (filled, cost_excl_fee, fee)."""
        book = self.get_orderbook(payload["ticker"])["orderbook_fp"]
        qty, limit = Decimal(payload["count"]), Decimal(payload["price"])
        if payload["side"] == "bid":  # buy YES: lift asks derived from NO bids
            levels = sorted((Decimal(1) - Decimal(p), Decimal(c)) for p, c in book["no_dollars"])
            ok = lambda px: px <= limit  # noqa: E731
        else:  # ask: sell YES == buy NO at 1 - price; hit YES bids
            levels = sorted(((Decimal(p), Decimal(c)) for p, c in book["yes_dollars"]),
                            reverse=True)
            ok = lambda px: px >= limit  # noqa: E731
        filled = cost = fee = Decimal(0)
        for px, avail in levels:
            if filled >= qty or not ok(px):
                break
            take = min(qty - filled, avail)
            exec_px = px if payload["side"] == "bid" else Decimal(1) - px  # what WE pay
            filled += take
            cost += take * exec_px
            fee += self.taker_rate * take * exec_px * (1 - exec_px)
        return filled, cost, fee.quantize(Decimal("0.000001"))

    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.create_calls += 1
        fault = self.faults.pop(0) if self.faults else None
        if fault == "timeout_before_accept":
            raise UnknownOutcome("timeout")
        if fault == "http_500":
            raise UnknownOutcome("http_500")
        if fault == "insufficient_balance":
            raise DefinitiveReject(400, "insufficient_balance")
        if fault == "market_inactive":
            raise DefinitiveReject(409, "market_inactive")
        if any(o["client_order_id"] == payload["client_order_id"] for o in self.orders):
            raise UnknownOutcome("order_already_exists")
        if fault == "duplicate":
            raise UnknownOutcome("order_already_exists")
        filled, cost, fee = self._fill(payload)
        if cost + fee > self.balance:
            raise DefinitiveReject(400, "insufficient_balance")
        self.balance -= cost + fee
        order = {
            "order_id": f"mock-{len(self.orders) + 1:06d}",
            "client_order_id": payload["client_order_id"], "ticker": payload["ticker"],
            "fill_count": f"{filled:.2f}", "remaining_count": "0.00",  # IOC: rest cancelled
            "average_fill_price": f"{(cost / filled):.4f}" if filled else None,
            "average_fee_paid": f"{(fee / filled):.6f}" if filled else None,
            "ts_ms": self.clock_ms(), "status": "executed" if filled else "canceled",
        }
        self.orders.append(order)
        if fault == "timeout_after_accept":
            raise UnknownOutcome("timeout")  # accepted, but the response was lost
        return {k: v for k, v in order.items() if k not in ("ticker", "status")}

    def find_order(self, ticker: str, client_order_id: str, min_ts: int) -> dict[str, Any] | None:
        return next((o for o in self.orders if o["client_order_id"] == client_order_id
                     and o["ticker"] == ticker and o["ts_ms"] >= min_ts), None)


# --- Kalshi DEMO gateway ----------------------------------------------------------------


class KalshiDemoGateway:
    """Signed client for Kalshi's DEMO environment only. Writes are sent exactly once
    (no retries); reads used for preflight/reconciliation."""

    env = "demo"
    _READ_PATHS = ("/markets/", "/portfolio/orders", "/portfolio/balance")
    _WRITE_PATH = "/portfolio/events/orders"

    def __init__(self, signer: Signer, base_url: str = KALSHI_DEMO_BASE, *,
                 timeout: float = 10.0, transport: httpx.BaseTransport | None = None,
                 clock_ms: Callable[[], int] = lambda: int(time.time() * 1000)) -> None:
        host = httpx.URL(base_url).host
        if host in _FORBIDDEN_HOSTS or host not in _ALLOWED_HOSTS:
            raise ValueError("Only the Kalshi DEMO environment is supported; production is "
                             "disabled in code")
        if not base_url.endswith(API_PREFIX):
            raise ValueError("Base URL must end with /trade-api/v2")
        self._signer = signer
        self._clock_ms = clock_ms
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport,
                                  follow_redirects=False,
                                  headers={"Accept": "application/json",
                                           "User-Agent": "krt-local-research/0.1 (demo)"})

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, *, params: dict | None = None,
                 json_body: dict | None = None) -> httpx.Response:
        allowed = (method == "POST" and path == self._WRITE_PATH) or (
            method == "GET" and any(path.startswith(p) for p in self._READ_PATHS))
        if not allowed:
            raise ValueError(f"{method} {path} is not allowlisted")
        ts = self._clock_ms()
        req = self._http.build_request(method, path, params=params, json=json_body)
        req.headers.update(self._signer.headers(ts, method, req.url.path))
        return self._http.send(req)

    def _get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        try:
            r = self._request("GET", path, params=params)
        except httpx.HTTPError:
            raise GatewayError("network") from None
        if r.status_code != 200:
            raise GatewayError(f"http_{r.status_code}")
        return r.json()

    def get_market(self, ticker: str) -> dict[str, Any]:
        return self._get(f"/markets/{ticker}")["market"]

    def get_orderbook(self, ticker: str) -> dict[str, Any]:
        return self._get(f"/markets/{ticker}/orderbook")

    def get_balance_dollars(self) -> Decimal:
        return Decimal(str(self._get("/portfolio/balance")["balance_dollars"]))

    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            r = self._request("POST", self._WRITE_PATH, json_body=payload)
        except httpx.HTTPError:
            raise UnknownOutcome("network_or_timeout") from None
        if r.status_code == 201:
            return r.json()
        try:
            body = r.json()
            code = (body.get("error") or {}).get("code") or body.get("code") or "unknown"
        except (ValueError, AttributeError):
            code = "unparseable"
        if r.status_code in (408, 429) or r.status_code >= 500 or code == "order_already_exists":
            # 429 is a definitive non-placement per docs, but treating it as unknown and
            # reconciling is the conservative choice.
            raise UnknownOutcome(f"http_{r.status_code}:{code}")
        raise DefinitiveReject(r.status_code, str(code))

    def find_order(self, ticker: str, client_order_id: str, min_ts: int) -> dict[str, Any] | None:
        params = {"ticker": ticker, "min_ts": max(0, min_ts // 1000 - 5), "limit": 200}
        for o in self._get("/portfolio/orders", params).get("orders", []):
            if o.get("client_order_id") == client_order_id:
                return {"order_id": o.get("order_id"), "client_order_id": client_order_id,
                        "fill_count": o.get("fill_count_fp"),
                        "remaining_count": o.get("remaining_count_fp"),
                        "status": o.get("status"), "raw": json.loads(json.dumps(o))}
        return None
