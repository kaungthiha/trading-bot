import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { HistoryPage } from "./HistoryPage";

const REPORT = {
  last_sync: { at: "2026-11-18T23:00:00Z", status: "success", message: "5 fills" },
  summary: { balance: "42.10", portfolio_value: "2.40", realized_pnl: "2.51", unrealized_pnl: "0.40",
             fees: "0.34", staked_closed: "8.39", roi: 0.299, settled_markets: 2, open_markets: 1,
             win_rate: { n: 2, won: 1, win_rate: 0.5, avg_price: 0.55, edge: -0.05, se: 0.35, small_sample: true },
             budget: "50" },
  reconciliation: { checked: 3, net: 2, gross: 1 },
  behavior: { fills: 5, markets: 4, active_days: 3, avg_entry_price: "0.476", longshot_share: 0.1,
              favorite_share: 0, taker_share: 1, fee_share_of_notional: 0.03, median_stake: 2.1,
              max_stake: 4.17, max_stake_share_of_budget: 0.083, combo_markets: 0,
              median_hours_before_settlement: { "game winner": 8 } },
  calibration: [{ range: "30–40¢", n: 1, won: 1, win_rate: 1, avg_price: 0.4, edge: 0.6, se: 0.49, small_sample: true }],
  by_type: [{ name: "player prop", series: "KXNBAPTS", markets: 1, staked: "3.58", pnl: "-3.58", roi: -1 }],
  by_series: [],
  open_positions: [{ ticker: "KXNBATOTAL-26NOV20BOSDEN-221", series: "KXNBATOTAL", series_title: "NBA Total",
    category: "Sports", type: "total", fills: 1, staked: "2.07", fees: "0.07", sides: ["yes"], result: null,
    status: "open", pnl: null, kalshi_realized: "0.00", position: "4.00",
    mark: { side: "yes", contracts: "4.00", mid: "0.600", value: "2.40", cost: "2.00", unrealized: "0.40" },
    first_trade_at: null }],
  markets: [],
  insights: [{ level: "info", text: "Only 2 settled market-sides so far." }],
  suggestions: [{ kind: "lean_in", title: "Open markets in NBA Game (KXNBAGAME)", why: "You are +$5.83",
                  events: [{ event_ticker: "KXNBAGAME-26NOV22BOSPHI", title: "Boston vs Philadelphia", sub_title: "" }] }],
  entry_quality: { clv: { n: 0, avg_pts: null, beat_share: null }, early_exits: { n: 1, in_profit: 1 },
                   held_to_settlement: { n: 2, lost: 1 } },
  combo_breakdown: { combos: 28, with_legs: 28, avg_legs: 9.4, lost: 25, lost_by_one: 7,
    by_size: [{ legs: "2", n: 7, won: 1 }, { legs: "6+", n: 18, won: 1 }],
    breakers: [{ type: "player prop", legs: 49 }, { type: "game winner", legs: 17 }] },
  playbook: [{ rule: "Cap each idea at $2.50", why: "5% of your $50 budget.", confidence: "standard" },
             { rule: "Keep combos to 2–3 legs", why: "1 win in 18 combos of 4+ legs.", confidence: "medium" }],
};

const OPEN = {
  positions: [{
    ticker: "KXNBATOTAL-26NOV20BOSDEN-221", title: "Over 220.5", event_ticker: "KXNBATOTAL-26NOV20BOSDEN",
    event_title: "Boston vs Denver: Total", type: "total", side: "yes", contracts: "4", avg_cost: "0.600",
    cost: "2.40", mid: "0.4", value: "1.60", unrealized: "-0.80", move_pts: -20, max_payout: "4.00",
    close_at: "2026-11-19T01:00:00Z", hours_to_close: 2, game: { prefix: "KXNBA", game_key: "26NOV20BOSDEN" },
    evidence: { ticker: "x", side: "yes", label: "x", supported: true, verdict: "market_higher",
      windows: { last5: [1, 5], last10: [3, 10], season: [5, 14], last_season: [40, 80] } },
    evidence_note: null,
    trail: [{ at: "2026-11-18T20:00:00Z", mid: 0.55 }, { at: "2026-11-18T22:00:00Z", mid: 0.4 }],
    combo: null,
    flags: [{ level: "warn", text: "Down 20 pts since entry. Would you buy it at today's price? If not, why hold?" },
            { level: "info", text: "Closes within 3 hours." }],
  }, {
    ticker: "KXMVECROSSCATEGORY-S1-A", title: "2-leg combo", event_ticker: null, event_title: null, type: "combo",
    side: "yes", contracts: "10", avg_cost: "0.100", cost: "1.00", mid: "0.6", value: "6.00", unrealized: "5.00",
    move_pts: 50, max_payout: "10.00", close_at: null, hours_to_close: null, game: null, evidence: null,
    evidence_note: null, trail: [], flags: [{ level: "info", text: "1 leg(s) won, 1 still open." }],
    combo: { fair: 0.6, won: 1, lost: 0, open: 1, legs: [
      { ticker: "L1", title: "Boston", side: "yes", type: "game winner", status: "open", probability: 0.6 },
      { ticker: "L2", title: "Brunson 25+", side: "no", type: "player prop", status: "won", probability: null }] },
  }],
  portfolio: { count: 2, cost: "3.40", value: "7.60", unrealized: "4.20", max_payout: "14.00", budget_share: 0.068,
    games: [] },
  correlation: [], evidence_enabled: true, evidence_error: null, as_of: "2026-11-18T23:00:00Z",
};

