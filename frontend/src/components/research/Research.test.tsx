import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../../App";
import { href, parseHash } from "../../router";
import { saved } from "../docket/saved";
import { slip } from "../games/slip";

const iso = (min: number) => new Date(Date.now() + min * 60_000).toISOString();
const health = { status: "ok", version: "0.1.0", env: "local", trading_mode: "paper", live_execution_enabled: false,
  market_data_source: "fixture", kalshi_env: "production", database: "ok", server_time: iso(0), credentials_configured: {} };

const card = (over: Record<string, unknown> = {}) => ({
  id: "o1", detected_at: iso(-10), expires_at: iso(50), status: "OPEN", kind: "LADDER", guaranteed: false,
  confirmed: true, event_ticker: "KXGOV-VT", title: "Vermont governor ladder", quantity: "2", cost: "1.84",
  fees: "0.04", min_payoff: "2.00", profit: "0.16", return_pct: "8.7", claim: "Exactly one of these wins.",
  checklist: ["Read the tie-break rule"], budget_cap: "2.50", fee_schedule_version: "kalshi-2026-02",
  journal: [], legs: [
    { ticker: "KXGOV-VT-A", title: "Scott", side: "YES", limit_price: "0.45", quantity: "2", cost: "0.92", fee: "0.02", available: "40" },
    { ticker: "KXGOV-VT-B", title: "Field", side: "NO", limit_price: "0.45", quantity: "2", cost: "0.92", fee: "0.02", available: "12" },
  ], ...over });

const signal = (over: Record<string, unknown> = {}) => ({
  id: "s1", created_at: iso(-5), expires_at: iso(-1), validity: "EXPIRED", market_id: "m1",
  market_ticker: "KXCPI-26DEC-T3.0", market_title: "CPI above 3.0%?", market_event_ticker: "KXCPI-26DEC",
  rules_source_url: "https://kalshi.com/rules", decision: "CANDIDATE_NO", side: "no", quantity: "10",
  p_yes: 0.3, p_lower: 0.25, p_upper: 0.36, entry: "0.55", fee: "0.02", slippage: "0.01", ev: "0.12",
  lower_edge: "0.06", reasons: ["Model below market"], caveats: ["Thin book"], quote_id: "q1",
  quote_observed_at: iso(-5), model_run_id: "r1", model: "cpi_v1", contract_key: "CPI>3.0", mapping_id: "mp1",
  mapping_status: "confirmed", fee_schedule_version: "kalshi-2026-02", details: {}, ...over });

let routes: Record<string, () => Response>;
const json = (b: unknown, status = 200) => () => new Response(JSON.stringify(b), { status });

beforeEach(() => {
  slip.clear();
  localStorage.clear();
  saved.reload();
  routes = {
    "/api/health": json(health),
    "/api/catalog/status": json({ refreshed_at: iso(-2), events: 1, markets: 1, series: 1 }),
    "/api/opportunities/o1": json(card()),
    "/api/signals/s1": json(signal()),
    "/api/opportunities": json([card(), card({ id: "o2", event_ticker: "OTHER", title: "Elsewhere" })]),
    "/api/signals": json([signal({ market_event_ticker: "KXGOV-VT", id: "s2", market_title: "Scott above 50%?" }), signal()]),
    "/api/history/open": json({ positions: [{ ticker: "KXGOV-VT-A", title: "Will Scott win?", event_ticker: "KXGOV-VT",
      side: "yes", contracts: "3", avg_cost: "0.40", mid: "0.46", unrealized: "0.18" }],
      portfolio: {}, correlation: [], evidence_enabled: false, evidence_error: null, as_of: iso(0) }),
  };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), "http://127.0.0.1").pathname;
    return (routes[path] ?? json({ error: { code: "NOT_FOUND", message: "nope" } }, 404))();
  }));
});
afterEach(() => { vi.unstubAllGlobals(); window.location.hash = ""; });

describe("research routes", () => {
  it("parse, validate and round-trip", () => {
    expect(parseHash("#/research/opp/o1").research).toEqual({ kind: "opp", id: "o1" });
    expect(parseHash("#/research/event/KXGOV-VT").research).toEqual({ kind: "event", id: "KXGOV-VT" });
    expect(parseHash("#/research/sig/<script>").page).toBe("today");
    expect(parseHash("#/research/nope/x").page).toBe("today");
    expect(parseHash(href.research("event", "KX.A_B-1")).research?.id).toBe("KX.A_B-1");
    expect(href.research("opp", "../../x")).toBe("#/");
  });
});

