import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { vi } from "vitest";

import type { CatalogEventDetail, CatalogMarket } from "../../api/types";
import { ResearchDocket } from "../docket/ResearchDocket";
import { slip } from "../games/slip";
import { MarketsPage } from "./MarketsPage";

const mk = (ticker: string, label: string, bid: string, ask: string, implied: number,
            strike: string | null = null): CatalogMarket => ({
  ticker, title: label, yes_sub_title: label, no_sub_title: "", status: "active",
  yes_bid: bid, yes_ask: ask, no_bid: null, no_ask: String((1 - Number(bid)).toFixed(2)),
  yes_bid_size: "50", yes_ask_size: "80", last_price: bid, change_24h: "0.0300",
  volume_24h: "5000", open_interest: "100", implied, implied_quality: "mid", spread: 0.01,
  floor_strike: strike, strike_type: strike ? "greater" : null, close_at: "2026-11-21T02:30:00Z",
});

const GAME: CatalogEventDetail = {
  event_ticker: "KXNBAGAME-26NOV18BOSDEN", series_ticker: "KXNBAGAME", category: "Sports",
  title: "Boston vs Denver", sub_title: "BOS vs DEN (Nov 18)", competition: "Pro Basketball (M)",
  mutually_exclusive: true, market_count: 2, volume_24h: 9000, open_interest: 200,
  close_at: "2026-11-21T02:30:00Z", occurs_at: null, refreshed_at: "2026-11-18T23:00:00Z",
  series_title: "NBA Game", combo_collections: ["KXMVECROSSCATEGORY-R"], rules_sample: "If Boston wins, Yes.",
  fee: { schedule: "kalshi-fee-schedule-2026-07-07", multiplier: "1", fee_type: "quadratic" },
  markets: [mk("KXNBAGAME-26NOV18BOSDEN-BOS", "Boston", "0.47", "0.48", 0.475),
            mk("KXNBAGAME-26NOV18BOSDEN-DEN", "Denver", "0.52", "0.53", 0.525)],
  stats: { exclusive: { outcomes: 2, priced: 2, sum_yes_ask: "1.01", sum_yes_bid: "0.99",
                        sum_implied: 1.0, overround: 0, normalized: {
                          "KXNBAGAME-26NOV18BOSDEN-BOS": 0.475, "KXNBAGAME-26NOV18BOSDEN-DEN": 0.525 } },
           ladders: [] },
};

const TOTAL: CatalogEventDetail = {
  ...GAME, event_ticker: "KXNBATOTAL-26NOV18BOSDEN", series_ticker: "KXNBATOTAL",
  title: "Boston vs Denver: Total Points", mutually_exclusive: false, market_count: 3,
  markets: [mk("T-215", "Over 215.5", "0.69", "0.71", 0.7, "215.5"),
            mk("T-220", "Over 220.5", "0.49", "0.51", 0.5, "220.5"),
            mk("T-225", "Over 225.5", "0.29", "0.31", 0.3, "225.5")],
  stats: { exclusive: null, ladders: [{
    label: "Over X points", strikes: 3, median: 220.5, p10: null, p25: 216.8, p75: 224.2,
    p90: null, mean: 220.4, sd: 6.1, tail_mass: 0.6, mean_reliable: false,
    monotonicity_violations: 0,
    buckets: [{ label: "≤ 215.5", lo: null, hi: 215.5, p: 0.3 }, { label: "215.5–220.5", lo: 215.5, hi: 220.5, p: 0.2 },
              { label: "220.5–225.5", lo: 220.5, hi: 225.5, p: 0.2 }, { label: "> 225.5", lo: 225.5, hi: null, p: 0.3 }],
    points: [{ ticker: "T-220", strike: 220.5, label: "Over 220.5", implied: 0.5, fitted: 0.46,
               residual: 0.04, quality: "mid", spread: 0.02, off_curve: true }],
  }] },
};

