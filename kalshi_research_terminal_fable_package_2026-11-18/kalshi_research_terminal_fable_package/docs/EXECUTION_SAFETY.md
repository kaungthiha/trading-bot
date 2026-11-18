# Live Execution Safety — Not Enabled by This Pack

## Mandatory separation
Research, signals, and paper trading cannot import or invoke order-creation code. Default `TRADING_MODE=paper`; `LIVE_EXECUTION_ENABLED=false`; invalid settings fail closed. Every distinct live order requires a fresh interactive user action granting authorization for market, YES/NO, buy/sell, maximum quantity, limit price, worst-case cost, expiry and unique approval ID. No broad session-level approval or programmatic autopilot.

## Future order flow
Proposal → fetch current quote/market rules → show exact order and maximum cost → local explicit approval with CSRF/origin/auth protection → persisted single-use intent → fresh backend eligibility, limit, fee, depth, status, safety ceiling checks → submit once using idempotency/client ID when supported → reconcile exchange order/fill state → append immutable audit. Reject changed price/cost rather than silently adjusting authorization.

## Threat model
Malicious browser website can send requests to localhost; browser extension or another local process may be hostile. Do not rely on loopback alone. Secrets only in backend secured local file/keychain, no logs, no frontend env; restrict CORS and origins; CSRF controls and sensitive-operation auth; audit retry and duplicate suppression. Network timeouts on submit are ambiguous; query order status before retry. Emergency disable switch should prevent any new live actions.

## User-managed bankroll
No allocation or rebalancing algorithm; guardrails allowed: maximum cost/contracts per order, market/event exposure, estimated daily loss, rate limits, quote age and spread. If a limit cannot be confidently measured, block rather than assert it passed.

## Readiness gates
Official Kalshi write endpoint/auth/fee docs reverified, sandbox/demo tests, limit price and fee checks, cancellation/partial fill reconciliation, duplicate-order tests, explicit user security review, separate explicit real-trading authorization. This file is a design spec, not permission to place trades.
