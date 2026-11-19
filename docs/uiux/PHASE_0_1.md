# UI/UX buildout: Phase 0 (baseline) and Phase 1 (Walnut Atelier foundation)

Target: `trading_bot_uiux_audit_buildout.md`. Scope was Phase 0 and Phase 1 only, as the
handoff asked. No financial maths, API, route, execution or approval code changed.

## Phase 0: baseline

### Screenshots
All five pages (Terminal, Games, Markets, My trades, Glossary) at 1440×900, 1280×800, 768×1024
and 390×844, before and after. They were taken from the running app with real local data, so
they stay out of the repo (they show account balances). Re-create them with any headless
browser against `http://127.0.0.1:5173`.

### Measured problems (before)
| Check | Result before | After Phase 1 |
| --- | --- | --- |
| Horizontal overflow at 390px | **All 5 pages** scrolled sideways (nav pill 71px too wide; 420px scanner cards; Markets sidebar) | 0 on every page and viewport |
| axe (WCAG 2.1 AA + best practice), 1280px | Terminal: 144 `color-contrast` failures (expired scanner cards at 60% opacity → 3.98:1). Games: 1 `aria-hidden-focus` | Terminal: 1 moderate (`heading-order`, see open issues). Others: 0 |
| Keyboard, Games deep link | First Tab landed on a decorative figure (riffle makes itself focusable) inside `aria-hidden` | Figure demoted to `tabindex=-1`; pointer interaction kept |
| Input borders vs paper | ~1.5:1 (below the 3:1 WCAG 1.4.11 asks for control boundaries) | `--field-line` 3:1+ token available; applied to new controls |
| Phone, Games | Sticky game list sat on top of the board while scrolling (single-column layout) | List is static below 720px with its own 42vh scroll |

### Keyboard audit (fresh load of `#/`)
Skip link → Compact rows → Terminal → Games → Markets → My trades → Glossary → page content.
Every stop shows a visible focus ring (ink on paper, light bronze on walnut). Tooltips (`Term`)
and the glossary dialog already handle Escape and focus return.

### Failure-state catalog
| Surface | Loading | Error | Empty | Stale/as-of | Retry |
| --- | --- | --- | --- | --- | --- |
| Scanner (OpportunitiesPanel) | yes | `role=alert` | figure empty state | scan time | none |
| Signals | yes | silent | none | quote age | none |
| Paper / Execution | none | `role=alert` (execution) | none | quote freshness gate | none |
| Models / Evidence | partial | `role=alert` | none | as-of shown | none |
| Games list / board / slip | skeleton + shimmer | `role=alert` | figure empty states | "prices Nh ago" | none |
| Ideas tab | yes | `role=alert` | yes | none | none |
| Markets / event | yes | `role=alert` | none | partial | none |
| My trades / Open | yes | `role=alert` | figure empty states | sync time | none |
| Glossary | n/a | n/a | "0 terms shown" | n/a | n/a |

Gaps: no surface offers retry after an error; Signals fails silently; Ideas has no as-of
time. These belong to Phase 2/3 (the global heartbeat and Docket show freshness).

### Five-task trace (friction)
1. **Price a two-leg game combo**: Games → game → chips → slip. 1 page, ~4 clicks. Low friction.
2. **Act on a scanner idea**: Terminal → Scanner card → checklist → journal. In-card. Low.
3. **Check a market against your own history**: Markets → event → My trades → Behavior.
   2 page switches and the selection is lost. **High** (audit P0/P2).
4. **AI read of open positions**: My trades → Open → button. 2 clicks. Low.
5. **Understand a term while pricing**: Terminal/Markets use `Term`; Games/My trades use 30+
   native `title` tooltips that never show on touch. **Medium** (audit P1 education).

Also confirmed: Games uses `BetSlip`, Markets uses a separate `ComboTray` for the same job
(audit P0 continuity). That's the Phase 3 Docket.

## Phase 1: what changed

### Tokens: `frontend/src/styles/tokens.css`
Walnut Atelier palette with every value checked:
- Text tokens ≥ 4.5:1 on paper, parchment and inset surfaces.
- **Deviation from the audit:** the proposed positive teal `#285E58` / negative `#A5483C` pair
  **fails** colour-blind separation (protan ΔE 4.4; floor is 8). Gains stay blue: `#356FA3`
  / loss `#B8483B` pass every dataviz-validator check (protan ΔE 15.8) on `#FFFCF6`.
- Old variable names (`--plate`, `--soft`, `--blue-ink` …) are aliases, so every existing
  selector re-skins without edits.
- Selection (chips, picked cells, the open game, tabs) moved from data blue to walnut, so
  blue now only ever means gain/series.

### Migration (non-destructive)
- ~180 hard-coded colours in `styles.css`, `theme.css`, `games/games.css` mapped to tokens by
  property (text on dark buttons → `--on-ink`, outlines → `--focus`). No selector renamed.
- Chart colours centralised in `styles/palette.ts` (SVG attributes can't read CSS vars);
  `PnlCharts`, `CalibrationChart`, `DistributionChart`, `LegResearch`, `OpenPositions` use it.
- Expired scanner cards: dashed edge + quiet fill instead of opacity (fixes 144 contrast fails).

### Materials and shell
- `styles/materials.css`: CSS-only walnut grain (no image), parchment page with a faint
  drafting dot, etched rules, paper `.surface`. Texture drops out in forced-colours mode.
- `styles/layout.css` + `components/shell/`: walnut left rail (desktop/tablet), bottom bar on
  phones, top bar with the **data heartbeat** (mode, execution, connection, source on hover)
  and a **Compact rows** density toggle stored in `localStorage` (`krt.density`, validated).
- Page titles use a locally installed serif (Palatino/Georgia stack); no web fonts loaded.
- Same five destinations and hrefs; every old deep link works. Task-based renaming is Phase 2.

### Primitives: `components/design/`
`Surface`, `HairlineDivider`, `Metric` (sign kept in text + class), `StatusLabel` (glyph for
states that need action). Presentational only; adoption into feature views is Phase 2+.

### Tests
- 8 new (`shell/Shell.test.tsx`): nav hrefs unchanged + `aria-current`, heartbeat states in
  words, density toggle persistence and tamper-resistance, primitives.
- All 91 frontend tests pass, typecheck clean, build OK, bundle secret scan clean.

## Open issues (not fixed, by design or scope)
- `heading-order` on Terminal: scanner cards use `h4` under a hidden `h2`. Changing it touches
  feature markup; fold into Phase 4 progressive disclosure.
- Deep-linking to a game starts Tab mid-page (the board scrolls into view). Pre-existing;
  Phase 2 routing should move focus to the page heading on navigation.
- `ControlBar` still appears in several page headers next to the new heartbeat. Consolidating
  scan controls into the heartbeat is Phase 2.
- Native `title` tooltips in Games/My trades (30+) → `Term` in Phase 5.
- No dark mode yet; tokens are structured so a dark set can be added and validated separately.
