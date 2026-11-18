# Tests, Validation and Acceptance Suite

## Test layers
**Unit:** Decimal pricing, derived asks, fee adapter fixtures, probability bounds, Brier/log loss, timestamp cutoffs, glossary IDs, reason-code logic. **Integration:** SQLite migration, restart/idempotency, API pagination, read-only exchange fixture adapter, mock external source, local worker retry. **Frontend:** accessible tooltips, keyboard Escape, touch detail, table headers, filters, stale indicators. **End-to-end:** market discovery → rules → evidence → model → signal → paper trade → settlement report, with deterministic fixtures.

## Specific tests
1. YES bid 0.43, NO bid 0.55 → derived NO ask 0.57 and YES ask 0.45; absent NO bid → no YES ask.
2. Prices are Decimal and adhere to market-specific `price_ranges`; reject off-grid order proposals.
3. A quote older than configured age yields `ABSTAIN`.
4. Rule-text hash change invalidates existing signals.
5. Evidence `available_at` after forecast cutoff must not enter features.
6. Repeated ingestion of same source revision creates no duplicate.
7. Modeled costs turn positive raw EV negative when appropriate.
8. Partial paper fill can't exceed visible simulated depth; never mark unfilled remainder as purchased.
9. Authenticated/write endpoints are never contacted by tests 01–08.
10. An unknown glossary term ID causes a type or test failure.
11. Hover/focus tooltip is dismissible with Escape; links exist only in separate detail popup, with touch fallback.
12. No external credential, PII or authorization header is leaked in frontend bundles/log output.
13. App restarts without resetting paper history or duplicating workers' snapshots.
14. Model backtest compares correct point-in-time vintage and calendar split.
15. Disabling source access causes explicit error status rather than invented model input.

## Quality report
Report test count, failures/skips, dependency versions, DB migration status, date/time of external API fixture capture, stale-data configuration, model-validation sample size, source coverage gaps, known risk/assumption list and unimplemented features. Require human inspection before any financial claims or future live mode.
