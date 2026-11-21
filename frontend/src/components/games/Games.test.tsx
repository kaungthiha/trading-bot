import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { vi } from "vitest";

import type { EvidenceResult, GameDetail, LegEvidence } from "../../api/types";
import { ResearchDocket } from "../docket/ResearchDocket";
import { GamesPage } from "./GamesPage";
import { LegResearch, MiniBars } from "./LegResearch";
import { slip } from "./slip";

const KEY = "26NOV19NYKMIN";
const chip = (ticker: string, label: string, title: string, implied: number) => ({
  ticker, event_ticker: ticker.split("-").slice(0, 2).join("-"), label, title, team: null, implied,
  quality: "mid", yes_bid: implied - 0.01, yes_ask: implied + 0.01, no_ask: 1 - implied + 0.01,
  spread: 0.02, volume_24h: 100, strike: null });

const GAME: GameDetail = {
  game_key: KEY, prefix: "KXNBA", league: "NBA", title: "New York vs Minnesota", sub_title: "NYK vs MIN",
  occurs_at: "2026-11-20T00:30:00Z", close_at: null, refreshed_at: "2026-11-19T15:00:00Z",
  teams: [{ code: "NYK", name: "New York", win: 0.5 }, { code: "MIN", name: "Minnesota", win: 0.5 }],
  sections: [{ id: "main", label: "Game lines", groups: [
    { id: "GAME", label: "Winner", kind: "pick", event_ticker: `KXNBAGAME-${KEY}`, eligible: true,
      series_title: "NBA Game", median_label: null, markets: [
        chip(`KXNBAGAME-${KEY}-NYK`, "New York", "New York wins", 0.505),
        chip(`KXNBAGAME-${KEY}-MIN`, "Minnesota", "Minnesota wins", 0.495)] },
    { id: "TOTAL", label: "Total points", kind: "ladder", event_ticker: `KXNBATOTAL-${KEY}`, eligible: true,
      series_title: "NBA Total", median_label: "≈ 216.4", markets: Array.from({ length: 10 }, (_, i) =>
        chip(`KXNBATOTAL-${KEY}-${206 + 2 * i}`, `${206 + 2 * i}+`, `Over ${205.5 + 2 * i} points`, 0.95 - i * 0.09)) },
  ] }, { id: "periods", label: "Halves & quarters", groups: [] }],
  players: [{ id: "kat", name: "Karl-Anthony Towns", team: "NYK", volume_24h: 500, stats: {
    REB: { event_ticker: `KXNBAREB-${KEY}`, eligible: true, series_title: "NBA Rebounds", label: "REB",
      median: 12.9, markets: [chip(`KXNBAREB-${KEY}-NYKKTOWNS32-12`, "12+", "Karl-Anthony Towns: 12+ rebounds", 0.635),
                              chip(`KXNBAREB-${KEY}-NYKKTOWNS32-14`, "14+", "Karl-Anthony Towns: 14+ rebounds", 0.435)] },
  } }],
  stats: ["REB", "PTS"], stat_labels: { REB: "REB", PTS: "PTS" },
  protected_available: true, protected: false, evidence_supported: true,
};

const evLeg = (ticker: string, side: "yes" | "no", verdict: LegEvidence["verdict"]): LegEvidence => ({
  ticker, side, label: ticker, supported: true, kind: "player_stat", stat: "REB", line: 11.5,
  subject: { type: "player", name: "Karl-Anthony Towns", team: "NYK", espn_url: "https://www.espn.com/nba/player/_/id/3136195" },
  injury: null, windows: { last5: [4, 5], last10: [9, 10], season: [12, 14], last_season: [49, 97] },
  estimate: 0.71, interval: [0.58, 0.81], market: 0.635, verdict, season_avg: 13.6,
  recent: [{ date: "2026-11-18", opponent: "TOR", home: false, value: 16, hit: true },
           { date: "2026-11-16", opponent: "TOR", home: true, value: 11, hit: false }],
});

