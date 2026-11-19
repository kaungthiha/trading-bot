// Mirrors backend/app/api/schemas.py. Prices are exact decimal STRINGS -- never parse them
// into floats for arithmetic; display them as-is.

export type DecimalString = string;

export interface Health {
  status: string;
  version: string;
  env: string;
  trading_mode: string;
  live_execution_enabled: boolean;
  market_data_source: string;
  kalshi_env: string;
  database: string;
  server_time: string;
  credentials_configured: Record<string, boolean>;
}

export type PriceProvenance = "exchange" | "derived_from_complementary_bid";

export interface Quote {
  observed_at: string;
  received_at: string;
  age_seconds: number;
  is_stale: boolean;
  max_age_seconds: number;
  yes_bid: DecimalString | null;
  no_bid: DecimalString | null;
  yes_ask: DecimalString | null;
  no_ask: DecimalString | null;
  yes_ask_provenance: PriceProvenance | null;
  no_ask_provenance: PriceProvenance | null;
  spread_yes: DecimalString | null;
}

// Kalshi market lifecycle (docs.kalshi.com market_lifecycle, checked 2026-11-18).
export const MARKET_STATUSES = [
  "initialized",
  "inactive",
  "active",
  "closed",
  "determined",
  "disputed",
  "amended",
  "finalized",
  "unknown",
] as const;
export type MarketStatus = (typeof MARKET_STATUSES)[number];

export interface MarketSummary {
  id: string;
  exchange: string;
  external_ticker: string;
  event_ticker: string;
  series_ticker: string | null;
  title: string;
  category: string;
  status: MarketStatus;
  status_raw: string | null;
  market_type: string | null;
  open_at: string | null;
  close_at: string | null;
  is_mock: boolean;
  quote: Quote | null;
}

export interface MarketFilters {
  category?: string;
  status?: MarketStatus;
  q?: string;
}

export interface IngestionRun {
  id: string;
  adapter: string;
  started_at: string;
  finished_at: string | null;
  status: "running" | "success" | "partial" | "failed";
  count: number;
  errors: { scope: string; code: string; message: string }[];
}

export interface BookLevel {
  price: DecimalString;
  quantity: DecimalString;
}

export interface MarketDetail extends MarketSummary {
  notional_value: DecimalString;
  price_ranges: { start: DecimalString; end: DecimalString; step: DecimalString }[];
  rules: { text: string; official_source_url: string | null; hash: string; observed_at: string } | null;
  yes_bids: BookLevel[];
  no_bids: BookLevel[];
  updated_at: string;
}

export interface MarketList {
  items: MarketSummary[];
  limit: number;
  offset: number;
}

export interface EvidenceSource {
  id: string;
  title: string;
  series_id: string;
  category: string;
  frequency: string;
  upstream_agency: string;
  source_page_url: string;
  license_notes: string;
  attribution: string | null;
  release_timing_note: string;
  configured: boolean;
  record_count: number;
  latest_vintage: string | null;
  latest_available_at: string | null;
  is_fresh: boolean;
  freshness_max_age_days: number;
  last_run: IngestionRun | null;
}

export interface EvidenceObservation {
  observation_date: string;
  vintage_date: string;
  value: DecimalString | null;
  quality: "ok" | "missing";
  available_at: string;
  retrieved_at: string;
  units: string | null;
  source_url: string;
}

export interface EvidenceAsOf {
  source_id: string;
  as_of: string;
  items: EvidenceObservation[];
}

export interface CollectionGap {
  id: string;
  job: string;
  gap_start: string;
  gap_end: string;
  detected_at: string;
  backfillable: boolean;
  reason: string;
}

export interface ModelCard {
  name: string;
  version: string;
  summary: string;
  contract_type: string;
  features: string;
  uncertainty_method: string;
  hyperparameters: Record<string, unknown>;
  limitations: string[];
}

export interface CalibrationBin {
  lower: number;
  upper: number;
  count: number;
  mean_p: number | null;
  observed_rate: number | null;
}