let configured = true;
let running = false;
const posts: { path: string; headers: Record<string, string> }[] = [];

beforeEach(() => {
  configured = true;
  running = false;
  posts.length = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), "http://127.0.0.1").pathname;
    const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
    if (path === "/api/history/coach") {
      posts.push({ path, headers: init?.headers as Record<string, string> });
      return json({ summary: "Combos are the leak; game winners are working.", strengths: ["+$9.87 on game winners"],
        leaks: ["Avg 9.4 legs per combo"], rules_for_next_50: ["Max 3 legs", "Limit orders only"],
        open_positions: [{ ticker: "KXNBATOTAL-26NOV20BOSDEN-221", note: "Down 20 pts vs entry" }],
        questions: ["Would I bet each leg alone?"], model: "gemma4:12b", seconds: 7.5,
        generated_at: "2026-11-19T18:00:00Z", cached: false });
    }
    if (path === "/api/history/open/review") {
      posts.push({ path, headers: init?.headers as Record<string, string> });
      return json({ summary: "Two positions; one is down 20 pts.", portfolio: ["Both ride on Boston tonight"],
        check: ["Starting lineups"], sources: [], model: "gemma4:12b", seconds: 9.1,
        generated_at: "2026-11-19T18:00:00Z", cached: false,
        positions: [{ ticker: "KXNBATOTAL-26NOV20BOSDEN-221", stance: "reconsider",
          read: "Paid 60c, now 40c; history says less likely.", plan: "Reassess under 30c", sources: [] }] });
    }
    if (path === "/api/history/coach/status") {
      return json({ provider: "Ollama", model: "gemma4:12b", local: true, configured: true, reachable: true });
    }
    if (init?.method === "POST") {
      posts.push({ path, headers: init.headers as Record<string, string> });
      running = true;
      return json({ started: true }, 202);
    }
    if (path === "/api/history/status") return json({ configured, kalshi_env: "production" });
    if (path === "/api/history/report") return json(REPORT);
    if (path === "/api/history/fills") return json({ items: [] });
    if (path === "/api/history/open") return json(OPEN);
    if (path === "/api/jobs") {
      const wasRunning = running;
      running = false;
      return json({ jobs: { history: { name: "history", running: wasRunning, last_status: "success",
        last_message: "5 fills, 2 settlements", last_started: null, last_finished: null } } });
    }
    return json({}, 404);
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("<HistoryPage>", () => {
  it("overview: P&L tiles, reconciliation, playbook and the coach placeholder", async () => {
    render(<HistoryPage />);
    expect(await screen.findByText("+$2.51")).toBeInTheDocument();
    expect(screen.getByText(/3 of 3 markets/)).toBeInTheDocument();
    expect(screen.getByText("50% vs 55%")).toBeInTheDocument();
    expect(screen.getByText("Keep combos to 2–3 legs")).toBeInTheDocument();
    expect(screen.getByText("from your data")).toBeInTheDocument();
    expect(await screen.findByText("Coach · gemma4:12b (local)")).toBeInTheDocument();
  });

  it("coach: runs the local model on click (CSRF header) and shows rules, leaks and notes", async () => {
    const user = userEvent.setup();
    render(<HistoryPage />);
    await user.click(await screen.findByRole("button", { name: "Get coaching" }));
    expect(await screen.findByText("Combos are the leak; game winners are working.")).toBeInTheDocument();
    expect(screen.getByText("Max 3 legs")).toBeInTheDocument();
    expect(screen.getByText("Avg 9.4 legs per combo")).toBeInTheDocument();
    expect(screen.getByText(/AI-written by gemma4:12b in 7.5s/)).toBeInTheDocument();
    const p = posts.find((x) => x.path === "/api/history/coach")!;
    expect(p.headers["X-KRT-Request"]).toBe("review");
  });

  it("open tab: positions with price trail, box-score verdict, flags and combo legs", async () => {
    const user = userEvent.setup();
    render(<HistoryPage />);
    await user.click(await screen.findByRole("tab", { name: "Open (1)" }));
    const total = (await screen.findByText("Over 220.5")).closest("article")!;
    expect(within(total).getByRole("link", { name: "Over 220.5" })).toHaveAttribute("href", "#/games?game=KXNBA-26NOV20BOSDEN");
    expect(within(total).getByRole("img", { name: "Price went from 55¢ to 40¢; you paid 60¢" })).toBeInTheDocument();
    expect(within(total).getByText("history: less likely")).toBeInTheDocument();
    expect(within(total).getByText(/Down 20 pts since entry/)).toBeInTheDocument();
    expect(screen.getByText("$3.40")).toBeInTheDocument();
    const combo = screen.getByText("2-leg combo").closest("article")!;
    await user.click(within(combo).getByRole("button", { name: "Legs (2)" }));
    expect(within(combo).getByText("Brunson 25+")).toBeInTheDocument();
    expect(within(combo).getByText("60¢")).toBeInTheDocument();
  });

  it("open tab: the local model reads each position on click", async () => {
    const user = userEvent.setup();
    render(<HistoryPage />);
    await user.click(await screen.findByRole("tab", { name: "Open (1)" }));
    await user.click(await screen.findByRole("button", { name: "AI read of these positions" }));
    expect(await screen.findByText("Two positions; one is down 20 pts.")).toBeInTheDocument();
    expect(screen.getByText("Both ride on Boston tonight")).toBeInTheDocument();
    const total = screen.getByText("Over 220.5").closest("article")!;
    expect(within(total).getByText("reconsider")).toBeInTheDocument();
    expect(within(total).getByText("Plan: Reassess under 30c")).toBeInTheDocument();
    const combo = screen.getByText("2-leg combo").closest("article")!;
    expect(within(combo).queryByText("reconsider")).toBeNull();
    expect(posts.find((x) => x.path === "/api/history/open/review")!.headers["X-KRT-Request"]).toBe("review");
  });

  it("behavior tab: insights, combo breakdown, entry quality and research links", async () => {
    const user = userEvent.setup();
    render(<HistoryPage />);
    await user.click(await screen.findByRole("tab", { name: "Behavior" }));
    expect(screen.getByText(/Only 2 settled/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "2 legs: 1 of 7 won; 6+ legs: 1 of 18 won" })).toBeInTheDocument();
    expect(screen.getByText(/player prop 74%/)).toBeInTheDocument();
    expect(screen.getByText("1/2")).toBeInTheDocument(); // held to end, lost
    expect(screen.getByRole("link", { name: "Boston vs Philadelphia" }))
      .toHaveAttribute("href", "#/research/event/KXNBAGAME-26NOV22BOSPHI");
    // a 1-market group never shows a return rate (was "-100%")
    expect(screen.getAllByRole("button", { name: "too few" }).length).toBeGreaterThan(0);
    expect(screen.queryByText("-100%")).not.toBeInTheDocument();
  });

  it("syncs through the history job with the ops header and reloads", async () => {
    const user = userEvent.setup();
    render(<HistoryPage />);
    await user.click(await screen.findByRole("button", { name: "Sync from Kalshi" }));
    expect(posts.map((p) => p.path)).toEqual(["/api/jobs/history/run"]);
    expect(posts[0]!.headers["X-KRT-Request"]).toBe("ops");
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("5 fills, 2 settlements"),
                  { timeout: 5000 });
  });

  it("explains key setup when no key is configured", async () => {
    configured = false;
    render(<HistoryPage />);
    expect(await screen.findByText(/Connect your account/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync from Kalshi" })).toBeDisabled();
  });
});
