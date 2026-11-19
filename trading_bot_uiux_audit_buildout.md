# Trading Bot — UI/UX Code Audit & Buildout

**Repository:** https://github.com/kaungthiha/trading-bot  
**Reviewed:** 2026-11-19, default branch `main`  
**Method:** Static source audit, not a rendered usability test. Recommendations are based on inspected React components, CSS, and documented backend capabilities; interaction quality must be validated in-browser.

## Executive recommendation

Make the product a **warm, modern research workbench**, not a dashboard collection. Preserve the existing 1px hairlines, tabular data, restrained information density, and expressive `@lucasmarkes/hairline` figures. Add an **oiled walnut / parchment / drafting-table** sensibility: warm neutrals, subtle woodgrain only in low-information areas, etched dividers, and sparing bronze accents. Build a persistent **Research Docket** (side rail/drawer) and a common event-centric **Research Workspace** that connect Discovery → Evidence → Valuation → Risk → Decision → Journal.

The highest-value change is **workflow continuity**, not more charts or decorative graphics.

## What exists today — source-based inventory

| Capability | Implementation | Finding |
| --- | --- | --- |
| Main navigation | `frontend/src/App.tsx` | Terminal, Games, Markets, My trades, Glossary; Terminal subdivided into six tabs. Navigation is feature-based rather than task-based. |
| Scanner ideas | `frontend/src/components/OpportunitiesPanel.tsx` | Detailed idea cards, multi-leg tables, verification checklists, and manual execution journal. Rich data but many separate cards and inline controls. |
| Games research | `frontend/src/components/games/GamesPage.tsx`, `GameBoard.tsx`, `IdeasPanel.tsx` | Game list + market board + bet slip. Useful three-pane layout; player prop grid and threshold chips support dense research. |
| Slip & analysis | `frontend/src/components/games/BetSlip.tsx`, `SlipCheck.tsx` | Shared slip selections, historical evidence, adjusted/fair probability, quote/stake entry, and recommendations. Works in Games view. |
| General market catalog | `frontend/src/components/markets/MarketsPage.tsx`, `EventView.tsx`, `ComboTray.tsx` | Browse by category/series, inspect event ladders and odds, create combo; combo tray differs from Games slip despite shared selection state. |
| Signals | `frontend/src/components/SignalsPanel.tsx` | Probability, quote, fees, slippage, EV, conservative edge, evidence lineage; housed away from main game/market research. |
| Execution | `frontend/src/components/ExecutionPanel.tsx` | Separate propose/approve flow, exact order payload, PIN, expiry, fresh quote safety, kill switch. Must preserve hard boundaries. |
| Personal performance | `frontend/src/components/history/HistoryPage.tsx` | Overview, open positions, behavior, ledger, calibration, coaching. Strong educational material but not linked tightly to candidate evaluation. |
| Glossary | `frontend/src/components/Term.tsx`, `GlossaryPage.tsx` | Accessible hover/focus tooltip plus click-to-learn dialog. Reuse rather than replace. |
| Styling | `frontend/src/theme.css`, `styles.css`, `games/games.css` | Contemporary monochrome hairline theme, dotted grid, pills, white cards, #2a78d6 and #e34948 for quantitative signals. Hairline figures are integrated through `Hairline.tsx`. |
| Refresh controls | `frontend/src/components/ControlBar.tsx` | Repeated compact scan controls in different page headers; 15s idle/1.5s running polling, more granular system actions in Terminal. |
| Navigation state | `frontend/src/App.tsx` | Small hash router and per-component state; only Terminal selected tab explicitly persists in sessionStorage. Cross-page focus continuity could improve. |

## Main usability problems (prioritized)

### P0 — Broken continuity between research surfaces

The same real-world decision moves across scanner, events, games, signals, and personal trades, but each presents a different context and interaction pattern. A selection in the Games slip has a sibling `ComboTray` on Markets; the scanner uses a journal-specific flow; execution uses a detached market dropdown. This asks the user to mentally maintain the trade thesis.

