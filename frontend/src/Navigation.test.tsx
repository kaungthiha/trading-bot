import { act, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const health = {
  status: "ok", version: "0.1.0", env: "local", trading_mode: "paper", live_execution_enabled: false,
  market_data_source: "fixture", kalshi_env: "production", database: "ok",
  server_time: "2026-11-18T15:00:30+00:00", credentials_configured: {},
};

function go(hash: string) {
  act(() => {
    window.location.hash = hash;
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
}

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), "http://127.0.0.1").pathname;
    if (path === "/api/health") return new Response(JSON.stringify(health), { status: 200 });
    if (path === "/api/catalog/status") {
      return new Response(JSON.stringify({ refreshed_at: new Date(Date.now() - 3 * 3600_000).toISOString(),
        events: 1, markets: 1, series: 1 }), { status: 200 });
    }
    return new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: "nope" } }), { status: 404 });
  }));
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

describe("navigation", () => {
  it("opens on Today, with the rail on Today and every source reporting its own state", async () => {
    window.location.hash = "";
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Today's desk", level: 2 })).toBeInTheDocument();
    const rail = screen.getByRole("navigation", { name: "Primary" });
    expect(within(rail).getByRole("link", { name: "Today" })).toHaveAttribute("aria-current", "page");
    // Backend has none of these endpoints here: each group says so and offers a retry.
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Retry" })).toHaveLength(4));
  });

  it("flags a stale price scan in the global heartbeat", async () => {
    render(<App />);
    expect(await screen.findByText(/Prices scanned 3h ago · stale/)).toBeInTheDocument();
  });

  it("follows hash changes (links, back/forward) and moves focus to the new page title", async () => {
    window.location.hash = "#/";
    render(<App />);
    await screen.findByRole("heading", { name: "Today's desk" });

    go("#/history"); // old link -> Journal
    const journal = await screen.findByRole("heading", { name: "My trades", level: 2 });
    expect(within(screen.getByRole("navigation", { name: "Primary" })).getByRole("link", { name: "Journal" }))
      .toHaveAttribute("aria-current", "page");
    await waitFor(() => expect(journal).toHaveFocus());

    go("#/terminal?tab=signals");
    expect(await screen.findByRole("heading", { name: "Tools", level: 2 })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Signals" })).toHaveAttribute("aria-selected", "true");

    go("#/"); // back to Today
    expect(await screen.findByRole("heading", { name: "Today's desk" })).toBeInTheDocument();
  });

  it("puts Games and All markets under Explore with a switch between them", async () => {
    window.location.hash = "#/markets";
    render(<App />);
    const sw = await screen.findByRole("navigation", { name: "Explore" });
    expect(within(sw).getByRole("link", { name: "All markets" })).toHaveAttribute("aria-current", "page");
    expect(within(sw).getByRole("link", { name: "Games" })).toHaveAttribute("href", "#/games");
    expect(within(screen.getByRole("navigation", { name: "Primary" })).getByRole("link", { name: "Explore" }))
      .toHaveAttribute("aria-current", "page");
  });
});
