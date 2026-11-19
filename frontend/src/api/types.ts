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
  market_event_ticker?: string | null;
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

export interface OpportunityLeg {
  ticker: string;
  title: string;
  side: "YES" | "NO";
  limit_price: DecimalString;
  quantity: DecimalString;
  cost: DecimalString;
  fee: DecimalString;
  available: DecimalString;
}

export interface OpportunityCard {
  id: string;
  detected_at: string;
  expires_at: string;
  status: "OPEN" | "EXPIRED" | "EXECUTED" | "SKIPPED";
  kind: "LADDER" | "EXCL_NO" | "EXCL_YES";
  guaranteed: boolean;
  confirmed: boolean;
  event_ticker: string;
  title: string;
  legs: OpportunityLeg[];
  quantity: DecimalString;
  cost: DecimalString;
  fees: DecimalString;
  min_payoff: DecimalString;
  profit: DecimalString;
  return_pct: DecimalString;
  claim: string;
  checklist: string[];
  budget_cap: DecimalString | null;
  fee_schedule_version: string;
  journal: { at: string; action: string; note: string; cost: string | null; payoff: string | null }[];
}

export interface ScannerStatus {
  interval_seconds: number;
  last_scan: {
    at: string; events: number; markets: number; candidates: number; confirmed: number;
    new_cards: number;
    coverage?: { categories: CoverageRow[]; top_series: CoverageRow[] };
    near_misses?: NearMiss[];
  } | null;
  budget: DecimalString | null;
  available: DecimalString | null;
  caps: { guaranteed: DecimalString; conditional: DecimalString };
  paused: boolean;
  note: string | null;
}

export interface ScorecardTotals { executed: number; settled: number; pnl: DecimalString; wins: number }

export interface Scorecard {
  budget: DecimalString | null;
  available: DecimalString | null;
  open_cost: DecimalString;
  realized_pnl: DecimalString;
  paused: boolean;
  note: string | null;
  all: ScorecardTotals;
  guaranteed: ScorecardTotals;
  conditional: ScorecardTotals;
  skipped: number;
}

export interface CoverageRow { name: string; events: number; markets: number }

export interface NearMiss {
  kind: string;
  event_ticker: string;
  title: string;
  category: string;
  raw_cost_per_set: DecimalString;
  payoff_per_set: DecimalString;
  gap: DecimalString;
  detail: string;
}

export type JobName = "refresh" | "evidence" | "scan" | "history" | "combos";

export interface JobState {
  name: JobName;
  running: boolean;
  last_started: string | null;
  last_finished: string | null;
  last_status: "success" | "partial" | "failed" | null;
  last_message: string | null;
}

export interface JobsSnapshot {
  jobs: Record<JobName, JobState>;
  auto_scan: { enabled: boolean; interval_seconds: number; next_run_at: string | null };
  worker_running: boolean;
  watchlist: string[];
}

export interface ApiErrorBody {
  error: { code: string; message: string };
}

// --- Market catalog (Markets page) ---------------------------------------------------------

export interface CatalogStatus { refreshed_at: string | null; events: number; markets: number; series: number }
export interface CatalogCategory { name: string; events: number; markets: number; volume_24h: number }
export interface CatalogSeries { ticker: string; title: string; events: number; markets: number; volume_24h: number }

export interface CatalogEvent {
  event_ticker: string;
  series_ticker: string;
  category: string;
  title: string;
  sub_title: string;
  competition: string | null;
  mutually_exclusive: boolean;
  market_count: number;
  volume_24h: number;
  open_interest: number;
  close_at: string | null;
  occurs_at: string | null;
  refreshed_at: string;
}

export interface CatalogEventList { items: CatalogEvent[]; total: number; limit: number; offset: number }
export type CatalogSort = "volume_24h" | "open_interest" | "volume" | "closing";

export interface CatalogMarket {
  ticker: string;
  title: string;
  yes_sub_title: string;
  no_sub_title: string;
  status: string;
  yes_bid: DecimalString | null;
  yes_ask: DecimalString | null;
  no_bid: DecimalString | null;
  no_ask: DecimalString | null;
  yes_bid_size: DecimalString | null;
  yes_ask_size: DecimalString | null;
  last_price: DecimalString | null;
  change_24h: DecimalString | null;
  volume_24h: DecimalString | null;
  open_interest: DecimalString | null;
  implied: number | null;
  implied_quality: "mid" | "tail" | "none";
  spread: number | null;
  floor_strike: DecimalString | null;
  strike_type: string | null;
  close_at: string | null;
}