**Solution:** Introduce a **Research Docket** (persistent on desktop; bottom sheet on narrow screens), driven by the existing shared slip state. Include selected contracts, calculated costs, live/freshness status, evidence status, blockers, and next safe action. Preserve precise source labels (market-implied vs model-estimated vs historical hit rate). Add a deep-linkable `Research Workspace` for event/market/idea IDs. Navigation should retain selection and scroll position.

### P0 — Recommendations are not triaged from a single inbox

`OpportunitiesPanel` and `IdeasPanel` generate ideas, `SignalsPanel` lists model signals, while price/volume market catalog is separate. There is no unified daily triage queue: needs review / data stale / researched / passed / paper tested / logged. 

**Solution:** Create a **Today** landing view (not an auto-trader), sourcing existing backend endpoints; show compact rows: event, market, thesis type, displayed edge, validation state, source freshness, close time, liquidity and primary action **Research**. Distinguish estimated edge from guaranteed arbitrage-like structures, and retain provenance badges. Implement watch/save/pass annotations locally if not already available; do not fabricate derived states.

### P1 — Navigation exposes implementation modules, not trader jobs

Current Terminal subtabs `Scanner`, `Watchlist`, `Signals`, `Paper & execution`, `Models & evidence`, `Setup & health` plus top-level Markets/Games/History create multiple levels and inconsistent vocabularies.

**Solution:** Primary navigation: **Today**, **Explore**, **Docket**, **Journal**, **Learn**; contextual Explore switch **Games | All markets**; move models/evidence/system to panels or utilities. Retain redirects for existing hash links and browser back/forward. No destructive renaming of backend contracts.

### P1 — Details often read like developer diagnostics

Market/event and signal views expose detailed identifiers, fee schedule versions, rule samples, model run IDs and diagnostics inline. These support auditability, but do not all need equal visual weight.

**Solution:** Progressive disclosure with three layers: (1) Decision summary, (2) research evidence and assumptions, (3) inspection/audit details. Make model limitations, staleness and resolution caveats impossible to miss. Never bury material risks behind optional disclosure.

### P1 — Refresh state is scattered

`ControlBar` appears in several headers while pages independently load data and polling is distributed. It is not always obvious whether a quote came from the last catalog scan or a recent market-specific refresh.

**Solution:** One global **Data heartbeat** in the top chrome: source, last market scan, worker state, backend status and stale indicator. Each price still carries its own **as of** timestamp and freshness policy. A manual refresh must clearly identify which scope it updates.

### P1 — Education is implemented, but inconsistently surfaced

`Term.tsx` already provides accessible glossary triggers. Many game-specific explanations still use native `title` attributes, which are poor on touch and less useful than the fuller glossary UI.

**Solution:** Keep `Term`, glossary registry, and detail dialog as the canonical definition system. Use consistent dotted-underlined labels / subtle info icons for specific terms (`implied probability`, `fair price`, `correlation`, `walk-away`, `spread`, `EV`, `CLV`, `overround`, `taker`). Provide one short sentence inline at decision points, plus layered deeper explanation on interaction. Do not pepper every table cell with tooltips.

### P2 — Dense game/player market surfaces could support quicker scanning

GameBoard chip rails and player grids are strong primitives but can benefit from sticky row/column headers, side-by-side team grouping, keyboard shortcuts, saved filters, selection visibility, and previews that do not cause page jumps.

**Solution:** Enhance grid with sticky player column and accessible keyboard selection; show a narrow **selection preview** in the right dock, keep chips legible, and encode out/ineligible status beyond color.

### P2 — Journal is separate from the next decision

HistoryPage contains performance, calibration, open-position, and coaching analysis. Yet when researching a similar market the user must visit My trades separately to consult prior behavior.

**Solution:** Contextual **From your history** module in the Docket: category/series historical trade counts, fees and outcomes if statistically meaningful; link to full journal. Mark small samples and never present coincidental patterns as proven edges.

## Proposed product model

