# trading-bot — Kalshi Research Terminal (local)

A local-only research and paper-trading terminal for Kalshi event contracts. It **does not
place orders**. The full specification and milestone prompts live in
[`kalshi_research_terminal_fable_package_2026-11-18/kalshi_research_terminal_fable_package/`](kalshi_research_terminal_fable_package_2026-11-18/kalshi_research_terminal_fable_package/README.md).

**Status:** milestones 01–08 are complete. The spec's optional milestone 09 (live execution)
has **not** been started; it needs a separate decision from you.
- **Markets:** synthetic `MOCK-` fixture markets, or real markets from Kalshi's **public,
  unauthenticated** market-data API.
- **Evidence:** FRED/ALFRED economic series with full vintage history, so you can see exactly
  what was known at any past moment. CPI is first.
- **Research:** models, fee-aware signals and paper trading, every step traceable to its data.
- No exchange credentials, no real orders, and paper mode is enforced.

> This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of
> St. Louis. See the [FRED API Terms of Use](https://fred.stlouisfed.org/docs/api/terms_of_use.html).

## Windows quick start
**Requirements:** Python 3.12+ (tested on 3.14.4) and Node.js 20+ (tested on 24.15.0), both on
`PATH`. Use Windows PowerShell, for example VS Code → Terminal → New Terminal.

```powershell
# 0. Once, if PowerShell says "running scripts is disabled on this system":
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 1. Install everything (locked versions; safe to re-run)
.\scripts\setup.ps1

# 2a. Explore offline with synthetic data (no keys, no network):
.\scripts\start-demo.ps1        # terminal 1
.\scripts\start-frontend.ps1    # terminal 2, then open http://127.0.0.1:5173

# 2b. ...or run with your real data:
.\scripts\start-backend.ps1     # terminal 1  (API docs at http://127.0.0.1:8000/api/docs)
.\scripts\start-frontend.ps1    # terminal 2
.\scripts\start-worker.ps1      # optional terminal 3: scheduled data refresh

# 3. Verify the installation (all tests, build, bundle scan)
.\scripts\test.ps1
```
In the app, the **Getting started** checklist tells you the next command to run until setup
is complete. Stop any server with Ctrl+C.

**Troubleshooting**

| Symptom | Fix |
|---|---|
| `error while attempting to bind on address ('127.0.0.1', 8000)` / Vite "port 5173 is in use" | An earlier backend or frontend is still running. Close its terminal or press Ctrl+C there. To find it: `Get-NetTCPConnection -LocalPort 8000,5173 -State Listen` |
| New panels missing after updating | Restart both servers. The backend runs database migrations on start. |
| `running scripts is disabled` | Run step 0 above, or use `powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1` |
| `Another worker holds worker.lock` | A worker is already running. Only one is allowed. |
| Signals all say `FEE_SCHEDULE_UNVERIFIED` | Expected until you verify fees. See *Signals* below. |
| `restore`/`reset` says the database is in use | Stop the backend and worker first. Your data was already backed up. |

## Your data: backup, restore, reset
```powershell
cd backend
.venv\Scripts\python -m app.cli backup                 # -> backend\data\backups\
.venv\Scripts\python -m app.cli list-backups
.venv\Scripts\python -m app.cli restore <file> --yes   # current data is backed up first
.venv\Scripts\python -m app.cli reset --yes            # backs up, then starts empty
```
Backups use SQLite's online backup API, so they're consistent even while the app runs. Restore
checks that the file is a valid database from this app, refuses while the worker is running,
and upgrades older backups to the current schema. Everything lives in `backend/data/`, which
git ignores. The demo uses its own `demo.sqlite3` and never touches your real database.

## Traceability and health
- **Lineage:** every signal card has **Trace lineage**, also available as
  `GET /api/lineage/signal/{id}` and `GET /api/lineage/paper-order/{id}`. It shows the quote
  snapshot and the ingestion run that captured it, the exact rules version, the mapping
  decision, the model run, and the exact FRED vintages used. A leakage check confirms that
  every input was published before the model's cutoff. It also shows the evaluation that
  validated the model and the fee schedule version.
- **Health panel** (`GET /api/diagnostics`): last run and failures per source, top error
  codes, quote freshness, collection gaps, signal reason counts, schema version, and database
  size.

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

## Signals (milestone 05): research hypotheses, never orders
```powershell
cd backend
.venv\Scripts\python -m app.cli ingest --source kalshi_public --series KXCPI   # markets + fees
.venv\Scripts\python -m app.cli propose-mappings                                # parser proposes
.venv\Scripts\python -m app.cli list-mappings                                   # read the notes
.venv\Scripts\python -m app.cli confirm-mapping KXCPI-26NOV-T0.3 --yes          # YOUR decision
.venv\Scripts\python -m app.cli generate-signals
```
**Mappings (human in the loop).** The parser recognises the two live `KXCPI` rule templates
("more than X% … as reported to one decimal place" and "more than X% (single-decimal) …").
It checks that the ticker and rules agree on month and threshold, then *proposes* a mapping
with review notes. Anything else is rejected rather than guessed. Notably, the rules text
doesn't say "seasonally adjusted", so check the contract terms before you confirm. A
confirmation is pinned to that exact rules text: if Kalshi edits the rules, existing signals
show `INVALIDATED_RULES_CHANGED` and new ones abstain until you re-confirm.

**Cost model.** All money math uses `Decimal`, per $1 contract:
`EV_yes = p − yes_entry − fee − slippage` and `EV_no = (1−p) − no_entry − fee − slippage`.
- The entry is the depth-aware VWAP over **derived asks** for the configured quantity, never
  the midpoint or last trade.
- The lower-bound edge uses the model's band (`p_lower` for YES, `1 − p_upper` for NO).
- A **candidate** requires the lower-bound edge to exceed `KRT_SIGNAL_MIN_EDGE`, and to stay
  positive when fees and slippage are doubled.

**Gates that force `ABSTAIN`:** market not open · not binary · no, unconfirmed or stale-rules
mapping · missing or stale quote · one-sided book · spread too wide · insufficient depth ·
off-grid price · model abstained · model not validated (holdout months below the minimum, or
not beating the base rate) · fee type unknown or unsupported · fee multiplier ≠ 1 · **fee
schedule unverified** · edge below margin or not robust to costs · **model–market
divergence**. The last one triggers when the model's probability is more than 0.20 outside
the market's bid–ask range. The model only knows past CPI prints, so a big gap means it is
probably missing information, not that it has found an opportunity.

> **Fee schedule: verified against Kalshi's official PDF** (effective July 7, 2026), with
> version `kalshi-fee-schedule-2026-07-07` in `backend/app/signals/fee_schedules.json`.
> - Taker fee `round up(M × 0.07 × C × P × (1−P))`; maker fee `0.0175` (= 0.25 × 0.07, or
>   0.5 for combos); no settlement fee. KXCPI uses maker and taker multipliers of 1.
> - `tests/test_fee_schedule_pdf.py` reproduces every row of the PDF's General Trading Fees
>   Table (1 and 100 contracts, $0.01 to $0.99) exactly.
> - Totals round up to the cent, as for a retail account. The PDF's centicent rounding applies
>   to direct members, so cent rounding can only overstate fees.
> - The engine still assumes taker fees and abstains when a market's fee multiplier isn't 1.
> - When Kalshi publishes a new schedule, add a **new** versioned entry rather than editing this
>   one, because past signals reference it.

Signals are immutable rows linking to the exact quote, model run, mapping, rules hash and fee
schedule version they used. The API remains GET-only.

## Paper trading (milestone 06): simulated, local only
```powershell
cd backend
.venv\Scripts\python -m app.cli paper-order KXCPI-26NOV-T0.0 NO BUY 20 0.99   # ticker side action qty limit
.venv\Scripts\python -m app.cli paper-account
.venv\Scripts\python -m app.cli paper-settle      # refresh held markets; settle finalized ones
.venv\Scripts\python -m app.cli paper-replay      # replay stored candidate signals
```
You can also place orders from the **Paper trading** panel in the UI. No exchange is ever
contacted.

- **Fill model (`paper-sim-v1`).** Orders are immediate-or-cancel limit orders against the
  latest stored order-book snapshot, which must be fresh. They never fill at the midpoint,
  never through the limit, and never beyond the displayed depth. Any unfilled remainder is
  cancelled, never treated as bought.

  | Scenario | Depth you can take | Price penalty (latency) |
  |---|---|---|
  | `conservative` (default) | 50% of displayed size | 1 grid step worse |
  | `harsh` | 25% | 2 steps worse |
  | `baseline` | 100% | none |
- **Fees.** Taker fees come from the fee schedule. Buy debits round up and sell credits round
  down. Each order records the fee schedule version and whether it was verified.
- **Rejections are recorded too:** stale or missing quote, off-grid limit, market not open or
  already settled, unknown fee, insufficient cash or position, invalid quantity. Re-sending the
  same `client_order_id` is idempotent.
- **Append-only ledger.** `paper_orders`, `paper_fills` and `paper_ledger` reject UPDATE and
  DELETE at the database level, via SQLite triggers. Starting cash is
  `KRT_PAPER_STARTING_CASH` (default 1000).
- **Realized vs unrealized P&L.** Positions use average cost (fees included). Realized P&L comes
  only from simulated sales and settlements. Unrealized P&L marks open positions at what you
  could sell for right now (own-side bids, taker fees, credit rounded down). If the book can't
  absorb the position, the remainder is marked at 0. The identity
  equity − deposits = realized + unrealized is tested.
- **Settlement only on verified resolution.** A payout needs the exchange status to be
  `finalized`; `determined`, `disputed` and `closed` all wait. For mapped CPI markets the
  result is also cross-checked against our own FRED first print. If they disagree, the
  settlement is **HELD**, with no payout, for human review.
- **Replay.** Each stored candidate signal is re-run against the quote snapshot it actually
  used, never a later one. Results are scored only once markets are finalized. The UI plots the
  calibration of replayed signals, and the Models panel now shows the holdout calibration chart.
- The `app/paper` package is tested to import no networking or execution code.
- `POST /api/paper/orders` is the only state-changing route. It requires the
  `X-KRT-Request: paper` header and a JSON body, plus the existing Origin allow-list, so other
  websites can't forge it.

## Learning mode (milestone 07)
- **One glossary, everywhere.** 48 terms live in `frontend/src/glossary/terms.ts`: the 42
  canonical terms from the spec's `GLOSSARY.md`, plus 6 terms specific to this app. Each entry
  has a short definition (200 characters or fewer), an example, a deeper explanation (*what it
  means, why it matters here, what could mislead you*), and, where useful, a formula and
  sources.
  - Tests check that every canonical term's wording matches the spec, so the two can't drift.
  - The backend's `GET /api/glossary` serves an exported copy. After editing a term, run
    `npm run glossary:export` from `frontend/`; a test fails if the copy is stale.
- **`<Term>` and `<MetricLabel>`.**
  - Hover or keyboard focus shows a short, non-interactive tooltip. You can move the pointer
    onto it (there's a 150 ms grace period), and Escape dismisses it while keeping focus.
  - Click, tap, Enter or Space opens a separate **dialog** with the full explanation, related
    terms and sources. It traps focus, closes on Escape or a backdrop click, and returns focus
    to the term.
  - Touch screens don't rely on hover. Links never appear inside a tooltip.
- **Glossary page** (`#/glossary`, linked in the header): search by name, alias or
  definition, filter by category, open "learn more", and try the worked examples for *edge*,
  *slippage* and *Brier score*.
- **No clutter.** Terms are explained on table headers and at their first meaningful use. A test
  fails if any panel marks the same term more than twice.

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
From `frontend/`: `npm test`, `npm run typecheck`, `npm run build`, `npm run check:bundle`,
`npm run glossary:export`.

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
  app/signals/    fee schedules (versioned JSON), mapping parser, engine, service
  app/paper/      fill simulator, broker/ledger/settlement service, signal replay
  app/worker.py   scheduled collector with gap detection and single-instance lock
  app/ops.py      backup / restore / reset;  app/demo.py  offline synthetic demo
  requirements.lock  exact backend dependency versions (frontend: package-lock.json)
  app/api/        /api/health, /api/markets (filters: category, status, series_ticker, q),
                  /api/markets/{id}, /api/markets/{id}/quotes, /api/categories,
                  /api/ingestion/runs, /api/evidence/sources,
                  /api/evidence/{id}/observations?as_of=, /api/evidence/{id}/vintages,
                  /api/collection-gaps, /api/models, /api/models/metrics,
                  /api/research/cpi-mom/forecast, /api/model-runs, /api/signals,
                  /api/markets/{id}/signals, /api/mappings, /api/fee-schedules,
                  /api/paper/{account,orders,settlements,replay}, POST /api/paper/orders
  alembic/        migrations 0001_initial … 0006_paper
  tests/          202 tests incl. end-to-end workflow and performance budgets (HTTP via mock transports; network is blocked)
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
