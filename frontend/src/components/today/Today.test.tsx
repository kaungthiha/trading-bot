import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TodayPage } from "./TodayPage";
import { loadTriage, TRIAGE_KEY } from "./triage";

const iso = (minutesFromNow: number) => new Date(Date.now() + minutesFromNow * 60_000).toISOString();

const position = (over: Record<string, unknown>) => ({
  ticker: "KXA-1", title: "Will A happen?", event_ticker: "KXA", event_title: "A", type: "binary",
  side: "yes", contracts: "4", avg_cost: "0.40", cost: "1.60", mid: "0.30", value: "1.20",
  unrealized: "-0.40", move_pts: -10, max_payout: "4.00", close_at: iso(60 * 72), hours_to_close: 72,
  game: null, evidence: null, evidence_note: null, trail: [], combo: null, flags: [], ...over,
});

let routes: Record<string, unknown>;
let failing: Set<string>;

function stubFetch() {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), "http://127.0.0.1").pathname;
    if (failing.has(path)) {
      return new Response(JSON.stringify({ error: { code: "SOURCE_FAILURE", message: "down for a bit" } }), { status: 502 });
    }
    const body = routes[path];
    return body !== undefined ? new Response(JSON.stringify(body), { status: 200 })
      : new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: "nope" } }), { status: 404 });
  }));
}

beforeEach(() => {
  localStorage.clear();
  failing = new Set();
  routes = {
    "/api/history/open": {
      positions: [
        position({ ticker: "KXWARN-1", title: "Warned position", flags: [{ level: "warn", text: "Down 10 pts since entry" }] }),
        position({ ticker: "KXSOON-1", title: "Closing soon", hours_to_close: 5, close_at: iso(300), unrealized: "0.20",
          game: { prefix: "KXNBA", game_key: "26NOV19GSWMEM" } }),
        position({ ticker: "KXFINE-1", title: "Fine position" }),
      ],
      portfolio: {}, correlation: [], evidence_enabled: true, evidence_error: null, as_of: iso(-2),
    },
    "/api/opportunities": [
      { id: "o1", detected_at: iso(-10), expires_at: iso(50), status: "OPEN", kind: "LADDER", guaranteed: true,
        confirmed: true, event_ticker: "KXLAD", title: "Ladder gap", legs: [], quantity: "1", cost: "0.90",
        fees: "0.02", min_payoff: "1.00", profit: "0.08", return_pct: "8.9", claim: "", checklist: [],
        budget_cap: null, fee_schedule_version: "v1", journal: [] },
      { id: "o2", detected_at: iso(-500), expires_at: iso(-400), status: "EXPIRED", kind: "LADDER", guaranteed: false,
        confirmed: false, event_ticker: "KXOLD", title: "Old idea", legs: [], quantity: "1", cost: "1", fees: "0",
        min_payoff: "1", profit: "0", return_pct: "0", claim: "", checklist: [], budget_cap: null,
        fee_schedule_version: "v1", journal: [] },
    ],
    "/api/scanner/status": { interval_seconds: 300, last_scan: { at: iso(-5), events: 1, markets: 1, candidates: 1,
      confirmed: 1, new_cards: 1 }, budget: null, available: null, caps: { guaranteed: "10", conditional: "2.5" },
      paused: false, note: null },
    "/api/signals": [
      { id: "s1", validity: "VALID", decision: "CANDIDATE_YES", market_title: "CPI above 3%?", side: "yes",
        model: "cpi_v1", lower_edge: "0.021", quote_observed_at: iso(-3), expires_at: iso(30) },
      { id: "s2", validity: "VALID", decision: "ABSTAIN", market_title: "Abstained", side: null, model: "cpi_v1",
        lower_edge: null, quote_observed_at: iso(-3), expires_at: iso(30) },
    ],
    "/api/games": { leagues: [], items: [
      { game_key: "26NOV19GSWMEM", league: "NBA", prefix: "KXNBA", title: "Golden State @ Memphis", sub_title: "",
        occurs_at: iso(120), close_at: iso(300), teams: [], events: 10, markets: 1175, volume_24h: 52000 },
      { game_key: "26NOV25LALBOS", league: "NBA", prefix: "KXNBA", title: "Far away game", sub_title: "",
        occurs_at: iso(60 * 24 * 6), close_at: null, teams: [], events: 1, markets: 10, volume_24h: 0 },
    ] },
  };
  stubFetch();
});
afterEach(() => vi.unstubAllGlobals());

const section = async (name: string) => screen.findByRole("region", { name });