export interface LadderBucket { label: string; lo: number | null; hi: number | null; p: number }
export interface LadderPoint {
  ticker: string; strike: number; label: string; implied: number; fitted: number;
  residual: number; quality: string; spread: number | null; off_curve: boolean;
}
export interface LadderStats {
  label: string; strikes: number;
  median: number | null; p10: number | null; p25: number | null; p75: number | null; p90: number | null;
  mean: number; sd: number; tail_mass: number; mean_reliable: boolean;
  monotonicity_violations: number; buckets: LadderBucket[]; points: LadderPoint[];
}
export interface ExclusiveStats {
  outcomes: number; priced: number; sum_yes_ask: DecimalString | null; sum_yes_bid: DecimalString;
  sum_implied: number; overround: number | null; normalized: Record<string, number>;
}

export interface CatalogEventDetail extends CatalogEvent {
  series_title: string;
  combo_collections: string[];
  game?: { prefix: string; game_key: string } | null;
  rules_sample: string;
  fee: { schedule: string | null; multiplier: string; fee_type: string | null };
  markets: CatalogMarket[];
  stats: { exclusive: ExclusiveStats | null; ladders: LadderStats[] };
}

export type Side = "yes" | "no";

export interface ExpectedValue {
  ticker: string; side: Side; price: DecimalString; price_source: string; snapshot_at: string;
  contracts: number; probability: DecimalString; notional: DecimalString; fee: DecimalString;
  total_cost: DecimalString; max_payout: DecimalString; expected_payout: DecimalString;
  expected_value: DecimalString; ev_per_dollar: DecimalString | null;
  breakeven_probability: DecimalString; kelly_fraction: DecimalString;
  depth_at_price: DecimalString | null; depth_warning: boolean; fee_schedule_version: string;
  budget?: DecimalString; quarter_kelly_stake?: DecimalString; cap_stake?: DecimalString;
  suggested_contracts?: number;
}

export interface ComboLeg { ticker: string; side: Side; label: string; event: string }
export interface ComboResult {
  legs: { ticker: string; label: string; side: Side; event: string; probability: number | null; quality: string }[];
  independent_probability: number | null; fair_price: number | null; fair_multiple: number | null;
  warnings: string[];
  kalshi?: { eligible: boolean; collections: string[]; ineligible_events: string[];
             history: (ComboStudyBucket & { bucket: string }) | null };
}

export interface ComboStudyBucket {
  n: number; avg_price: number; hit_rate: number; edge: number; se: number; return_per_dollar: number | null;
}
export interface ComboStudy {
  overall: ComboStudyBucket | null;
  by_legs: (ComboStudyBucket & { bucket: string })[];
  by_price: (ComboStudyBucket & { bucket: string })[];
  markets_scanned: number;
  generated_at: string;
}

export interface BookSnapshot {
  market: Record<string, string | null>;
  yes_bids: { price: DecimalString; quantity: DecimalString }[];
  no_bids: { price: DecimalString; quantity: DecimalString }[];
}

// --- My trades (account history) ----------------------------------------------------------

export interface HistoryStatus { configured: boolean; kalshi_env: string }
export interface WinStat { n: number; won: number; win_rate: number; avg_price: number; edge: number; se: number | null; small_sample: boolean }
export interface HistoryMark { side: Side; contracts: string; mid: string | null; value: DecimalString | null; cost: DecimalString; unrealized: DecimalString | null }
export interface HistoryMarket {
  ticker: string; series: string; series_title: string; category: string; type: string;
  fills: number; staked: DecimalString; fees: DecimalString; sides: Side[]; result: string | null;
  status: "settled" | "closed" | "open"; pnl: DecimalString | null; kalshi_realized: DecimalString | null;
  position: string | null; mark: HistoryMark | null; first_trade_at: string | null;
}
export interface HistoryGroup { name: string; series: string; markets: number; staked: DecimalString; pnl: DecimalString; roi: number | null }
export interface HistoryReport {
  last_sync: { at: string; status: string; message: string } | null;
  summary: {
    balance: DecimalString | null; portfolio_value: DecimalString | null; realized_pnl: DecimalString;
    unrealized_pnl: DecimalString; fees: DecimalString; staked_closed: DecimalString; roi: number | null;
    settled_markets: number; open_markets: number; win_rate: WinStat | null; budget: DecimalString | null;
  };
  reconciliation: { checked: number; net: number; gross: number };
  timeline: { date: string; pnl: DecimalString; cumulative: DecimalString; markets: number; wins: number;
              by_type: Record<string, DecimalString> }[];
  behavior: {
    fills: number; markets: number; active_days: number; avg_entry_price: DecimalString | null;
    longshot_share: number | null; favorite_share: number | null; taker_share: number | null;
    fee_share_of_notional: number | null; median_stake: number | null; max_stake: number | null;
    max_stake_share_of_budget: number | null; combo_markets: number;
    median_hours_before_settlement: Record<string, number>;
  };
  calibration: (WinStat & { range: string })[];
  by_type: HistoryGroup[];
  by_series: HistoryGroup[];
  open_positions: HistoryMarket[];
  markets: HistoryMarket[];
  insights: { level: "good" | "warn" | "info"; text: string }[];
  suggestions: { kind: string; title: string; why: string; events: { event_ticker: string; title: string; sub_title: string }[] }[];
  entry_quality?: EntryQuality;
  combo_breakdown?: ComboBreakdown | null;
  playbook?: PlaybookRule[];
}
export interface EntryQuality {
  clv: { n: number; avg_pts: number | null; beat_share: number | null };
  early_exits: { n: number; in_profit: number };
  held_to_settlement: { n: number; lost: number };
}
export interface ComboBreakdown {
  combos: number; with_legs: number; avg_legs?: number;
  by_size?: { legs: string; n: number; won: number }[];
  lost?: number; lost_by_one?: number; breakers?: { type: string; legs: number }[];
}
export interface PlaybookRule { rule: string; why: string; confidence: "standard" | "medium" | "low" }
export interface ComboLegState { ticker: string; title: string; side: Side; type: string;
  status: "won" | "lost" | "open"; probability: number | null }
