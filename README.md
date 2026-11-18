# trading-bot — Kalshi Research Terminal (local)

A local-only research and paper-trading terminal for Kalshi event contracts. It **does not
place orders**. The full specification and milestone prompts live in
[`kalshi_research_terminal_fable_package_2026-11-18/kalshi_research_terminal_fable_package/`](kalshi_research_terminal_fable_package_2026-11-18/kalshi_research_terminal_fable_package/README.md).

**Status:** Milestones 01 (bootstrap), 02 (Kalshi read-only market data), 03 (evidence
pipeline) and 04 (probability models) are done.
- **Markets:** synthetic `MOCK-` fixture markets, or real markets from Kalshi's **public,
  unauthenticated** market-data API.
- **Evidence:** FRED/ALFRED economic series with full vintage history, so you can see exactly
  what was known at any past moment. CPI is first.
- No exchange credentials and no order routes.

> This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of
> St. Louis. See the [FRED API Terms of Use](https://fred.stlouisfed.org/docs/api/terms_of_use.html).

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

## Economic evidence (FRED, vintage-aware)
Put your key in `.env` as `KRT_FRED_API_KEY=...`, then:
```powershell
cd backend
.venv\Scripts\python -m app.cli ingest-evidence                       # sources in KRT_EVIDENCE_SOURCES
.venv\Scripts\python -m app.cli ingest-evidence --source fred:UNRATE  # one-off
```
- **Every vintage is kept.** Each stored row is one value for one period *as published on one
  date* (FRED's `realtime_start`). Revisions are added as new rows and never overwrite earlier
  ones. If FRED ever changes an already-stored vintage, the run reports a
  `VINTAGE_CONTENT_CHANGED` conflict and keeps the original.
- **Release time is part of availability.** `available_at` is the vintage date at the source
  agency's published release time: 08:30 US Eastern for BLS CPI and jobs data, converted
  correctly across daylight-saving changes. The as-of view
  (`/api/evidence/{id}/observations?as_of=...`) only returns values with `available_at` at or
  before the cutoff, so models and backtests can't see data before it was published.
- **Missing values stay missing.** FRED's `.` is stored as `missing`, never as 0.
- **Each run fetches the full history** (about 3k rows for CPI, around 2 s). Duplicates are
  skipped, so re-running is safe.
- **Your key stays private.** It is sent only to `api.stlouisfed.org`. Error messages never
  include URLs, and httpx's request logs pass through a redaction filter.
- **Only registered sources run.** `KRT_EVIDENCE_SOURCES` must list sources registered in
  `app/evidence/sources.py`. Each entry records its license notes and release-timing source.

## Probability models (CPI, milestone 04)
**Contract type (narrow by design):** headline CPI-U, seasonally adjusted, month-over-month %
change for the next reference month, *as first published*, rounded to 0.1, strictly above a
threshold T. Before applying this to any real market, read that market's official rules (SA vs
NSA, rounding, first release vs revised, strict vs inclusive).

```powershell
cd backend
.venv\Scripts\python -m app.cli evaluate-models            # walk-forward; stores reports
.venv\Scripts\python -m app.cli forecast-cpi --threshold 0.3 [--save]
```

| Model | What it does | Uncertainty |
|---|---|---|
| `base_rate` v1.0.0 | Share of the last 120 first prints that would have resolved YES | Jeffreys Beta posterior; 90% credible interval |
| `gaussian_trailing` v1.0.0 | Normal(mean of last 12, SD of last 36 first-print MoMs). Rounding is exact: rounded > T ⇔ x ≥ T+0.05 | Heuristic ±1 SE band on the mean (**not** a confidence interval) |

- **First prints are rebuilt from vintages.** Each month's change compares its first index
  with the previous month's index *from the same release*. Months whose earliest stored
  vintage arrives more than 60 days after the month ends aren't true first prints and are
  excluded; the excluded counts are reported.
- **No look-ahead in evaluation.** For each month, the cutoff is 1 s before its release, so
  the model sees only prints already public. Leakage checks raise errors instead of trusting
  the data. Hyperparameters were fixed in advance, not tuned. Dev (before 2015) and holdout
  (2015 onward) are reported separately, and the split is enforced.
- **Models abstain instead of guessing** on: insufficient history, a month already published,
  any month other than the next unreleased one, or a threshold off the 0.1 grid.
- **Results are reproducible.** The same inputs produce identical forecasts. Each forecast
  records its input hash, and each evaluation records its dataset hash. Stored forecasts and
  evaluations are immutable rows (`model_runs`, `model_evaluations`).

**Evaluation on real FRED data (run 2026-11-18, dataset `c6ff5fd82633`, thresholds −0.1…0.6):**

| Model | Period | Predictions | Months | Brier | Log loss |
|---|---|---|---|---|---|
| base_rate | holdout 2014-12 → 2026-10 | 1,120 | 140 | 0.1655 | 0.5076 |
| gaussian_trailing | holdout 2014-12 → 2026-10 | 1,120 | 140 | 0.1559 | 0.4784 |

These are forecast-quality scores, **not trading results**. Lower is better, and a constant
50% forecast scores 0.25 on Brier. Predictions within a month are correlated, so the number of
months is the effective sample size. The models use only past CPI prints and ignore energy
prices, nowcasts and consensus forecasts.

## Scheduled collection (worker)
```powershell
.\scripts\start-worker.ps1   # or: cd backend; .venv\Scripts\python -m app.worker
```
- Runs FRED refreshes every 6 h, plus Kalshi quotes every 15 min if
  `KRT_MARKET_DATA_SOURCE=kalshi_public` and a watchlist are set.
- Sleeps until the next job is due, with no busy loop, and waits 10 min before retrying a
  failed job.
- Only one worker can run at a time; a second one exits. This uses an OS file lock.
- **Gaps are recorded, not filled.** If the laptop sleeps or the worker is off, the gap
  appears in the UI and at `/api/collection-gaps`, marked *recoverable* (FRED: vintages are
  re-fetched) or *not recoverable* (Kalshi quote snapshots).

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
  app/adapters/http.py  shared hardened GET client (allowlists, backoff, no URL leaks)
  app/evidence/   source registry, FRED adapter, insert-only repository, as-of queries
  app/ingest.py   runs an adapter, persists snapshots, records ingestion_runs
  app/research/   CPI contract + first prints, models & cards, metrics, walk-forward
  app/worker.py   scheduled collector with gap detection and single-instance lock
  app/api/        /api/health, /api/markets (filters: category, status, series_ticker, q),
                  /api/markets/{id}, /api/markets/{id}/quotes, /api/categories,
                  /api/ingestion/runs, /api/evidence/sources,
                  /api/evidence/{id}/observations?as_of=, /api/evidence/{id}/vintages,
                  /api/collection-gaps, /api/models, /api/models/metrics,
                  /api/research/cpi-mom/forecast, /api/model-runs; uniform error envelope
  alembic/        migrations 0001_initial … 0004_models
  tests/          121 tests (HTTP via mock transports; network is blocked)
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
