from fastapi.testclient import TestClient

WRITE_ROUTES = {
    ("/api/paper/orders", "post"),  # simulated paper orders
    ("/api/execution/intents", "post"),  # propose (mock/demo only)
    ("/api/execution/intents/{intent_id}/approve", "post"),  # PIN-gated approval
    ("/api/execution/intents/{intent_id}/reconcile", "post"),  # read-only lookup
    ("/api/execution/kill-switch", "post"),  # engage only
    ("/api/opportunities/{opportunity_id}/journal", "post"),  # record YOUR manual trades
    ("/api/jobs/{name}/run", "post"),  # UI buttons: refresh / FRED / scan
    ("/api/jobs/auto-scan", "post"),  # UI auto-scan toggle
    ("/api/games/review", "post"),  # optional paid AI second opinion (CSRF + daily cap)
    ("/api/games/news", "post"),  # "Headlines here": one Brave request (CSRF + app-wide cap)
    ("/api/history/coach", "post"),  # local AI coach (CSRF header; Ollama on loopback)
    ("/api/history/open/review", "post"),  # local AI read of open positions (CSRF)
    ("/api/research/investigations", "post"),  # on-demand pick research (CSRF)
    ("/api/research/investigations/{inv_id}/refresh", "post"),
    ("/api/games/{prefix}/{key}/ideas/ai", "post"),  # local AI picks from screened ideas
}


def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["trading_mode"] == "paper"
    assert body["live_execution_enabled"] is False
    assert body["database"] == "ok"
    assert all(v is False for v in body["credentials_configured"].values())
    assert r.headers["x-content-type-options"] == "nosniff"


def test_list_markets(client: TestClient) -> None:
    r = client.get("/api/markets")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 4
    assert all(i["is_mock"] and i["external_ticker"].startswith("MOCK-") for i in items)


def test_category_filter_and_validation(client: TestClient) -> None:
    r = client.get("/api/markets", params={"category": "economics"})
    assert {i["category"] for i in r.json()["items"]} == {"economics"}
    bad = client.get("/api/markets", params={"category": "x' OR 1=1"})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.get("/api/markets", params={"limit": 0}).status_code == 422
    assert client.get("/api/markets", params={"limit": 201}).status_code == 422


def test_pagination(client: TestClient) -> None:
    page1 = client.get("/api/markets", params={"limit": 2}).json()["items"]
    page2 = client.get("/api/markets", params={"limit": 2, "offset": 2}).json()["items"]
    assert len(page1) == len(page2) == 2
    assert {m["id"] for m in page1}.isdisjoint({m["id"] for m in page2})


def _by_ticker(client: TestClient, ticker: str) -> dict:
    items = client.get("/api/markets").json()["items"]
    return next(i for i in items if i["external_ticker"] == ticker)


def test_market_detail_prices_are_exact_strings(client: TestClient) -> None:
    m = _by_ticker(client, "MOCK-CPIYOY-26DEC-T3.0")
    d = client.get(f"/api/markets/{m['id']}").json()
    q = d["quote"]
    prices = (q["yes_bid"], q["no_bid"], q["yes_ask"], q["no_ask"])
    assert prices == ("0.43", "0.55", "0.45", "0.57")
    assert q["yes_ask_provenance"] == "derived_from_complementary_bid"
    assert q["is_stale"] is False  # observed 30s before frozen now, max age 60s
    assert d["rules"]["text"].startswith("SYNTHETIC RULES")
    assert len(d["rules"]["hash"]) == 64
    assert d["yes_bids"][0] == {"price": "0.43", "quantity": "120"}


def test_stale_and_one_sided_quote(client: TestClient) -> None:
    m = _by_ticker(client, "MOCK-TECHREL-26DEC-SHIP")
    q = m["quote"]
    assert q["is_stale"] is True
    assert q["yes_ask"] is None and q["yes_ask_provenance"] is None
    assert q["no_ask"] == "0.80"


def test_unknown_market_404(client: TestClient) -> None:
    r = client.get("/api/markets/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_untrusted_host_header_rejected(client: TestClient) -> None:
    r = client.get("/api/health", headers={"host": "evil.example"})
    assert r.status_code == 400


def test_cors_only_for_allowed_origin(client: TestClient) -> None:
    ok = client.get("/api/health", headers={"origin": "http://127.0.0.1:5173"})
    assert ok.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
    bad = client.get("/api/health", headers={"origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers


def test_cross_origin_post_blocked(client: TestClient) -> None:
    r = client.post("/api/markets", headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"


def test_no_exchange_order_routes_and_only_paper_post(client: TestClient) -> None:
    paths = client.get("/api/openapi.json").json()["paths"]
    assert "/api/markets" in paths  # sanity: schema is populated
    assert not any("portfolio" in p for p in paths)
    writes = {(p, m) for p, ops in paths.items() for m in ops if m != "get"}
    # The only state-changing route SIMULATES orders locally (milestone 06).
    assert writes == WRITE_ROUTES


def test_glossary_endpoint_serves_exported_registry(client: TestClient) -> None:
    body = client.get("/api/glossary").json()
    assert body["count"] >= 42 and body["source"].endswith("terms.ts")
    ids = [t["id"] for t in body["terms"]]
    assert len(ids) == len(set(ids))
    for required in ("edge", "slippage", "brier-score", "bid", "abstention"):
        assert required in ids
    assert all(t["shortDefinition"] and t["deepExplanation"] for t in body["terms"])
    hits = client.get("/api/glossary", params={"q": "EV"}).json()["terms"]
    assert "expected-value" in [t["id"] for t in hits]


def test_paper_mode_is_enforced_end_to_end(client: TestClient) -> None:
    """Acceptance (08): paper mode enforced -- config, health, diagnostics and routes agree."""
    h = client.get("/api/health").json()
    assert h["trading_mode"] == "paper" and h["live_execution_enabled"] is False
    d = client.get("/api/diagnostics").json()["safety"]
    assert d == {"trading_mode": "paper", "live_execution_enabled": False}
    paths = client.get("/api/openapi.json").json()["paths"]
    assert not any(k in p for p in paths for k in ("portfolio", "exchange", "live", "execute"))
