# trading-bot — Kalshi Research Terminal (local)

A local-only research and paper-trading terminal for Kalshi event contracts. It **does not
place orders**. The full specification and milestone prompts live in
[`kalshi_research_terminal_fable_package_2026-11-18/kalshi_research_terminal_fable_package/`](kalshi_research_terminal_fable_package_2026-11-18/kalshi_research_terminal_fable_package/README.md).

**Status:** milestones 01–09 are complete. Milestone 09 adds **approval-gated execution for
the mock exchange and Kalshi's DEMO environment only**. Production execution is not
implemented, and it cannot be configured.
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

**Everyday use:** `.\scripts\dev.ps1` (re)starts the backend and frontend in their own windows.
Add `-Worker` to also start the worker, or use `-Stop` to stop everything. In the app, the
buttons at the top replace the CLI:
- **Refresh data**: Kalshi markets on the watchlist, then mapping proposals, then signals.
- **Refresh FRED**: new CPI vintages, then a model re-evaluation. Needs `KRT_FRED_API_KEY`.
- **Scan now**: every open Kalshi market for mispricings.
- **Auto-scan**: scans every few minutes. It is disabled while the separate worker runs.

Under the opportunity list, "What the last scan looked at" shows coverage by category and
series, and the events that came closest to a mispricing.

**Pages (left rail; a bottom bar on phones).** Old links keep working.
- **Today** (`#/`): the daily desk. Your open positions that need a look (a warning, or
  closing within 24h), open scanner ideas, valid model signals, and the most-traded games
  starting in the next 36h. Each group keeps its own number and label and is never ranked
  against another group. Mark items *Researching* or *Pass* and add a note; marks live only in
  this browser (`localStorage`). Each group loads on its own and offers Retry if it fails.
- **Explore**: Games (`#/games`) and All markets (`#/markets`), with a switch between them.
- **Journal** (`#/journal`, was `#/history`): your synced Kalshi history.
- **Learn** (`#/glossary`): the glossary.
- **Tools** (`#/terminal`, `?tab=scanner|watchlist|signals|paper|models|system`): the former
  Terminal tabs, including approval-gated execution.
- **Research pages** (shareable links; "Copy link" copies only ids, never prices or account
  data): `#/research/opp/<id>` for a scanner idea, `#/research/sig/<id>` for a model signal,
  `#/research/event/<event ticker>` for an event. Each opens with a **decision summary**
  (cost, payoff, downside, model vs all-in market cost) and the risks you must check (always
  visible), then **evidence and assumptions** (every leg with its fee, the fee schedule,
  freshness), then **audit details** (ids, journal, signal lineage; collapsed). Stale or
  expired items are flagged at the top. The event page gathers your open positions, scanner
  ideas, signals and saved research for that event above its markets. Today's rows, scanner
  cards and signal cards link here.

The top bar shows mode, live execution, connection and when prices were last scanned (marked
stale after 30 minutes). **Compact rows** tightens tables and is saved in this browser.

**Markets page (`#/markets`):** every open Kalshi event and market from the last scan, about
21k events and 186k markets. Each scan saves this snapshot, so browsing makes no extra API
calls. Browse by category and series, search, and open an event to see:
- every market's bid, ask, implied probability, spread, 24h change, volume and open interest;
- for "exactly one wins" sets: how much the prices add up to (the overround) and normalized
  odds;
- for ladders (totals, spreads, player props): the implied distribution, with median,
  quartiles, and strikes priced off the smooth curve or out of order. Spread ladders for the
  two teams are merged into one margin distribution;