export interface MetricSummary {
  n_predictions: number;
  n_events: number;
  n_abstained: number;
  base_rate: number | null;
  brier: number | null;
  log_loss: number | null;
  log_loss_eps: number;
  calibration: CalibrationBin[];
}

export interface ModelEvaluation {
  id: string;
  created_at: string;
  model: string;
  version: string;
  feature_version: string;
  dataset_hash: string;
  config: {
    thresholds: string[];
    holdout_start: string;
    dev_range: [string, string] | null;
    holdout_range: [string, string] | null;
  } & Record<string, unknown>;
  dev: MetricSummary;
  holdout: MetricSummary;
  data_notes: { first_prints_used: number; excluded: Record<string, number> };
}

export interface ModelForecast {
  model: string;
  version: string;
  decision: "FORECAST" | "ABSTAIN";
  p_yes: number | null;
  lower: number | null;
  upper: number | null;
  uncertainty_method: string;
  reasons: string[];
  inputs: Record<string, unknown>;
}

export interface CpiForecast {
  contract_key: string | null;
  reference_month: string | null;
  threshold: DecimalString;
  as_of: string;
  forecasts: ModelForecast[];
  recent_prints: { month: string; mom_rounded: DecimalString; released_at: string }[];
  caveat: string;
}

export interface SignalSide {
  side: string;
  entry: DecimalString | null;
  fee: DecimalString | null;
  slippage: DecimalString | null;
  ev: DecimalString | null;
  lower_edge: DecimalString | null;
  lower_edge_stressed: DecimalString | null;
  filled: DecimalString | null;
  reasons: string[];
}

export interface Signal {
  id: string;
  created_at: string;
  expires_at: string;
  validity: "VALID" | "EXPIRED" | "INVALIDATED_RULES_CHANGED";
  market_id: string;
  market_ticker: string;
  market_title: string;
  rules_source_url: string | null;
  decision: "CANDIDATE_YES" | "CANDIDATE_NO" | "ABSTAIN";
  side: string | null;
  quantity: DecimalString | null;
  p_yes: number | null;
  p_lower: number | null;
  p_upper: number | null;
  entry: DecimalString | null;
  fee: DecimalString | null;
  slippage: DecimalString | null;
  ev: DecimalString | null;
  lower_edge: DecimalString | null;
  reasons: string[];
  caveats: string[];
  quote_id: string | null;
  quote_observed_at: string | null;
  model_run_id: string | null;
  model: string | null;
  contract_key: string | null;
  mapping_id: string | null;
  mapping_status: string | null;
  fee_schedule_version: string | null;
  details: {
    yes?: SignalSide;
    no?: SignalSide;
    spread_yes?: DecimalString | null;
    model_market_divergence?: DecimalString | null;
  } & Record<string, unknown>;
}

export interface FeeScheduleInfo {
  version: string;
  verified: boolean;
  verified_by: string | null;
  verified_at: string | null;
  source_url: string;
}

export interface PaperFill {
  quantity: DecimalString;
  price: DecimalString;
  displayed_price: DecimalString;
  fee: DecimalString;
  filled_at: string;
  assumption_code: string;
}

export interface PaperOrder {
  id: string;
  client_order_id: string;
  submitted_at: string;
  market_id: string;
  market_ticker: string;
  side: "YES" | "NO";
  action: "BUY" | "SELL";
  quantity: DecimalString;
  limit_price: DecimalString;
  status: "FILLED" | "PARTIAL" | "CANCELLED" | "REJECTED";
  filled_quantity: DecimalString;
  reject_reason: string | null;
  scenario: string;
  simulation_version: string;
  fee_schedule_version: string | null;
  fee_schedule_verified: boolean;
  quote_id: string | null;
  signal_id: string | null;
  source: string;
  fills: PaperFill[];
  duplicate: boolean;
}

export interface PaperPosition {
  market_id: string;
  market_ticker: string;
  side: string;
  open_qty: DecimalString;
  avg_cost: DecimalString;
  realized: DecimalString;
  unrealized: DecimalString;
  mark_value: DecimalString;
  mark_note: string | null;
  settled: boolean;
  held: boolean;
}

