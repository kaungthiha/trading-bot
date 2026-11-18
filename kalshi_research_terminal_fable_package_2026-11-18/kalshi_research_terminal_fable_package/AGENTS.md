# Persistent Instructions for All Coding Agents

Read `README.md`, `MANIFEST.md`, all relevant `docs/` specifications and the active numbered prompt before editing. Work in bounded milestones. First inspect repo state; then write a short plan; implement; add tests; run commands; report actual results. Do not claim tests passed unless executed.

## Architecture and implementation
- Local-only browser frontend, FastAPI backend on `127.0.0.1`, SQLite via Alembic. Never expose secrets via frontend build variables or responses.
- Separate `ExchangeMarketDataAdapter`, `EvidenceAdapter`, `ProbabilityModel`, `SignalEngine`, `PaperBroker`, and future `ExecutionGateway` interfaces. No accidental cross-dependencies.
- Use typed interfaces and Pydantic validation. Use `Decimal` for USD, fees and contract-price calculations. Use timezone-aware UTC and preserve original exchange IDs.
- Maintain immutable snapshot/evidence/model-run/signal records; don't overwrite the past.
- Do not assume Kalshi has YES/NO ask arrays; derive complementary asks from opposite bids when valid, with derived provenance.
- Do not hard-code 1-cent tick increments, price-field precision, or a universal fee formula. Verify exchange details in current official docs.
- Include explicit uncertain/missing/stale data states and `ABSTAIN` decisions.

## Educational UX is mandatory
- Create one typed registry of financial, market, trading, quantitative and risk concepts with stable IDs, aliases, short definitions, example, long explanation and source/review metadata.
- Use consistent accessible term triggers rather than hand-written tooltip text. Support keyboard focus, Escape dismissal, mouse hover, and touch/click access to richer help. Tooltip must be non-interactive; detailed content uses a separate popover/dialog.
- In dense tables explain headers once rather than decorating every cell. Provide searchable glossary page. Tests must reject unknown term IDs.

## Security
- Real trading disabled by default. No submission paths in milestones 0–8. Mock/demo only in testing. Never autonomously call live endpoints or flip a live flag.
- Keep exchange secrets server-side only; never log them; prevent public API binds; appropriate origin/CSRF controls for future execution operations. Localhost is not sufficient authentication.
- The final optional execution milestone is design/implementation only, with user authorization required before any real orders.

## End-of-prompt completion report
Describe: files changed, commands run, tests passed/failed, demonstrated features, undocumented assumptions, security checks, known gaps, and recommendation for next prompt.