describe("scanner idea workspace (deep link)", () => {
  it("shows the decision summary, keeps risks visible and the audit layer collapsed", async () => {
    window.location.hash = "#/research/opp/o1";
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Vermont governor ladder", level: 2 })).toBeInTheDocument();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Today" })).toHaveAttribute("href", "#/");
    const l1 = screen.getByRole("region", { name: "Decision summary" });
    expect(l1).toHaveTextContent("Total cost (incl. fees)$1.84");
    expect(l1).toHaveTextContent("Profit if rules hold$0.16");
    expect(l1).toHaveTextContent("up to −$1.84");
    const before = within(l1).getByRole("region", { name: "Before acting" });
    expect(before).toHaveTextContent("Read the tie-break rule");
    expect(before).toHaveTextContent("You can lose the full cost");
    // Layer 2: every leg with its fee, and the fee schedule version
    const table = screen.getByRole("table", { name: "Legs of this idea" });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("KXGOV-VT-B")).toBeInTheDocument();
    expect(screen.getAllByText("kalshi-2026-02").length).toBeGreaterThan(0);
    // Layer 3 starts closed
    expect(screen.getByText("Audit details").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByRole("link", { name: "Research the whole event" })).toHaveAttribute("href", "#/research/event/KXGOV-VT");
    expect(screen.getByRole("complementary", { name: "Research docket" })).toBeInTheDocument();
  });

  it("flags an expired idea as stale", async () => {
    routes["/api/opportunities/o1"] = json(card({ status: "EXPIRED", expires_at: iso(-30) }));
    window.location.hash = "#/research/opp/o1";
    render(<App />);
    expect(await screen.findByText(/This idea has expired/)).toBeInTheDocument();
  });

  it("says when an id no longer exists, and retries on errors", async () => {
    window.location.hash = "#/research/opp/gone";
    const { unmount } = render(<App />);
    expect(await screen.findByRole("heading", { name: "Not found" })).toBeInTheDocument();
    unmount();
    routes["/api/opportunities/o1"] = json({ error: { code: "SOURCE_FAILURE", message: "db busy" } }, 503);
    window.location.hash = "#/research/opp/o1";
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("db busy");
    routes["/api/opportunities/o1"] = json(card());
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "Vermont governor ladder" })).toBeInTheDocument();
  });
});

describe("signal workspace", () => {
  it("shows model vs all-in market cost for the chosen side, and the staleness", async () => {
    window.location.hash = "#/research/sig/s1";
    render(<App />);
    expect(await screen.findByRole("heading", { name: "CPI above 3.0%?", level: 2 })).toBeInTheDocument();
    expect(screen.getByText(/Expired: the quote behind this signal/)).toBeInTheDocument();
    const l1 = screen.getByRole("region", { name: "Decision summary" });
    expect(l1).toHaveTextContent("Model chance of NO70.0%");          // 1 − 0.30 for the NO side
    expect(l1).toHaveTextContent("band 64.0%–75.0%");
    expect(l1).toHaveTextContent("all-in cost per contract58.0¢");     // 55 + 2 + 1
    expect(l1).toHaveTextContent("entry 55.0¢ + fee 2.0¢ + slippage 1.0¢");
    expect(within(l1).getByRole("region", { name: "Where the model may be wrong" })).toHaveTextContent("Thin book");
    expect(screen.getByRole("button", { name: "Trace lineage" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Research the whole event" })).toHaveAttribute("href", "#/research/event/KXCPI-26DEC");
  });
});

describe("abstained signal", () => {
  it("says the model abstained instead of showing empty numbers", async () => {
    routes["/api/signals/s1"] = json(signal({ decision: "ABSTAIN", side: null, p_yes: null, entry: null, ev: null,
      lower_edge: null, reasons: ["MODEL_ABSTAINED"] }));
    window.location.hash = "#/research/sig/s1";
    render(<App />);
    const l1 = await screen.findByRole("region", { name: "Decision summary" });
    expect(l1).toHaveTextContent("The model abstained");
    expect(l1).toHaveTextContent("Why: model abstained.");
    expect(within(l1).queryByText("Expected value per contract")).not.toBeInTheDocument();
  });
});

describe("event workspace", () => {
  it("links your positions, scanner ideas, signals and saved research for the event", async () => {
    saved.add({ decision: "watch", note: "", fair: 0.4,
      legs: [{ ticker: "KXGOV-VT-A", side: "yes", label: "Scott wins", event: "KXGOV-VT" }] });
    window.location.hash = "#/research/event/KXGOV-VT";
    render(<App />);
    const l1 = await screen.findByRole("region", { name: "What you already have here" });
    expect(await within(l1).findByText("Will Scott win?")).toBeInTheDocument();
    expect(await within(l1).findByRole("link", { name: "Vermont governor ladder" })).toHaveAttribute("href", "#/research/opp/o1");
    expect(within(l1).queryByText("Elsewhere")).not.toBeInTheDocument();
    expect(await within(l1).findByRole("link", { name: "Scott above 50%?" })).toHaveAttribute("href", "#/research/sig/s2");
    expect(within(l1).queryByText("CPI above 3.0%?")).not.toBeInTheDocument();
    expect(within(l1).getByText("Scott wins")).toBeInTheDocument();
  });
});

describe("copy link", () => {
  it("copies the page address", async () => {
    const user = userEvent.setup(); // installs a clipboard stub
    window.location.hash = "#/research/opp/o1";
    render(<App />);
    await screen.findByRole("heading", { name: "Vermont governor ladder" });
    await user.click(screen.getByRole("button", { name: "Copy link" }));
    await waitFor(() => expect(screen.getByText("Link copied.")).toBeInTheDocument());
    expect(await navigator.clipboard.readText()).toContain("#/research/opp/o1");
  });
});