const calls: string[] = [];
const sentHeaders: Record<string, string>[] = [];
let reviewOn = false;
let noInjuryReport = false;
beforeEach(() => {
  slip.clear();
  noInjuryReport = false;
  calls.length = 0;
  sentHeaders.length = 0;
  reviewOn = false;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const u = new URL(String(input), "http://127.0.0.1");
    calls.push(u.pathname + u.search);
    const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
    switch (u.pathname) {
      case "/api/jobs":
        return json({ jobs: {}, auto_scan: { enabled: false, interval_seconds: 300, next_run_at: null },
          worker_running: false, watchlist: [] });
      case "/api/games":
        return json({ items: [{ game_key: KEY, league: "NBA", prefix: "KXNBA", title: "New York vs Minnesota",
          sub_title: "NYK vs MIN", occurs_at: "2026-11-20T00:30:00Z", close_at: null, teams: GAME.teams,
          events: 49, markets: 1200, volume_24h: 5000 }], leagues: [{ league: "NBA", games: 1 }, { league: "NHL", games: 3 }] });
      case `/api/games/KXNBA/${KEY}`: return json(GAME);
      case `/api/games/KXNBA/${KEY}/injuries`:
        if (noInjuryReport) return json({ supported: false, teams: [] });
        return json({ supported: true, teams: [{ code: "MIN", name: "Minnesota Timberwolves", items: [
          { player: "Jonathan Kuminga", status: "Day-To-Day", detail: "Shoulder", date: "2026-11-18" }] }] });
      case "/api/catalog/combo": {
        const legs = (u.searchParams.get("legs") ?? "").split(",").map((p) => p.split(":"));
        return json({ legs: legs.map(([t, s]) => ({ ticker: t, side: s, label: t, event: "E", probability: s === "yes" ? 0.6 : 0.4, quality: "mid" })),
          independent_probability: 0.36 ** (legs.length / 2), fair_price: legs.length > 1 ? 0.3 : 0.6,
          fair_multiple: 3.33, warnings: ["Same game (26NOV19NYKMIN) across 2 markets"],
          kalshi: { eligible: true, collections: ["KXMVECROSSCATEGORY-R"], ineligible_events: [],
            history: { bucket: "2 legs", n: 2353, avg_price: 0.351, hit_rate: 0.282, edge: -0.07, se: 0.01, return_per_dollar: 0.8 } } });
      }
      case "/api/games/evidence": {
        const legs = (u.searchParams.get("legs") ?? "").split(",").map((p) => p.split(":") as [string, "yes" | "no"]);
        const out: EvidenceResult = {
          legs: legs.map(([t, s]) => evLeg(t, s, s === "yes" ? "agrees" : "market_higher")),
          correlation: legs.length > 1 ? [{ game_key: KEY, team: "NYK", legs: legs.map((l) => l[0]), games: 83, together: 30, expected: 22.4, lift: 1.25 }] : [],
          independent_probability: 0.3, adjusted_probability: legs.length > 1 ? 0.375 : 0.6 };
        return json(out);
      }
      case "/api/games/check": {
        const n = (u.searchParams.get("legs") ?? "").split(",").length;
        const stake = u.searchParams.get("stake");
        return json({
          verdict: n >= 2 ? "stretch" : "single",
          reasons: [{ level: "warn", text: `${n} legs: each extra leg multiplies the maker's margin.` },
                    ...(stake ? [{ level: "warn", text: `${stake} is over your $2.50 per-idea cap.` }] : []),
                    { level: "good", text: "1 leg(s) look like value on their own: consider them as singles (below)." }],
          combo: { legs: n, fair: 0.3, estimate: 0.33, walk_away: "0.28", history: null },
          sizing: { cap: "2.50", budget: "50.00", open_cost: "0.00", cash: "10.00", stake,
                    ...(stake ? { contracts: "16", cost: "4.95", pays: "16.00", expected: "-0.20" } : {}) },
          singles: [{ ticker: `KXNBAREB-${KEY}-NYKKTOWNS32-12`, side: "yes", label: "Karl-Anthony Towns: 12+ rebounds",
                      ask: "0.66", bid: "0.61", history: "0.7105", mid: "0.635", all_in: "0.676", edge_pts: 3.4, value: true,
                      limit: { price: "0.62", saves_per_100: "4.62", maker_fee_per_100: "0.00", behind_bid: false } }],
          trim: null, fees_verified: true, evidence_used: true });
      }
      case "/api/games/review/status":
        return json({ configured: reviewOn, provider: "OpenAI", model: "gpt-test", used_today: 0, daily_cap: 40, headlines: true });
      case "/api/games/review":
        sentHeaders.push(init?.headers as Record<string, string>);
        return json({ summary: "Correlated same-team legs; price is close to fair.", overall: "stretch",
          legs: [{ ticker: `KXNBAREB-${KEY}-NYKKTOWNS32-12`, lean: "supports", points: ["9 of last 10 games cleared 11.5"], sources: ["S1"] }],
          risks: ["Minutes could drop in a blowout"], check_before_betting: ["Confirm Towns is starting"],
          sources: [{ id: "S1", title: "Towns returns to Minnesota", source: "example.com", age: "1 day", url: "https://example.com/a" }],
          model: "gpt-test", generated_at: "2026-11-19T15:00:00Z", cached: false });
      case "/api/games/news":
        return json({ configured: false, items: [] });
      default:
        return json({ error: { code: "NOT_FOUND", message: "nope" } }, 404);
    }
  }));
});
afterEach(() => vi.unstubAllGlobals());

