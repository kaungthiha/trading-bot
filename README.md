# trading-bot — Kalshi Research Terminal (local)

A local-only research and paper-trading terminal for Kalshi event contracts. It **does not
place orders**. The full specification and milestone prompts live in
[`kalshi_research_terminal_fable_package_2026-11-18/kalshi_research_terminal_fable_package/`](kalshi_research_terminal_fable_package_2026-11-18/kalshi_research_terminal_fable_package/README.md).

**Status:** Milestones 01 (bootstrap) and 02 (Kalshi read-only market data) are done. The app
can show synthetic `MOCK-` fixture markets or real markets fetched from Kalshi's **public,
unauthenticated** market-data API. There are no credentials and no order routes.

## Requirements
- Python 3.12+ (tested on 3.14.4)
- Node.js 20+ (tested on 24.15.0)

## Setup (Windows PowerShell)
```powershell
.\scripts\setup.ps1          # venv + deps, DB migration, seeds the mock markets
```

## Run
```powershell
.\scripts\start-backend.ps1  # http://127.0.0.1:8000  (API docs: /api/docs)
.\scripts\start-frontend.ps1 # http://127.0.0.1:5173  (open this one in your browser)
```

## Fetch real Kalshi markets (read-only, no key)
```powershell
cd backend
.venv\Scripts\python -m app.cli ingest --source kalshi_public --series KXFED KXHIGHNY
```
Or set `KRT_MARKET_DATA_SOURCE=kalshi_public` and `KRT_KALSHI_SERIES_WATCHLIST=["KXFED"]` in
`.env`, then run `python -m app.cli ingest`. Each run fetches each series' metadata (which
supplies the category), its markets (paginated), and one orderbook snapshot per market. Quotes
are appended, never overwritten. Every run is recorded and shown at `/api/ingestion/runs` and
in the UI header, including per-market errors. Add `--demo` to use Kalshi's demo environment.

The client only sends GET requests to the two documented Kalshi hosts, on an allowlist of
`/markets`, `/events` and `/series` paths. It never sends auth headers or follows redirects.
On 429 or 5xx responses it retries with bounded exponential backoff, and it spaces requests at
least 0.25 s apart.

## Test
```powershell
.\scripts\test.ps1           # pytest + ruff, then tsc + vitest
```

Manual equivalents (from `backend/`): `.venv\Scripts\python -m pytest`,
`.venv\Scripts\python -m app.cli migrate|downgrade [rev]|seed-mock`.
From `frontend/`: `npm test`, `npm run typecheck`, `npm run build`.

## Secrets and API keys
- Copy `.env.example` to `.env` and fill in keys **only when a later milestone needs them**.
  Milestone 01 needs none. `.env`, `*.pem`, `*.key` and `secrets/` are git-ignored.
- Keep the Kalshi private key file **outside this repo**; only its path goes in `.env`.
- Keys are loaded as `SecretStr` on the backend. They never appear in logs (a redaction filter
  covers auth headers, API keys and PEM blocks), in API responses (`/api/health` reports only
  whether each key is configured, true/false), or in the browser bundle.
- Blank placeholders (`KRT_FRED_API_KEY=`) count as not configured.

## Safety rails (enforced in code and tests)
- The backend refuses to start on a non-loopback host, with a wildcard CORS origin or allowed host,
  with `KRT_TRADING_MODE` set to anything other than `paper`, or with `KRT_LIVE_EXECUTION_ENABLED=true`.
- Requests with a Host header other than `127.0.0.1`/`localhost` are rejected (DNS-rebinding
  defense). Cross-origin non-GET requests are rejected. Security headers are set on every response.
- No order or portfolio routes exist; a test asserts the API exposes only GET operations.
- Tests block all non-loopback network connections.

## Layout
```
backend/
  app/core/       config (fail-closed), clock, log redaction, HTTP security middleware
  app/domain/     immutable Pydantic types; Decimal pricing (derived asks, price grid, staleness)
  app/adapters/   ExchangeMarketDataAdapter protocol; fixture adapter; Kalshi public adapter
  app/db/         SQLAlchemy models, exact-decimal/UTC column types, append-only repository
  app/ingest.py   runs an adapter, persists snapshots, records ingestion_runs
  app/api/        /api/health, /api/markets (filters: category, status, series_ticker, q),
                  /api/markets/{id}, /api/markets/{id}/quotes, /api/categories,
                  /api/ingestion/runs; uniform error envelope
  alembic/        migrations (0001_initial, 0002_kalshi_read_only)
  tests/          80 tests (Kalshi tests use a mock HTTP transport; network is blocked)
frontend/
  src/api/        typed client (prices kept as exact decimal strings)
  src/glossary/   typed term registry (unknown IDs fail typecheck)
  src/components/ MarketList, MarketDetail, accessible <Term> tooltip
scripts/          PowerShell setup/start/test
```

## Pricing conventions
Kalshi's order book (`orderbook_fp.yes_dollars` / `no_dollars`) publishes only YES bids and NO
bids, sorted ascending so the best bid is the last element. Asks are **derived**:
`YES ask = payout − best NO bid` and `NO ask = payout − best YES bid`. Each derived ask is labeled
with its provenance. If the opposite side has no bid, the ask is `null`; the app never invents one.
Asks are derived only for `binary` markets. For `scalar` or unknown types the complement
relation hasn't been verified, so only bids are shown. On a live check (2026-11-18) the derived
asks matched Kalshi's own `yes_ask_dollars` / `no_ask_dollars` on every market sampled.
Prices are `Decimal` end to end and serialized as strings. Each market has its own price grid, so
there is no hard-coded 1¢ tick.
