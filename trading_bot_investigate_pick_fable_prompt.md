# Fable Build Prompt — On-Demand Pick Investigation

**Repository:** `kaungthiha/trading-bot`  
**Build objective:** Turn the existing sports scanner/research experience into a compact, on-demand **Investigate this pick** workflow.  
**UX decision:** **Summary-first by default.** Deeper research is available only when the user expands it.  
**Deployment:** Local-first; local Ollama; existing Brave Search integration; existing warm, wood-driven hairline theme.  
**Scope:** Research and education only. No trade submission, no approval changes, no bankroll automation.

---

## Paste this prompt into Fable

You are working in the existing `kaungthiha/trading-bot` repository. **Audit the current implementation before writing code**, then implement a unified, on-demand investigation workflow for a single selected sports prediction. Use the current branch as the source of truth; some file paths may have changed since the audit below.

### 1. Product intent

The user is browsing Kalshi sports markets, considers a specific outcome (e.g., *Team B wins*, *Team B covers -4.5*, *a player exceeds 24.5 points*, *under 5.5 total goals*), and clicks **Investigate this pick**.

Open a focused research drawer **without navigating away or changing the selected contract**. Answer the user's real question:

> **What supports my pick, what could make me wrong, and is the current market price defensible?**

The scanner itself must remain uncluttered. **Do not** automatically research every detected opportunity or render a large research report inline for every leg. The investigation is an optional, explicit action.

**Critical interaction design:** After the investigation finishes, show a *short summary* by default: **a one- or two-sentence takeaway, up to three key findings, a compact price comparison, and an obvious expandable “View full research” control**. The complete evidence, opposing analysis, calculations, sources, and methodology belong behind progressive disclosure. A user should be able to interpret the initial result in around ten seconds.

### 2. Existing capabilities to reuse

The repository already has relevant components and backend services. Inspect and reuse, rather than duplicating:

- `frontend/src/components/games/GameBoard.tsx` — market/outcome selection.
- `frontend/src/components/games/BetSlip.tsx` — persistent selections and price/evidence context.
- `frontend/src/components/games/LegResearch.tsx` — game logs, historical hit rates, injuries and Brave-backed headlines.
- `frontend/src/components/games/SecondOpinion.tsx` — on-demand local-LLM critique.
- `frontend/src/components/games/SlipCheck.tsx` — quote, value, cap and walk-away analysis.
- `frontend/src/components/games/IdeasPanel.tsx` — proposed sports picks.
- `frontend/src/components/games/slip.ts` — shared, locally persisted slip state.
- `frontend/src/components/OpportunitiesPanel.tsx` — scanner opportunities.
- `frontend/src/components/markets/EventView.tsx` — general event exploration.
- `frontend/src/components/Term.tsx` and `frontend/src/glossary/terms.ts` — accessible tooltip/glossary infrastructure.
- `frontend/src/theme.css` — existing visual tokens; respect the **current** warm visual redesign, not earlier monochrome versions.
- `backend/app/api/games_routes.py` — existing `/api/games/news` and `/api/games/review` routes.
- `backend/app/sportsdata/news.py` and `backend/app/sportsdata/llm.py` — Brave Search and model integration.
- Existing evidence, sportsdata, catalog, database and API client modules.

Inspect tests before refactoring. Preserve preexisting behavior unless it is intentionally replaced and covered by new tests. Do not create competing implementations of the same Brave client, LLM provider, evidence schema or probability/fee calculator.

### 3. Required UX: compact summary first

#### 3.1 Entry point

Add **Investigate** to the selected single outcome in Games, Ideas, Bet Slip and eligible scanner cards. Include Markets/EventView where the contract can be mapped reliably to a supported sports hypothesis. Do not surface a working-looking action for unsupported selections; explain the limitation.

The action should pass the exact selected contract: ticker, YES/NO side, event/game, league/sport, market type, strike/threshold, subject (team/player), snapshot timestamp. Opposite sides and different lines are **different** hypotheses. Never research only the team name and assume this answers a player prop, spread or total.

#### 3.2 Drawer layout

On desktop: a responsive right-side research dossier/drawer, with the current page still visible. On narrow screens: full-width accessible sheet. On both: keep the bet slip and page state intact, manage keyboard focus, restore focus on close, support Escape, and maintain a readable scroll position.

