import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Brief, SlateState } from "../../api/types";
import { SlatePanel } from "./SlatePanel";
import { slip } from "./slip";

const brief = (lead: string): Brief => ({
  lean: "strong", headline: "Strong case: 3 for, 0 against", score: 3,
  for: [{ text: lead, kind: "form" }, { text: "Minutes up: 37.2 vs 30.4", kind: "minutes" }],
  against: [], context: [{ text: "He has had 2 days of rest", kind: "rest" }],
});
const leg = (ticker: string, label: string, side: "yes" | "no", game: string, price: number) => ({
  ticker, side, label, bet: `${side.toUpperCase()} · ${label}`, event_ticker: ticker.split("-").slice(0, 2).join("-"),
  game, price,
});
const L1 = leg("KXNBAPTS-26NOV24DETORL-DETCCUNNINGHAM2-25", "Cade Cunningham pts 25+", "yes", "Detroit vs Orlando", 0.5);
const L2 = leg("KXNBAAST-26NOV24BOSWAS-WASTYOUNG11-8", "Trae Young ast 8+", "no", "Boston vs Washington", 0.46);
const L3 = leg("KXNBA3PT-26NOV24DALDEN-DALKIRVING11-4", "Kyrie Irving 3pm 4+", "yes", "Dallas vs Denver", 0.44);
const READY: SlateState = {
  status: "ready", finished_at: "2026-11-24T20:00:00Z", fresh: true,
  result: {
    prefix: "KXNBA", generated_at: "2026-11-24T20:00:00Z",
    games: [{ game_key: "26NOV24DETORL", title: "Detroit vs Orlando", occurs_at: "2026-11-25T00:00:00Z" }],
    combos: [{
      legs: [L1, L2, L3].map((x) => ({ ...x, headline: "Strong case", why: [{ text: `why ${x.label}`, kind: "form" }] })),
      games: 3, market: 0.101, adjusted: 0.101, pays: 9.9, together: [],
      risks: [{ leg: "Trae Young ast 8+", text: "Out for his team: Jamir Watkins" }],
      past: { bucket: "3 legs", n: 890, return_per_dollar: 0.85 },
    }],
    pool: [{ ...L1, brief: brief("Had 25+ points in 7 of his last 10") }],
    briefed: 240, leans: { strong: 17, mixed: 174, weak: 49 }, skipped: [],
    rules: { leg_price: [0.4, 0.8], min_score: 2, max_per_game: 2 },
  },
};

let state: SlateState = { status: "idle" };
const posts: Record<string, string>[] = [];

beforeEach(() => {
  slip.clear();
  posts.length = 0;
  state = { status: "idle" };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), "http://127.0.0.1").pathname;
    if (path === "/api/games/slate/KXNBA") {
      if (init?.method === "POST") {
        posts.push(init.headers as Record<string, string>);
        state = READY;
        return new Response(JSON.stringify({ status: "building", progress: "Reading game 1 of 4" }), { status: 200 });
      }
      return new Response(JSON.stringify(state), { status: 200 });
    }
    return new Response("{}", { status: 404 });
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("<SlatePanel>", () => {
  it("builds only on click, shows progress, then combos with reasons and risks", async () => {
    const user = userEvent.setup();
    render(<SlatePanel />);
    expect(await screen.findByText("Not built yet")).toBeInTheDocument();
    expect(posts).toHaveLength(0); // opening the page never starts a build

    await user.click(screen.getByRole("button", { name: "Build tonight's combos" }));
    expect(posts[0]!["X-KRT-Request"]).toBe("slate");
    expect(await screen.findByText(/Reading game 1 of 4/)).toBeInTheDocument();

    // polling picks up the finished build
    const combo = await screen.findByRole("heading", { name: /Combo 1 · 3 legs · 3 games/ }, { timeout: 4000 });
    const card = combo.closest("li")!;
    expect(within(card).getByText("10.1%")).toBeInTheDocument();
    expect(within(card).getByText("9.9×")).toBeInTheDocument();
    expect(within(card).getByText("why Trae Young ast 8+")).toBeInTheDocument();
    expect(within(card).getByText(/Out for his team: Jamir Watkins/)).toBeInTheDocument();
    expect(within(card).getByText(/Past 3 legs combos on Kalshi paid \$0.85 per \$1/)).toBeInTheDocument();
    expect(screen.getByText(/240 legs briefed across 1 game · 17 strong, 174 mixed, 49 weak/)).toBeInTheDocument();

    await user.click(within(card).getByRole("button", { name: "Put on docket" }));
    expect(slip.get().map((l) => `${l.label}:${l.side}`)).toEqual([
      "Cade Cunningham pts 25+:yes", "Trae Young ast 8+:no", "Kyrie Irving 3pm 4+:yes"]);
  });

  it("says plainly when no combo passed", async () => {
    state = { ...READY, result: { ...READY.result!, combos: [], pool: [] } };
    render(<SlatePanel />);
    expect(await screen.findByText("No combo passed tonight")).toBeInTheDocument();
    expect(screen.getByText(/priced 40–80%/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rebuild" })).toBeInTheDocument();
  });
});
