import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../../App";
import { slip } from "../games/slip";
import { ResearchDocket } from "./ResearchDocket";
import { SAVED_KEY, saved } from "./saved";

const A = { ticker: "KXNBAGAME-26NOV19NYKMIN-NYK", side: "yes" as const, label: "New York wins", event: "KXNBAGAME-26NOV19NYKMIN" };
const B = { ticker: "KXNBAREB-26NOV19NYKMIN-KAT-12", side: "yes" as const, label: "Towns 12+ rebounds", event: "KXNBAREB-26NOV19NYKMIN" };
const C = { ticker: "KXNBAPTS-26NOV19NYKMIN-BRU-25", side: "yes" as const, label: "Brunson 25+ points", event: "KXNBAPTS-26NOV19NYKMIN" };

const health = { status: "ok", version: "0.1.0", env: "local", trading_mode: "paper", live_execution_enabled: false,
  market_data_source: "fixture", kalshi_env: "production", database: "ok", server_time: "2026-11-19T15:00:00Z",
  credentials_configured: {} };

/** Combo price depends on the legs requested; per-request delays let a test reorder replies. */
let comboDelay: (legs: string) => number;
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });

function comboFor(legsParam: string) {
  const legs = legsParam.split(",").map((p) => p.split(":") as [string, string]);
  const prob = 0.5;
  return { legs: legs.map(([t, s]) => ({ ticker: t, label: t, side: s, event: "E", probability: prob, quality: "mid" })),
    independent_probability: prob ** legs.length, fair_price: prob ** legs.length, fair_multiple: 1 / prob ** legs.length,
    warnings: [], kalshi: { eligible: legs.length < 3, collections: ["X"], ineligible_events: legs.length < 3 ? [] : ["E3"], history: null } };
}

beforeEach(() => {
  slip.clear();
  localStorage.clear();
  saved.reload();
  comboDelay = () => 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const u = new URL(String(input), "http://127.0.0.1");
    const legs = u.searchParams.get("legs") ?? "";
    switch (u.pathname) {
      case "/api/health": return json(health);
      case "/api/catalog/status": return json({ refreshed_at: new Date().toISOString(), events: 1, markets: 1, series: 1 });
      case "/api/catalog/combo": {
        const d = comboDelay(legs);
        if (d) await new Promise((r) => setTimeout(r, d));
        return json(comboFor(legs));
      }
      case "/api/games/evidence":
        return json({ legs: legs.split(",").map((p) => {
          const [ticker, side] = p.split(":");
          return ticker === B.ticker
            ? { ticker, side, label: "Towns", supported: true, verdict: "agrees", estimate: 0.6, interval: [0.45, 0.72],
                windows: { last5: [3, 5], last10: [6, 10], season: [9, 14], last_season: [40, 70] },
                injury: { player: "Karl-Anthony Towns", status: "Questionable", detail: "Knee", date: "2026-11-19" } }
            : { ticker, side, label: "x", supported: false, reason: "Team markets are checked on the board" };
        }), correlation: [], independent_probability: null, adjusted_probability: null });
      default: return json({ error: { code: "NOT_FOUND", message: "nope" } }, 404);
    }
  }));
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.location.hash = "";
});

const docket = () => screen.getByRole("complementary", { name: "Research docket" });

function go(hash: string) {
  act(() => { window.location.hash = hash; window.dispatchEvent(new HashChangeEvent("hashchange")); });
}

describe("Research docket across pages", () => {
  it("follows you from Explore to Today and keeps its legs; hides on Journal", async () => {
    slip.add(A);
    slip.add(B);
    window.location.hash = "#/markets";
    render(<App />);
    expect(within(docket()).getByLabelText("2 legs")).toBeInTheDocument();
    go("#/");
    await screen.findByRole("heading", { name: "Today's desk" });
    expect(within(docket()).getByLabelText("2 legs")).toBeInTheDocument();
    expect(within(docket()).getByRole("button", { name: "New York wins" })).toBeInTheDocument();
    go("#/journal");
    await screen.findByRole("heading", { name: "My trades" });
    expect(screen.queryByRole("complementary", { name: "Research docket" })).not.toBeInTheDocument();
    go("#/games");
    expect(within(await screen.findByRole("complementary", { name: "Research docket" })).getByLabelText("2 legs")).toBeInTheDocument();
  });
});

