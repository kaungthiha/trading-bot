import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { IdeasPanel } from "./IdeasPanel";
import { slip } from "./slip";

const IDEAS = {
  game: { prefix: "KXNBA", game_key: "26NOV19NYKMIN", title: "New York vs Minnesota", occurs_at: null },
  singles: [
    { id: "S1", ticker: "KXNBAREB-26NOV19NYKMIN-NYKKTOWNS32-14", side: "no", bet: "NO · Karl-Anthony Towns reb 14+",
      ask: "0.57", bid: "0.56", all_in: "0.587", history: "1.0", mid: "0.565", edge_pts: 41.3, interval: [0.93, 1],
      limit: { price: "0.56", saves_per_100: "2.72", maker_fee_per_100: "0.00", behind_bid: true },
      strength: "strong", event_ticker: "KXNBAREB-26NOV19NYKMIN", eligible: true, subject: "Karl-Anthony Towns",
      windows: { last5: [5, 5], last10: [10, 10], season: [12, 12], last_season: [12, 12] }, season_avg: 11.7,
      line: 13.5, injury: null, contracts_at_cap: 4 },
    { id: "S2", ticker: "KXNBAGAME-26NOV19NYKMIN-NYK", side: "yes", bet: "YES · Winner New York",
      ask: "0.51", bid: "0.50", all_in: "0.528", history: "0.6742", mid: "0.505", edge_pts: 14.7, interval: [0.5, 0.8],
      strength: "lean", event_ticker: "KXNBAGAME-26NOV19NYKMIN", eligible: true, subject: "New York Knicks",
      windows: null, season_avg: null, line: null, injury: { status: "Day-To-Day", detail: "x" }, contracts_at_cap: 5 },
  ],
  combos: [{ id: "K1", legs: ["S1", "S2"], tickers: [], bets: ["NO · Karl-Anthony Towns reb 14+", "YES · Winner New York"],
    sides: ["no", "yes"], fair: 0.285, history: 0.674, lift: 1.1, walk_away: "0.55", ratio: 2.36,
    past: { bucket: "2 legs", n: 50, return_per_dollar: 0.82 } }],
  entries: [{ ticker: "KXNBAREB-26NOV19NYKMIN-NYKKTOWNS32-12", side: "no", bet: "NO · Karl-Anthony Towns reb 12+",
    ask: "0.39", bid: "0.34", limit: "0.35", saves_per_100: "5.67", maker_fee_per_100: "0.00", mid: "0.365" }],
  screened: 15, skipped: { thin: 0, injured: 0, no_history: 4, priced_right: 4 },
  evidence_enabled: true, evidence_error: null, cap: "2.50", open_cost: "0.00", budget: "50",
  fees_verified: true, generated_at: "2026-11-19T15:00:00Z",
};

const posts: { path: string; headers: Record<string, string> }[] = [];

beforeEach(() => {
  posts.length = 0;
  slip.clear();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), "http://127.0.0.1").pathname;
    const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
    if (path.endsWith("/ideas")) return json(IDEAS);
    if (path === "/api/games/review/status") {
      return json({ provider: "Ollama", model: "gemma4:12b", local: true, configured: true, reachable: true,
        used_today: 0, daily_cap: null, headlines: false });
    }
    if (path.endsWith("/ideas/ai")) {
      posts.push({ path, headers: init?.headers as Record<string, string> });
      return json({ summary: "One strong single; the combo adds little.", skip: [{ id: "K1", why: "Win leg is a lean" }],
        picks: [{ id: "S1", how: "limit", stake: 2.24, why: ["Never 14+ in 24 games"], risks: ["Matchup ignored"], sources: [] }],
        sources: [], model: "gemma4:12b", seconds: 11, generated_at: "x", cached: false });
    }
    return new Response("{}", { status: 404 });
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("<IdeasPanel>", () => {
  it("lists singles, combos and book-only entries, and adds to the slip", async () => {
    const user = userEvent.setup();
    render(<IdeasPanel prefix="KXNBA" gameKey="26NOV19NYKMIN" />);
    const row = (await screen.findByText("Karl-Anthony Towns reb 14+")).closest("li")!;
    expect(within(row).getByText("strong")).toBeInTheDocument();
    expect(within(row).getByText("+41 pts")).toBeInTheDocument();
    expect(within(row).getByText(/limit 56¢/)).toBeInTheDocument();
    // the exact single can be investigated straight from the row (Phase E entry point)
    expect(within(row).getByRole("button", { name: /^Investigate NO: Karl-Anthony Towns reb 14\+|^Investigate YES: Karl-Anthony Towns reb 14\+/ })).toBeInTheDocument();
    expect(screen.getByText(/Screened 15 legs · 2 beat the price · cap \$2.50/)).toBeInTheDocument();
    expect(screen.getByText(/Day-To-Day/)).toBeInTheDocument();
    expect(screen.getByText("quote ≤ 55¢")).toBeInTheDocument();
    expect(screen.getByText(/saves \$5.67\/100/)).toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: "Add" }));
    expect(slip.get()).toEqual([{ ticker: "KXNBAREB-26NOV19NYKMIN-NYKKTOWNS32-14", side: "no",
      label: "Karl-Anthony Towns reb 14+", event: "KXNBAREB-26NOV19NYKMIN" }]);
    await user.click(screen.getByRole("button", { name: "Put on docket" }));
    expect(slip.get().map((l) => l.side)).toEqual(["no", "yes"]);
  });

  it("asks the local model to pick from the list (CSRF header)", async () => {
    const user = userEvent.setup();
    render(<IdeasPanel prefix="KXNBA" gameKey="26NOV19NYKMIN" />);
    await user.click(await screen.findByRole("button", { name: "Ask the local model to pick (or pass)" }));
    expect(await screen.findByText("One strong single; the combo adds little.")).toBeInTheDocument();
    expect(screen.getByText("Never 14+ in 24 games")).toBeInTheDocument();
    expect(screen.getByText(/rest a limit at 56¢ · \$2.24/)).toBeInTheDocument();
    expect(posts[0]!.headers["X-KRT-Request"]).toBe("review");
  });
});
