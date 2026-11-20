import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FromHistory } from "../docket/FromHistory";
import { WhatChanged } from "../history/HistoryPage";
import { Tip } from "./Tip";

describe("<Tip>", () => {
  it("shows on keyboard focus, hides on Escape and keeps focus on the trigger", async () => {
    const user = userEvent.setup();
    render(<p>Edge <Tip text="±2.1 pts standard error">+4.0 pts</Tip></p>);
    await user.tab();
    const trigger = screen.getByRole("button", { name: "+4.0 pts" });
    expect(trigger).toHaveFocus();
    expect(screen.getByRole("tooltip")).toHaveTextContent("±2.1 pts standard error");
    expect(trigger).toHaveAttribute("aria-describedby", screen.getByRole("tooltip").id);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("toggles on tap for touch users and closes when tapping elsewhere", () => {
    render(<div><Tip text="Explained">Label</Tip><span>elsewhere</span></div>);
    const trigger = screen.getByRole("button", { name: "Label" });
    fireEvent.pointerEnter(trigger.parentElement!, { pointerType: "touch" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument(); // no hover-open on touch
    fireEvent.click(trigger);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Explained");
    fireEvent.pointerDown(screen.getByText("elsewhere"));
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    fireEvent.click(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument(); // second tap closes
  });
});

describe("<FromHistory>", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const u = new URL(String(input), "http://127.0.0.1");
      expect(u.pathname).toBe("/api/history/similar");
      return new Response(JSON.stringify({ min_sample: 10, synced_at: null, groups: [
        { kind: "series", key: "KXNBAGAME", label: "NBA Game", n: 3, won: 3, pnl: "9.50", staked: "3.00",
          roi: null, mean_return: null, se: null, verdict: "too_few",
          text: "3 closed trades, net $9.50: too few to say anything about how these go for you (needs 10+)." },
        { kind: "type", key: "player prop", label: "All your player prop markets", n: 14, won: 4, pnl: "-6.10",
          staked: "20.00", roi: -0.305, mean_return: -0.3, se: 0.1, verdict: "worse",
          text: "Won 4 of 14, net $-6.10. Worse than luck would usually give over 14 trades." },
      ] }), { status: 200 });
    }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("never turns a tiny winning streak into a rate, and marks the threshold", async () => {
    render(<FromHistory legs={[{ ticker: "KXNBAGAME-26NOV19NYKMIN-NYK", side: "yes" }]} as="section" />);
    const tiny = await screen.findByText(/too few to say anything/);
    expect(tiny.textContent).not.toMatch(/%/);
    expect(tiny.closest("li")).toHaveClass("muted");
    expect(screen.getByText(/Worse than luck/).closest("li")).toHaveClass("hist-worse");
    expect(screen.getByText(/Records under 10 closed trades show counts only/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "sample size" })).toHaveAttribute("data-term-id", "sample-size");
  });
});

describe("<WhatChanged>", () => {
  const now = Date.parse("2026-11-19T12:00:00Z");
  it("tallies the last 7 days and says a few results aren't a trend", () => {
    render(<WhatChanged now={now} timeline={[
      { date: "2026-11-01", pnl: "50.00", cumulative: "50.00", markets: 9, wins: 9, by_type: {} },
      { date: "2026-11-15", pnl: "2.00", cumulative: "52.00", markets: 2, wins: 1, by_type: {} },
      { date: "2026-11-18", pnl: "-0.50", cumulative: "51.50", markets: 1, wins: 0, by_type: {} },
    ]} />);
    const s = screen.getByRole("region", { name: "Last 7 days" });
    expect(s).toHaveTextContent("+$1.50 net over 3 markets closed, 1 won.");
    expect(within(s).getByText(/too few results to read anything into/)).toBeInTheDocument();
  });

  it("says so when nothing closed", async () => {
    render(<WhatChanged now={now} timeline={[]} />);
    await waitFor(() => expect(screen.getByText(/Nothing settled or sold/)).toBeInTheDocument());
  });
});
