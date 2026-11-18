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

export interface MarketSummary {
  id: string;
  exchange: string;
  external_ticker: string;
  event_ticker: string;
  title: string;
  category: string;
  status: string;
  close_at: string | null;
  is_mock: boolean;
  quote: Quote | null;
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

export interface ApiErrorBody {
  error: { code: string; message: string };
}
