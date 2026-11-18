# Architecture

```text
Browser (React/Vite)
   | HTTP localhost; no credentials
FastAPI: market / evidence / research / paper / glossary routes
   |                 |                    |
SQLite             models              local collection worker
   |                 |                    |
Alembic             signals             Kalshi read-only + official external sources

OPTIONAL FUTURE: a separately permissioned, approval-gated live execution gateway.
```

## Modules
- `backend/app/api`: versioned Pydantic request/response routes.
- `backend/app/core`: configuration, clock, secrets, structured logging, errors.
- `backend/app/db`: SQLAlchemy models, repositories, Alembic migrations.
- `backend/app/adapters`: exchange market metadata, orderbook, evidence source adapters.
- `backend/app/research`: feature construction, model registry, forecast validation.
- `backend/app/signals`: conservatively calculated market edge and abstention.
- `backend/app/paper`: simulated orders, fills, positions, reconciliation.
- `backend/app/audit`: append-only events.
- `frontend/src/components`: market explorer, cards, tables, charts, `Term` and Glossary.
- `frontend/src/glossary`: typed registry, helpers and test fixtures.
- `worker`: explicitly bounded scheduled polling; sleep/suspend recovery and replay-safe deduplication.

## Local execution
Bind server to `127.0.0.1` and set exact allowed CORS origins. Keep all API/private keys in OS-protected local environment or keychain. Provide `.env.example`, never commit `.env`; do not expose database files. SQLite WAL where suitable, serialized writes, migrations from day one. Worker retries bounded with backoff; no busy-loop polling. If laptop sleeps, do not pretend intervals were collected; backfill only available historical data and mark gaps explicitly.

## Dataflow
Discover → normalize event/contract rules → ingest quote/evidence with provenance → validate as-of cutoff → estimate p(YES) → calculate cost-adjusted edge and abstention gates → store immutable signal → explain in dashboard → optional paper simulation. Actual trading requires separate architecture and authorization.

## Constraints
Rate-limit-aware adapters; source license and provenance; idempotency; measured stale-data age; stable IDs; auditability; model versioning; deterministic tests using frozen clocks. No hosted database/cloud requirements for MVP. Do not make undocumented API assumptions.
