import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import type { HistoryReport } from "../../api/types";
import { PnlCharts } from "../history/PnlCharts";
import { ComboStudyPanel } from "./ComboStudyPanel";

const bucket = (b: string, n: number, p: number, h: number) => ({
  bucket: b, n, avg_price: p, hit_rate: h, edge: h - p, se: 0.01, return_per_dollar: h / p });
const STUDY = {
  overall: { n: 19000, avg_price: 0.127, hit_rate: 0.048, edge: -0.079, se: 0.002, return_per_dollar: 0.378 },
  by_legs: [bucket("2 legs", 1085, 0.317, 0.241), bucket("6+ legs", 12116, 0.089, 0.023)],
  by_price: [bucket("35¢+", 1852, 0.59, 0.388)],
  markets_scanned: 19000, generated_at: "2026-11-18T23:00:00Z",
};
beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), "http://127.0.0.1").pathname;
    if (path === "/api/catalog/combo-study") return new Response(JSON.stringify({ study: STUDY }));
    return new Response("{}", { status: 404 });
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("combos", () => {
  it("shows the settled-combo study by legs and price", async () => {
    render(<ComboStudyPanel />);
    expect(await screen.findByText(/\$0\.38 per \$1/)).toBeInTheDocument();
    expect(screen.getByText("2 legs")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh the study" })).toBeInTheDocument();
  });
});

describe("<PnlCharts>", () => {
  const tl: HistoryReport["timeline"] = [
    { date: "2026-11-10", pnl: "2.00", cumulative: "2.00", markets: 2, wins: 2, by_type: { total: "2.00" } },
    { date: "2026-11-11", pnl: "-3.00", cumulative: "-1.00", markets: 1, wins: 0, by_type: { "player prop": "-3.00" } },
    { date: "2026-11-12", pnl: "1.50", cumulative: "0.50", markets: 1, wins: 1, by_type: { "game winner": "1.50" } },
  ];

  it("renders cumulative and daily charts with a table view", () => {
    render(<PnlCharts timeline={tl} />);
    expect(screen.getByRole("img", { name: /Cumulative realized P&L over 3 days, now \+\$0\.50/ })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Daily realized P&L for 3 days/ })).toBeInTheDocument();
    expect(screen.getByText("player prop −$3.00")).toBeInTheDocument();
    expect(screen.getByText(/gain \(above the line\)/)).toBeInTheDocument();
  });

  it("asks for more history when there is under two days", () => {
    render(<PnlCharts timeline={tl.slice(0, 1)} />);
    expect(screen.getByText(/at least two different days/)).toBeInTheDocument();
  });
});
