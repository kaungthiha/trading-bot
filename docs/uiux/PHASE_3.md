# UI/UX buildout: Phase 3 (the Research Docket)

Follows `PHASE_2.md`. No financial maths, API, execution or approval code changed; the
Docket calls the same endpoints the slip already used.

## What changed
- **One Docket, three pages.** The slip store (`games/slip.ts`) was already shared, but the
  UI was split: Games had `BetSlip`, Markets had a separate `ComboTray`. Both are gone; one
  `docket/ResearchDocket.tsx` renders at the app shell on **Today, Games and All markets**
  (not on Journal, Learn or Tools). Legs persist across pages and reloads.
- **Layout.** ≥1180px: a full-height right column (360px) that collapses to a 52px strip
  (remembered locally). Below: a bottom sheet with a summary handle ("Docket · 2 legs · fair
  19.4¢"), Escape closes it; on phones it sits above the bottom nav.
- **Decision structure** (audit blueprint), in order:
  1. Legs (side toggle, market-implied %, history verdict, L10, injury, research drawer).
  2. Fair price / history-adjusted / Kalshi eligibility (as before).
  3. **What would have to happen**: sides in words ("Happens" / "Doesn't happen"); "all N
     must go your way". Always visible.
  4. **Where this may be wrong**: injuries, unsupported legs, thin data, linked same-game
     legs (lift), combos Kalshi can't build, the backend's warnings, and the standing
     "history ignores tonight's matchup" caveat. Always visible (material risks are never
     collapsed).
  5. **What the price implies**: market-implied per leg + independent fair, with the scan
     time as its source timestamp.
  6. **My evidence**: last 10 / season / history estimate with range, labelled as a
     frequency from a small sample, **not a calibrated probability**.
  7. **What I would pay**: the existing slip check (stake, quote, walk-away, alternatives).
  8. AI second opinion (unchanged).
  9. **Save or pass**: decision + reason, saved locally (`krt.dockets.v1`, ≤25, 60-day
     expiry, validated on read) with the fair price as a labelled snapshot. Listed in the
     Docket and on Today under **Saved research**, with "Load into docket".
- **No stale numbers.** Combo and evidence results are keyed to the exact legs they were
  computed for; while a new request is in flight the Docket shows a loading mark, never the
  previous slip's price, and late replies for old legs are ignored.
- **Shared scan time.** `docket/scanTime.ts` is one cached fetch used by the top bar and
  the Docket.

## Tests
109 frontend tests pass. New `docket/Docket.test.tsx`: cross-page persistence (Markets →
Today → hidden on Journal → Games), rapid leg changes with out-of-order replies (only the
final price ever shows), side wording / frequency label / risk list, save → stored → load,
tampered saved storage, collapse persistence and sheet Escape. Games, Markets and Ideas
tests now render the page with the Docket. Execution / kill-switch tests unchanged and
passing. axe: 0 violations on all pages and inside the Docket with legs (desktop and phone
sheet). Build and bundle secret scan clean.

## Still open
- "Paper" action from the Docket: paper orders use internal market ids, not catalog tickers;
  needs a backend mapping before it can be offered honestly.
- Today rows can't be pushed onto the Docket yet (scanner ideas are multi-leg structures
  bought separately, not parlays, so they must not be priced as one).
- Phase 4: deep-linkable research workspace; Phase 5: journal context in the Docket and
  `Term` tooltips in place of native `title`.