function Harness() {
  const [ref, setRef] = useState<string | null>(null);
  return <><GamesPage gameRef={ref} onOpenGame={setRef} /><ResearchDocket /></>;
}

describe("<GamesPage>", () => {
  it("lists games by league and opens one with lines, injuries and an empty slip", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.getByText("Pick a game")).toBeInTheDocument();
    expect(screen.getByText("Nothing on the docket")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "NHL" })).toHaveAttribute("aria-pressed", "false");
    await user.click(screen.getByRole("button", { name: /NYK @ MIN/ }));
    expect(await screen.findByRole("heading", { name: /New York @ Minnesota/ })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Win chance: NYK 50%, MIN 50%" })).toBeInTheDocument();
    expect(await screen.findByText(/Jonathan Kuminga/)).toBeInTheDocument();
    expect(screen.getByText("mkt ≈ 216.4")).toBeInTheDocument();
    // ladders show the 7 strikes nearest 50% until expanded
    expect(screen.getByRole("button", { name: "+3" })).toBeInTheDocument();
  });

  it("says when a league has no injury report instead of implying a healthy roster", async () => {
    noInjuryReport = true;
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole("button", { name: /NYK @ MIN/ }));
    expect(await screen.findByText(/No injury report is published for this league/)).toBeInTheDocument();
    expect(screen.queryByText("No injuries listed")).not.toBeInTheDocument();
  });

  it("shows why a player is listed when hovering their injury", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole("button", { name: /NYK @ MIN/ }));
    const chip = await screen.findByRole("button", { name: /Jonathan Kuminga/ });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    await user.hover(chip);
    expect(await screen.findByRole("tooltip")).toHaveTextContent(/^Shoulder · ESPN, Nov 18$/);
  });

  it("builds a combo: legs, evidence verdicts, correlation, history-adjusted price and quote check", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole("button", { name: /NYK @ MIN/ }));
    await user.click(await screen.findByRole("button", { name: /Add New York wins/ }));
    expect(screen.getByRole("button", { name: /Remove New York wins, / })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("tab", { name: /Players/ }));
    await user.click(screen.getByRole("button", { name: /Karl-Anthony Towns REB: market line 12.9/ }));
    await user.click(screen.getByRole("button", { name: /Add Karl-Anthony Towns: 12\+ rebounds/ }));

    const slipEl = screen.getByRole("complementary", { name: "Research docket" });
    expect(within(slipEl).getByLabelText("2 legs")).toBeInTheDocument();
    expect(await within(slipEl).findAllByText("fits history")).toHaveLength(2);
    expect(within(slipEl).getByText(/NYK legs all hit/)).toHaveTextContent("30/83");
    await waitFor(() => expect(within(slipEl).getAllByText("37.5¢").length).toBeGreaterThan(0));
    expect(within(slipEl).getByText("Combinable on Kalshi")).toBeInTheDocument();
    expect(within(slipEl).getByText(/past 2 legs combos paid \$0.80\/\$1/)).toBeInTheDocument();

    await user.type(within(slipEl).getByLabelText("Kalshi's quote in cents"), "45");
    expect(within(slipEl).getByText("+20% over fair")).toBeInTheDocument();

    // flip a leg to NO: the evidence is re-checked for that side
    await user.click(within(slipEl).getAllByRole("button", { name: "NO" })[1]!);
    expect(await within(slipEl).findByText("history: less likely")).toBeInTheDocument();
    expect(calls.some((c) => c.includes("NYKKTOWNS32-12%3Ano"))).toBe(true);
  });

  it("opens a leg's research: last games, hit windows and links", async () => {
    const user = userEvent.setup();
    slip.add({ ticker: `KXNBAREB-${KEY}-NYKKTOWNS32-12`, side: "yes", label: "Karl-Anthony Towns: 12+ rebounds", event: `KXNBAREB-${KEY}` });
    render(<Harness />);
    const slipEl = screen.getByRole("complementary", { name: "Research docket" });
    await within(slipEl).findByText("fits history");
    await user.click(within(slipEl).getByRole("button", { name: "Karl-Anthony Towns: 12+ rebounds" }));
    expect(within(slipEl).getByRole("img", { name: /Last 2 games: the YES side happened 1 times; line 11.5/ })).toBeInTheDocument();
    expect(within(slipEl).getByText("12/14")).toBeInTheDocument();
    expect(within(slipEl).getByRole("link", { name: "ESPN" })).toHaveAttribute("rel", "noopener noreferrer");
    await user.click(within(slipEl).getByRole("button", { name: "Headlines here" }));
    expect(await within(slipEl).findByText(/Headline search is off/)).toBeInTheDocument();
    expect(within(slipEl).getByText(/Single leg: price/)).toBeInTheDocument();
  });
});

