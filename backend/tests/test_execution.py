"""Adversarial tests for approval-gated execution (milestone 09).

Acceptance: replay/duplicate approvals rejected; changed price fails closed; ambiguous
timeout never blind-retries; demo-gateway behaviour tested with a mock transport (no
network); production disabled by default and not configurable.
"""

from __future__ import annotations

import ast
import base64
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import literal_column, select, text
from sqlalchemy.exc import DatabaseError

from app.core.clock import FrozenClock
from app.core.config import REPO_ROOT, Settings
from app.db.models import ExecutionEvent, ExecutionIntent, Market
from app.db.repositories import MarketRepository
from app.db.session import make_engine, make_session_factory
from app.execution.factory import sync_mock_from_db
from app.execution.gateway import (
    DefinitiveReject,
    KalshiDemoGateway,
    MockExchange,
    UnknownOutcome,
)
from app.execution.service import (
    ExecutionError,
    IntentRequest,
    approve_and_submit,
    build_payload,
    create_intent,
    hash_pin,
    reconcile,
    set_kill_switch,
    verify_pin,
)
from app.execution.signing import Signer
from app.main import create_app
from tests.test_signals import NOW, kxcpi_snapshot, schedule

D = Decimal
PIN = "246813"
TICKER = "KXCPI-24JAN-T0.2"


# --- Fixtures ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pin_hash() -> str:
    return hash_pin(PIN)


@pytest.fixture
def xsettings(settings: Settings, pin_hash: str) -> Settings:
    return Settings(_env_file=None, database_url=settings.database_url, execution_enabled=True,
                    execution_env="mock", execution_approval_pin_hash=pin_hash)


@pytest.fixture
def db(xsettings: Settings):  # type: ignore[no-untyped-def]
    engine = make_engine(xsettings.database_url)
    f = make_session_factory(engine)
    with f() as s:
        # quote observed NOW-10s; fresh for the 15s execution limit. YES ask 0.45 (NO bid 0.55)
        MarketRepository(s, FrozenClock(NOW)).upsert_snapshot(kxcpi_snapshot(), "kalshi_public")
        set_kill_switch(s, NOW - timedelta(minutes=1), engage=False, actor="test", reason="")
        s.commit()
    yield f
    engine.dispose()


def mid(s) -> str:  # type: ignore[no-untyped-def]
    return s.scalar(select(Market.id).where(Market.external_ticker == TICKER))


def mock_for(s, **kw) -> MockExchange:  # type: ignore[no-untyped-def]
    return sync_mock_from_db(MockExchange(clock_ms=lambda: int(NOW.timestamp() * 1000), **kw), s)


def propose(s, settings, side="YES", qty="10", limit="0.46", at=NOW):  # type: ignore[no-untyped-def]
    return create_intent(s, settings, IntentRequest(mid(s), side, D(qty), D(limit)), at,
                         schedules=[schedule()])


def approve(s, settings, intent, gw, pin=PIN, at=NOW, h=None):  # type: ignore[no-untyped-def]
    return approve_and_submit(s, settings, intent.id, h or intent.payload_hash, pin, gw, at,
                              schedules=[schedule()])


def kinds(s, intent_id: str) -> list[str]:  # type: ignore[no-untyped-def]
    return [e.kind for e in s.scalars(select(ExecutionEvent).where(
        ExecutionEvent.intent_id == intent_id).order_by(
        ExecutionEvent.at, literal_column("execution_events.rowid")))]


# --- PIN, payload, signing -------------------------------------------------------------


def test_pin_hashing(pin_hash: str) -> None:
    assert pin_hash.startswith("scrypt$") and PIN not in pin_hash
    assert verify_pin(PIN, pin_hash) and not verify_pin("246814", pin_hash)
    assert not verify_pin(PIN, "garbage") and not verify_pin(PIN, "md5$x$y$z$a$b")
    with pytest.raises(ValueError):
        hash_pin("123")
    assert hash_pin(PIN) != pin_hash  # salted


def test_payload_maps_to_yes_leg_v2_schema() -> None:
    yes = build_payload(TICKER, "YES", D(10), D("0.46"), "krt-a")
    assert yes == {"ticker": TICKER, "client_order_id": "krt-a", "side": "bid",
                   "count": "10.00", "price": "0.4600", "time_in_force": "immediate_or_cancel",
                   "self_trade_prevention_type": "taker_at_cross", "reduce_only": False}
    no = build_payload(TICKER, "NO", D(3), D("0.40"), "krt-b")
    assert (no["side"], no["price"]) == ("ask", "0.6000")  # buy NO @0.40 == sell YES @0.60