describe("<TodayPage>", () => {
  it("shows each source in its own group with its own measure, filtering what isn't actionable", async () => {
    render(<TodayPage />);
    const pos = await section("Your open positions");
    expect(await within(pos).findByText("Warned position")).toBeInTheDocument();
    expect(within(pos).getByText("Closing soon")).toBeInTheDocument();
    expect(within(pos).queryByText("Fine position")).not.toBeInTheDocument();
    expect(within(pos).getByText("1 other open position look on track.")).toBeInTheDocument();
    expect(within(pos).getByRole("link", { name: "Open game" })).toHaveAttribute("href", "#/games?game=KXNBA-26NOV19GSWMEM");
    expect(within(pos).getAllByText("Paid → now (mid)")).toHaveLength(2);

    const scan = await section("Scanner ideas");
    expect(await within(scan).findByText("Ladder gap")).toBeInTheDocument();
    expect(within(scan).queryByText("Old idea")).not.toBeInTheDocument();
    expect(within(scan).getByText("Guaranteed if rules hold")).toBeInTheDocument();
    expect(within(scan).getByText("Scanner profit after fees")).toBeInTheDocument();
    expect(within(scan).getByRole("link", { name: "Research" })).toHaveAttribute("href", "#/research/opp/o1");

    const sig = await section("Model signals");
    expect(await within(sig).findByText("+2.1¢ per contract")).toBeInTheDocument();
    expect(within(sig).queryByText("Abstained")).not.toBeInTheDocument();

    const games = await section("Games starting soon");
    expect(await within(games).findByText("Golden State @ Memphis")).toBeInTheDocument();
    expect(within(games).queryByText("Far away game")).not.toBeInTheDocument();
    expect(within(games).getByText("Not screened yet")).toBeInTheDocument();

    expect(within(screen.getByRole("group", { name: "Show" })).getByRole("button", { name: /To review/ })).toHaveTextContent("5");
  });

  it("marks items researching or passed, saves notes locally, and filters by mark", async () => {
    const user = userEvent.setup();
    render(<TodayPage />);
    const scan = await section("Scanner ideas");
    await within(scan).findByText("Ladder gap");
    await user.click(within(scan).getByRole("button", { name: "Pass" }));
    expect(within(scan).queryByText("Ladder gap")).not.toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Show" })).getByRole("button", { name: /Passed/ })).toHaveTextContent("1");
    expect(loadTriage()["opp:o1"]?.status).toBe("passed");

    await user.click(within(screen.getByRole("group", { name: "Show" })).getByRole("button", { name: /Passed/ }));
    expect(within(scan).getByText("Ladder gap")).toBeInTheDocument();
    await user.click(within(scan).getByRole("button", { name: "Note" }));
    await user.type(within(scan).getByRole("textbox", { name: /Note on Ladder gap/ }), "Rules unclear{Enter}");
    expect(within(scan).getByText("Note: Rules unclear")).toBeInTheDocument();
    expect(loadTriage()["opp:o1"]).toMatchObject({ status: "passed", note: "Rules unclear" });

    await user.click(within(scan).getByRole("button", { name: "Pass" })); // un-pass
    await user.click(within(screen.getByRole("group", { name: "Show" })).getByRole("button", { name: /To review/ }));
    expect(within(scan).getByText("Ladder gap")).toBeInTheDocument();
  });

  it("isolates a failing source and offers a retry", async () => {
    failing.add("/api/signals");
    const user = userEvent.setup();
    render(<TodayPage />);
    const sig = await section("Model signals");
    expect(await within(sig).findByRole("alert")).toHaveTextContent("down for a bit");
    expect(await within(await section("Scanner ideas")).findByText("Ladder gap")).toBeInTheDocument();
    failing.delete("/api/signals");
    await user.click(within(sig).getByRole("button", { name: "Retry" }));
    expect(await within(sig).findByText("CPI above 3%?")).toBeInTheDocument();
  });
});

describe("triage storage", () => {
  it("drops tampered, malformed and expired entries", () => {
    localStorage.setItem(TRIAGE_KEY, JSON.stringify({
      "opp:ok": { status: "passed", note: "x".repeat(999), at: new Date().toISOString() },
      "evil:<img>": { status: "passed", note: "", at: new Date().toISOString() },
      "sig:weird": { status: "deleted", note: 5, at: new Date().toISOString() },
      "game:old": { status: "passed", note: "", at: "2020-01-01T00:00:00Z" },
    }));
    const t = loadTriage();
    expect(Object.keys(t)).toEqual(["opp:ok"]);
    expect(t["opp:ok"]!.note).toHaveLength(280);
    localStorage.setItem(TRIAGE_KEY, "not json");
    expect(loadTriage()).toEqual({});
  });
});