### Desktop shell

- **Top bar** — wordmark; global search / command menu; market freshness; mode (paper/live) & execution status; settings.
- **Slim left rail** — Today, Explore, Docket, Journal, Learn, using simple hairline glyphs.
- **Center work surface** — current research view, usually lists and charts on paper-like panels.
- **Persistent right rail** — Docket: current selection, probability provenance, quote, fees, max price, reasons, saved notes; collapsible in Browse mode.
- **Mobile/narrow** — Docket as bottom sheet with a persistent small status handle; navigation bottom bar or compact top menu.

### Five-step journey

1. **Discover** — shortlist ideas from scanner, opportunities, Games, catalog and watchlist.
2. **Understand** — resolve exact rules, provenance, freshness, baseline and what must happen.
3. **Price** — model vs market, spread, all-in costs, sizing illustration, confidence and contraindications.
4. **Decide** — Save/Pass/Paper-test; future live execution is a separate explicit confirm flow, with no silent transfer of authorization.
5. **Reflect** — journal, realized vs expected, calibration, errors, and lessons for similar future events.

A single event should be linkable as a deep link and recover its contextual state on reload, without retaining any sensitive approval state.

## Warm wood / hairline design language

### Art direction: **Walnut Atelier**

Concept: a walnut drafting table with archival paper, technical ink lines and a minimal scientific instrument. Modern and restrained; not a casino dashboard, not a skeuomorphic stockbroker desk.

### Palette (suggested tokens, to verify for WCAG contrast)

```
--canvas:       #F5F0E6;  /* parchment */
--surface:      #FFFCF6;  /* paper */
--surface-alt:  #ECE3D5;  /* warm inset */
--ink:          #2D2925;  /* charcoal walnut */
--ink-secondary:#625B53;
--muted:        #746E66;
--hairline:     #D7CDC0;
--hairline-strong: #B9AA98;
--walnut:       #5A3F31;  /* navigation / brand furniture */
--bronze:       #936B42;  /* focus / active decorative emphasis */
--positive:     #285E58;  /* accessible favorable status */
--negative:     #A5483C;  /* accessible adverse status */
--warning:      #8C622E;
```

Use semantic success/negative colors **only** for data outcomes and statuses; make sure labels/icons carry meaning too. Do not change a positive EV to amber merely to match the brand.

### Material rules

- **Warm wood as an accent surface:** narrow left rail, header edge, or side docket cap. Use CSS-generated low-contrast grain or one optimized texture asset at most; no random AI wood-image backgrounds.
- **Paper as the data plane:** warm off-white content with near-white cards and subtle etched horizontal lines. Keep charts clean and mostly white.
- **Hairline strokes:** 1px borders, no drop shadows or glows, restrained 6–10px corners, strong whitespace rhythm.
- **Typography:** readable editorial sans for UI, restrained serif for selected page titles or editorial notes, tabular mono for prices/tickers. Avoid mixing more than three font families; rely on local/system fonts or bundled licensed assets.
- **Motion:** reuse existing `@lucasmarkes/hairline` as chapter markers, skeleton/empty states and intentional transitions; never run large animations amid fast-changing market data; respect reduced motion.
- **Density modes:** Comfortable (default) and Compact for markets tables, stored locally.
- **Charts:** thin strokes, restrained grid, clear legends and as-of data, accessible textual summaries.

### Visual anti-patterns

Avoid oversized gradients, glossy cards, dense wood grain behind text, wood knobs, colored capsules on every metric, unnecessary iconography, flashing charts, and generic AI-generated finance illustrations.

## Five key screen blueprints

### 1. Today — Daily research queue

Header: `Today's desk` + last verified data timestamp + refresh control.

Left/center: shortlist table segmented **Needs attention / Researching / Paper tracked / Passed**. Columns: event, candidate type, net edge (when evidenced), confidence/freshness, closes, quick note. Filter by Economics, NBA, Culture, Tech. One-click opens research workspace and focuses docket. Right rail: Docket or upcoming contract close reminders.