**Before running:**

- Natural-language hypothesis and contract identity.
- Current executable quote (ask when evaluating a buy), observed-at timestamp and stale/fresh label.
- Existing quantitative estimate only if a credible model is supported.
- Button: **Run investigation**.
- Small note indicating whether a fresh Brave query would incur a metered request or a cached result is available.

**After running — default “Summary” view:**

1. **Takeaway:** 1–2 sober, useful sentences that state whether evidence supports, challenges or is insufficient for the hypothesis. Do not say “guaranteed,” “easy money,” or “AI-approved.”
2. **Three things that matter:** at most three ordered findings, selecting the most decision-relevant supporting fact, counterargument or unresolved question. Each external claim has a discreet, clickable source marker.
3. **Price lens:** market ask, model probability/band if available, indicative raw difference, and after-cost conservative edge **only when mathematically supported**. Label quote age and calculation assumptions. If unsupported, show “Not enough evidence to estimate an edge,” not fabricated values.
4. **Actionable research gap:** e.g., “Starting goalie not confirmed” or “The article uses a different spread.”
5. **View full research** expandable control. Keep all lengthy material collapsed by default.

Display source count and “last checked” timestamp quietly. Prioritize reading, not badge overload. The default summary should fit in a typical laptop drawer viewport without a lengthy scroll where feasible.

**Expanded “Full research” view (optional):** four clearly labeled sections:

- **What supports the pick?** Relevant verified facts, historical stats, and attributed analyst claims.
- **What could make me wrong?** Counterarguments, injuries, uncertain lineups, contradictory reporting, sample limitations, mismatched lines and model weaknesses.
- **Is the price justified?** Executable market quote, implied-price caveats, model estimate and bounds, fees, slippage, break-even probability, walk-away level and abstention reasons from the existing deterministic logic.
- **Sources and methodology.** Publisher/author, original URLs, article dates, retrieval dates, model/version, sample sizes, source permissions, evidence freshness, and cached status. Collapsed nested detail is fine.

Make the summary and full view read from **one canonical investigation result**; do not issue a new Brave request or LLM call merely because the user expands the full research section.

#### 3.3 Visual language

Preserve the **finished warm wood / walnut / archival-paper hairline design** as found in the current code. Use thin rules, warm neutral surfaces, strong typography, restrained semantic color, whitespace and existing hairline figures sparingly. Do not invent a separate design system or add generic chat bubbles, glossy gradient cards, heavy drop shadows, large emoji, decorative wood photo textures or five layers of nested cards. Keep numeric prices in tabular numerals.

Use existing accessible `<Term>`/glossary conventions for financial vocabulary; add concise entries only when necessary. Tooltip detail should not obscure the pick or the principal summary.

### 4. External research and Brave Search

#### 4.1 Search is user-triggered, bounded and optional

Existing Brave Search may already be configured. Extend it rather than creating another paid client. Use **News Search** and, if useful and entitled, **Web Search** to discover articles about the *specific* game, date, selection, line and counterarguments. Verify current Brave API endpoints, plan features, request pricing and permitted storage/usage before changes. **Do not assume a $5 credit balance can be queried via API**, and do not hardcode a claim of free searches.

Application-side default ceilings (configurable in `.env.example` and documented):

```dotenv
KRT_RESEARCH_BRAVE_DAILY_REQUEST_CAP=20
KRT_RESEARCH_BRAVE_MONTHLY_REQUEST_CAP=200
KRT_RESEARCH_MAX_SEARCHES_PER_INVESTIGATION=3
KRT_RESEARCH_MAX_SOURCES_PER_INVESTIGATION=5
KRT_RESEARCH_SEARCH_CACHE_HOURS=6
```

- Only **Run investigation**, explicit **Refresh research**, or similarly clear user action may generate metered search requests.
- Deduplicate queries and reuse cached results. No fetch-on-render, hover, tab switch, repeated React mount, or full-report expansion may consume searches.
- Persist a durable local usage ledger with atomic concurrency-safe cap enforcement; display request count against the local cap. Track actual network attempts; do not charge cache hits. Do not infer actual Brave billing or balance from an internal counter.
- Respect 429 and other provider errors without uncontrolled retries.
- Surface clear “budget exhausted,” “Brave not configured,” and “results unavailable” states. Existing local stats and cached research should still work.
- Use a targeted maximum of three queries: matchup analysis, material news (injuries/lineups), and a contrary or specialized perspective. Often one or two will suffice.

