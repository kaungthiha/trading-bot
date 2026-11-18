# Kalshi API Research Notes — Reverify When Coding

**Checked against documentation referenced 2026-11-18.** All exchange schemas evolve; official docs have priority.

## Environments
Production REST base: `https://external-api.kalshi.com/trade-api/v2` (confirm current). Demo REST base: `https://external-api.demo.kalshi.co/trade-api/v2` (confirm current). Separate environments/credentials; demo money and behavior are not real-market evidence. See [API environments](https://docs.kalshi.com/getting_started/api_environments.md) and [demo](https://docs.kalshi.com/getting_started/demo_env.md).

## Read-only MVP
Official docs describe public unauthenticated market-data surfaces for series/events/markets/orderbooks. Start with read-only market discovery and quotes; do not ask for user trading keys for these steps. [Market data quick start](https://docs.kalshi.com/getting_started/quick_start_market_data.md).

## Orderbook semantics
Current docs describe orderbook **YES bids and NO bids**, not direct YES/NO asks. Derive `YES ask = $1.00 - best NO bid`, `NO ask = $1.00 - best YES bid`, subject to exact market structure, missing levels and price ranges. Store each derived ask with provenance. [Orderbook responses](https://docs.kalshi.com/getting_started/orderbook_responses.md).

## Fixed-point fields
Current guidance uses price strings allowing up to four decimal places, quantity strings with fractional contracts where supported, and market-specific `price_ranges`. Parse with `Decimal`, verify each market's grid, and avoid older cent-integer fields without explicit schema checking. [Fixed-point migration](https://docs.kalshi.com/getting_started/fixed_point_migration.md).

## Auth and writes (future ONLY)
Signed authenticated requests use access-key ID, timestamp and signature; documentation discusses RSA-PSS/SHA-256 and Ed25519 methods. Sign exact documented timestamp/method/path fields; never expose signatures in browser. [Authenticated requests](https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md). Current docs point to `POST /portfolio/events/orders` as create-order V2; older write path `/portfolio/orders` may return 410. Reverify [Create Order V2](https://docs.kalshi.com/api-reference/orders/create-order-v2.md) before implementing.

## Rate limits/history/fees
Token-bucket read/write budgets, endpoint-specific costs, HTTP 429 handling and headers should be dynamically respected; do not hardcode a universal requests-per-second budget. [Rate limits](https://docs.kalshi.com/getting_started/rate_limits.md). Historic archives may be separated from live market data by cutoff; [Historical data](https://docs.kalshi.com/getting_started/historical_data.md). Fees differ by market/type and can include rounding/rebates; verify exact current documented calculation and source schedule rather than using one hardcoded percentage. [Fee rounding](https://docs.kalshi.com/getting_started/fee_rounding.md).

## Mandatory adapter verification checklist
Actual routes, pagination cursors, quote field names, lifecycle statuses, market-specific allowed price ranges, field precisions, per-market fee terms, auth method, error shapes, 429 behavior, history cutoff, backfill availability, licenses and policy. Keep captured API fixtures with timestamp and redact sensitive fields. Never touch live order routes in prompts 01–08.
