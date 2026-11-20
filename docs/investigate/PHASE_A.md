# Investigate this pick: Phase A (interface skeleton)

Spec: `trading_bot_investigate_pick_fable_prompt.md`. Phase A builds the drawer against
**sample data** only. It makes no Brave or Ollama calls, and the UI labels everything as a
preview.

## Audit (current branch vs the spec's file list)
- `games/BetSlip.tsx` no longer exists. The UI/UX Phase 3 Docket
  (`docket/ResearchDocket.tsx`) is now the slip on Today, Games, All markets and Research,
  over the same `games/slip.ts` store. The entry point lives there.
- Reusable as-is:
  - **Leg evidence** (`/api/games/evidence`): `kind` (team_win / team_margin / game_total /
    team_total / player_stat), `line` and `subject`.
  - **Scan time** (`docket/scanTime.ts`).
  - **Slip check** (fees, walk-away), **second opinion** (Ollama), and **news search**
    (`sportsdata/news.py`, Brave).
  - **Glossary** (`Term`) and **tips** (`design/Tip`).
- **No calibrated model exists for NBA single-game markets.** Box-score frequency is a
  frequency, not a probability, so the price lens says so rather than showing an edge.

## Built
- **Contract types** (`api/types.ts`): `InvestigationResult` follows section 6 of the spec
  (hypothesis, quote, summary, price assessment, details, sources, processing) plus
  `ResearchUsage`.
- **`investigate/hypothesis.ts`**: builds the exact hypothesis from the selected leg.
  - The key is ticker + side, so YES ≠ NO and every line is its own ticker.
  - Market type comes from the evidence, falling back to the series. A winner has no line.
  - Supported: NBA single-game winner, spread, totals and player props. Other leagues,
    season-long markets and non-sports markets explain why instead of offering the action.
- **`investigate/store.ts`**: drawer state and one canonical result per hypothesis.
  - Runs only on click and is de-duplicated: a second click, re-render or reopen reuses the
    job, and a run counter is asserted in tests.
  - Expanding the full view only reads the stored result.
  - The `ResearchSource` interface (preflight / run / usage) is the seam for Phases C–D.
- **`investigate/InvestigationDrawer.tsx`**:
  - **Layout:** a right-hand dossier over a light scrim; a full-width sheet on phones.
  - **Accessibility:** modal dialog with labelled title; focus moves in, Tab is trapped,
    Escape works wherever focus is, and focus returns to the trigger.
  - **Before running:** statement, contract, quote with age and fresh/stale label, model
    (or "no calibrated model"), and the search budget note.
  - **Summary by default:**
    - a takeaway clamped to 2 sentences and at most 3 findings, each with a stance and
      source markers (unknown source ids are shown as "unverified");
    - a price lens that never invents an edge;
    - one "still unknown" item;
    - a quiet line with source count, last checked and refresh.
  - **"View full research", collapsed:** what supports it, what could make me wrong, is the
    price justified, sources and methodology (access level, duplicates marked "not
    independent", different-line or past-matchup flags).
- **Entry point:** "Investigate" on each Docket leg, or "can't investigate" with the reason.

## Tests (12 new, 134 frontend total, all passing)
- Hypothesis exactness: YES vs NO, moneyline vs spread, distinct thresholds, no line on a
  winner.
- Results follow side and line; unsupported markets explain instead of offering the action.
- Summary is clamped to 2 sentences and 3 findings.
- Opening is free and leaves the slip untouched; Escape returns focus to the trigger.
- Summary shows by default, full research is collapsed, and expanding makes zero extra runs.
- Unknown source ids are marked unverified; double clicks, re-renders and reopening start
  no second job.
- Degraded modes (model offline, Brave not set up, budget used up) are explained.
- Escape works after focus leaves the drawer; Tab is trapped.

Browser check (1440 and 390): the default summary fits the drawer viewport (ends at
717 / 1000 px and 780 / 844 px), axe finds 0 violations inside the drawer, and there are no
page errors.

## Next
- **B:** real quote (catalog ask and age), box-score evidence, slip-check numbers, rules link.
- **C:** Brave discovery with a durable usage ledger and caps, rights-aware publisher
  registry, cache, and event/line matching.
- **D:** Ollama claim extraction with citation checks and fail-closed output.
- **E:** more entry points (Ideas, Markets, scanner).
- **F:** quality pass.