const calls: string[] = [];
beforeEach(() => {
  slip.clear();
  calls.length = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const u = new URL(String(input), "http://127.0.0.1");
    calls.push(u.pathname + u.search);
    const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
    switch (u.pathname) {
      case "/api/jobs":
        return json({ jobs: Object.fromEntries(["refresh", "evidence", "scan"].map((n) => [n, {
          name: n, running: false, last_started: null, last_finished: null, last_status: null,
          last_message: null }])), auto_scan: { enabled: false, interval_seconds: 300, next_run_at: null },
          worker_running: false, watchlist: ["KXCPI"] });
      case "/api/catalog/status":
        return json({ refreshed_at: "2026-11-18T23:00:00Z", events: 2, markets: 5, series: 2 });
      case "/api/catalog/categories":
        return json({ items: [{ name: "Sports", events: 2, markets: 5, volume_24h: 9000 }] });
      case "/api/catalog/series":
        return json({ items: [{ ticker: "KXNBAGAME", title: "NBA Game", events: 1, markets: 2, volume_24h: 9000 }] });
      case "/api/catalog/events":
        return json({ items: [GAME, TOTAL], total: 2, limit: 50, offset: 0 });
      case `/api/catalog/events/${GAME.event_ticker}`: return json(GAME);
      case `/api/catalog/events/${TOTAL.event_ticker}`: return json(TOTAL);
      case "/api/catalog/combo":
        return json({ legs: [], independent_probability: 0.2375, fair_price: 0.2375,
                      fair_multiple: 4.21, warnings: ["Same game (26NOV18BOSDEN) across 2 markets"] });
      default:
        if (u.pathname.endsWith("/ev")) {
          return json({ ticker: "x", side: "yes", price: "0.48", price_source: "snapshot ask",
            snapshot_at: "2026-11-18T23:00:00Z", contracts: 10, probability: "0.5500",
            notional: "4.80", fee: "0.18", total_cost: "4.98", max_payout: "10",
            expected_payout: "5.5000", expected_value: "0.5200", ev_per_dollar: "0.1044",
            breakeven_probability: "0.4980", kelly_fraction: "0.1036", depth_at_price: "80",
            depth_warning: false, fee_schedule_version: "v", budget: "50",
            quarter_kelly_stake: "1.29", cap_stake: "2.50", suggested_contracts: 2 });
        }
        return json({ error: { code: "NOT_FOUND", message: "nope" } }, 404);
    }
  }));
});
afterEach(() => vi.unstubAllGlobals());

function Harness() {
  const [ev, setEv] = useState<string | null>(null);
  return <><MarketsPage eventTicker={ev} onOpenEvent={setEv} /><ResearchDocket /></>;
}

describe("<MarketsPage>", () => {
  it("lists categories, series and events from the catalog", async () => {
    render(<Harness />);
    expect(await screen.findByRole("button", { name: /Sports/ })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /NBA Game/ })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Boston vs Denver" })).toBeInTheDocument();
    expect(screen.getByText(/2 open events/)).toBeInTheDocument();
  });

  it("opens a game: prices, implied odds, and the exclusive-set summary", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole("button", { name: "Boston vs Denver" }));
    expect(await screen.findByText(/Exactly one outcome wins/)).toBeInTheDocument();
    const row = screen.getByText("KXNBAGAME-26NOV18BOSDEN-BOS").closest("tr")!;
    expect(within(row).getAllByText("47.5%", { selector: "td" })).toHaveLength(2); // implied + normalized
    expect(within(row).getByText("+3¢")).toBeInTheDocument();
  });

  it("shows a ladder's implied distribution and off-curve strikes", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole("button", { name: "Boston vs Denver: Total Points" }));
    expect(await screen.findByRole("img", { name: /Over X points: implied probability/ })).toBeInTheDocument();
    expect(screen.getByText(/Median/)).toHaveTextContent("220.5");
    expect(screen.getByText(/Off the smooth curve/)).toHaveTextContent("Over 220.5");
    expect(screen.getByText(/mean unreliable/)).toBeInTheDocument();
  });

  it("computes expected value and builds a combo with correlation warnings", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole("button", { name: "Boston vs Denver" }));
    await screen.findByText(/Exactly one outcome wins/);
    await user.click(screen.getAllByRole("button", { name: "EV" })[0]!);
    expect(await screen.findByText(/2 contract\(s\)/)).toBeInTheDocument();
    expect(calls.some((c) => c.includes("/ev?side=yes&prob=0.4750&contracts=10"))).toBe(true);
    await user.click(screen.getByRole("button", { name: "Add YES Boston to combo" }));
    // Markets and Games share one Docket (no separate combo tray).
    const docket = screen.getByRole("complementary", { name: "Research docket" });
    expect(within(docket).getByLabelText("1 legs")).toBeInTheDocument();
    await waitFor(() => expect(within(docket).getByRole("region", { name: "Where this may be wrong" }))
      .toHaveTextContent("Same game"));
    expect(screen.getByRole("button", { name: "Add YES Boston to combo" })).toBeDisabled();
  });

  it("explains how to load the catalog when it is empty", async () => {
    const real = fetch;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/api/catalog/status")) {
        return new Response(JSON.stringify({ refreshed_at: null, events: 0, markets: 0, series: 0 }));
      }
      return real(input, init);
    }));
    render(<Harness />);
    expect(await screen.findByText(/No catalog yet/)).toBeInTheDocument();
  });
});
