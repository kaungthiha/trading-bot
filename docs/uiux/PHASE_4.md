# UI/UX buildout: Phase 4 (research workspace)

Follows `PHASE_3.md`. No financial maths or execution code changed. Backend: two read-only
GET endpoints and one additive response field.

## What changed
- **Deep-linkable research pages** (`frontend/src/components/research/`):
  - `#/research/opp/<id>`: a scanner idea.
  - `#/research/sig/<id>`: a model signal.
  - `#/research/event/<event ticker>`: an event.
  Ids are validated by the router; a malformed link falls back to Today. Reloading a link
  re-fetches everything. "Copy link" copies the address (ids only). Breadcrumbs lead back to
  Today. The Docket stays alongside.
- **Progressive disclosure** (audit P1), the same on every page:
  1. **Decision summary**, always open. Scanner idea: total cost incl. fees, minimum payoff,
     profit if rules hold, downside. Signal: model chance for the chosen side (with band),
     all-in market cost (entry + fee + slippage), EV and conservative edge per contract.
     Abstained signals say so instead of showing empty numbers. **Risks to check are in this
     layer** (checklist, rule caveats, model caveats), never collapsed.
  2. **Evidence and assumptions**, open: every leg with limit, quantity, cost, fee and depth;
     the fee schedule version; price freshness; signal reasons and per-side breakdown; rules
     link.
  3. **Audit details**, collapsed: ids, budget cap, journal, signal lineage trace.
- **Staleness**: expired / executed / skipped ideas and expired or rule-invalidated signals
  get a banner above everything.
- **Linking**: Today's scanner and signal rows open their research page; positions outside
  a game open their event page; scanner and signal card titles in Tools link here; idea and
  signal pages link to their event. The event page lists your open positions, scanner ideas,
  signals and saved research for that event, then the event's markets (the same view as
  Explore, adding to the Docket as usual).
- **Backend**: `GET /api/opportunities/{id}`, `GET /api/signals/{id}` (404 when unknown),
  and `market_event_ticker` on signals. No new write routes.
- **Accessibility**: the scanner card `heading-order` issue from Phase 0 is fixed (card title
  is now an `h3`). axe: 0 violations on every page, including Tools and all three research
  pages.

## Tests
Frontend 117 pass. New `research/Research.test.tsx`: route parsing and builders (rejects bad
ids), scanner idea deep link (summary numbers, risks visible, every leg and the fee schedule,
audit collapsed, event link, Docket present), expired banner, not-found and retry, signal
side-adjusted model chance and all-in cost with staleness and caveats, abstained signal,
event page linking (filters to the event), copy link. Backend suite passes, including new
assertions for both single-item endpoints and the event field. Ruff clean, build and bundle
secret scan clean.

## Still open
- The JS bundle crossed Vite's 500 kB warning (≈153 kB gzipped). Fine locally; code-split the
  research and history pages in Phase 6 if it matters.
- An event page for a game event could also show the game's Ideas screen; for now it links
  to the game from the markets view.
- Phase 5: history context in the Docket ("from your history", with sample-size guards) and
  `Term` tooltips in place of native `title`.
