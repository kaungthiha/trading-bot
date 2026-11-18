import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { FeeScheduleInfo, Signal } from "../api/types";
import { SignalsPanel } from "./SignalsPanel";

const base: Signal = {
  id: "s1",
  created_at: "2026-11-18T22:50:00Z",
  expires_at: "2026-11-18T22:51:00Z",
  validity: "VALID",
  market_id: "m1",
  market_ticker: "KXCPI-26NOV-T0.1",
  market_title: "Will CPI rise more than 0.1% in November 2026?",
  rules_source_url: "https://assets.kalshi.com/regulatory/product-certifications/CPI.pdf",
  decision: "ABSTAIN",
  side: "YES",
  quantity: "10",
  p_yes: 0.799,
  p_lower: 0.709,
  p_upper: 0.87,
  entry: "0.030000",
  fee: "0.003000",
  slippage: "0.01",
  ev: "0.756373",
  lower_edge: "0.666083",
  reasons: ["MAPPING_NOT_CONFIRMED", "FEE_SCHEDULE_UNVERIFIED", "MODEL_MARKET_DIVERGENCE"],
  caveats: ["Research hypothesis only: not an order, not a recommendation, and nothing is executed."],
  quote_id: "q1234567890",
  quote_observed_at: "2026-11-18T22:49:50Z",
  model_run_id: "mr123456789",
  model: "gaussian_trailing",
  contract_key: "CPI_MOM_SA_FIRST>0.1@2026-11",
  mapping_id: "map1",
  mapping_status: "proposed",
  fee_schedule_version: "kalshi-quadratic-candidate-2026-11",
  details: { model_market_divergence: "0.769000" },
};

const candidate: Signal = {
  ...base,
  id: "s2",
  market_ticker: "KXCPI-26NOV-T-0.2",
  market_title: "Will CPI rise more than -0.2% in November 2026?",
  decision: "CANDIDATE_YES",
  reasons: [],
};

const expired: Signal = { ...candidate, id: "s3", market_ticker: "X", validity: "EXPIRED" };

const fees: FeeScheduleInfo[] = [
  {
    version: "kalshi-quadratic-candidate-2026-11",
    verified: false,
    verified_by: null,
    verified_at: null,
    source_url: "https://kalshi.com/docs/kalshi-fee-schedule.pdf",
  },
];

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://127.0.0.1").pathname;
      const body = path === "/api/signals" ? [base, candidate, expired]
        : path === "/api/fee-schedules" ? fees : null;
      return new Response(JSON.stringify(body ?? {}), { status: body ? 200 : 404 });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("<SignalsPanel>", () => {
  it("shows cost breakdown, reasons, IDs, caveats and the research-only disclaimer", async () => {
    render(<SignalsPanel />);
    const card = (await screen.findByText(base.market_title)).closest("article")!;
    const c = within(card);
    expect(c.getByText("ABSTAIN")).toBeInTheDocument();
    expect(c.getByText("$0.030000")).toBeInTheDocument();
    expect(c.getByText("$0.666083")).toBeInTheDocument();
    expect(c.getByText("MODEL_MARKET_DIVERGENCE")).toBeInTheDocument();
    expect(c.getByText("0.769000")).toBeInTheDocument();
    expect(c.getByText(/model run mr123456/)).toBeInTheDocument();
    expect(c.getByRole("link", { name: "contract terms" })).toHaveAttribute(
      "href", base.rules_source_url,
    );
    expect(c.getByText(/not an order/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing here places, queues or authorizes an order/)).toBeInTheDocument();
  });

  it("warns that fees are unverified and links the official schedule", async () => {
    render(<SignalsPanel />);
    expect(await screen.findByText("FEES UNVERIFIED")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "official fee schedule" })).toHaveAttribute(
      "href", fees[0]!.source_url,
    );
  });

  it("labels candidates as research only and filters to valid candidates", async () => {
    const user = userEvent.setup();
    render(<SignalsPanel />);
    expect(await screen.findByText("CANDIDATE YES (research only)")).toBeInTheDocument();
    expect(screen.getByText("EXPIRED")).toBeInTheDocument();
    await user.click(screen.getByLabelText("Show only valid candidates"));
    expect(screen.queryByText(base.market_title)).toBeNull();
    expect(screen.queryByText("EXPIRED")).toBeNull();
    expect(screen.getByText(candidate.market_title)).toBeInTheDocument();
  });
});
