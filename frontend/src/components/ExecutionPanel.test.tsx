import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { ExecutionIntent, ExecutionStatus } from "../api/types";
import { ExecutionPanel } from "./ExecutionPanel";

const baseStatus: ExecutionStatus = {
  execution_enabled: false, env: "mock", production: "not implemented (disabled in code)",
  kill_switch_engaged: true, pin_configured: false, demo_credentials_configured: false,
  caps: { max_contracts_per_order: 10, max_cost_per_order: "25", max_daily_cost: "100" },
};

const intent: ExecutionIntent = {
  id: "i1", created_at: "2026-11-18T23:00:00Z",
  expires_at: new Date(Date.now() + 60_000).toISOString(), env: "mock",
  market_ticker: "KXCPI-26NOV-T0.2", side: "YES", quantity: "5", limit_price: "0.46",
  approved_ask: "0.45", est_fee: "0.09", max_cost: "2.39",
  fee_schedule_version: "kalshi-fee-schedule-2026-07-07", status: "PROPOSED", block_reason: null,
  summary: "BUY 5 YES KXCPI-26NOV-T0.2 at limit $0.46 (max cost $2.39 incl. est. fee $0.09) [MOCK]",
  payload: { ticker: "KXCPI-26NOV-T0.2", side: "bid", count: "5.00", price: "0.4600",
             time_in_force: "immediate_or_cancel" },
  payload_hash: "a".repeat(64), exchange_order: null, events: [],
};

let status = baseStatus;
const posts: { path: string; headers: Record<string, string>; body: Record<string, unknown> }[] = [];
let approveResponse: ExecutionIntent = { ...intent, status: "BLOCKED", block_reason: "PRICE_CHANGED" };

beforeEach(() => {
  posts.length = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), "http://127.0.0.1").pathname;
    if (init?.method === "POST") {
      posts.push({ path, headers: init.headers as Record<string, string>,
                   body: JSON.parse(String(init.body)) });
      const body = path.endsWith("/approve") ? approveResponse
        : path === "/api/execution/kill-switch" ? { kill_switch_engaged: true } : intent;
      return new Response(JSON.stringify(body), { status: path.endsWith("/intents") ? 201 : 200 });
    }
    const body = path === "/api/execution/status" ? status
      : path === "/api/execution/intents" ? []
        : path === "/api/markets" ? { items: [{ id: "m1", external_ticker: "KXCPI-26NOV-T0.2" }] }
          : null;
    return new Response(JSON.stringify(body ?? {}), { status: body ? 200 : 404 });
  }));
});
afterEach(() => {
  vi.unstubAllGlobals();
  status = baseStatus;
});

describe("<ExecutionPanel>", () => {
  it("is disabled by default and explains how to enable mock execution", async () => {
    render(<ExecutionPanel />);
    expect(await screen.findByText(/Disabled \(the default\)/)).toBeInTheDocument();
    expect(screen.getByText(/not implemented \(disabled in code\)/)).toBeInTheDocument();
    expect(screen.getByText("ENGAGED")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Propose/ })).toBeNull();
  });

  it("proposes, shows the exact payload, and approves with hash + PIN + CSRF header", async () => {
    status = { ...baseStatus, execution_enabled: true, kill_switch_engaged: false, pin_configured: true };
    const user = userEvent.setup();
    render(<ExecutionPanel />);
    await screen.findByRole("option", { name: "KXCPI-26NOV-T0.2" });
    await user.click(screen.getByRole("button", { name: "Propose (no order yet)" }));
    expect(await screen.findByText(intent.summary)).toBeInTheDocument();
    expect(posts[0]!.headers["X-KRT-Request"]).toBe("execution");
    expect(screen.getByText(/"time_in_force": "immediate_or_cancel"/)).toBeInTheDocument();
    const approveBtn = screen.getByRole("button", { name: "Approve and send to MOCK" });
    expect(approveBtn).toBeDisabled(); // PIN required
    await user.type(screen.getByLabelText("Approval PIN"), "246813");
    await user.click(approveBtn);
    await waitFor(() => expect(posts.some((p) => p.path.endsWith("/approve"))).toBe(true));
    const ap = posts.find((p) => p.path.endsWith("/approve"))!;
    expect(ap.headers["X-KRT-Request"]).toBe("execution");
    expect(ap.body).toEqual({ payload_hash: "a".repeat(64), pin: "246813" });
    expect(await screen.findByText(/PRICE_CHANGED/)).toBeInTheDocument();
  });

  it("emergency stop engages the kill switch", async () => {
    const user = userEvent.setup();
    render(<ExecutionPanel />);
    await user.click(await screen.findByRole("button", { name: /Emergency stop/ }));
    await waitFor(() => expect(posts.map((p) => p.path)).toContain("/api/execution/kill-switch"));
  });

  it("explains unknown outcomes are looked up, not re-sent", async () => {
    status = { ...baseStatus, execution_enabled: true, kill_switch_engaged: false, pin_configured: true };
    approveResponse = { ...intent, status: "UNKNOWN", block_reason: "timeout" };
    const user = userEvent.setup();
    render(<ExecutionPanel />);
    await screen.findByRole("option", { name: "KXCPI-26NOV-T0.2" });
    await user.click(screen.getByRole("button", { name: "Propose (no order yet)" }));
    await user.type(await screen.findByLabelText("Approval PIN"), "246813");
    await user.click(screen.getByRole("button", { name: "Approve and send to MOCK" }));
    expect(await screen.findByRole("status")).toHaveTextContent(/UNKNOWN.*looked up, never re-sent/);
  });
});
