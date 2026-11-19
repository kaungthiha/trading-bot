import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { OpportunityCard, ScannerStatus, Scorecard } from "../api/types";
import { OpportunitiesPanel } from "./OpportunitiesPanel";

const card: OpportunityCard = {
  id: "o1", detected_at: "2026-11-18T23:00:00Z", expires_at: "2026-11-18T23:03:00Z",
  status: "OPEN", kind: "LADDER", guaranteed: true, confirmed: true,
  event_ticker: "KXTEST-1", title: "Chicago total",
  legs: [
    { ticker: "KXTEST-1-100", title: "over 100", side: "YES", limit_price: "0.4000",
      quantity: "10", cost: "4.17", fee: "0.17", available: "100.00" },
    { ticker: "KXTEST-1-110", title: "over 110", side: "NO", limit_price: "0.5000",
      quantity: "10", cost: "5.18", fee: "0.18", available: "100.00" },
  ],
  quantity: "10", cost: "9.35", fees: "0.35", min_payoff: "10", profit: "0.65", return_pct: "6.95",
  claim: "'over 100' is priced BELOW 'over 110'...",
  checklist: ["Same underlying and source.", "Strikes comparable.", "Thinner leg first."],
  budget_cap: "10.00", fee_schedule_version: "kalshi-fee-schedule-2026-07-07", journal: [],
};
const status: ScannerStatus = {
  interval_seconds: 300, budget: "50", available: "50", paused: false, note: null,
  caps: { guaranteed: "10.00", conditional: "2.50" },
  last_scan: { at: "2026-11-18T23:00:00Z", events: 21655, markets: 193685, candidates: 1,
               confirmed: 1, new_cards: 1 },
};
const score: Scorecard = {
  budget: "50", available: "50", open_cost: "0", realized_pnl: "0", paused: false, note: null,
  all: { executed: 0, settled: 0, pnl: "0", wins: 0 },
  guaranteed: { executed: 0, settled: 0, pnl: "0", wins: 0 },
  conditional: { executed: 0, settled: 0, pnl: "0", wins: 0 }, skipped: 0,
};

let cards: OpportunityCard[] = [card];
const posts: { path: string; headers: Record<string, string>; body: Record<string, unknown> }[] = [];

beforeEach(() => {
  posts.length = 0;
  cards = [card];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), "http://127.0.0.1").pathname;
    if (init?.method === "POST") {
      posts.push({ path, headers: init.headers as Record<string, string>,
                   body: JSON.parse(String(init.body)) });
      return new Response(JSON.stringify(card), { status: 201 });
    }
    const body = path === "/api/opportunities" ? cards : path === "/api/scanner/status" ? status
      : path === "/api/scorecard" ? score : null;
    return new Response(JSON.stringify(body ?? {}), { status: body ? 200 : 404 });
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("<OpportunitiesPanel>", () => {
  it("renders a guaranteed thesis card with legs, costs, budget caps and scan stats", async () => {
    render(<OpportunitiesPanel />);
    const art = (await screen.findByText("Chicago total")).closest("article")!;
    const c = within(art);
    expect(c.getByText("GUARANTEED (if rules hold)")).toBeInTheDocument();
    expect(c.getByText("$0.4000")).toBeInTheDocument();
    expect(art.querySelector(".thesis-profit")).toHaveTextContent("$0.65 profit");
    expect(screen.getByText(/193685 markets/)).toBeInTheDocument();
    expect(screen.getByText(/\$10\.00 guaranteed \/ \$2\.50 conditional/)).toBeInTheDocument();
    expect(screen.getByText(/Suggestions only/)).toBeInTheDocument();
  });

  it("requires every checklist item before recording an execution with CSRF header", async () => {
    const user = userEvent.setup();
    render(<OpportunitiesPanel />);
    const exec = await screen.findByRole("button", { name: "I executed this on Kalshi" });
    expect(exec).toBeDisabled();
    for (const box of screen.getAllByRole("checkbox")) await user.click(box);
    expect(exec).toBeEnabled();
    await user.click(exec);
    await user.click(screen.getByRole("button", { name: "Save to journal" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    const p = posts[0]!;
    expect(p.path).toBe("/api/opportunities/o1/journal");
    expect(p.headers["X-KRT-Request"]).toBe("journal");
    expect(p.body.action).toBe("EXECUTED");
    expect(p.body.legs).toEqual([
      { ticker: "KXTEST-1-100", side: "YES", quantity: 10, avg_price: "0.4", fee: "0" },
      { ticker: "KXTEST-1-110", side: "NO", quantity: 10, avg_price: "0.5", fee: "0" },
    ]);
  });

  it("can skip a card", async () => {
    const user = userEvent.setup();
    render(<OpportunitiesPanel />);
    await user.click(await screen.findByRole("button", { name: "Skip" }));
    await waitFor(() => expect(posts[0]?.body.action).toBe("SKIPPED"));
  });

  it("explains that empty scans are normal", async () => {
    cards = [];
    render(<OpportunitiesPanel />);
    expect(await screen.findByText(/Most scans find nothing, and that is/)).toBeInTheDocument();
  });
});
