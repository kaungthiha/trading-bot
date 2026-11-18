# Kalshi Research Terminal — Fable Build Package

**Version:** 2026-11-18 · **Delivery:** local-first developer specifications and sequential coding-agent prompts.

This is a personal research and decision-support terminal for Kalshi markets across **economics, NBA, culture, and technology**. It estimates event probabilities, compares them with executable prices, explains statistical terms in context, and runs paper-trading experiments. It does **not** automatically authorize live trades or manage a bankroll. Never treat simulated profitability as proof of real-world expected returns.

## How to use this ZIP with Fable / Opus 5.5

1. Unzip into a new project/repository; keep the folder structure intact.
2. Give Fable access to the entire extracted directory, rather than pasting files individually.
3. First ask it to read `AGENTS.md`, `MANIFEST.md`, and the `docs/` directory.
4. Then ask it to execute `prompts/01_BOOTSTRAP.md`. Only after acceptance tests pass, proceed to the next numbered prompt.
5. Stop at prompt 08 for a complete **paper-trading research product**. Prompt 09 is **optional and safety-gated**; it does not authorize real trading.
6. Keep secrets outside Git, and run all components locally. No paid cloud services required for the MVP.

## Technology

Frontend: React + TypeScript + Vite. Backend: Python 3.12+ + FastAPI + Pydantic. Operational data: SQLite + SQLAlchemy + Alembic. Research: pandas, NumPy, SciPy, scikit-learn; DuckDB + Parquet optional. Local scheduled collector with bounded retries. Unit tests: pytest / Vitest. Browser has no exchange credentials.

## Main product surfaces

- **Discover:** filters, watchlists, official market rules, status, quote freshness.
- **Research:** evidence provenance, model probability, uncertainty, executable-side prices, fee-adjusted edge, transparent abstention.
- **Paper:** manually simulated orders, conservative fill assumptions, settled P&L and calibration metrics.
- **Learn:** contextual glossary tooltips, accessible detailed definitions and worked examples, dedicated searchable glossary.
- **Health:** adapter failures, ingestion times, source freshness, model version, audit entries.

## Strong constraints

- NO real exchange order submission in milestones 0–8.
- Paper trading cannot import live-execution code.
- Each eventual live order requires distinct explicit user approval and revalidation.
- No autonomous bankroll allocation, portfolio rebalancing, paywall bypass, or unauthorized scraping.
- Official contract resolution rules outrank titles or model assumptions.
- Pricing and fee conventions must be verified against current Kalshi documentation.
- Never invent fills, prices, data sources, or positive historical performance.

The content here is a **specification and agent prompt pack**, not a completed or tested application. External API details are time-sensitive and must be reverified at implementation.
