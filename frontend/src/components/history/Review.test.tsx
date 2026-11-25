import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { DayBet, DayDetail, JournalEntry } from "../../api/types";
import { LogBet } from "../docket/LogBet";
import { PastMistakes } from "../docket/PastMistakes";
import { slip } from "../games/slip";
import { BetQueue } from "./BetQueue";
import { DailyReview } from "./DailyReview";

const CADE = "KXNBAPTS-26NOV24DETORL-DETCCUNNINGHAM2-25";
const DUREN = "KXNBAREB-26NOV24DETORL-DETJDUREN0-10";
const legs = [
  { ticker: CADE, side: "no" as const, label: "Cade Cunningham pts 25+", event: "KXNBAPTS-26NOV24DETORL" },
  { ticker: DUREN, side: "yes" as const, label: "Jalen Duren reb 10+", event: "KXNBAREB-26NOV24DETORL" },
];
const bet: DayBet = {
  ticker: "KXMVE-1", combo: true, title: "2-leg combo", placed_at: "2026-11-25T01:00:00Z", side: "yes",
  contracts: "10", avg_price: "0.1500", cost: "1.52", max_payout: "10.00", status: "settled", pnl: "-1.52",
  sold_early: false, legs_lost: 1, sunk_by_one: true,
  legs: [
    { ticker: CADE, side: "no", title: "Cade Cunningham: 25+ points", status: "lost", subject: "Cade Cunningham",
      category: "Unders on points", kind: "player_stat", line: 25, stat: "PTS", what_happened: "had 31 points vs the 25+ line, 36 min" },
    { ticker: DUREN, side: "yes", title: "Jalen Duren: 10+ rebounds", status: "won", subject: "Jalen Duren",
      category: "Overs on rebounds", kind: "player_stat", line: 10, stat: "REB", what_happened: "had 14 rebounds vs the 10+ line" },
  ],
  journal: { note: "Cade has been cold", source: "docket", my_price: "0.1400", market_price: "0.1500" },
};
const DAY: DayDetail = {
  date: "2026-11-24", bets: [bet],
  totals: { bets: 1, settled: 1, won: 0, pnl: "-1.52", staked: "1.52", open: 0, combos_sunk_by_one: 1 },
  breakers: [{ ...bet.legs[0]!, combos: 1, sunk_alone: 1 }], winners: [], losers: [bet], skipped: [],
  box_scores: { checked: 2, pending: 0 },
};
const entry = (status: JournalEntry["status"], over: Partial<JournalEntry> = {}): JournalEntry => ({
  id: `e-${status}`, created_at: "2026-11-24T22:00:00Z", status, source: "docket", note: "Duren vs small lineup",
  legs, market_price: "0.1500", my_price: "0.1400", stake: "1.50", kalshi: null, legs_outcome: null, ...over,
});

let posts: { path: string; body: unknown; purpose: string | null }[] = [];
let lessons: unknown[] = [];

