# Data Contracts and Initial Schema

Store timestamps as UTC ISO 8601 or timezone-aware SQL types; **prices/fees as exact decimal strings** and monetary operations with `Decimal`. Probabilities must be finite and within [0, 1]. Nullable fields are not zero.

## Tables
| Table | Primary columns |
|---|---|
| `markets` | id UUID, exchange, external_ticker UNIQUE, event_ticker, title, category, status, close_at, updated_at |
| `market_rule_versions` | id, market_id, rules_text, official_source_url, hash, observed_at, is_current |
| `quote_snapshots` | id, market_id, observed_at, received_at, yes_bid, no_bid, yes_ask_derived, no_ask_derived, depth_json, raw_ref |
| `evidence_records` | id, source, source_url, published_at, retrieved_at, available_at, revision/vintage, normalized_json, hash, license_notes, quality |
| `model_runs` | id, market_id, model, version, feature_version, as_of, p_yes, lower, upper, uncertainty_method, evidence_ids_json, metrics_json |
| `signals` | id, market_id, quote_id, model_run_id, created_at, expires_at, side, decision, entry, fee, slippage, ev, lower_edge, reasons_json |
| `paper_orders` | id, market_id, side, action, quantity, limit_price, submitted_at, status, simulation_version |
| `paper_fills` | id, paper_order_id, quantity, price, fee, filled_at, assumption_code |
| `ingestion_runs` | id, adapter, start, end, status, count, errors_json |
| `audit_events` | id, at, actor, action, object_type, object_id, metadata_json |

Later: `live_order_intents`, `approval_events`, `exchange_orders`, `exchange_fills` with unique client order IDs and immutable audit trail. Never reuse paper orders as authorizations.

## Invariants
- Immutable evidence, price, model and signal snapshots; models record exact cutoff and version.
- Rule text changes invalidate dependent signals until revalidation.
- Orderbook **asks may be derived** from complementary bids; distinguish from raw exchange fields, never fabricate absent counterparties.
- Quote observation time ≠ receipt time; historical quote ≠ executable offer.
- Market `close_at`, estimated event time, official resolution time, settlement time are distinct.
- Price grid and contract quantity precision are configurable per market; no blanket 1¢ assumption.
- Encode provenance of evidence and all derived prices.
- Historical data eligibility: evidence `available_at` <= model evaluation cutoff.

## API MVP
`GET /api/health`, `GET /api/markets`, `GET /api/markets/{id}`, `GET /api/markets/{id}/quotes`, `GET /api/markets/{id}/evidence`, `POST /api/research/evaluate`, `GET /api/markets/{id}/signals`, `GET /api/paper/orders`, `POST /api/paper/orders`, `GET /api/glossary`, `GET /api/models/metrics`.

Validate pagination, request payload, timestamps and all database foreign keys. Add explicit API response error codes for stale quote, invalid rules, missing evidence, invalid price grid, insufficient book depth and source failure.