export interface OpenPosition {
  ticker: string; title: string; event_ticker: string | null; event_title: string | null; type: string;
  side: Side; contracts: string; avg_cost: string | null; cost: string; mid: string | null;
  value: string | null; unrealized: string | null; move_pts: number | null; max_payout: string;
  close_at: string | null; hours_to_close: number | null;
  game: { prefix: string; game_key: string } | null;
  evidence: LegEvidence | null; evidence_note: string | null;
  trail: { at: string; mid: number | null }[];
  combo: { legs: ComboLegState[]; fair: number | null; won: number; lost: number; open: number } | null;
  flags: { level: "good" | "warn" | "info"; text: string }[];
}
export interface OpenAnalysis {
  positions: OpenPosition[];
  portfolio: { count: number; cost: string; value: string; unrealized: string; max_payout: string;
    budget_share: number | null; games: { game_key: string; title: string | null; tickers: string[]; cost: string; share: number | null }[] };
  correlation: LegCorrelation[]; evidence_enabled: boolean; evidence_error: string | null; as_of: string;
}
export interface HistoryFill {
  fill_id: string; ticker: string; side: Side; action: "buy" | "sell"; count: string; price: DecimalString;
  fee: DecimalString; is_taker: boolean; created_at: string; type: string;
}

// --- Games page (one game per screen + evidence for combo legs) ---------------------------

export interface GameTeam { code: string; name: string; win: number | null }
export interface GameSummary {
  game_key: string; league: string; prefix: string; title: string; sub_title: string;
  occurs_at: string | null; close_at: string | null; teams: GameTeam[];
  events: number; markets: number; volume_24h: number;
}
export interface GameList { items: GameSummary[]; leagues: { league: string; games: number }[] }
export interface GameChip {
  ticker: string; event_ticker: string; label: string; title: string; team: string | null;
  implied: number | null; quality: string; yes_bid: number | null; yes_ask: number | null;
  no_ask: number | null; spread: number | null; volume_24h: number; strike: number | null;
}
export interface GameGroup {
  id: string; label: string; kind: "pick" | "ladder"; event_ticker: string; eligible: boolean;
  series_title: string; median_label: string | null; markets: GameChip[];
}
export interface PlayerStatGroup {
  event_ticker: string; eligible: boolean; series_title: string; label: string;
  median: number | null; markets: GameChip[];
}
export interface GamePlayer { id: string; name: string; team: string | null; volume_24h: number;
  stats: Record<string, PlayerStatGroup> }
export interface GameDetail {
  game_key: string; prefix: string; league: string; title: string; sub_title: string;
  occurs_at: string | null; close_at: string | null; refreshed_at: string | null; teams: GameTeam[];
  sections: { id: string; label: string; groups: GameGroup[] }[];
  players: GamePlayer[]; stats: string[]; stat_labels: Record<string, string>;
  protected_available: boolean; protected: boolean; evidence_supported: boolean;
}
export type Verdict = "agrees" | "market_higher" | "market_lower" | "thin" | "no_price";
export interface LegEvidence {
  ticker: string; side: Side; label: string; supported: boolean; reason?: string;
  subject?: { type: "player" | "team"; name: string; team: string | null; espn_url: string | null };
  kind?: string; line?: number | null; stat?: string | null;
  injury?: { player: string; status: string; detail: string; date: string } | null;
  windows?: { last5: [number, number]; last10: [number, number]; season: [number, number];
              last_season: [number, number] };
  estimate?: number; interval?: [number, number]; market?: number | null; verdict?: Verdict;
  season_avg?: number | null;
  recent?: { date: string; opponent: string; home: boolean; value: number | null; hit: boolean | null }[];
}
export interface LegCorrelation {
  game_key: string; team: string; legs: string[]; games: number; together: number;
  expected: number | null; lift: number | null;
}
export interface EvidenceResult {
  legs: LegEvidence[]; correlation: LegCorrelation[];
  independent_probability: number | null; adjusted_probability: number | null;
}
export interface GameInjuries {
  supported: boolean;
  teams: { code: string; name: string; items: { player: string; status: string; detail: string; date: string }[] }[];
}
export interface NewsResult {
  configured: boolean;
  items: { title: string; url: string; source: string; age: string; description: string }[];
}