### 2. Explore — Markets and games

Segment switch between the existing `GamesPage` and `MarketsPage` views. Keep event/category selection in route; add global search across markets. In Games use narrow game list + flexible player market grid + Docket. In Markets use category filters + event table + Docket. Use one quote-selection pattern.

### 3. Research Workspace — Deep dive

Breadcrumbs and shareable link → title/rules summary → decision snapshot (`Market vs model`, estimated costs, downside, timestamp) → evidence timeline / graph → alternative contracts and correlated exposure. Right Docket: selected sides, fees, slippage, current action. Advanced tab: technical lineage and raw rule versions.

### 4. Docket — Decision and safety

Permanent compact selection and quote/stale status; detailed review expands. Sections: `What would have to happen?`, `What the price implies`, `My evidence`, `Where the model may be wrong`, `What I would pay`, `Why I would pass`, `Save/Paper`. If live execution exists, separate guarded screen with exact order, expiry, PIN and revalidation; no generic approval by click.

### 5. Journal — Learn from realized results

Overview becomes: `Portfolio now` (cash, open positions, fees, unrealized status), `What changed` (week/month), `Decision quality` (calibration, entry vs close with small sample caveats), `Patterns and lessons` with links back into related research, then detailed ledger.

## Component / code plan

### Reuse

- `Hairline.tsx`: keep motion and figure signature.
- `Term.tsx`, glossary: extend to the same decision UI and tables.
- `GameBoard.tsx`: retain prop rails and player matrix.
- `EventView.tsx`: retain ladder/stats math.
- `BetSlip.tsx`, `SlipCheck.tsx`: retain analysis and inputs.
- `HistoryPage.tsx`: retain analysis data and coaching.
- `ExecutionPanel.tsx`: preserve server validation and approval flow.

### Refactor / add

- `components/shell/AppShell.tsx`, `LeftRail.tsx`, `Topbar.tsx`, `DataHeartbeat.tsx`, `GlobalSearch.tsx`.
- `components/docket/ResearchDocket.tsx`, `DocketSummary.tsx`, `DecisionBreakdown.tsx`, `DocketProvider.tsx`.
- `components/today/TodayPage.tsx`, `CandidateRow.tsx`, `CandidateFilters.tsx`.
- `components/research/ResearchWorkspace.tsx`, `ContractRules.tsx`, `EvidenceTimeline.tsx`, `PriceVsModel.tsx`.
- `components/design/Surface.tsx`, `HairlineDivider.tsx`, `Metric.tsx`, `StatusLabel.tsx`, `TooltipLabel.tsx`.
- `router/`: replace brittle page-only hash parsing with declarative typed route handling (library optional), preserving old deep links.
- `styles/tokens.css`, `styles/materials.css`, `styles/layout.css`; migrate current CSS gradually, maintaining old selectors until each view is moved.

One canonical slip/Docket store should be reused across Games, Markets and Today. Do not duplicate state or recalculate financial quantities in frontend if backend already provides the canonical values.

## Staged implementation plan for Fable

### Phase 0 — Visual and workflow baseline

Capture current desktop (1440x900), laptop (1280x800), narrow tablet (768px), and mobile (390px) screenshots for all major pages using the running app, with mock/fixture data and non-secret configuration. Trace five user tasks and record friction counts. Check the real browser before replacing layout. **Deliverable:** before screenshots, UI inventory, keyboard audit, failure-state catalog.

### Phase 1 — Theme and foundational UI (low risk)

Add Walnut Atelier tokens to a new theme file; preserve existing class names, positive/negative semantics and accessible contrast. Build reusable primitives and responsive density. Restyle header and table surfaces without rewriting feature logic. **Tests:** visual regression screenshots, WCAG contrast, focus, reduced-motion, phone overflow.

### Phase 2 — Navigation / Today (high impact)

Introduce new shell + Today page from existing scanner, signal, catalog and game idea APIs. Route preservation; unify saved research status where durable server support is missing. Avoid treating candidate types with different math as directly comparable rankings. **Tests:** direct deep link, back/forward, load/error/empty/stale, keyboard navigation.