#### 4.2 Publisher registry and rights

Create or extend a structured registry for candidate sites, including Pickswise, Boyd's Bets, Covers, PickDawgz, Sports Betting Dime, Sportsbook Review, official league/team sources, and publishers offering authorized feeds.

The registry must record allowed discovery approach, full-text processing permission status, retention policy, attribution, source priority, request limits, and enable/disable status. **Do not enable automated full-article scraping simply because a page is publicly visible or this tool is personal/educational.** Follow publisher terms, robots/access controls, copyright, and API licensing. No paywall/CAPTCHA/login bypass. Use approved feeds/APIs or licensed context where available; otherwise ingest only metadata/snippets where permitted and link to the original article.

The aspiration is to reason over relevant article content **beyond headlines**, but only when the access and use rights permit it. Where unavailable, clearly indicate that only a headline/snippet was reviewed; never imply a full article was read.

#### 4.3 Relevance and deduplication

Match articles to the exact league, game date, opposing teams, players, market and line. Detect past matchups and renamed teams. Normalize canonical URLs, distinguish syndicated duplicates and multiple sites citing the same underlying injury report, and avoid calling these independent confirmation. Give source freshness and direct factual relevance more weight than sheer publisher count.

### 5. Ollama: evidence extraction and balanced synthesis

Reuse the existing Ollama/local LLM integration. The LLM is a **research summarizer and claim-extractor**, not a probability engine or execution agent. It may not call the trading gateway, place orders, approve orders or secretly adjust model probabilities.

Pipeline:

1. Resolve and validate the exact hypothesis and resolution rules.
2. Read existing deterministic statistical evidence and the latest defensible quote.
3. Gather eligible, cached or newly discovered commentary within budget.
4. Normalize and deduplicate evidence and check recency/line match.
5. Extract structured claims with source IDs and relevant quoted context/reference (within retention/licensing limits).
6. Classify each claim as `factual`, `statistical`, `analyst_opinion`, `prediction` or `interpretation`; stance `supports`, `opposes` or `neutral`; verify independently where possible.
7. Generate a **1–2 sentence takeaway and no more than 3 key findings**, explicitly including material counterevidence and unknowns.
8. Attach deterministic price analysis from existing calculator(s).
9. Persist, cache and display the result with source and model provenance.

Require typed Pydantic schemas and fail closed on invalid or ungrounded model output. A factual claim without a valid source reference must be dropped or clearly labeled as unverified. “Extraction confidence” is confidence in the parsing, **not** probability the selection wins. The LLM must never invent odds, probabilities, injury facts, timestamps, authors or market rules.

Treat source material as **untrusted input**, not instructions. Test for prompt injection. Place strict limits on source size and parallelism, timeouts and cancellations. When Ollama is unavailable, return a useful deterministic-only result. If the selected sport/market lacks reliable quantitative support, return an appropriately qualified research summary and an `ABSTAIN`/insufficient-evidence price interpretation.

### 6. Data contracts and API

Prefer extending existing API patterns and tables with non-destructive migrations. Suggested minimal routes (adapt naming to repository conventions):

```text
POST /api/research/investigations        # explicit on-demand job start
GET  /api/research/investigations/{id}   # status + canonical result
POST /api/research/investigations/{id}/refresh
GET  /api/research/usage                  # Brave usage against local cap
```

Protect all metered POST operations using established localhost-origin, request-header/CSRF and authentication mechanisms; do not assume localhost alone prevents malicious web pages from spending API credits.

A result should contain:

- `investigation_id`, `status`, `created_at`, `completed_at`, `stale_at`.
- `hypothesis`: exact `ticker`, `event_id`, `sport`, `league`, `side`, `market_type`, `threshold`, `subject`, rules reference.
- `quote`: executable price, side, observed time, freshness and snapshot reference.
- `summary`: concise takeaway, up to three findings, major unresolved question(s), evidence stance, explicit uncertainty.
- `price_assessment`: baseline probabilities only if modeled, conservative bounds where justified, fee/slippage assumptions, abstention reasons, source/version references.
- `details`: supporting findings, counterarguments, methodology, data gaps and source registry references.
- `sources`: ID, canonical URL, title, publisher, author if known, publication/retrieval times, content access level, citation references.
- `processing`: local LLM model/version, search query count, cache hit/miss, errors, partial-result reasons.

