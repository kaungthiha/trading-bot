# Implementation Sequence

Run numbered prompts in `prompts/` one at a time. Do not skip acceptance gates. Each prompt needs tested code, documentation and a completion report.

| Stage | Goal | Done when |
|---|---|---|
| 01 | Local repo/bootstrap | React, FastAPI, SQLite, tests and mock UI run with no credentials |
| 02 | Kalshi read-only | Public market metadata, rules, bids, derived asks and persistence work; errors tested |
| 03 | Evidence pipeline | One official source adapter, provenance, freshness, retries and dedupe |
| 04 | Probability baselines | As-of features, deterministic estimates, validation reports and abstention |
| 05 | Signals | Fee-aware expected value, risk/quality gates, explainable stored signals |
| 06 | Paper trading | Simulated orders/fills with conservative assumptions, immutable accounting |
| 07 | Educational UX | Central glossary, accessible terms, searchable glossary and content tests |
| 08 | Hardening | End-to-end trace, regression/security checks, usability and reproducibility |
| 09 | OPTIONAL | Approval-gated demo/live gateway design; still disabled unless separately approved |

**Prioritized vertical:** economics first for a clearly specified contract and official historical series. Then NBA with a reliable licensed source; culture and technology after proven evidence adapters. No model uses LLM sentiment alone as a high-confidence probability.

**Definition of done:** documented startup commands; actual tests run; frozen-clock fixtures; all new API assumptions cited; DB migration clean; no real orders; readable diagnostics and educational tooltips for technical terms.
