import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type {
  CalibrationBin,
  PaperAccount,
  PaperOrder,
  PaperSettlement,
  ReplayReport,
} from "../api/types";
import { CalibrationChart } from "./CalibrationChart";
import { PaperPanel } from "./PaperPanel";

const account: PaperAccount = {
  as_of: "2026-11-18T23:00:00Z",
  cash: "982.25",
  deposits: "1000",
  open_value: "16.82",
  equity: "999.07",
  realized: "0.000000",
  unrealized: "-0.930000",
  fee_schedule_verified: false,
  notes: ["Fees use an UNVERIFIED schedule; P&L may be misstated."],
  positions: [{
    market_id: "m1", market_ticker: "KXCPI-26NOV-T0.0", side: "NO", open_qty: "20",
    avg_cost: "0.887500", realized: "0.000000", unrealized: "-0.930000", mark_value: "16.82",
    mark_note: null, settled: false, held: false,
  }],
};

const order: PaperOrder = {
  id: "o1", client_order_id: "ui-abc", submitted_at: "2026-11-18T23:00:00Z", market_id: "m1",
  market_ticker: "KXCPI-26NOV-T0.0", side: "NO", action: "BUY", quantity: "20",
  limit_price: "0.99", status: "PARTIAL", filled_quantity: "12", reject_reason: null,
  scenario: "conservative", simulation_version: "paper-sim-v1",
  fee_schedule_version: "kalshi-quadratic-candidate-2026-11", fee_schedule_verified: false,
  quote_id: "q1", signal_id: null, source: "manual", duplicate: false,
  fills: [{ quantity: "12", price: "0.88", displayed_price: "0.87", fee: "0.010000",
            filled_at: "2026-11-18T23:00:00Z", assumption_code: "IOC_DEPTH50_TICK1" }],
};

const settlement: PaperSettlement = {
  id: "st1", created_at: "2026-12-11T00:00:00Z", market_ticker: "KXCPI-26NOV-T0.3",
  exchange_status: "finalized", exchange_result: "no", evidence_check: "disagree",
  status: "HELD", notes: ["Exchange result contradicts our evidence: HELD for human review"],
};

const replay: ReplayReport = {
  as_of: "2026-11-18T23:00:00Z", scenario: "conservative", n_signals: 0, n_resolved: 0,
  total_cost: "0", realized_pnl: "0", unresolved_cost: "0", resolved_brier: null, trades: [],
  caveat: "Simulated replay of research signals under stated fill assumptions; not evidence of real-world returns.",
};

let posted: { headers: Record<string, string>; body: Record<string, unknown> } | null = null;

beforeEach(() => {
  posted = null;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://127.0.0.1").pathname;
      if (init?.method === "POST") {
        posted = {
          headers: init.headers as Record<string, string>,
          body: JSON.parse(String(init.body)),
        };
        return new Response(JSON.stringify(order), { status: 201 });
      }
      const body =
        path === "/api/paper/account" ? account
          : path === "/api/paper/orders" ? [order]
            : path === "/api/paper/settlements" ? [settlement]
              : path === "/api/paper/replay" ? replay
                : path === "/api/markets" ? {
                  items: [{ id: "m1", external_ticker: "KXCPI-26NOV-T0.0" }], limit: 200, offset: 0,
                }
                  : null;
      return new Response(JSON.stringify(body ?? {}), { status: body ? 200 : 404 });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("<PaperPanel>", () => {
  it("shows account tiles, positions, fills with displayed vs simulated price, HELD settlement", async () => {
    render(<PaperPanel />);
    expect(await screen.findByText("$999.07")).toBeInTheDocument();
    expect(screen.getByText(/UNVERIFIED schedule/)).toBeInTheDocument();
    expect(screen.getByText("12 @ 0.88 / 0.87")).toBeInTheDocument();
    expect(screen.getByText("PARTIAL 12/20", { exact: false })).toBeInTheDocument();
    const s = screen.getByText("KXCPI-26NOV-T0.3").closest("li")!;
    expect(s).toHaveTextContent(/: HELD · exchange no · evidence disagree/);
    expect(within(s).getByText(/HELD for human review/)).toBeInTheDocument();
    expect(screen.getByText(/Simulated trading only/)).toBeInTheDocument();
    expect(screen.getByText(/No resolved forecasts to plot yet/)).toBeInTheDocument();
  });

  it("submits a simulated order with the CSRF header, JSON body and an idempotency key", async () => {
    const user = userEvent.setup();
    render(<PaperPanel />);
    await screen.findByRole("option", { name: "KXCPI-26NOV-T0.0" });
    await user.selectOptions(screen.getByLabelText("Side"), "NO");
    const limit = screen.getByLabelText("Limit ($)");
    await user.clear(limit);
    await user.type(limit, "0.99");
    await user.click(screen.getByRole("button", { name: "Simulate order" }));
    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted!.headers["X-KRT-Request"]).toBe("paper");
    expect(posted!.headers["Content-Type"]).toBe("application/json");
    expect(posted!.body).toMatchObject({ market_id: "m1", side: "NO", action: "BUY",
                                         quantity: 10, limit_price: "0.99",
                                         scenario: "conservative" });
    expect(String(posted!.body.client_order_id)).toMatch(/^ui-[0-9a-f]{24}$/);
    expect(await screen.findByText(/PARTIAL: 12\/20 · fees UNVERIFIED/)).toBeInTheDocument();
  });
});

describe("<CalibrationChart>", () => {
  const bins: CalibrationBin[] = [
    { lower: 0.4, upper: 0.5, count: 120, mean_p: 0.45, observed_rate: 0.43 },
    { lower: 0.5, upper: 0.6, count: 0, mean_p: null, observed_rate: null },
    { lower: 0.8, upper: 0.9, count: 30, mean_p: 0.84, observed_rate: 0.9 },
  ];

  it("plots one marker per non-empty bin with an accessible label and hover tooltip", () => {
    render(<CalibrationChart title="Holdout calibration" bins={bins} />);
    expect(screen.getByRole("img", { name: /Holdout calibration: 2 bins/ })).toBeInTheDocument();
    const target = screen.getByLabelText(/Bin 40% to 50%: 120 forecasts/);
    fireEvent.mouseEnter(target);
    expect(screen.getByRole("status")).toHaveTextContent("120 forecasts · mean 45% · observed 43%");
    fireEvent.mouseLeave(target);
    expect(screen.queryByRole("status")).toBeNull();
    fireEvent.focus(screen.getByLabelText(/Bin 80% to 90%/));
    expect(screen.getByRole("status")).toHaveTextContent("observed 90%");
  });
});
