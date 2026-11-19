# UI/UX buildout: typography and Phase 2 (navigation + Today)

Follows `PHASE_0_1.md`. No financial maths, API, execution or approval code changed.

## Typography
Bundled, open-licensed (SIL OFL 1.1) faces via Fontsource, latin subset, served from the app
(`font-src 'self'` added to the production CSP; nothing is fetched from a font CDN):
- **Fraunces** (variable, optical size): page titles, section heads, hero numbers, disclaimers.
- **IBM Plex Sans** 400/500/600 + italic: all UI text. Tabular figures everywhere.
- **IBM Plex Mono** 400/500: tickers, payloads, code.

About 240 KB of font files on first load, cached after. Type scale lives in
`frontend/src/styles/typography.css`; tokens in `styles/tokens.css`.

## Phase 2
### Navigation (audit P1)
Rail: **Today · Explore · Journal · Learn**, then **Tools** below a rule. Docket joins in
Phase 3. Typed router in `frontend/src/router.ts` with validated query values and link
builders. Every pre-Phase-2 link resolves:

| Old | Now |
| --- | --- |
| `#/` (Terminal) | Today. Terminal is `#/terminal` ("Tools"), `?tab=` deep-links a tab |
| `#/games`, `#/markets` | Unchanged URLs, under Explore with a Games / All markets switch |
| `#/history` | Journal (`#/journal` also works) |
| `#/glossary?term=` | Learn (`#/learn?term=` also works) |

On page change, focus moves to the new page title (closes the Phase 0 "Tab starts
mid-page" issue for in-app navigation).

### Today (audit P0 triage)
Four groups from existing endpoints, each with its own measure, label, as-of time,
loading skeleton, empty text and **Retry** on error (closes the Phase 0 "no retry" gap for
these sources). Groups are never merged into one ranking, because their maths differ:

| Group | Source | Shown measure |
| --- | --- | --- |
| Your open positions | `/api/history/open` | paid → now (mid), unrealized. Only warnings or ≤24h to close |
| Scanner ideas | `/api/opportunities`, `/api/scanner/status` | scanner profit after fees; guaranteed vs conditional |
| Model signals | `/api/signals` | conservative (lower-bound) edge per contract; VALID, non-abstain only |
| Games starting soon | `/api/games` | "Not screened yet": markets and volume only; screening is the Ideas tab |

Triage marks (*Researching*, *Pass*, note ≤280 chars) are stored in this browser only
(`krt.triage.v1`). The server has no such states, so none are inferred. Stored data is
validated on read (key pattern, status enum, note length, 30-day expiry).

### Data heartbeat (audit P1 refresh)
The top bar now also shows when prices were last scanned (catalog `refreshed_at`), marked
**stale** after 30 minutes, refreshed when a background job finishes.

### Tests
104 frontend tests pass (13 new: router parsing/aliases/builders, Today grouping and
filtering, triage marks and notes, per-source failure + retry, tampered storage, app-level
navigation with back/forward, focus and the Explore switch). Typecheck, build, bundle scan
clean. axe: 0 violations on Today, Explore, Journal, Learn; Tools keeps the one known
`heading-order` (scanner card `h4`).

## Still open
- Scan controls (`ControlBar`) still sit in page headers; the heartbeat shows freshness but
  not the button. Consider moving "Scan now" into the top bar in Phase 3.
- Today has no category filter (Economics / NBA / …): scanner and signal rows don't carry a
  category in their API responses. Needs a small backend field.
- "Paper tracked" segment from the audit is not shown: it would need a link from paper orders
  to candidates, which doesn't exist yet.
- Native `title` tooltips → `Term` (Phase 5); scanner `heading-order` (Phase 4).