beforeEach(() => {
  posts = [];
  lessons = [];
  slip.clear();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const u = new URL(String(input), "http://127.0.0.1");
    const ok = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body ?? "{}")) as Record<string, unknown>;
      posts.push({ path: u.pathname, body, purpose: (init.headers as Record<string, string>)["X-KRT-Request"] ?? null });
      if (u.pathname === "/api/history/day/review") {
        return ok({ date: "2026-11-24", summary: "Cade sank it again.", went_right: ["Duren hit."],
          went_wrong: [{ text: "Second Cade under lost in a week.", kind: "process", sources: ["N1"] }],
          lessons: [{ text: "Stop fading Cade's points.", player: "Cade Cunningham", stat: "PTS", side: "no" }],
          next_time: ["Check his last 5 first."], model: "gemma4:12b", seconds: 31, lessons_saved: 1, cached: false,
          news: [{ id: "N1", about: "Cade Cunningham", title: "Cade drops 31", source: "example.com", age: "1 day", url: "https://example.com/r" }],
          news_info: { searched: 1, items: 1, status: "ok" } });
      }
      if (u.pathname === "/api/history/lessons") {
        lessons = [{ id: 1, day: "2026-11-24", text: body.text, player: body.player, stat: body.stat, side: body.side, author: "you", created_at: "x" }];
        return ok({ saved: 1 });
      }
      if (u.pathname.startsWith("/api/journal/")) return ok(entry("placed"));
      if (u.pathname === "/api/journal") return ok(entry("queued"));
      return ok({});
    }
    switch (u.pathname) {
      case "/api/history/warnings":
        return ok({ history_legs: 938, general_lessons: [{ id: 2, day: "2026-11-23", text: "Keep combos to 3 legs." }],
          legs: { [`${CADE}:no`]: [{ level: "high", kind: "same_bet", text: "Unders on points for Cade Cunningham: you're 0-2 on this before." }],
            [`${DUREN}:yes`]: [] } });
      case "/api/history/days":
        return ok({ days: [{ date: "2026-11-24", bets: 1, settled: 1, won: 0, pnl: "-1.52", staked: "1.52" },
          { date: "2026-11-23", bets: 3, settled: 3, won: 1, pnl: "2.10", staked: "3.00" }] });
      case "/api/history/day": return ok(DAY);
      case "/api/history/lessons": return ok({ items: lessons });
      case "/api/history/legs": return ok({ legs: 938, won: 671, lost: 267, overall_loss_rate: 0.285, min_pattern: 10,
        hurt: [{ name: "Paul George", n: 6, won: 1, lost: 5, combos_hurt: 4, recent_losses: [{ bet: "YES · Paul George: 30+ points", date: "2026-11-24", what_happened: "had 18 points vs the 30+ line" }] }],
        carried: [], by_category: [{ name: "Picking winners", n: 242, won: 150, lost: 92, loss_rate: 0.38, pattern: true }] });
      case "/api/history/top": return ok({ winners: [], losers: [bet] });
      case "/api/journal": return ok({ queued: 1, items: [entry("queued"),
        entry("placed", { id: "e-p", kalshi: { ticker: "KXMVE-1", combo: true, status: "settled", pnl: "-1.52", staked: "1.52", avg_price: "0.1500", contracts: "10", placed_at: "x" } }),
        entry("skipped", { id: "e-s", legs_outcome: "won" })] });
      default: return new Response("{}", { status: 404 });
    }
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("Docket: past mistakes and logging a bet", () => {
  it("flags a leg that repeats a past loss, with your lessons", async () => {
    render(<PastMistakes legs={legs} />);
    const sec = await screen.findByRole("region", { name: /Your past mistakes \(1 leg\)/ });
    expect(within(sec).getByText(/you're 0-2 on this before/)).toBeInTheDocument();
    expect(within(sec).getByText("Keep combos to 3 legs.")).toBeInTheDocument();
  });

  it("queues the bet with your price, stake and reason (journal header)", async () => {
    const user = userEvent.setup();
    render(<LogBet legs={legs} fair={0.1512} quoteCents="14" />);
    await user.type(screen.getByLabelText(/Stake/), "1.5");
    await user.type(screen.getByLabelText("Why this bet"), "Duren vs small lineup");
    await user.click(screen.getByRole("button", { name: "Add to bet queue" }));
    expect(await screen.findByText(/Queued/)).toBeInTheDocument();
    expect(posts[0]).toMatchObject({ path: "/api/journal", purpose: "journal",
      body: { status: "queued", source: "docket", my_price: "0.1400", stake: "1.50", market_price: "0.1512",
        note: "Duren vs small lineup" } });
  });
});

describe("<DailyReview>", () => {
  it("shows the day's bets, what each player did, the legs that sank you, and the model's lessons", async () => {
    const user = userEvent.setup();
    render(<DailyReview />);
    const sank = await screen.findByRole("region", { name: /Legs that sank you \(1\)/ });
    expect(within(sank).getByText(/had 31 points vs the 25\+ line/)).toBeInTheDocument();
    expect(within(sank).getByText(/the only miss in 1/)).toBeInTheDocument();
    const all = screen.getByRole("region", { name: /Every bet on/ });
    expect(within(all).getByText(/paid 15.0¢/)).toBeInTheDocument();
    expect(within(all).getByText(/Cade has been cold/)).toBeInTheDocument();
    expect(await screen.findByText("Paul George")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Review this day with the local model" }));
    expect(await screen.findByText("Cade sank it again.")).toBeInTheDocument();
    expect(posts.at(-1)).toMatchObject({ path: "/api/history/day/review", purpose: "review", body: { date: "2026-11-24" } });
    expect(screen.getByRole("link", { name: "N1" })).toHaveAttribute("rel", "noopener noreferrer nofollow");
    expect(screen.getByText(/flags unders on Cade Cunningham PTS/)).toBeInTheDocument();
  });

  it("saves your own tagged lesson", async () => {
    const user = userEvent.setup();
    render(<DailyReview />);
    await user.type(await screen.findByLabelText("New lesson"), "No unders on Cade");
    await user.type(screen.getByLabelText("Player (optional)"), "Cade Cunningham");
    await user.selectOptions(screen.getByLabelText("Stat"), "PTS");
    await user.selectOptions(screen.getByLabelText("Side"), "no");
    await user.click(screen.getByRole("button", { name: "Save lesson" }));
    expect(posts.at(-1)).toMatchObject({ path: "/api/history/lessons", purpose: "lesson",
      body: { text: "No unders on Cade", player: "Cade Cunningham", stat: "PTS", side: "no" } });
    expect(await screen.findByRole("button", { name: /Remove lesson: No unders on Cade/ })).toBeInTheDocument();
  });
});

describe("<BetQueue>", () => {
  it("groups queued, placed and skipped bets; marks one placed; loads one into the docket", async () => {
    const user = userEvent.setup();
    render(<BetQueue />);
    const queued = await screen.findByRole("region", { name: "Queued: still to place" });
    expect(screen.getByRole("region", { name: "Placed" })).toHaveTextContent(/paid 15.0¢ for 10 contracts/);
    expect(screen.getByRole("region", { name: "Placed" })).toHaveTextContent(/paid more than you planned/);
    expect(screen.getByRole("region", { name: "Skipped" })).toHaveTextContent(/it would have won/);
    await user.click(within(queued).getByRole("button", { name: "I placed it" }));
    expect(posts.at(-1)).toMatchObject({ path: "/api/journal/e-queued", purpose: "journal", body: { status: "placed" } });
    await user.click(within(queued).getByRole("button", { name: "Load into docket" }));
    expect(slip.get().map((l) => l.ticker)).toEqual([CADE, DUREN]);
  });
});
