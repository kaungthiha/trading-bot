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
      past: { bucket: "3 legs", n: 890, return_per_dollar: 0.85 }, source: "rules",
    }],
    engine: { mode: "rules", model: null, seconds: 0, reason: "Ollama isn't running on this machine" },
    summary: "", pass_reason: "", rule_combos: [], reviews: [], dropped: [], conflicts: [], news: [],
    news_info: { searched: 0, items: 0, status: "off" },
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

  it("shows the local model's synthesis: case, risk, conflicts with cited news, drops", async () => {
    const base = READY.result!;
    const modelCombo = { ...base.combos[0]!, source: "model" as const,
      case: "Three games, each leg with a clear case the news doesn't contradict.",
      risk: "Cunningham's knee: a minutes limit sinks leg 1." };
    state = { ...READY, result: { ...base,
      engine: { mode: "local_model", model: "gemma4:12b", seconds: 41.5, reason: null },
      summary: "One combo across three games; Detroit's center news cut two legs.",
      pass_reason: "Other legs leaned on stale minutes.",
      combos: [modelCombo], rule_combos: [base.combos[0]!],
      conflicts: [{ bet: "YES · Jalen Duren reb 12+", game: "Detroit vs Orlando",
        note: "Preview says he's on a minutes limit after returning", sources: ["N2"] }],
      dropped: [{ bet: "YES · Total points 213+", game: "Detroit vs Orlando", note: "Both starters out per report", sources: ["N1"] }],
      reviews: [{ game: "Detroit vs Orlando", note: "Duren returns on a limit.", news: ["N1", "N2"] }],
      news: [{ id: "N1", game: "Detroit vs Orlando", title: "Pistons injury report", source: "example.com", age: "2 hours", url: "https://example.com/1" },
             { id: "N2", game: "Detroit vs Orlando", title: "Duren minutes limit", source: "example.org", age: "1 hour", url: "https://example.org/2" }],
      news_info: { searched: 6, items: 2, status: "ok" } } };
    render(<SlatePanel />);
    expect((await screen.findByText(/Synthesized by your local model/)).closest("p")).toHaveTextContent("gemma4:12b, 41.5s");
    expect(screen.getByText(/6 news searches, 2 items/)).toBeInTheDocument();
    expect(screen.getByText(/Detroit's center news cut two legs/)).toBeInTheDocument();
    expect(screen.getByText(/each leg with a clear case/)).toBeInTheDocument();
    expect(screen.getByText(/a minutes limit sinks leg 1/)).toBeInTheDocument();
    const conflicts = screen.getByRole("region", { name: "Stats vs news" });
    expect(within(conflicts).getByRole("link", { name: "N2" })).toHaveAttribute("href", "https://example.org/2");
    expect(within(conflicts).getByRole("link", { name: "N2" })).toHaveAttribute("rel", "noopener noreferrer nofollow");
    expect(screen.getByRole("region", { name: "Dropped by the model" })).toHaveTextContent("Both starters out per report");
    expect(screen.getByText(/Rules-only combos, for comparison \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Fewer than three: Other legs leaned on stale minutes/)).toBeInTheDocument();
  });

  it("says why it fell back to rules", async () => {
    state = READY;
    render(<SlatePanel />);
    expect((await screen.findByText(/Rules only./)).closest("p")).toHaveTextContent("Ollama isn't running on this machine");
  });

  it("says plainly when no combo passed", async () => {
    state = { ...READY, result: { ...READY.result!, combos: [], pool: [] } };
    render(<SlatePanel />);
    expect(await screen.findByText("No combo tonight")).toBeInTheDocument();
    expect(screen.getByText(/priced 40–80%/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rebuild" })).toBeInTheDocument();
  });
});
