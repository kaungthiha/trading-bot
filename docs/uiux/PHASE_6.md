# UI/UX buildout: Phase 6 (validation and polish) and final comparison

Closes the buildout in `trading_bot_uiux_audit_buildout.md` (phases 0–6). Phase 6 changed
no backend code.

## Safety boundaries: unchanged
Checked against commit `7a1e964` (the last commit before Phase 0):
- `backend/app/execution/`, `backend/app/paper/`, `api/execution_routes.py`,
  `api/paper_routes.py`, `core/security.py`, `core/config.py`, `ExecutionPanel.tsx`,
  `PaperPanel.tsx`: **no diff**.
- Write routes (non-GET) are the same 12, and `backend/tests/test_api.py`, which pins that
  set, is unchanged and passing. Every backend change across phases 4–5 was a read-only GET
  or wording in existing read-only summaries.
- Execution, approval, PIN, kill-switch, stale-quote and paper tests: 85 selected, all pass.
  The full backend suite passes.
- Phase 6 lazy-loads the execution panel. It is the same component, behind the same
  server-side approval flow.

## Polish
- **Code splitting:** Journal, Learn, All markets, Research and each Tools panel load on
  demand. The main JS went from 500 kB (Phase 4) to **400 kB / 129 kB gzipped**, and Vite's
  size warning is gone. The bundle secret scan now checks all 38 output files.
- **Focus on navigation** waits for the new page's own title, so lazy pages still get focus,
  and focus never lands on the old page's title while it unmounts.
- **Scrollable tables on phones** (scanner cards, research legs) are now focusable,
  labelled regions, so keyboard users can scroll them (axe `scrollable-region-focusable`).

## Final sweep
| Check | Result |
| --- | --- |
| Horizontal overflow, 9 pages × 1440/1280/768/390 | **0** |
| axe (WCAG 2.1 AA + best practice), 9 pages at 1440 and 390 | **0 violations** |
| Page errors / failed requests during the sweep | **0 / 0** |
| Frontend tests | 122 pass (typecheck, build, bundle scan clean) |
| Backend tests | all pass, ruff clean |

The 9 pages are Today, Games (with a game open), All markets, Journal, Learn, Tools,
scanner-idea research, signal research and event research.

## Five tasks, scripted against the live app
| Task | Phase 0 (traced) | Now (measured) |
| --- | --- | --- |
| 1. Price a two-leg game combo | 1 page, ~4 clicks; risks in a collapsed note | 4 clicks, 1 page change, 2.4 s; fair price **and** "where this may be wrong" visible together |
| 2. Act on a scanner idea | inside a Terminal card; no page to share or reopen | 2 clicks to a deep-linkable research page with the decision summary and checklist |
| 3. Check a bet against your history | Markets → event → My trades → Behavior: 2 page changes, combo tray left behind | 4 clicks, 1 page change; history beside the bet, slip kept, small samples labelled |
| 4. Reach the AI read of open positions | 2 clicks | 2 clicks (unchanged) |
| 5. Understand a term while pricing, on a phone | 30+ native `title` hints that never show on touch | 1 tap on "Fair price" opens the glossary entry; tips open by tap |

Every task completed with no page errors. Time-to-decision and decision-error rates need real
sessions; they can't be measured honestly by a script.

## Against the audit's success measures
| Measure | Phase 0 | Now |
| --- | --- | --- |
| Page/tab switches to evaluate one contract | 2+ with context loss | 0–1, with the Docket persistent |
| Candidates with a visible freshness indicator | scanner and games partial; signals none; no global | every Today group and research page shows as-of times; global "prices scanned" with a stale flag |
| Model/price comparisons with provenance and costs | spread across panels | every measure labelled (market-implied / model / history frequency); all-in cost broken into entry + fee + slippage |
| Resume research after navigating away or reload | slip persisted; nothing else | Docket, triage marks, saved research, and deep links for ideas, signals and events |
| Unauthorized live orders / safeguards | none | none; execution code and write routes unchanged (above) |
| Keyboard/touch completion of core tasks | phones overflowed; touch hints missing | all five tasks scripted; touch task done by tap; 0 axe violations |

## Left for later
- Real-user walk-throughs (time-to-decision, decision errors) and a dark theme.
- Today category filter (needs a category field on scanner/signal responses).
- A "Paper" action from the Docket (needs a ticker → internal market id mapping).
- `report()['markets']` caps history comparisons at the 200 most recent closed markets.
- On Windows, run frontend tests from `C:\…` (uppercase drive); see `PHASE_5.md`.