### Phase 3 — Persistent Docket (highest workflow impact)

Wrap existing slip state in a typed global provider. Show one Docket across Games, Markets and Today. Add clear side semantics, source timestamps, evidence, pricing and reasons. Preserve quote estimation and warning behavior. Avoid showing historical frequency as a calibrated probability. **Tests:** cross-page persistence, rapid selection changes, no stale analysis flashing, state restoration, kill-switch unaffected.

### Phase 4 — Research workspace

Link event, signal, opportunity and candidate surfaces into a deep-linkable workspace. Progressive disclosure: one decision summary, then evidence + caveats, then raw audit. **Tests:** source linkage and all condition/fee assumptions, staleness, deep link reload, data provenance.

### Phase 5 — Journal and education

Bring 'similar past trades' summaries into research (with minimum-sample thresholds), enhance Journal and standardize glossary tooltips. **Tests:** no misleading positive trend on tiny samples; touch and screen reader; tooltip Escape and focus return.

### Phase 6 — Polish / validation

Usability walk-throughs (5 tasks), visual regressions, responsive tests, axe checks, no critical failing unit/integration tests. Compare time-to-evaluate, click count, tab switches, and decision-error rates with baseline. Confirm that production order gating, PIN, stale quote handling, idempotency and limits are completely unchanged without separately approved backend work.

## Success measures

- Time from finding a candidate to a documented pass/paper decision.
- Number of page/tab switches to evaluate one contract.
- Percentage of candidates with a visible evidence freshness indicator.
- Percentage of model/price comparisons with clear provenance and cost assumptions.
- Ability to resume research after navigating away or reload.
- Zero unauthorized live-order submissions; execution safeguards fully regression-tested.
- Keyboard/touch completion of all core tasks.

## Agent handoff — first assignment

> Inspect the existing repository and running interface. Follow this audit as the target but validate it against the current code and screenshot the current app before modifying it. Implement **Phase 0 and Phase 1 only**: a warm Walnut Atelier token system, accessible hairline primitives, responsive app shell prototype and non-destructive theme migration. Preserve all financial calculations, APIs, execution approval semantics, and existing route behavior. Run all relevant tests and report changed files, tests, screenshots, and unresolved issues. Do not implement live-trading changes.

## Source references

- [`App.tsx`](https://github.com/kaungthiha/trading-bot/blob/main/frontend/src/App.tsx)
- [`theme.css`](https://github.com/kaungthiha/trading-bot/blob/main/frontend/src/theme.css)
- [`Hairline.tsx`](https://github.com/kaungthiha/trading-bot/blob/main/frontend/src/components/Hairline.tsx)
- [`GamesPage.tsx`](https://github.com/kaungthiha/trading-bot/blob/main/frontend/src/components/games/GamesPage.tsx)
- [`BetSlip.tsx`](https://github.com/kaungthiha/trading-bot/blob/main/frontend/src/components/games/BetSlip.tsx)
- [`MarketsPage.tsx`](https://github.com/kaungthiha/trading-bot/blob/main/frontend/src/components/markets/MarketsPage.tsx)
- [`OpportunitiesPanel.tsx`](https://github.com/kaungthiha/trading-bot/blob/main/frontend/src/components/OpportunitiesPanel.tsx)
- [`SignalsPanel.tsx`](https://github.com/kaungthiha/trading-bot/blob/main/frontend/src/components/SignalsPanel.tsx)
- [`HistoryPage.tsx`](https://github.com/kaungthiha/trading-bot/blob/main/frontend/src/components/history/HistoryPage.tsx)
- [`Term.tsx`](https://github.com/kaungthiha/trading-bot/blob/main/frontend/src/components/Term.tsx)
- [`ExecutionPanel.tsx`](https://github.com/kaungthiha/trading-bot/blob/main/frontend/src/components/ExecutionPanel.tsx)
