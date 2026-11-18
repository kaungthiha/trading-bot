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

export interface ApiErrorBody {
  error: { code: string; message: string };
}
