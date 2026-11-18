import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { Diagnostics, SetupStatus, SignalLineage } from "../api/types";
import { LineageView } from "./LineageView";
import { GettingStarted, HealthPanel } from "./OpsPanels";

const setup: SetupStatus = {
  paper_mode: true, complete: false,
  steps: [
    { key: "fred_key", title: "Add your FRED API key", status: "ok", hint: "x" },
    { key: "fees", title: "Verify the fee schedule", status: "warn", hint: "Edit fee_schedules.json" },
    { key: "mappings", title: "Confirm a mapping", status: "todo", hint: "confirm-mapping <TICKER> --yes" },
  ],
};

const diag: Diagnostics = {
  app_version: "0.1.0", schema_revision: "0006_paper", database_bytes: 2048 * 1024,
  server_time: "2026-11-18T23:00:00Z",
  safety: { trading_mode: "paper", live_execution_enabled: false }, config: {},
  ingestion: [{ adapter: "fred:CPIAUCSL", last_status: "success",
                last_started_at: "2026-11-18T22:00:00Z", last_success_at: "2026-11-18T22:00:02Z",
                recent_runs: 5, recent_failures: 1, top_error_codes: [["RATE_LIMITED", 2]] }],
  collection_gaps: 1, quotes: { markets_with_quotes: 20, stale: 20, fresh: 0 },
  evidence: [{ source_id: "fred:CPIAUCSL", records: 3364, latest_vintage: "2026-11-10",
               fresh: true, configured: true }],
  signals_24h: { count: 20, by_decision: { ABSTAIN: 20 }, top_reasons: [["FEE_SCHEDULE_UNVERIFIED", 20]] },
  paper_rejections: [],
};

const lineage: SignalLineage = {
  signal: { id: "s1", decision: "ABSTAIN", reasons: [] }, market: { ticker: "KXCPI-26NOV-T0.2" },
  quote: { id: "q1", observed_at: "2026-11-18T22:00:00Z", yes_bid: "0.4300", yes_ask_derived: "0.4500",
           ingestion_run: { id: "run12345678", adapter: "kalshi_public", status: "success" } },
  rules: { hash: "a".repeat(64), is_current: true },
  mapping: { status: "confirmed", actor: "user", reference_month: "2026-11-01", threshold: "0.2" },
  model_run: { model: "gaussian_trailing", version: "1.0.0", as_of: "2026-11-18T22:00:00Z", p_yes: 0.61 },
  evidence: [
    { id: "e1", observation_date: "2023-11-01", vintage_date: "2023-12-12", available_at: "x" },
    { id: "e2", observation_date: "2026-10-01", vintage_date: "2026-11-10", available_at: "y" },
  ],
  leakage_check: "pass", fee_schedule: { version: "v1", verified: false },
};

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), "http://127.0.0.1").pathname;
    const body = path === "/api/setup-status" ? setup : path === "/api/diagnostics" ? diag
      : path.startsWith("/api/lineage/signal/") ? lineage : null;
    return new Response(JSON.stringify(body ?? {}), { status: body ? 200 : 404 });
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("onboarding, health and lineage", () => {
  it("shows the setup checklist with next steps and remembers dismissal", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<GettingStarted />);
    expect(await screen.findByText(/1 of 3 setup steps done/)).toBeInTheDocument();
    expect(screen.getByText("confirm-mapping <TICKER> --yes")).toBeInTheDocument();
    expect(screen.getByText(/paper mode is enforced/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Hide" }));
    unmount();
    render(<GettingStarted />);
    expect(await screen.findByRole("button", { name: "Show getting-started checklist" })).toBeInTheDocument();
  });

  it("renders ingestion diagnostics including error codes and safety mode", async () => {
    render(<HealthPanel />);
    expect(await screen.findByText("RATE_LIMITED×2")).toBeInTheDocument();
    expect(screen.getByText(/schema 0006_paper/)).toBeInTheDocument();
    expect(screen.getByText(/0 fresh \/ 20 stale/)).toBeInTheDocument();
    expect(screen.getByText(/FEE_SCHEDULE_UNVERIFIED×20/)).toBeInTheDocument();
  });

  it("traces lineage on demand with the leakage check", async () => {
    const user = userEvent.setup();
    render(<LineageView signalId="s1" />);
    await user.click(screen.getByRole("button", { name: "Trace lineage" }));
    expect(await screen.findByText("pass")).toBeInTheDocument();
    expect(screen.getByText(/kalshi_public run run12345/)).toBeInTheDocument();
    expect(screen.getByText(/2 vintages/)).toBeInTheDocument();
    expect(screen.getByText(/confirmed by user/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hide lineage" })).toHaveAttribute("aria-expanded", "true");
  });
});
