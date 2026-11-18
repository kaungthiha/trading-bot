# Prompt 07 — Contextual glossary and learning mode

## Instructions to Fable / Opus 5.5

Read `AGENTS.md` and all relevant `docs/*.md`; review previous milestone artifacts. Implement this **one milestone only** and provide an actual test report.

## Objective
Make education a first-class feature across market explorer, research signal cards, model metrics and paper history.

## Deliverables
Typed 42+ term registry seeded from GLOSSARY, reusable Term/MetricLabel components, keyboard/hover/touch handling, separate detailed popover/dialog, searchable glossary page and examples.

## Explicit exclusions
No inconsistent ad-hoc definitions or hyperlinks embedded inside role=tooltip.

## Engineering process
1. Inspect repo and explain relevant existing files.
2. Identify assumptions and verify official references when external APIs are involved.
3. Make smallest coherent feature implementation with typed contracts, config, robust errors and tests.
4. Add fixture-based tests with frozen time, mock network, and deterministic expected values.
5. Run available commands; only claim verified passes; fix errors.
6. Update README/spec docs to accurately describe what exists.
7. Report files changed, exact commands, test result counts, security review, remaining gaps.

## Acceptance criteria
Unknown term IDs fail; Escape/focus/touch tests pass; first meaningful jargon occurrence is explained without visual clutter.

## Finance and education safety
Model probabilities are not profits. Use executable-side prices, conservative costs, official rules and source timestamps. Expose relevant terms from the central glossary UI. Never place a live order. Treat unverified API details as blockers to implementing those details, not invitations to improvise.

## Completion handoff
Once acceptance tests pass, recommend the next numbered prompt; do not implement it automatically. Explicitly list deviations or unresolved requirements.
