# Package Manifest

This pack contains **24 Markdown files**: 3 root files, 12 specification/reference files in `docs/`, and 9 agent prompts in `prompts/`.

## Directory

```text
README.md
AGENTS.md
MANIFEST.md
docs/
  ARCHITECTURE.md
  DATA_CONTRACTS.md
  SIGNAL_ENGINE.md
  EXECUTION_SAFETY.md
  BUILD_PLAN.md
  UX_EDUCATION.md
  GLOSSARY.md
  KALSHI_API_NOTES.md
  DATA_SOURCES.md
  TESTING.md
  SOURCES.md
prompts/
  01_BOOTSTRAP.md
  02_KALSHI_READ_ONLY.md
  03_EVIDENCE_PIPELINE.md
  04_PROBABILITY_MODELS.md
  05_SIGNAL_ENGINE.md
  06_PAPER_TRADING.md
  07_EDUCATIONAL_UX.md
  08_VALIDATION_HARDENING.md
  09_OPTIONAL_LIVE_EXECUTION.md
```

**Actual count:** 24 Markdown files (3 root + 12 docs + 9 prompts). The directory tree is authoritative.

**Prompt order:** 01 → 02 → 03 → 04 → 05 → 06 → 07 → 08. Prompt 09 only by an explicit, separate decision.

All specifications are requirements, not proof of implementation or verified integration. Review `docs/KALSHI_API_NOTES.md` before using live API fields. This pack is compatible with a local-first implementation; Supabase and GitHub Pages are not dependencies.