def _verify(key, sig_b64: str, message: bytes) -> None:  # type: ignore[no-untyped-def]
    sig = base64.b64decode(sig_b64)
    if isinstance(key, rsa.RSAPrivateKey):
        key.public_key().verify(sig, message, padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256())
    else:
        key.public_key().verify(sig, message)


@pytest.mark.parametrize("key", [rsa.generate_private_key(public_exponent=65537, key_size=2048),
                                 ed25519.Ed25519PrivateKey.generate()])
def test_signature_matches_documented_scheme(key, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    pem = tmp_path / "k.pem"
    pem.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                      serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    signer = Signer.from_pem_file("key-id", pem)
    h = signer.headers(1703123456789, "get",
                       "https://external-api.demo.kalshi.co/trade-api/v2/portfolio/orders?limit=5")
    assert h["KALSHI-ACCESS-KEY"] == "key-id" and h["KALSHI-ACCESS-TIMESTAMP"] == "1703123456789"
    _verify(key, h["KALSHI-ACCESS-SIGNATURE"], b"1703123456789GET/trade-api/v2/portfolio/orders")
    assert "PRIVATE" not in repr(signer) and "key-id" not in repr(signer)


# --- Demo gateway (mock transport; no network) ---------------------------------------------


def demo_gateway(handler):  # type: ignore[no-untyped-def]
    key = ed25519.Ed25519PrivateKey.generate()
    seen: list[httpx.Request] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return handler(req)

    gw = KalshiDemoGateway(Signer("demo-key", key), transport=httpx.MockTransport(h),
                           clock_ms=lambda: 1700000000000)
    return gw, seen, key


def test_demo_gateway_refuses_production_and_unlisted_paths() -> None:
    key = ed25519.Ed25519PrivateKey.generate()
    for base in ("https://external-api.kalshi.com/trade-api/v2",
                 "https://api.elections.kalshi.com/trade-api/v2", "https://evil.example/trade-api/v2"):
        with pytest.raises(ValueError, match="DEMO"):
            KalshiDemoGateway(Signer("k", key), base)
    gw, seen, _ = demo_gateway(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        gw._request("DELETE", "/portfolio/events/orders/x")
    with pytest.raises(ValueError):
        gw._request("POST", "/api_keys")
    assert seen == []


def test_demo_create_order_is_signed_and_sent_once() -> None:
    gw, seen, key = demo_gateway(lambda r: httpx.Response(201, json={
        "order_id": "o1", "fill_count": "10.00", "remaining_count": "0.00", "ts_ms": 1}))
    out = gw.create_order(build_payload(TICKER, "YES", D(10), D("0.46"), "krt-x"))
    assert out["order_id"] == "o1" and len(seen) == 1
    req = seen[0]
    assert req.url.host == "external-api.demo.kalshi.co"
    assert req.url.path == "/trade-api/v2/portfolio/events/orders" and req.method == "POST"
    _verify(key, req.headers["KALSHI-ACCESS-SIGNATURE"],
            b"1700000000000POST/trade-api/v2/portfolio/events/orders")


@pytest.mark.parametrize("resp,expected", [
    (httpx.Response(500, json={"error": {"code": "internal"}}), UnknownOutcome),
    (httpx.Response(504), UnknownOutcome),
    (httpx.Response(409, json={"error": {"code": "order_already_exists"}}), UnknownOutcome),
    (httpx.Response(400, json={"error": {"code": "insufficient_balance"}}), DefinitiveReject),
    (httpx.Response(409, json={"error": {"code": "market_inactive"}}), DefinitiveReject),
])
def test_demo_error_classification_without_retry(resp, expected) -> None:  # type: ignore[no-untyped-def]
    gw, seen, _ = demo_gateway(lambda r: resp)
    with pytest.raises(expected):
        gw.create_order(build_payload(TICKER, "YES", D(1), D("0.5"), "krt-y"))
    assert len(seen) == 1  # never retried


def test_demo_timeout_is_unknown_and_not_retried() -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("t", request=req)
    gw, seen, _ = demo_gateway(boom)
    with pytest.raises(UnknownOutcome):
        gw.create_order(build_payload(TICKER, "YES", D(1), D("0.5"), "krt-z"))
    assert len(seen) == 1


# --- Config: production cannot be configured; keys outside repo ------------------------


def test_production_is_not_configurable() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, execution_env="production")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, live_execution_enabled=True)
    s = Settings(_env_file=None)
    assert s.execution_enabled is False and s.execution_env.value == "mock"


