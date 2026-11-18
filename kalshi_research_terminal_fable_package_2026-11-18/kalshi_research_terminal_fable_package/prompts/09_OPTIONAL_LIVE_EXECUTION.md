# Prompt 09 — Optional approval-gated execution design

## Instructions to Fable / Opus 5.5

Read `AGENTS.md` and all relevant `docs/*.md`; review previous milestone artifacts. Implement this **one milestone only** and provide an actual test report.

## Objective
This phase is separately authorized ONLY. Review latest Kalshi write API, fees, auth and demo docs, security threats, order semantics. Implement strict approval contract and demo-first mock gateway.

## Deliverables
Per-order single-use approval, signed/backend-only request, CSRF/origin protections, cost/quantity/position caps, stale quote revalidation, kill switch, idempotency and response reconciliation; extensive adversarial tests.

## Explicit exclusions
Do not place real orders or enable production during implementation; user must explicitly authorize each real order and any activation.

## Engineering process
1. Inspect repo and explain relevant existing files.
2. Identify assumptions and verify official references when external APIs are involved.
3. Make smallest coherent feature implementation with typed contracts, config, robust errors and tests.
4. Add fixture-based tests with frozen time, mock network, and deterministic expected values.
5. Run available commands; only claim verified passes; fix errors.
6. Update README/spec docs to accurately describe what exists.
7. Report files changed, exact commands, test result counts, security review, remaining gaps.

## Acceptance criteria
Replay/duplicate approvals rejected; changed price fails closed; ambiguous timeout never blind-retries; demo tests pass; production disabled by default.

## Finance and education safety
Model probabilities are not profits. Use executable-side prices, conservative costs, official rules and source timestamps. Expose relevant terms from the central glossary UI. Never place a live order. Treat unverified API details as blockers to implementing those details, not invitations to improvise.

## Completion handoff
Once acceptance tests pass, recommend the next numbered prompt; do not implement it automatically. Explicitly list deviations or unresolved requirements.