export interface PaperAccount {
  as_of: string;
  cash: DecimalString;
  deposits: DecimalString;
  open_value: DecimalString;
  equity: DecimalString;
  realized: DecimalString;
  unrealized: DecimalString;
  fee_schedule_verified: boolean;
  notes: string[];
  positions: PaperPosition[];
}

export interface PaperSettlement {
  id: string;
  created_at: string;
  market_ticker: string;
  exchange_status: string;
  exchange_result: string;
  evidence_check: string;
  status: "SETTLED" | "HELD";
  notes: string[];
}

export interface ReplayTrade {
  signal_id: string;
  market_ticker: string;
  side: string;
  requested: DecimalString;
  filled: DecimalString;
  avg_price: DecimalString | null;
  cost: DecimalString;
  status: string;
  outcome: string | null;
  payout: DecimalString;
  p_side: number | null;
  note: string | null;
}

export interface ReplayReport {
  as_of: string;
  scenario: string;
  n_signals: number;
  n_resolved: number;
  total_cost: DecimalString;
  realized_pnl: DecimalString;
  unresolved_cost: DecimalString;
  resolved_brier: number | null;
  trades: ReplayTrade[];
  caveat: string;
}

export interface PaperOrderInput {
  market_id: string;
  side: "YES" | "NO";
  action: "BUY" | "SELL";
  quantity: number;
  limit_price: string;
  scenario?: string;
}

export interface SetupStatus {
  steps: { key: string; title: string; status: "ok" | "todo" | "warn"; hint: string }[];
  complete: boolean;
  paper_mode: boolean;
}

export interface Diagnostics {
  app_version: string;
  schema_revision: string | null;
  database_bytes: number | null;
  server_time: string;
  safety: { trading_mode: string; live_execution_enabled: boolean };
  config: Record<string, unknown>;
  ingestion: {
    adapter: string;
    last_status: string | null;
    last_started_at: string | null;
    last_success_at: string | null;
    recent_runs: number;
    recent_failures: number;
    top_error_codes: [string, number][];
  }[];
  collection_gaps: number;
  quotes: { markets_with_quotes: number; stale: number; fresh: number };
  evidence: { source_id: string; records: number; latest_vintage: string | null; fresh: boolean; configured: boolean }[];
  signals_24h: { count: number; by_decision: Record<string, number>; top_reasons: [string, number][] };
  paper_rejections: [string, number][];
}

export interface SignalLineage {
  signal: { id: string; decision: string; reasons: string[] };
  market: { ticker: string };
  quote: {
    id: string;
    observed_at: string;
    yes_bid: string | null;
    yes_ask_derived: string | null;
    ingestion_run: { id: string; adapter: string; status: string } | null;
  } | null;
  rules: { hash: string; is_current: boolean } | null;
  mapping: { status: string; actor: string; reference_month: string | null; threshold: string | null } | null;
  model_run: { model: string; version: string; as_of: string; p_yes: number | null } | null;
  evidence: { id: string; observation_date: string; vintage_date: string; available_at: string }[];
  leakage_check: string;
  fee_schedule: { version: string; verified: boolean } | null;
}

export interface ExecutionStatus {
  execution_enabled: boolean;
  env: "mock" | "demo";
  production: string;
  kill_switch_engaged: boolean;
  pin_configured: boolean;
  demo_credentials_configured: boolean;
  caps: Record<string, string | number>;
}

export interface ExecutionIntent {
  id: string;
  created_at: string;
  expires_at: string;
  env: string;
  market_ticker: string;
  side: "YES" | "NO";
  quantity: DecimalString;
  limit_price: DecimalString;
  approved_ask: DecimalString;
  est_fee: DecimalString;
  max_cost: DecimalString;
  fee_schedule_version: string;
  status: string;
  block_reason: string | null;
  summary: string;
  payload: Record<string, unknown>;
  payload_hash: string;
  exchange_order: {
    exchange_order_id: string | null;
    source: string;
    fill_count: string;
    average_fill_price: string | null;
    average_fee_paid: string | null;
  } | null;
  events: { at: string; kind: string; detail: Record<string, unknown> }[];
}

export interface ApiErrorBody {
  error: { code: string; message: string };
}
