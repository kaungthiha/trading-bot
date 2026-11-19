import { render, screen, waitFor, within } from "@testing-library/react";
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
  series_ticker: "MOCK-CPIYOY",
  title: "[MOCK] CPI above 3.0%?",
  category: "economics",
  status: "active" as const,
  status_raw: "active",
  market_type: "binary",
  open_at: null,
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
  kalshi_env: "production",
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

const calls: string[] = [];

function mockFetch() {
  const routes: Record<string, unknown> = {
    "/api/health": health,
    "/api/markets": { items: [summary, stale], limit: 200, offset: 0 } satisfies MarketList,
    "/api/markets/m1": detail,
    "/api/categories": { items: ["economics", "technology"] },
    "/api/ingestion/runs": {
      items: [
        {
          id: "r1",
          adapter: "fixture",
          started_at: "2026-11-18T15:00:00+00:00",
          finished_at: "2026-11-18T15:00:01+00:00",
          status: "success",
          count: 2,
          errors: [],
        },
      ],
    },
  };
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    expect(init?.credentials).toBe("omit");
    const url = new URL(String(input), "http://127.0.0.1");
    calls.push(url.pathname + url.search);
    const body = routes[url.pathname];
    return body
      ? new Response(JSON.stringify(body), { status: 200 })
      : new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: "nope" } }), { status: 404 });
  });
}

async function openWatchlist(user = userEvent.setup()) {
  await user.click(await screen.findByRole("tab", { name: "Watchlist" }));
  return user;
}

describe("<App>", () => {
  beforeEach(() => {
    calls.length = 0;
    sessionStorage.clear();
    window.location.hash = "#/terminal"; // these tests cover the Tools page (former Terminal)
    vi.stubGlobal("fetch", mockFetch());
  });
  afterEach(() => vi.unstubAllGlobals());

  it("opens on the scanner, with the paper-mode banner always visible", async () => {
    render(<App />);
    expect(await screen.findByText("PAPER MODE")).toBeInTheDocument();
    expect(screen.getByText(/Live execution: disabled/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Scanner" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "Tools", level: 2 })).toBeInTheDocument();
  });

  it("renders paper-mode banner and mock market list with stale indicator", async () => {
    render(<App />);
    expect(await screen.findByText("PAPER MODE")).toBeInTheDocument();
    expect(screen.getByText(/Live execution: disabled/)).toBeInTheDocument();
    await openWatchlist();
    const table = await screen.findByRole("table");
    expect(within(table).getAllByText("MOCK")).toHaveLength(2);
    expect(within(table).getByText("STALE")).toBeInTheDocument();
    expect(within(table).getByText("$0.45")).toBeInTheDocument();
  });

  it("shows market detail with derived asks, empty side, and rules", async () => {
    render(<App />);
    const user = await openWatchlist();
    await user.click(await screen.findByRole("button", { name: "[MOCK] CPI above 3.0%?" }));
    const article = await screen.findByRole("article");
    expect(within(article).getByText("YES ask (derived)").nextSibling).toHaveTextContent("$0.45");
    expect(within(article).getByText("NO ask (derived)").nextSibling).toHaveTextContent("$0.57");
    expect(within(article).getByText(/No bids — no counterparty/)).toBeInTheDocument();
    expect(within(article).getByText("SYNTHETIC RULES FOR TESTING.")).toBeInTheDocument();
    expect(within(article).getByText("MOCK DATA")).toBeInTheDocument();
  });

  it("shows last ingestion run and category options", async () => {
    render(<App />);
    await openWatchlist();
    expect(await screen.findByText(/Last ingestion:/)).toHaveTextContent("success via fixture, 2 markets");
    const category = screen.getByLabelText("Category");
    await screen.findByRole("option", { name: "technology" });
    expect(within(category).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "All",
      "economics",
      "technology",
    ]);
  });

  it("refetches markets with status, category and debounced search filters", async () => {
    render(<App />);
    const user = await openWatchlist();
    await screen.findByRole("table");
    await user.selectOptions(screen.getByLabelText("Status"), "active");
    await waitFor(() => expect(calls).toContain("/api/markets?limit=200&status=active"));
    await screen.findByRole("option", { name: "economics" });
    await user.selectOptions(screen.getByLabelText("Category"), "economics");
    await waitFor(() =>
      expect(calls).toContain("/api/markets?limit=200&category=economics&status=active"),
    );
    await user.type(screen.getByLabelText("Search"), "cpi");
    await waitFor(() =>
      expect(calls).toContain("/api/markets?limit=200&category=economics&status=active&q=cpi"),
    );
    // Debounced: no request for the partial strings "c" / "cp".
    expect(calls.some((c) => c.endsWith("&q=c") || c.endsWith("&q=cp"))).toBe(false);
  });

  it("shows the FRED attribution notice required by its terms", async () => {
    render(<App />);
    expect(
      screen.getByText(/This product uses the FRED® API but is not endorsed or certified/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "FRED API Terms of Use" })).toHaveAttribute(
      "href",
      "https://fred.stlouisfed.org/docs/api/terms_of_use.html",
    );
    await screen.findByText("PAPER MODE");
  });

  it("shows an explicit error when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("network"))));
    render(<App />);
    expect(await screen.findByText(/Backend: Backend unreachable/)).toBeInTheDocument();
  });
});