def test_private_key_inside_repo_rejected() -> None:
    with pytest.raises(ValidationError, match="OUTSIDE"):
        Settings(_env_file=None, kalshi_demo_private_key_path=REPO_ROOT / "demo.pem")


# --- Intent creation gates -------------------------------------------------------------


def test_intent_requires_enabled_and_released_kill_switch(db, settings: Settings,
                                                          xsettings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        with pytest.raises(ExecutionError, match="EXECUTION_DISABLED"):
            propose(s, settings)  # default settings: execution off
        set_kill_switch(s, NOW, engage=True, actor="t", reason="")
        with pytest.raises(ExecutionError, match="KILL_SWITCH_ENGAGED"):
            propose(s, xsettings)


@pytest.mark.parametrize("kw,code", [
    ({"qty": "11"}, "CAP_CONTRACTS_PER_ORDER"),
    ({"limit": "0.455"}, "LIMIT_OFF_GRID"),
    ({"qty": "2.5"}, "INVALID_QUANTITY"),
    ({"at": NOW + timedelta(seconds=10)}, "QUOTE_STALE"),  # quote now 20s old > 15s
])
def test_intent_validation(db, xsettings, kw, code) -> None:  # type: ignore[no-untyped-def]
    with db() as s, pytest.raises(ExecutionError, match=code):
        propose(s, xsettings, **kw)


def test_cost_and_daily_caps(db, xsettings: Settings) -> None:  # type: ignore[no-untyped-def]
    tight = xsettings.model_copy(update={"execution_max_cost_per_order": D("1")})
    with db() as s, pytest.raises(ExecutionError, match="CAP_COST_PER_ORDER"):
        propose(s, tight)
    daily = xsettings.model_copy(update={"execution_max_daily_cost": D("5")})
    with db() as s:
        i = propose(s, daily)  # max cost ~4.78
        approve(s, daily, i, mock_for(s))
        with pytest.raises(ExecutionError, match="CAP_DAILY_COST"):
            propose(s, daily, qty="1")


def test_unverified_fees_block_intent(db, xsettings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s, pytest.raises(ExecutionError, match="FEES_UNVERIFIED"):
        create_intent(s, xsettings, IntentRequest(mid(s), "YES", D(1), D("0.46")), NOW,
                      schedules=[schedule(verified=False)])


def test_intent_terms_are_immutable_in_db(db, xsettings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        i = propose(s, xsettings)
        s.commit()
        for col in ("payload_json", "limit_price", "quantity", "max_cost", "client_order_id"):
            with pytest.raises(DatabaseError, match="immutable"):
                s.execute(text(f"UPDATE execution_intents SET {col} = 'x' WHERE id = :i"),
                          {"i": i.id})
            s.rollback()
        with pytest.raises(DatabaseError, match="append-only"):
            s.execute(text("DELETE FROM execution_events"))


# --- Approval & submission -------------------------------------------------------------


def test_happy_path_fills_once_with_full_audit_trail(db, xsettings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        i = propose(s, xsettings)
        gw = mock_for(s)
        out = approve(s, xsettings, i, gw)
        assert out.status == "FILLED" and gw.create_calls == 1
        sent = gw.orders[0]
        assert sent["client_order_id"] == i.client_order_id
        assert kinds(s, i.id) == ["INTENT_CREATED", "APPROVED", "PREFLIGHT_PASSED", "SUBMITTING",
                                  "EXCHANGE_RECORDED"]


def test_replay_and_duplicate_approvals_rejected(db, xsettings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        i = propose(s, xsettings)
        gw = mock_for(s)
        approve(s, xsettings, i, gw)
        for _ in range(2):
            with pytest.raises(ExecutionError, match="ALREADY_USED"):
                approve(s, xsettings, i, gw)
        assert gw.create_calls == 1
        assert kinds(s, i.id).count("APPROVAL_REPLAY_REJECTED") == 2


def test_hash_mismatch_rejected_and_does_not_consume_approval(db, xsettings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        i = propose(s, xsettings)
        gw = mock_for(s)
        with pytest.raises(ExecutionError, match="HASH_MISMATCH"):
            approve(s, xsettings, i, gw, h="0" * 64)
        assert s.get(ExecutionIntent, i.id).status == "PROPOSED" and gw.create_calls == 0
        assert approve(s, xsettings, i, gw).status == "FILLED"


def test_wrong_pin_and_lockout(db, xsettings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        i = propose(s, xsettings)
        gw = mock_for(s)
        for _ in range(5):
            with pytest.raises(ExecutionError, match="PIN_INVALID"):
                approve(s, xsettings, i, gw, pin="000000")
        with pytest.raises(ExecutionError, match="PIN_LOCKED_OUT"):
            approve(s, xsettings, i, gw)  # even the right PIN is refused now
        assert gw.create_calls == 0
        later = NOW + timedelta(minutes=16)
        with pytest.raises(ExecutionError, match="EXPIRED"):  # lockout over; intent expired
            approve(s, xsettings, i, gw, at=later)


def test_no_pin_configured(db, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    nopin = Settings(_env_file=None, database_url=settings.database_url,
                     execution_enabled=True)
    with db() as s:
        i = propose(s, nopin)
        with pytest.raises(ExecutionError, match="PIN_NOT_CONFIGURED"):
            approve(s, nopin, i, mock_for(s))


def test_expired_intent(db, xsettings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        i = propose(s, xsettings)
        with pytest.raises(ExecutionError, match="EXPIRED"):
            approve(s, xsettings, i, mock_for(s), at=NOW + timedelta(seconds=61))
        assert s.get(ExecutionIntent, i.id).status == "EXPIRED"


def _worsen(gw: MockExchange, no_bid: str) -> None:
    gw.books[TICKER] = {"orderbook_fp": {"yes_dollars": [["0.4000", "100.00"]],
                                         "no_dollars": [[no_bid, "100.00"]]}}


def test_changed_price_fails_closed(db, xsettings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        i = propose(s, xsettings)  # approved ask 0.45
        gw = mock_for(s)
        _worsen(gw, "0.5400")  # YES ask now 0.46 -- still within the limit, but worse
        out = approve(s, xsettings, i, gw)
        assert (out.status, out.block_reason) == ("BLOCKED", "PRICE_CHANGED")
        assert gw.create_calls == 0


def test_improved_price_still_allowed(db, xsettings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        i = propose(s, xsettings)
        gw = mock_for(s)
        _worsen(gw, "0.5600")  # YES ask 0.44: better than approved
        assert approve(s, xsettings, i, gw).status == "FILLED"


@pytest.mark.parametrize("mutate,reason", [
    (lambda g: g.markets[TICKER].update(status="closed"), "MARKET_NOT_ACTIVE"),
    (lambda g: g.markets[TICKER].update(rules_primary="EDITED RULES"), "RULES_CHANGED"),
    (lambda g: g.books.update({TICKER: {"orderbook_fp": {"yes_dollars": [],
                                                          "no_dollars": []}}}), "NO_LIQUIDITY"),
    (lambda g: setattr(g, "balance", D("1")), "INSUFFICIENT_BALANCE"),
    (lambda g: setattr(g, "env", "demo"), "ENV_MISMATCH"),
])
def test_preflight_blocks(db, xsettings, mutate, reason) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        i = propose(s, xsettings)
        gw = mock_for(s)
        mutate(gw)
        out = approve(s, xsettings, i, gw)
        assert (out.status, out.block_reason) == ("BLOCKED", reason)
        assert gw.create_calls == 0


def test_kill_switch_engaged_after_approval_window_opens(db, xsettings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        i = propose(s, xsettings)
        set_kill_switch(s, NOW, engage=True, actor="t", reason="panic")
        out = approve(s, xsettings, i, mock_for(s))
        assert (out.status, out.block_reason) == ("BLOCKED", "KILL_SWITCH_ENGAGED")


def test_timeout_before_accept_is_unknown_and_never_resubmitted(db, xsettings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        i = propose(s, xsettings)
        gw = mock_for(s, faults=["timeout_before_accept"])
        out = approve(s, xsettings, i, gw)
        assert out.status == "UNKNOWN" and gw.create_calls == 1
        for _ in range(3):  # later reconciliations are read-only
            assert reconcile(s, i.id, gw, NOW).status == "UNKNOWN"
        assert gw.create_calls == 1
        k = kinds(s, i.id)
        assert "OUTCOME_UNKNOWN" in k and k.count("RECONCILE_NOT_FOUND") == 4
        # Unknown counts against the position cap as if filled.
        with pytest.raises(ExecutionError, match="CAP_POSITION"):
            propose(s, xsettings.model_copy(update={"execution_max_position_contracts": 15}))


def test_timeout_after_accept_is_reconciled_without_resubmission(db, xsettings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        i = propose(s, xsettings)
        gw = mock_for(s, faults=["timeout_after_accept"])
        out = approve(s, xsettings, i, gw)
        assert out.status == "FILLED" and gw.create_calls == 1
        assert "OUTCOME_UNKNOWN" in kinds(s, i.id)
        from app.db.models import ExchangeOrder
        eo = s.scalar(select(ExchangeOrder).where(ExchangeOrder.intent_id == i.id))
        assert eo.source == "reconciliation" and eo.fill_count == D("10.00")


@pytest.mark.parametrize("fault,status,reason", [
    ("http_500", "UNKNOWN", "http_500"),
    ("duplicate", "UNKNOWN", "order_already_exists"),
    ("insufficient_balance", "REJECTED", "insufficient_balance"),
    ("market_inactive", "REJECTED", "market_inactive"),
])
def test_exchange_failures(db, xsettings, fault, status, reason) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        i = propose(s, xsettings)
        gw = mock_for(s, faults=[fault])
        out = approve(s, xsettings, i, gw)
        assert (out.status, out.block_reason) == (status, reason)
        assert gw.create_calls == 1


def test_ioc_unfilled_is_not_filled(db, xsettings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        i = propose(s, xsettings, limit="0.44")  # below the 0.45 ask
        out = approve(s, xsettings, i, mock_for(s))
        assert out.status == "NOT_FILLED"


def test_concurrent_second_session_cannot_reuse_approval(db, xsettings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s1:
        i = propose(s1, xsettings)
        s1.commit()
        gw = mock_for(s1)
        approve(s1, xsettings, i, gw)
    with db() as s2:
        i2 = s2.get(ExecutionIntent, i.id)
        with pytest.raises(ExecutionError, match="ALREADY_USED"):
            approve(s2, xsettings, i2, gw)
    assert gw.create_calls == 1


# --- API ------------------------------------------------------------------------------


def test_execution_api_flow_and_csrf(db, xsettings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        market_id = mid(s)
    app = create_app(xsettings, FrozenClock(NOW))
    hdr = {"X-KRT-Request": "execution"}
    with TestClient(app, base_url="http://127.0.0.1") as c:
        st = c.get("/api/execution/status").json()
        assert st["production"].startswith("not implemented") and st["env"] == "mock"
        body = {"market_id": market_id, "side": "YES", "quantity": 5, "limit_price": "0.46"}
        assert c.post("/api/execution/intents", json=body).status_code == 403
        evil = c.post("/api/execution/intents", json=body,
                      headers={**hdr, "Origin": "https://evil.example"})
        assert evil.status_code == 403
        r = c.post("/api/execution/intents", json=body, headers=hdr)
        assert r.status_code == 201, r.text
        intent = r.json()
        assert intent["status"] == "PROPOSED" and "MOCK" in intent["summary"]
        bad = c.post(f"/api/execution/intents/{intent['id']}/approve", headers=hdr,
                     json={"payload_hash": intent["payload_hash"], "pin": "999999"})
        assert bad.status_code == 403 and bad.json()["error"]["code"] == "PIN_INVALID"
        ok = c.post(f"/api/execution/intents/{intent['id']}/approve", headers=hdr,
                    json={"payload_hash": intent["payload_hash"], "pin": PIN})
        assert ok.status_code == 200 and ok.json()["status"] == "FILLED", ok.text
        again = c.post(f"/api/execution/intents/{intent['id']}/approve", headers=hdr,
                       json={"payload_hash": intent["payload_hash"], "pin": PIN})
        assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_USED"
        detail = c.get(f"/api/execution/intents/{intent['id']}").json()
        assert detail["exchange_order"]["fill_count"] == "5.00"
        assert [e["kind"] for e in detail["events"]][-2:] == [
            "EXCHANGE_RECORDED", "APPROVAL_REPLAY_REJECTED"]  # the replay is audited too
        assert c.post("/api/execution/kill-switch", json={"reason": "t"},
                      headers=hdr).json()["kill_switch_engaged"] is True
        assert c.get("/api/execution/status").json()["kill_switch_engaged"] is True
        paths = c.get("/api/openapi.json").json()["paths"]
        assert not any("release" in p for p in paths)  # release is CLI-only
    app.state.engine.dispose()


# --- Isolation -------------------------------------------------------------------------


def test_research_signals_paper_never_import_execution() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    for pkg in ("research", "signals", "paper", "evidence", "adapters", "domain"):
        for py in (root / pkg).glob("*.py"):
            for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                    [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                assert not any(m.startswith("app.execution") for m in mods), f"{pkg}/{py.name}"


def test_no_secrets_in_status_or_events(db, xsettings: Settings) -> None:  # type: ignore[no-untyped-def]
    with db() as s:
        i = propose(s, xsettings)
        approve(s, xsettings, i, mock_for(s))
        blob = json.dumps([e.detail_json for e in s.scalars(select(ExecutionEvent))])
        assert PIN not in blob and "scrypt$" not in blob
