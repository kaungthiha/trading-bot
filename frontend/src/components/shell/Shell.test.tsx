import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import type { Health } from "../../api/types";
import { HairlineDivider, Metric } from "../design/primitives";
import { StatusLabel } from "../design/StatusLabel";
import { LeftRail, NAV, UTILITY } from "./LeftRail";
import { DataHeartbeat, Topbar } from "./Topbar";

const HEALTH = {
  status: "ok", version: "0.1.0", env: "local", trading_mode: "paper",
  live_execution_enabled: false, market_data_source: "kalshi_public", kalshi_env: "production",
  database: "ok",
} as unknown as Health;

afterEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.density;
});

describe("LeftRail", () => {
  it("shows the task sections plus Tools, and marks the current section", () => {
    render(<LeftRail section="explore" />);
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ...NAV.map((n) => [n.label, n.href]), [UTILITY.label, UTILITY.href]]);
    expect(links.map((a) => a.textContent)).toEqual(["Today", "Explore", "Journal", "Learn", "Tools"]);
    expect(within(nav).getByRole("link", { name: "Explore" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Today" })).not.toHaveAttribute("aria-current");
  });
});

describe("DataHeartbeat", () => {
  it("states mode, execution and connection in words, not colour alone", () => {
    render(<DataHeartbeat health={{ state: "ok", data: HEALTH }} />);
    const s = screen.getByRole("status");
    expect(s).toHaveTextContent("PAPER MODE");
    expect(s).toHaveTextContent("Live execution: disabled");
    expect(s).toHaveTextContent("connected");
    expect(s).not.toHaveTextContent("DEMO");
  });

  it("flags demo data, a bad database and an unreachable backend", () => {
    const { rerender } = render(
      <DataHeartbeat health={{ state: "ok", data: { ...HEALTH, env: "demo", database: "error" } as Health }} />);
    expect(screen.getByRole("status")).toHaveTextContent("DEMO · synthetic data");
    expect(screen.getByRole("status")).toHaveTextContent("DB: error");
    rerender(<DataHeartbeat health={{ state: "error", message: "Backend unreachable" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Backend: Backend unreachable");
    rerender(<DataHeartbeat health={{ state: "loading" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Connecting…");
  });
});

describe("density toggle", () => {
  it("switches rows to compact, stores it locally and restores it", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<Topbar health={{ state: "loading" }} />);
    const btn = screen.getByRole("button", { name: "Compact rows" });
    expect(btn).toHaveAttribute("aria-pressed", "false");
    expect(document.documentElement.dataset.density).toBe("comfortable");
    await user.click(btn);
    expect(btn).toHaveAttribute("aria-pressed", "true");
    expect(document.documentElement.dataset.density).toBe("compact");
    expect(localStorage.getItem("krt.density")).toBe("compact");
    unmount();
    render(<Topbar health={{ state: "loading" }} />);
    expect(screen.getByRole("button", { name: "Compact rows" })).toHaveAttribute("aria-pressed", "true");
  });

  it("ignores a tampered stored value", () => {
    localStorage.setItem("krt.density", "<script>");
    render(<Topbar health={{ state: "loading" }} />);
    expect(document.documentElement.dataset.density).toBe("comfortable");
  });
});

describe("primitives", () => {
  it("Metric keeps the sign in the text and adds the matching class", () => {
    render(<Metric label="Realized P&L" value="−$61.54" sign="neg" sub="41 settled" />);
    const v = screen.getByText("−$61.54");
    expect(v).toHaveClass("metric-value", "ev-neg");
    expect(screen.getByText("41 settled")).toBeInTheDocument();
  });

  it("StatusLabel adds a glyph for states that need action, hidden from screen readers", () => {
    render(<StatusLabel tone="stale">STALE</StatusLabel>);
    const label = screen.getByText("STALE");
    expect(label).toHaveClass("badge", "stale");
    expect(label.querySelector(".status-mark")).toHaveAttribute("aria-hidden", "true");
  });

  it("HairlineDivider is decorative unless labelled", () => {
    const { container, rerender } = render(<HairlineDivider />);
    expect(container.querySelector("hr")).toHaveAttribute("aria-hidden", "true");
    rerender(<HairlineDivider label="Evidence" />);
    expect(screen.getByRole("separator", { name: "Evidence" })).toBeInTheDocument();
  });
});
