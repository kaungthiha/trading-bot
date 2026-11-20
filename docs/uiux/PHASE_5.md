# UI/UX buildout: Phase 5 (history in context, honest records, accessible tooltips)

Follows `PHASE_4.md`. No execution code changed. Backend: one read-only GET and stricter
wording/levels in existing insights and suggestions.

## From your history (audit P2)
- `GET /api/history/similar?legs=TICKER:side,...&series=SERIES,...` (read-only, local data).
  Groups: same series, same market type, all your Kalshi combos, your combos with the same
  number of legs.
- **One rule for every summarised record** (`backend/app/history/similar.py`):
  - under 10 closed trades: counts and net P&L only, "too few to say"; no rate, no ROI;
  - 10+: return on money staked (total P&L ÷ total staked) against its standard error
    (ratio estimator, i.e. stake-weighted). Within 2 SE of zero: "within what luck alone
    produces". Beyond: better / worse than luck, "a record, not a forecast".
  - Stake weighting matters on real data: the user's 28 combos lost $70.23 of $72.68, but an
    unweighted mean was dominated by one 10¢ long shot that paid 13× and read as "noise".
    Weighted, it's 11 SE below zero: "worse than luck".
- Shown in the Docket (collapsed section, keyed to the current legs) and on event research
  pages.

## Journal (audit P2)
- By-type and by-series tables: groups under 10 markets show **"too few"** (with a tip)
  instead of an ROI, and their P&L is not coloured as a trend.
- Won-vs-price table: small-sample rows aren't coloured; the standard error is a tip.
- **Last 7 days** tally on Overview ("a tally, not a trend").
- Insights: the overall win-rate line is coloured only beyond 2 SE; "Best market type" is
  only called a strength when it beats luck (otherwise "Most profitable so far … too few or
  too noisy"). "Lean in" suggestions require a record that beats luck (previously 3 markets).
- Suggestion reasons are shown inline; their event links open the event research page.

## Tooltips and glossary (audit P1 education)
- New `design/Tip` replaces native `title` where it explained something (Docket verdicts,
  injuries, history-adjusted price, Games median line, Protected props, Ideas strength,
  open-position verdicts, Journal tips, event combo collections). Hover/focus shows it, tap
  toggles it on touch, Escape closes it and keeps focus on the trigger, tapping elsewhere
  closes it. `title` remains only where it duplicates visible text or an accessible name.
- Six glossary terms added (fair price, walk-away price, combo, overround, closing line
  value, sample size), synced to `backend/app/glossary.json`, and attached with `<Term>` at
  the decision points (Docket fair price, market-implied, combo; slip check walk-away; event
  overround; Journal entry vs close; history sample size).

## Tests
Frontend 122 pass: Tip keyboard/Escape/focus and touch toggle/outside tap; FromHistory never
shows a rate for a tiny streak and marks the threshold; Last-7-days tally; Journal "too few"
replaces a 1-market ROI; updated glossary count and research links. Backend suite passes:
assess (none / too few / noise / better / worse / tiny long shot can't hide losses), similar
grouping, insights guards, API (tiny sample → no ROI, bad ticker → 422). axe: 0 violations on
every page and inside the Docket with history open (desktop and phone). Build and bundle
secret scan clean.

## Notes
- Run frontend tests from a shell whose working directory uses an uppercase drive letter
  (`C:\…`). With `c:\…` vitest can load two copies of itself on Windows and every suite
  fails with "failed to find the current suite".
- `report()['markets']` is capped at the 200 most recent closed markets, so history groups
  cover at most those.
