import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { JobsSnapshot } from "../api/types";
import { ControlBar } from "./ControlBar";

const idle = (name: "refresh" | "evidence" | "scan" | "history" | "combos") => ({
  name, running: false, last_started: null, last_finished: null, last_status: null,
  last_message: null,
});

let snap: JobsSnapshot;
const posts: { path: string; headers: Record<string, string>; body: unknown }[] = [];

beforeEach(() => {
  posts.length = 0;
  snap = {
    jobs: { refresh: idle("refresh"), evidence: idle("evidence"), scan: idle("scan"), history: idle("history"), combos: idle("combos") },
    auto_scan: { enabled: false, interval_seconds: 300, next_run_at: null },
    worker_running: false, watchlist: ["KXCPI"],
  };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), "http://127.0.0.1").pathname;
    if (init?.method === "POST") {
      posts.push({ path, headers: init.headers as Record<string, string>,
                   body: JSON.parse(String(init.body)) });
      if (path === "/api/jobs/scan/run") {
        snap = { ...snap, jobs: { ...snap.jobs, scan: { ...snap.jobs.scan, running: true } } };
      }
      if (path === "/api/jobs/auto-scan") {
        snap = { ...snap, auto_scan: { ...snap.auto_scan, enabled: true } };
      }
      return new Response(JSON.stringify(snap), { status: 202 });
    }
    return new Response(JSON.stringify(snap), { status: 200 });
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("<ControlBar>", () => {
  it("does not re-poll in a loop while idle", async () => {
    render(<ControlBar />);
    await screen.findByRole("button", { name: "Scan now" });
    await new Promise((r) => setTimeout(r, 300));
    expect((fetch as unknown as { mock: { calls: unknown[] } }).mock.calls.length).toBe(1);
  });

  it("shows the three data buttons and the watchlist", async () => {
    render(<ControlBar />);
    expect(await screen.findByRole("button", { name: "Refresh data" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh FRED" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Scan now" })).toBeInTheDocument();
    expect(screen.getByText(/watchlist: KXCPI/)).toBeInTheDocument();
  });

  it("starts a scan with the ops CSRF header and shows it running", async () => {
    const user = userEvent.setup();
    render(<ControlBar />);
    await user.click(await screen.findByRole("button", { name: "Scan now" }));
    await waitFor(() => expect(posts[0]?.path).toBe("/api/jobs/scan/run"));
    expect(posts[0]!.headers["X-KRT-Request"]).toBe("ops");
    expect(await screen.findByRole("button", { name: "Scan now: running…" })).toBeDisabled();
  });

  it("announces a data refresh when a running job finishes", async () => {
    const heard = vi.fn();
    window.addEventListener("krt:data-updated", heard);
    const user = userEvent.setup();
    render(<ControlBar />);
    await user.click(await screen.findByRole("button", { name: "Scan now" }));
    snap = { ...snap, jobs: { ...snap.jobs, scan: { ...idle("scan"), last_status: "success",
             last_finished: "2026-11-18T23:00:30Z", last_message: "0 new card(s)" } } };
    await waitFor(() => expect(heard).toHaveBeenCalled(), { timeout: 4000 });
    expect(await screen.findByText(/0 new card\(s\)/)).toBeInTheDocument();
    window.removeEventListener("krt:data-updated", heard);
  });

  it("toggles auto-scan, and disables it while the worker is running", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<ControlBar />);
    await user.click(await screen.findByLabelText(/Auto-scan every 5 min/));
    await waitFor(() => expect(posts.some((p) => p.path === "/api/jobs/auto-scan")).toBe(true));
    unmount();
    snap = { ...snap, worker_running: true };
    render(<ControlBar />);
    expect(await screen.findByLabelText(/Auto-scan every 5 min/)).toBeDisabled();
    expect(screen.getByText("worker running")).toBeInTheDocument();
  });
});