export interface LlmStatus {
  configured: boolean; provider: string; model: string; local: boolean; reachable: boolean | null;
  installed?: string[];
}
export interface ReviewStatus extends LlmStatus { used_today: number; daily_cap: number | null; headlines: boolean }
export interface CoachResult {
  summary: string; strengths: string[]; leaks: string[]; rules_for_next_50: string[];
  open_positions: { ticker: string; note: string }[]; questions: string[];
  model: string; seconds?: number; generated_at: string; cached: boolean;
}
export interface Headline { id: string; title: string; source: string; age: string; url: string }
export interface OpenReview {
  summary: string;
  positions: { ticker: string; stance: "on_track" | "watch" | "reconsider"; read: string; plan: string; sources: string[] }[];
  portfolio: string[]; check: string[]; sources: Headline[];
  model: string; seconds?: number; generated_at: string; cached: boolean;
}

export interface IdeaLimit { price: string; saves_per_100: string | null; maker_fee_per_100: string | null; behind_bid: boolean }
export interface IdeaSingle {
  id: string; ticker: string; side: Side; bet: string; ask: string | null; bid: string | null;
  all_in?: string; history: string | null; mid: string | null; edge_pts?: number; interval: [number, number];
  limit?: IdeaLimit; strength: "strong" | "lean"; event_ticker: string; eligible: boolean;
  subject: string | null; windows: Record<"last5" | "last10" | "season" | "last_season", [number, number]> | null;
  season_avg: number | null; line: number | null; injury: { status: string; detail: string } | null;
  contracts_at_cap: number; caution: string | null; kind: string | null; family: string;
}
export interface IdeaCombo {
  id: string; legs: string[]; tickers: string[]; bets: string[]; sides: Side[];
  fair: number; history: number; lift: number | null; walk_away: string | null; ratio: number | null;
  past: (ComboStudyBucket & { bucket: string }) | null;
}
export interface IdeaEntry {
  ticker: string; side: Side; bet: string; ask: string; bid: string; limit: string;
  saves_per_100: string | null; maker_fee_per_100: string | null; mid: string;
}
export interface GameIdeas {
  game: { prefix: string; game_key: string; title: string; occurs_at: string | null };
  singles: IdeaSingle[]; combos: IdeaCombo[]; entries: IdeaEntry[];
  screened: number; skipped: { thin: number; injured: number; no_history: number; priced_right: number };
  evidence_enabled: boolean; evidence_error: string | null;
  cap: string; open_cost: string; budget: string | null; fees_verified: boolean; generated_at: string;
}
export interface IdeasAi {
  summary: string;
  picks: { id: string; how: "limit" | "take_ask" | "quote_at_or_below"; stake: number; why: string[]; risks: string[]; sources: string[] }[];
  skip: { id: string; why: string }[]; sources: Headline[];
  model: string | null; seconds?: number; generated_at: string; cached: boolean;
}

export interface ReviewResult {
  summary: string; overall: "reasonable" | "stretch" | "avoid";
  legs: { ticker: string; lean: "supports" | "against" | "unclear"; points: string[]; sources: string[] }[];
  risks: string[]; check_before_betting: string[];
  sources: { id: string; title: string; source: string; age: string; url: string }[];
  model: string; generated_at: string; cached: boolean; seconds?: number;
}

export interface SlipCheck {
  verdict: "reasonable" | "stretch" | "avoid" | "single";
  reasons: { level: "good" | "warn" | "info"; text: string }[];
  combo: { legs: number; fair: number | null; estimate: number | null; walk_away: string | null;
           history: (ComboStudyBucket & { bucket: string }) | null };
  sizing: { cap: string | null; budget: string | null; open_cost: string | null; cash: string | null;
            stake: string | null; kelly_quarter?: string | null; contracts?: string; cost?: string;
            pays?: string; expected?: string };
  singles: { ticker: string; side: Side; label: string; ask: string | null; bid: string | null;
             history: string | null; mid: string | null; all_in?: string; edge_pts?: number; value?: boolean;
             limit?: { price: string; saves_per_100: string | null; maker_fee_per_100: string | null; behind_bid: boolean } }[];
  trim: { drop: string; label: string; fair_after: number; legs_after: number;
          history_after: (ComboStudyBucket & { bucket: string }) | null } | null;
  fees_verified: boolean; evidence_used: boolean;
}
