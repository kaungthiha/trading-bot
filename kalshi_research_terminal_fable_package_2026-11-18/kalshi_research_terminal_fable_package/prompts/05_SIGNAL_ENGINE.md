# Prompt 05 — Explainable fee-adjusted signals

## Instructions to Fable / Opus 5.5

Read `AGENTS.md` and all relevant `docs/*.md`; review previous milestone artifacts. Implement this **one milestone only** and provide an actual test report.

## Objective
Implement quotes+models→immutable signals using executable-side prices, cost assumptions, robustness and abstention gates.

## Deliverables
Signal creation, side-specific EV, fee versioning, spread/depth/freshness tests, conservative uncertainty and reason codes, dashboard cards with source links and timestamps.

## Explicit exclusions
No actual orders or auto approval.

## Engineering process
1. Inspect repo and explain relevant existing files.
2. Identify assumptions and verify official references when external APIs are involved.
3. Make smallest coherent feature implementation with typed contracts, config, robust errors and tests.
4. Add fixture-based tests with frozen time, mock network, and deterministic expected values.
5. Run available commands; only claim verified passes; fix errors.
6. Update README/spec docs to accurately describe what exists.
7. Report files changed, exact commands, test result counts, security review, remaining gaps.

## Acceptance criteria
Fees lower EV, stale/missing quote abstains, rule changes invalidate, signal always contains quote/model IDs and caveats.

## Finance and education safety
Model probabilities are not profits. Use executable-side prices, conservative costs, official rules and source timestamps. Expose relevant terms from the central glossary UI. Never place a live order. Treat unverified API details as blockers to implementing those details, not invitations to improvise.

## Completion handoff
Once acceptance tests pass, recommend the next numbered prompt; do not implement it automatically. Explicitly list deviations or unresolved requirements.
