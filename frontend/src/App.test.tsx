import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import App from "./App";
import type { Health, MarketDetail, MarketList } from "./api/types";

const quote = {
  observed_at: "2026-11-18T15:00:00+00:00",
  received_at: "2026-11-18T15:00:30+00:00",
  age_seconds: 30,
  is_stale: false,
  max_age_seconds: 60,
  yes_bid: "0.43",
  no_bid: "0.55",
  yes_ask: "0.45",
  no_ask: "0.57",
  yes_ask_provenance: "derived_from_complementary_bid" as const,
  no_ask_provenance: "derived_from_complementary_bid" as const,
  spread_yes: "0.02",
};

const summary = {
  id: "m1",
  exchange: "kalshi",
  external_ticker: "MOCK-CPIYOY-26DEC-T3.0",
  event_ticker: "MOCK-CPIYOY-26DEC",
  title: "[MOCK] CPI above 3.0%?",
  category: "economics",
  status: "open",
  close_at: "2026-12-10T13:25:00+00:00",
  is_mock: true,
  quote,
};

const stale = {
  ...summary,
  id: "m2",
  external_ticker: "MOCK-TECHREL-26DEC-SHIP",
  title: "[MOCK] Vendor ships v9?",
  quote: { ...quote, is_stale: true, age_seconds: 10830, yes_ask: null, yes_ask_provenance: null },
};

const health: Health = {
  status: "ok",
  version: "0.1.0",
  env: "local",
  trading_mode: "paper",
  live_execution_enabled: false,
  market_data_source: "fixture",
  database: "ok",
  server_time: "2026-11-18T15:00:30+00:00",
  credentials_configured: { kalshi: false },
};

const detail: MarketDetail = {
  ...summary,
  notional_value: "1.00",
  price_ranges: [{ start: "0.01", end: "0.99", step: "0.01" }],
  rules: {
    text: "SYNTHETIC RULES FOR TESTING.",
    official_source_url: "https://www.bls.gov/cpi/",
    hash: "a".repeat(64),
    observed_at: "2026-11-18T15:00:30+00:00",
  },
  yes_bids: [{ price: "0.43", quantity: "120" }],
  no_bids: [],
  updated_at: "2026-11-18T15:00:30+00:00",
};

function mockFetch() {
  const routes: Record<string, unknown> = {
    "/api/health": health,
    "/api/markets": { items: [summary, stale], limit: 50, offset: 0 } satisfies MarketList,
    "/api/markets/m1": detail,
  };
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    expect(init?.credentials).toBe("omit");
    const body = routes[String(input)];
    return body
      ? new Response(JSON.stringify(body), { status: 200 })
      : new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: "nope" } }), { status: 404 });
  });
}

describe("<App>", () => {
  beforeEach(() => vi.stubGlobal("fetch", mockFetch()));
  afterEach(() => vi.unstubAllGlobals());

  it("renders paper-mode banner and mock market list with stale indicator", async () => {
    render(<App />);
    expect(await screen.findByText("PAPER MODE")).toBeInTheDocument();
    expect(screen.getByText(/Live execution: disabled/)).toBeInTheDocument();
    const table = await screen.findByRole("table");
    expect(within(table).getAllByText("MOCK")).toHaveLength(2);
    expect(within(table).getByText("STALE")).toBeInTheDocument();
    expect(within(table).getByText("$0.45")).toBeInTheDocument();
  });

  it("shows market detail with derived asks, empty side, and rules", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "[MOCK] CPI above 3.0%?" }));
    const article = await screen.findByRole("article");
    expect(within(article).getByText("YES ask (derived)").nextSibling).toHaveTextContent("$0.45");
    expect(within(article).getByText("NO ask (derived)").nextSibling).toHaveTextContent("$0.57");
    expect(within(article).getByText(/No bids — no counterparty/)).toBeInTheDocument();
    expect(within(article).getByText("SYNTHETIC RULES FOR TESTING.")).toBeInTheDocument();
    expect(within(article).getByText("MOCK DATA")).toBeInTheDocument();
  });

  it("shows an explicit error when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("network"))));
    render(<App />);
    expect(await screen.findByText(/Backend: Backend unreachable/)).toBeInTheDocument();
  });
});