Cache keys must distinguish ticker, side, game, line, meaningful evidence/quote timestamps, model version and source policy version. Research can be shown after expiration if labeled stale. Do not mark stale research as current or feed it to actionable financial calculations.

### 7. Integrate progressively, without regression

Implement in these phases; **finish and test each phase before moving on**:

**Phase A — Interface skeleton:** Review current source and build a fixture-backed, accessible summary-first `InvestigationDrawer` with a single entry point from `GameBoard`/`BetSlip`. Verify interactions and theme before introducing network calls.

**Phase B — Reuse existing evidence:** Wire deterministic leg evidence, model/market comparison, `SlipCheck` outputs, rules, price, and local glossary. Collapse the legacy research display where appropriate without deleting valuable capability.

**Phase C — Brave and source controls:** Implement bounded on-demand discovery, persistent budget ledger, explicit rights-aware source registry, caches, exact event/line matching, and informative failures.

**Phase D — Local Ollama synthesis:** Implement typed claim extraction, citation verification, compulsory counterarguments, compact summary output, detailed expandable sources, and fallback modes.

**Phase E — Broader entry points:** Add `Investigate` to Ideas, supported Markets/EventView and scanner cards. Support NBA first; extend to NHL and NCAA basketball only where entity matching and evidence contracts can be tested. Unsupported markets should fail gracefully, not hallucinate research.

**Phase F — Quality:** Run all existing backend/frontend tests and new tests, inspect responsive UI (with screenshots if tooling allows), confirm financial math unchanged, verify no paid calls without deliberate click, and document known limitations.

### 8. Acceptance tests

At minimum, add deterministic tests proving:

- Summary is the **default** post-investigation view; full details remain collapsed.
- Summary has ≤2 sentences of takeaway and ≤3 key findings; sources remain accessible.
- Opening/closing research preserves the original selected pick and slip state.
- Investigation results are correct for YES versus NO, moneyline versus spread, and distinct thresholds.
- Quote age, article age, model age and missing price/model states are explicit.
- Full research expansion makes **zero** additional Brave or Ollama calls.
- React re-renders do not duplicate research jobs or paid requests.
- Daily/monthly Brave request caps are honored under concurrent requests.
- Cache hit, provider downtime, no search results and exhausted budget yield understandable outcomes.
- Content from a previous matchup or different line is not treated as direct support.
- Duplicate syndication is not counted as independent corroboration.
- Unapproved full-text sources are not fetched or stored.
- A malicious article cannot instruct the local model or service to access credentials or call execution functions.
- Invalid LLM source IDs and invented numeric claims are rejected or visibly marked unverified.
- Ollama offline yields a useful deterministic-only summary.
- Keyboard focus, Escape, screen reader labels and narrow-screen layout work.
- No existing scanner, trade-history, paper-trading, or execution-approval tests regress.
- **No real exchange orders are submitted during development or testing.**

### 9. What you must deliver

- Working code, migrations, typed API contracts and UI components.
- Documentation for local Ollama, Brave key setup and application-side spending caps.
- Source permission registry and a clear statement of which approved sources allow article-level processing.
- Unit/integration UI tests with no live Brave charges.
- Screenshots or an actual browser walkthrough if available.
- A concise implementation report listing files changed, tests actually run, unsupported markets, source-access limitations and remaining gaps.

**Do not label this complete merely because the LLM can summarize an article.** It is complete when a user can inspect an exact contract, get a short grounded, source-linked assessment, expand counterarguments and methodology if desired, and return to the same pick without friction.

**Guiding principle: The scanner finds possibilities. An optional investigation tests the thesis. The user decides.**

---

## Optional first instruction if Fable works in small batches

If you want to split implementation without changing the overall spec, send this first:

> Read the full `trading_bot_investigate_pick_fable_prompt.md`. Start with Phase A only: audit the current components and build the fixture-backed, summary-first Investigation Drawer in the existing warm hairline theme. Show me the working UI and tests before integrating any new Brave requests or LLM processing. The expanded report must be hidden by default. Keep the existing slip and trading logic unchanged.