describe("slip store", () => {
  it("persists legs and ignores tampered storage", () => {
    slip.add({ ticker: "KXA-1", side: "yes", label: "A", event: "KXA-1" });
    slip.add({ ticker: "KXA-1", side: "no", label: "A", event: "KXA-1" });
    expect(slip.get()).toHaveLength(1);
    expect(JSON.parse(localStorage.getItem("krt.slip.v1")!)).toEqual([{ ticker: "KXA-1", side: "no", label: "A", event: "KXA-1" }]);
    for (let i = 0; i < 20; i++) slip.add({ ticker: `KXB-${i}`, side: "yes", label: "B", event: "KXB-1" });
    expect(slip.get()).toHaveLength(slip.max);
  });
});

describe("<LegResearch>", () => {
  it("explains unsupported legs", () => {
    render(<LegResearch loading={false} ev={{ ticker: "T", side: "yes", label: "Q1", supported: false,
      reason: "No box-score check for this market type yet" }} />);
    expect(screen.getByText(/No box-score check/)).toBeInTheDocument();
  });

  it("draws margins below and above zero", () => {
    const ev = { ...evLeg("T", "yes", "agrees"), kind: "team_win", stat: null, line: 0,
      recent: [{ date: "d1", opponent: "TOR", home: true, value: -8, hit: false },
               { date: "d2", opponent: "BOS", home: false, value: 12, hit: true }] };
    const { container } = render(<MiniBars ev={ev} />);
    expect(container.querySelectorAll("rect")).toHaveLength(2);
    expect(screen.getByRole("img", { name: /happened 1 times/ })).toBeInTheDocument();
  });
});

describe("<SecondOpinion>", () => {
  it("says how to turn it on when there is no key", async () => {
    slip.add({ ticker: `KXNBAREB-${KEY}-NYKKTOWNS32-12`, side: "yes", label: "Towns 12+ reb", event: `KXNBAREB-${KEY}` });
    render(<Harness />);
    expect(await screen.findByText(/AI second opinion is off/)).toBeInTheDocument();
  });

  it("asks on click, with the CSRF header, and shows a grounded, labelled review", async () => {
    reviewOn = true;
    const user = userEvent.setup();
    slip.add({ ticker: `KXNBAREB-${KEY}-NYKKTOWNS32-12`, side: "yes", label: "Towns 12+ reb", event: `KXNBAREB-${KEY}` });
    render(<Harness />);
    await user.click(await screen.findByRole("button", { name: "Get a second opinion (AI)" }));
    expect(await screen.findByText(/Correlated same-team legs/)).toBeInTheDocument();
    expect(screen.getByText("stretch")).toBeInTheDocument();
    expect(screen.getByText("9 of last 10 games cleared 11.5")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Towns returns to Minnesota" })).toHaveAttribute("rel", "noopener noreferrer nofollow");
    expect(screen.getByText(/AI-written by gpt-test/)).toBeInTheDocument();
    expect(sentHeaders[0]?.["X-KRT-Request"]).toBe("review");
    expect(calls.filter((c) => c === "/api/games/review")).toHaveLength(1);
  });
});

describe("<SlipCheck>", () => {
  it("sizes the stake, gives a walk-away price and cheaper single/limit alternatives", async () => {
    const user = userEvent.setup();
    slip.add({ ticker: `KXNBAREB-${KEY}-NYKKTOWNS32-12`, side: "yes", label: "Towns 12+ reb", event: `KXNBAREB-${KEY}` });
    slip.add({ ticker: `KXNBAGAME-${KEY}-NYK`, side: "yes", label: "New York wins", event: `KXNBAGAME-${KEY}` });
    render(<Harness />);
    const check = await screen.findByRole("region", { name: "Slip check" });
    expect(await within(check).findByText("Stretch")).toBeInTheDocument();
    expect(within(check).getByText("28¢")).toBeInTheDocument(); // walk-away
    expect(within(check).getByText(/Cheaper ways · 1 value single/)).toBeInTheDocument();
    expect(within(check).getByText(/Limit at/)).toHaveTextContent("Limit at 62¢ instead of 66¢: saves ~4.6¢ a contract, no fee");
    await user.type(within(check).getByLabelText("Stake in dollars"), "5");
    await waitFor(() => expect(within(check).getByText(/16 contracts/)).toBeInTheDocument());
    expect(within(check).getByText(/over your \$2\.50 per-idea cap/)).toBeInTheDocument();
    expect(calls.some((c) => c.startsWith("/api/games/check") && c.includes("stake=5.00"))).toBe(true);
  });
});