- **EV**: enter your own probability. It shows the all-in cost with the verified fee (and the
  series' fee multiplier), the break-even chance, expected value, and a quarter-Kelly size
  capped at 5% of your budget. It can also fetch the current orderbook and full rules from
  Kalshi;
- **Add to the Docket**: add YES or NO legs to price a parlay as if the legs were
  independent. The Docket warns about legs from the same game or event, where that
  assumption is wrong.

Prices are a snapshot from the last scan, so check the live book before trading. The catalog
is a cache: closed markets drop out on the next complete scan.

**Combos on Kalshi.** Kalshi builds combo (multivariate) markets on request, and market
makers price them privately, so there is no public combo orderbook. The app gives you:
- **Eligibility:** each scan reads Kalshi's combo collections, and events that can be legs
  show "combo-eligible on Kalshi". The Docket says whether Kalshi can build your exact
  combination.
- **Quote check:** type the quote Kalshi gives you into the Docket to see the markup over
  the independent fair value. It flags legs from the same game, where that fair value is
  wrong.
- **"Do combos pay?" study (Markets page):** reads recently settled combos and compares their
  last traded price with how often they actually hit, by leg count and by price. The combo
  builder shows the result for your leg count. Refresh it with the button there; it takes
  about a minute.

**P&L over time (My trades):** cumulative realized P&L and P&L by day, with a table view.

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

## Approval-gated execution (milestone 09): mock and Kalshi DEMO only
**Production trading is not implemented.** The configuration has no production option, and the
demo client refuses Kalshi's production hosts in code. Execution is **off** by default, and
the kill switch starts **engaged**.

```powershell
# 1. In .env:  KRT_EXECUTION_ENABLED=true   (KRT_EXECUTION_ENV=mock is the default)
cd backend
.venv\Scripts\python -m app.cli set-approval-pin --write-env   # stores a salted scrypt hash, never the PIN
.venv\Scripts\python -m app.cli kill-switch release --yes       # CLI only; engaging is one click in the UI
.venv\Scripts\python -m app.cli execution-status
# 2. Restart the backend; use the "Execution (approval-gated)" panel.
```

**What happens to every order**
1. **Propose.** The exact exchange payload is fixed: an immediate-or-cancel limit order with
   self-trade prevention. Its SHA-256 hash is stored along with a unique `client_order_id`, the
   snapshot ask, the fee estimate from the **verified** schedule, and the worst-case cost.
   Proposals are refused if the quote is older than 15 s, fees are unverified, the price is off
   the grid, or any cap would be breached. The database blocks any later change to the terms.
2. **Approve.** You approve that exact hash with your **PIN**. Five wrong PINs lock approvals
   for 15 minutes. An approval works once (a unique constraint plus a conditional status update)
   and expires after 60 s. A replayed or duplicate approval returns `ALREADY_USED`.
3. **Preflight, immediately before sending.** Checks the kill switch and environment, the
   market is still `active`, the **rules hash** is unchanged, a fresh executable ask (**any
   worse price blocks the order**), all caps, the exchange balance, and the same verified fee
   schedule.
4. **Send exactly once.** The `SUBMITTING` state is saved first.
   - **Accepted:** FILLED, PARTIAL or NOT_FILLED.
   - **Definitive 4xx:** REJECTED.
   - **Timeout, 5xx or duplicate ID:** UNKNOWN. A read-only lookup by `client_order_id`
     follows. The order is **never resubmitted**; use `execution-reconcile <id>` or the UI to
     look it up again later.
5. **Audit.** Every step is an append-only `execution_events` row. Approvals, controls and
   exchange orders are also append-only (database triggers).

**Caps** (in `.env`): `KRT_EXECUTION_MAX_CONTRACTS_PER_ORDER` (10),
`KRT_EXECUTION_MAX_COST_PER_ORDER` ($25), `KRT_EXECUTION_MAX_POSITION_CONTRACTS` (50, unknown
outcomes count as filled), `KRT_EXECUTION_MAX_DAILY_COST` ($100), intent lifetime (60 s) and
quote age (15 s).

**Kalshi DEMO** (optional, mock funds): create a **demo** API key at https://demo.kalshi.co
(demo and production keys are separate). Save the private key **outside** this repository;
paths inside it are rejected. Set `KRT_KALSHI_DEMO_API_KEY_ID`,
`KRT_KALSHI_DEMO_PRIVATE_KEY_PATH` and `KRT_EXECUTION_ENV=demo`, and ingest demo markets with
`ingest --demo`. Requests are signed as documented (RSA-PSS SHA-256 or Ed25519 over
`timestamp + METHOD + /trade-api/v2/path`). Only order creation, order lookup, balance and
market reads are allowlisted. Demo behaviour isn't real-market evidence.

**Moving to real money would be a separate project,** needing a fresh review of Kalshi's terms
(including the data-use questions in the research report) and your explicit authorisation. It
can't be switched on with configuration.

## Opportunity scanner: trade ideas you verify and place yourself
The scanner reads **every open Kalshi event** (about 21,000 events and 190,000 markets in
roughly 110 public API calls, no key). It looks for prices that are internally inconsistent,
re-checks each candidate against the live order books, and turns survivors into **thesis
cards**. It never trades. You check the card, place the trades on Kalshi yourself, and record
what you did.

```powershell
cd backend
.venv\Scripts\python -m app.cli scan             # one full scan now
.venv\Scripts\python -m app.cli scorecard        # budget, open cost, realized P&L
.venv\Scripts\python -m app.cli journal-settle   # settle journaled trades on FINALIZED results
# continuous: KRT_MARKET_DATA_SOURCE=kalshi_public in .env, then .\scripts\start-worker.ps1
#   (scans every 5 min; a Windows notification appears when a new card shows up)
```

| Detector | Trade | Why it should pay | Label |
|---|---|---|---|
| Ladder violation | YES on a lower strike + NO on a higher strike of the **same** ladder | pays ≥ $1 per set in every outcome | GUARANTEED (if rules hold) |
| Exclusive set, NO side | NO on every outcome of a mutually exclusive event | at most one YES, so pays ≥ n − 1 | GUARANTEED (if rules hold) |
| Exclusive set, YES side | YES on every outcome | pays $1 **only if one listed outcome must win** | CONDITIONAL |

**Safeguards learned from live data**
- **Same-ladder check.** Markets count as rungs of one ladder only if their rules text is
  identical apart from the numbers. Kalshi events often hold several ladders, such as each
  team's total. The first live run produced 29,000 false "arbitrages" before this check.
- **Catch-all check.** Exclusive-YES ideas are shown only when the event lists a catch-all
  outcome ("Other", "None", "Field"…). Otherwise the cheap total just reflects the unlisted
  result, for example "no 51st state".
- **Exact cost sizing.** Every leg's taker fee comes from the PDF-verified schedule and is
  rounded up to the cent **per order**, so tiny orders on cheap contracts are rejected. Size is
  limited to the depth at the best price, and candidates are re-confirmed against live books.
- **Nothing hidden.** Ideas already reported in the last 30 minutes are skipped, and a
  truncated scan is reported, never hidden.

**Budget rules** (`KRT_EXPERIMENT_BUDGET_DOLLARS`, currently **$50** in your `.env`)
- At most **20 %** per guaranteed idea ($10) and **5 %** per conditional idea ($2.50).
- **Available budget** is the budget plus realized P&L minus money in open trades.
- New cards **pause** after a 30 % realized loss.
- The scorecard keeps guaranteed and conditional results separate, so you can see which kind
  actually works.

**What to expect.** Most scans find nothing, which is what a healthy market looks like. The
live scans on 2026-11-18 found **no guaranteed gaps after fees** across 192,000 markets, and one
conditional idea. The value is in watching continuously for brief gaps, not in a steady stream
of trades.

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

## Games page: build a same-game combo and check it
**Games** puts one game on one screen: winner, spread, totals, team totals, halves and
quarters, and a grid of every player's props. Each cell in the grid shows where the market
puts that stat's 50/50 point (its median line). Tap a price to add it to the **Docket**.

**The Docket** is one slip that follows you across Today, Games and All markets, kept across
reloads. On wide screens it's a right-hand column (collapse it with »); on narrower screens
it's a bar at the bottom that opens into a sheet. For the legs on it, it shows, in order:
what would have to happen (sides in words: "Happens" / "Doesn't happen"), the price and
history numbers below, **where this may be wrong** (injuries, thin data, linked same-game
legs, combos Kalshi can't build; never collapsed), what the price implies (market-implied,
with the scan time), your box-score evidence (labelled as a frequency, not a calibrated
probability), what you'd pay (the slip check), the AI second opinion, and **Save or pass**:
your decision and why, saved in this browser with the price at the time and listed on Today
under *Saved research*. Numbers are only shown for the legs they were computed for.

**Investigate this pick.** On a single-game NBA, WNBA, college basketball (men's or women's),
NHL, NFL or soccer leg (Docket, the Ideas tab, a game's market table, or such a leg on a scanner card) click
*Investigate*. A drawer opens for that
exact contract and side, without leaving the page or touching your slip. Nothing runs until you
click **Run investigation**. Then you get:
- a summary: two sentences, up to three sourced findings (at least one counterargument or open
  question), a price lens and what's still unknown;
- *View full research* (collapsed): what supports the pick, what could make you wrong, whether
  the price is justified (fees, break-even, walk-away, rules excerpt), sources and method.

What it uses:
- **The app's own data:** the Kalshi quote, ESPN box scores and injury report, and the slip
  check's fee maths. Box-score history is a frequency, not a probability. No edge is shown when
  the quote is stale, the sample is small, or tonight's lineup isn't normal.
- **College basketball** (game winner, spread and total; halves aren't covered): teams are
  matched by school name, since Kalshi's codes often differ from ESPN's. ESPN publishes no
  college injury report, so the lineup is treated as unknown and **no edge is ever shown**. A
  college team's history also comes from opponents of very different strength, and the result
  says so. News searches name the sport, and articles about football or the other basketball
  program are dropped.
- **NHL** (game winner, puck line, game and team totals; periods, overtime and player props
  aren't covered): season stats from **MoneyPuck** (expected-goals share, goals for/against,
  goalie save % and goals saved above expected; free for non-commercial use, credited "Data:
  MoneyPuck.com"). ESPN and the NHL's own endpoints aren't used for hockey. The starting goalie
  is *unknown*, *expected (reported by news)* or *conflicting*, never *confirmed*: no official
  lineup source is connected. There's no validated NHL model, so **no estimate or edge is
  shown**; the stats are context. Kalshi settles game winner and puck line on the official
  final result (overtime and shootout included), and totals count a shootout as one goal.
- **NFL** (game winner, spread, game and team totals; halves, quarters and player props aren't
  covered): from **nflverse** release files, each with its own rights entry: the schedule
  (kickoff, scores, rest days, roof, listed QB; the sportsbook line columns are never read),
  weekly team stats (points and EPA per play) and the weekly injury report. Credited "Data:
  nflverse (CC BY 4.0)". Season form counts **only games played before this kickoff**. Weather
  comes from **Open-Meteo** (free, no key) at kickoff, for open-air home stadiums only. ESPN
  and NFL.com aren't used. The starting QB is *expected* (listed or reported), *unknown* or
  *conflicting*, never *confirmed*. A listed QB who is Out or Doubtful counts as unknown, and if
  this week's injury report isn't out yet, availability is shown as unknown, not healthy. No
  validated NFL model exists, so **no estimate or edge is shown**. Kalshi settles the game
  winner on the official result (overtime counts; a tie pays $0.50 per team); spreads and
  totals use the official score, overtime included.
- **Soccer** (Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Champions League, MLS;
  match winner including the separate *Tie* contract, spread, totals, both teams to score;
  halves, corners and correct score aren't covered): everything settles **after 90 minutes
  plus stoppage time** (no extra time or penalties), so past results are read as 90-minute
  scores. Results come from **football-data.org** (free tier; set `KRT_FOOTBALL_DATA_API_KEY`
  in `.env`; credited "Football data provided by the Football-Data.org API"), counting only
  matches **before this kickoff**. Without the key, or for MLS (not in the free tier), you get
  the price, rules and news only. No lineup or injury source exists for soccer, so team news is
  always shown as unknown. No validated model, so **no estimate or edge is shown**.
- **News (optional, Brave News Search):** up to 3 targeted searches per run (4 for the NHL and
  NFL, starting with the goalie or quarterback; soccer starts with team news). Only headlines
  and snippets are used; no article page is ever fetched. Results must name this game's teams
  (or the prop's player). Articles about a past matchup or a different line are flagged and
  never count as support. Syndicated copies count once. Brave's terms allow only temporary
  storage, so once a saved investigation is older than `KRT_RESEARCH_SEARCH_CACHE_HOURS`
  (default 6), its articles and the summary written from them are deleted from the database.
  The box-score check, injury report and price stay. Refresh to search again.
- **Excerpts you paste (optional):** under a result, *Add an excerpt you've read* takes a
  passage from an article you read, plus its source and (optionally) link and date. It stays on
  this computer, the app never opens the link, it costs no search, and it's always shown as
  *user-provided, unverified* until another source agrees. It's checked for the wrong sport,
  a different line, or a date after the game. If Ollama is on, the summary is rewritten with it.
  Excerpts stay until you remove them (also after a refresh).
- **Your local model (optional, Ollama):** writes the summary from that evidence. Its output is
  checked: unknown sources are removed, numbers not in the evidence are marked unverified, hype
  and injected instructions are dropped. If Ollama is off, you get the app's own summary.

Setup and spending caps:
- **Brave:** set `KRT_BRAVE_SEARCH_API_KEY` in `.env` (a key from https://brave.com/search/api/;
  at the time of writing $5 per 1,000 requests with $5 free credit a month, so check the
  current price there).
- **One app-wide Brave cap** (`.env.example`): `KRT_RESEARCH_BRAVE_DAILY_REQUEST_CAP` (60) and
  `KRT_RESEARCH_BRAVE_MONTHLY_REQUEST_CAP` (800) apply to the **total** of every Brave use:
  Investigate, the "Headlines here" button and the AI reviews' headlines. Also
  `KRT_RESEARCH_MAX_SEARCHES_PER_INVESTIGATION` (5), `KRT_RESEARCH_MAX_SOURCES_PER_INVESTIGATION`
  (7), `KRT_RESEARCH_SEARCH_CACHE_HOURS` (6). The defaults are also the maximums: 800 a month
  is about $4 at $5 per 1,000, below a $5 monthly credit. You can lower them; raising them
  needs a code change. Every network attempt is written to a local ledger before it's sent, and
  the caps are enforced atomically across features. Cache hits are free. Retries are off,
  because each attempt is billed. The drawer shows "Brave requests: N / 800 this month" with a
  per-feature breakdown; **your Brave balance isn't visible to the app**, so check the Brave
  dashboard. "Headlines here" is a click-only POST (a link on another site can't spend it).
- **Data sources:** `app/investigate/sources.py` records each source's reviewed terms and the
  exact operations allowed (`GET /api/research/sources` shows the matrix). Turn one off with
  `KRT_RESEARCH_DISABLED_SOURCES=moneypuck,nflverse_injuries` (any ids from the matrix).
  Details: `docs/investigate/EVIDENCE_V2.md`, `NFL.md` and `SOCCER.md` there.
- **Checks:** `krt research-eval` prints an evidence-quality report over saved investigations
  (offline). `krt research-smoke --live-moneypuck` downloads MoneyPuck's two files once and
  `--live-nflverse` nflverse's three files once; `--live-football-data` sends one
  football-data.org request to check your key (all free; never Brave). Without a flag it does
  nothing.
- **Ollama:** the same local model as the other AI features (`KRT_LLM_PROVIDER=ollama`,
  `KRT_OLLAMA_MODEL`). An investigation's summary is capped at 90 seconds, one at a time.
- **Runs in the background:** *Run investigation* queues the work and the drawer shows what it's
  doing (waiting, searching news, summarising). You can close the drawer and come back; a
  double click joins the same run, and a waiting run can be cancelled. Only that click starts
  work: opening the drawer or polling never searches.

Only clicking *Run investigation* or *Refresh research* can spend a search. Opening the
drawer, expanding the full research and reloading never do. Nothing here places orders.

**From your history** (in the Docket and on event research pages) shows how trades like
these went for you: the same series, the same market type, your Kalshi combos and combos with
the same number of legs. One rule applies everywhere a record is summarised, including the
Journal: under 10 closed trades you see counts and net P&L only, marked "too few to say";
from 10 up, your return on money staked is tested against luck (stake-weighted, so one tiny
long-shot win can't hide big losses), and only a record beyond two standard errors is called
better or worse than luck. The Journal's tables show "too few" instead of an ROI for small
groups, a "Last 7 days" tally, and insights and "lean in" suggestions that pass the same
test.

For the legs on the Docket:
- **Fair price** is the market's prices multiplied together, as if the legs were independent.
- **Per-leg check.** NBA, WNBA and college basketball legs are checked against ESPN box scores: last 5 and last 10
  games, this season, last season, and a shrunk estimate with an 80% range. The pill says
  whether the price fits that history ("fits history"), looks too high ("history: less
  likely") or looks too low ("history: likelier"). Tap a leg to see its last 10 games
  against the line.
- **History-adjusted price.** For legs on the same team, it counts how often they all landed
  in the same past game, compared with what independence predicts. That ratio scales the
  fair price, which captures the correlation a plain multiplied price ignores.
- **Quote check.** Type the price Kalshi quotes you to see the markup over fair.

Limits: box scores don't know tonight's matchup, minutes or injuries. The injury strip and
news links are there for that. Quarter and half markets have no box-score check yet.
Headlines in the app need an optional Brave Search key (`KRT_BRAVE_SEARCH_API_KEY` in `.env`);
without one you get search links. `KRT_SPORTS_EVIDENCE_ENABLED=false` stops all ESPN calls.

**Slip check (no AI).** Enter your **stake** and Kalshi's **quote**. The slip then shows:
- a verdict (reasonable / stretch / avoid) with short reasons;
- a **walk-away price**: the most the combo is worth with a 10% edge left after fees;
- what your stake buys: contracts, cost, payout, expected value, your cap and quarter-Kelly;
- **cheaper ways**: each leg as a single, flagged as value when box scores beat the price,
  with a **limit price** and its savings in price and fees (makers pay no fee on most sports
  series), or "only worth it at ≤X¢"; and which leg to drop.

Kalshi's combo quotes are take-it-or-leave-it, so limit orders apply to single legs only.

**Ideas tab (per basketball game).** A screen of the whole game, not a pick list:
- **Singles:** every liquid full-game leg (10–90% priced, up to 90 of them) is checked
  against box scores, on both YES and NO. A leg is listed only when its history estimate
  beats Kalshi's **all-in price** (ask + taker fee) by 2+ points. Each one shows a limit
  price and how many contracts your cap buys. **Strong** means history's whole 80% range
  is above the price; **lean** means the edge is real but the range overlaps it. One line per
  ladder; injured (out/doubtful) players are skipped.
- **Role-change guard:** if the market prices 3+ of one player's props against his history,
  all the same way, it probably knows about a lineup or minutes change that box scores
  don't show yet. Those legs are demoted and marked.
- **Small combos:** 2–3 legs taken only from the singles. Each combo takes at most one of
  winner/spread, since a 6+ point win already is a win. The ratio compares history with
  the market price, with the same same-team correlation applied to both. Each combo comes
  with a walk-away quote.
- **Cheaper entries:** from Kalshi's order book alone. If you already want a leg with a
  wide spread, rest a limit order instead of paying the ask plus the fee. **Kalshi data on
  its own can't tell you which side is likelier**, because the price is the market's
  estimate. It can only tell you how to get in cheaper. Direction needs history.
- **Ask the local model to pick (or pass):** it may choose at most 3 ids from the list.
  Picks on one team count as one exposure. Stakes are clipped to your cap, with 3 caps in
  total. Passing is allowed. It can't add bets that aren't on the list.

**Local AI (Ollama): second opinion and Coach.** The app uses a model running on your own
machine (default `gemma4:12b`). It is free and private, and the app only connects to
loopback (`KRT_OLLAMA_BASE_URL` must be `http://127.0.0.1:<port>`).
- **Get a second opinion (AI)** on the slip. The model gets the slip check above, the
  box-score stats, the together-count, injuries and Brave headlines (labelled S1, S2, …). It
  returns a verdict, a for/against read on each leg with cited sources, risks, and things to
  check before betting.
- **Get coaching** on My trades → Overview. The model reads your P&L, behavior, combo
  history, rule-based playbook and open positions. It writes a summary, leaks, strengths
  (each tied to a number), 3–5 rules for your next $50, and notes on open positions.
- **AI read of these positions** on My trades → Open. For each open position the model gets
  the price trail vs entry, the box-score check, injuries, combo legs and headlines. It
  returns a stance (on track / watch / reconsider), a two-sentence read, a "reassess if…"
  plan, and portfolio-level risks. It judges each position at today's price, not at what
  you paid.

How it's kept honest and safe:
- The model is told to use only the facts it's given; its own memory of players and rosters
  is stale.
- Its reply must match a JSON schema and is validated before display. Tickers it invents are
  dropped. Headlines are passed as untrusted data.
- Each run is a button click, and needs the app's CSRF header so another website can't
  trigger it. Identical requests are cached (slip 15 min, ideas
  10 min, open read 15 min, coach 30 min).
- Thinking mode is turned off (`think: false`). Otherwise thinking models spend their whole
  budget on hidden reasoning and return nothing.
- Settings: `KRT_OLLAMA_MODEL`, `KRT_OLLAMA_NUM_CTX` (default 16384),
  `KRT_LLM_TIMEOUT_SECONDS`.

Paid alternative: `KRT_LLM_PROVIDER=openai` with `KRT_OPENAI_API_KEY`. This uses a daily cap
(`KRT_LLM_MAX_REVIEWS_PER_DAY`). The coach, the open-positions read and the ideas picks
stay local-only, because they see your account data.

Treat the output as a checklist generator, not a forecast: it can be confidently wrong.

## Your trade history (My trades page, read-only)
Syncs your own Kalshi account so you can see your P&L and how you trade. Nothing is executed.
1. On Kalshi: Account → Profile → API Keys → create a key. Choose **read-only** if offered.
   Save the private key file; Kalshi shows it only once.
2. Put the file **outside this folder**, e.g. `C:\Users\you\.kalshi\krt-read.pem`.
3. In `.env`, set `KRT_KALSHI_API_KEY_ID=<key id>` and
   `KRT_KALSHI_PRIVATE_KEY_PATH=C:\Users\you\.kalshi\krt-read.pem`, then restart
   (`scripts\dev.cmd`).
4. Open **My trades** and click **Sync from Kalshi**.

What it does:
- It reads fills (live and archived), settlements, positions and your balance, and nothing
  else. The client implements GET only, to six allow-listed endpoints, over HTTPS to Kalshi's
  hosts. It does not follow redirects and has no order code at all. Data stays in the local
  database (and its backups).
- It computes realized P&L from your fills and settlement payouts, net of fees, and checks it
  against Kalshi's own per-market realized P&L ("N of M match").
- It shows how you trade (longshot vs favorite share, taker share, fees vs amount spent,
  stake sizes against your budget), how your picks did vs the price you paid (with standard
  errors), and P&L by market type and series. Open positions are marked to the last scan's
  mid.
- Its suggestions come from your own record and link to open markets on the Markets page.
  Each one says why it's listed. They are not predictions.

The page has four tabs:
- **Overview:** headline numbers, the P&L chart, and your **playbook**. The playbook is a
  short list of rules drawn from your record, such as "Keep combos to 2–3 legs: 1 win in 18
  combos of 4+ legs". Each rule shows its evidence and how far to trust it. The **Coach**
  (local AI) turns your record into a short plan.
- **Open:** every open position, with:
  - price now versus what you paid, and a price trail;
  - time to close, and what it pays if right;
  - for NBA/WNBA game legs, the same box-score check as the Games slip, plus injuries;
  - flags such as "down 20 pts since entry: would you buy it at today's price?", over 10%
    of budget, closes soon, or several positions riding on one game.

  Open combos are split into their legs. Each leg shows whether it won, lost or is still
  open, and the combo gets a live value.
- **Behavior:**
  - how your combos lived and died: legs per combo, wins by size, how often you lost by
    exactly one leg, and which leg types broke them;
  - entry quality;
  - won vs price paid;
  - P&L by market type and series.
- **Ledger:** closed markets and fills.

**Stored locally, kept forever:**
- **Position marks:** each open position's price at every sync and scan (table
  `position_marks`). Over time these give "entry vs close": did you buy cheaper than where
  the market ended up? That says more about skill than a small sample of wins.
- **Combo legs:** the legs of every combo you traded (table `combo_legs`), taken from
  Kalshi's public data during sync. A finished leg is fetched once and never again. The
  first sync after upgrading makes a few hundred public calls (about a minute).

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
- A test pins the exact set of state-changing routes:
  - simulated paper orders;
  - execution propose, approve (PIN), reconcile (read-only), and kill-switch **engage**.

  Each requires a purpose-specific `X-KRT-Request` header in addition to the Origin allow-list.
  There are no production exchange routes, and the kill switch has no "release" route.
- Research, signals, paper trading, evidence and adapters are tested to never import the
  execution package.
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
  app/execution/  approval contract, preflight, mock exchange, demo-only signed gateway
  app/scanner/    mispricing detectors, full-catalogue scan, thesis cards, journal, alerts
  requirements.lock  exact backend dependency versions (frontend: package-lock.json)
  app/api/        /api/health, /api/markets (filters: category, status, series_ticker, q),
                  /api/markets/{id}, /api/markets/{id}/quotes, /api/categories,
                  /api/ingestion/runs, /api/evidence/sources,
                  /api/evidence/{id}/observations?as_of=, /api/evidence/{id}/vintages,
                  /api/collection-gaps, /api/models, /api/models/metrics,
                  /api/research/cpi-mom/forecast, /api/model-runs, /api/signals,
                  /api/markets/{id}/signals, /api/mappings, /api/fee-schedules,
                  /api/paper/{account,orders,settlements,replay}, POST /api/paper/orders
  alembic/        migrations 0001_initial … 0008_scanner
  tests/          292 tests incl. e2e workflow, perf budgets, adversarial execution (HTTP via mock transports; network is blocked)
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