describe("<ResearchDocket>", () => {
  it("never shows the previous legs' price while the new one is loading", async () => {
    // The 2-leg price arrives late; the 3-leg price arrives first. Only 12.5¢ may ever show.
    comboDelay = (legs) => (legs.split(",").length === 2 ? 120 : 0);
    slip.add(A);
    render(<ResearchDocket />);
    act(() => { slip.add(B); });
    act(() => { slip.add(C); });
    await waitFor(() => expect(within(docket()).getAllByText("12.5¢").length).toBeGreaterThan(0));
    await new Promise((r) => setTimeout(r, 200)); // let the stale 2-leg reply land
    expect(within(docket()).queryAllByText("25.0¢")).toHaveLength(0);
    expect(within(docket()).getAllByText("12.5¢").length).toBeGreaterThan(0);
  });

  it("states sides in words, labels evidence as frequency and lists what could be wrong", async () => {
    slip.add({ ...A, side: "no" });
    slip.add(B);
    slip.add(C);
    render(<ResearchDocket />);
    const must = within(docket()).getByRole("region", { name: "What would have to happen" });
    expect(must).toHaveTextContent("Doesn't happen New York wins");
    expect(must).toHaveTextContent("All 3 must go your way");
    const risks = within(docket()).getByRole("region", { name: "Where this may be wrong" });
    await waitFor(() => expect(risks).toHaveTextContent("Karl-Anthony Towns: Questionable"));
    expect(risks).toHaveTextContent("no box-score check");
    expect(risks).toHaveTextContent("Kalshi can't combine these legs");
    expect(risks).toHaveTextContent("ignores tonight's matchup");
    expect(within(docket()).getByText(/not a calibrated\s+probability/)).toBeInTheDocument();
    expect(within(docket()).getByText(/last 10: 6\/10 · season: 9\/14 · history estimate 60%/)).toBeInTheDocument();
    expect(within(docket()).getAllByText("Not: New York wins").length).toBeGreaterThan(0);
    expect(within(docket()).getByText(/Prices from the scan/)).toBeInTheDocument();
  });

  it("saves a decision locally, lists it, and loads it back", async () => {
    const user = userEvent.setup();
    slip.add(A);
    slip.add(B);
    render(<ResearchDocket />);
    await waitFor(() => expect(within(docket()).getAllByText("25.0¢").length).toBeGreaterThan(0));
    await user.type(within(docket()).getByLabelText(/Why you'd buy/), "Walk away above 20¢");
    await user.click(within(docket()).getByRole("button", { name: "Save to watch" }));
    expect(within(docket()).getByText(/Saved\. It's on Today/)).toBeInTheDocument();
    const stored = JSON.parse(localStorage.getItem(SAVED_KEY)!);
    expect(stored[0]).toMatchObject({ decision: "watch", note: "Walk away above 20¢", fair: 0.25 });
    expect(stored[0].legs).toHaveLength(2);

    act(() => { slip.clear(); });
    await user.click(within(docket()).getByText(/Saved research \(1\)/));
    await user.click(within(docket()).getByRole("button", { name: "Load into docket" }));
    expect(slip.get().map((l) => l.ticker)).toEqual([A.ticker, B.ticker]);
  });

  it("drops tampered saved research", () => {
    localStorage.setItem(SAVED_KEY, JSON.stringify([
      { id: "abc123", at: new Date().toISOString(), decision: "watch", note: "ok", fair: 0.3, legs: [A] },
      { id: "<x>", at: new Date().toISOString(), decision: "watch", note: "", fair: 0.3, legs: [A] },
      { id: "def456", at: new Date().toISOString(), decision: "buy", note: "", fair: 0.3, legs: [A] },
      { id: "ghi789", at: new Date().toISOString(), decision: "pass", note: "", fair: 7, legs: [{ ticker: "../x" }] },
    ]));
    saved.reload();
    expect(saved.get().map((d) => d.id)).toEqual(["abc123"]);
  });

  it("remembers collapsed, and the sheet closes on Escape", async () => {
    const user = userEvent.setup();
    slip.add(A);
    const { unmount } = render(<ResearchDocket />);
    await user.click(within(docket()).getByRole("button", { name: "Collapse the docket" }));
    expect(docket()).toHaveAttribute("data-collapsed", "true");
    unmount();
    render(<ResearchDocket />);
    expect(docket()).toHaveAttribute("data-collapsed", "true");
    const handle = within(docket()).getByRole("button", { name: /Docket 1 leg/ });
    await user.click(handle);
    expect(handle).toHaveAttribute("aria-expanded", "true");
    await user.keyboard("{Escape}");
    expect(handle).toHaveAttribute("aria-expanded", "false");
  });
});
