# Educational UI and Tooltip Design

The interface is both research workstation and learning tool. Every meaningful finance/trading/quant/market term introduced in primary UX should be discoverable without leaving the workflow.

## A centralized registry
Implement `frontend/src/glossary/terms.ts` as a typed map of stable glossary IDs. Each entry: `id`, `label`, `aliases`, `category`, `shortDefinition` (aim ≤ 200 chars), `example`, `deepExplanation`, `formula?`, `sourceUrls?`, `reviewedAt`, `relatedTermIds`. Keep wording as plain English, then progressively expose math where useful. `docs/GLOSSARY.md` is initial editorial source; build may serialize from typed registry but must avoid divergent duplicated definitions.

## Reusable components
- `<Term id="spread">spread</Term>` accessible term marker, with `aria-describedby` to tooltip when open.
- `<MetricLabel termId="brier-score">Brier score</MetricLabel>` for table headers/cards.
- `<GlossaryPage>` searchable by term, alias and category, links to examples and related topics.
- `<LearnMore>` opens a proper dialog/popover with longer explanation, formula and sources.

## Interaction
Mouse hover and keyboard focus reveal short non-interactive tooltip; Escape dismisses; keep keyboard focus on trigger. Hoverable tooltip body where applicable and no premature dismissal while navigating pointer. For touch, offer click/tap entry into detailed definition; do not depend on hover. Detail views with links or controls are **not ARIA tooltips**; use a dialog/popover appropriate to the interaction. Avoid repeating an info icon every cell; glossary-aware column headers and first significant occurrence in a section are usually enough. Links and buttons visibly focusable, sensible contrast and placement. Follow W3C tooltip and WCAG hover/focus patterns.

## Editorial style
Answer: 'What does this mean?', 'Why does it matter here?', and 'What could mislead me?' Use concrete numbers, neutral language, and distinguish estimated from realized. Define bid/ask from the user's perspective, show an actual $0.01–$0.99-style contract example only if price grid permits, and specify who pays fees. Do not imply confidence interval = chance of profit, or 70% p = certainty.

## Required validation
Build test that every `termId` used in JSX exists; glossary entries have nonempty short definitions and category; aliases don't collide ambiguously; no duplicate IDs; keyboard focus/Escape/hover/touch behavior tested; UI audit of designated jargon components (not a brittle global word-ban); links reviewed. Add story/demo showing tooltip and long-form explanation for 'edge', 'slippage', 'Brier score'.
