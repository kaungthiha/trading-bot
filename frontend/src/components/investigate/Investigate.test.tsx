import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ComboLeg, InvestigationHypothesis, LegEvidence, ResearchJob } from "../../api/types";
import { slip } from "../games/slip";
import { fixtureInvestigation } from "./fixture";
import { buildHypothesis, hypothesisKey, MARKET_LABEL, supportFor } from "./hypothesis";
import { InvestigateButton } from "./InvestigateButton";
import { clampSummary, InvestigationHost } from "./InvestigationDrawer";
import { fixtureSource, investigation, type Progress, type RunOptions } from "./store";

const WIN: ComboLeg = { ticker: "KXNBAGAME-26NOV19GSWMEM-GSW", side: "yes", label: "Golden State wins", event: "KXNBAGAME-26NOV19GSWMEM" };
const SPREAD: ComboLeg = { ticker: "KXNBASPREAD-26NOV19GSWMEM-MEM4", side: "yes", label: "Memphis wins by over 4.5 points", event: "KXNBASPREAD-26NOV19GSWMEM" };
const REB12: ComboLeg = { ticker: "KXNBAREB-26NOV19NYKMIN-NYKKTOWNS32-12", side: "yes", label: "Karl-Anthony Towns: 12+ rebounds", event: "KXNBAREB-26NOV19NYKMIN" };
const REB10: ComboLeg = { ...REB12, ticker: "KXNBAREB-26NOV19NYKMIN-NYKKTOWNS32-10", label: "Karl-Anthony Towns: 10+ rebounds" };
const towns: LegEvidence = { ticker: REB12.ticker, side: "yes", label: "Towns", supported: true, kind: "player_stat", line: 11.5,
  subject: { type: "player", name: "Karl-Anthony Towns", team: "NYK", espn_url: null } };

function Harness({ leg = WIN, ev }: { leg?: ComboLeg; ev?: LegEvidence }) {
  return (
    <>
      <InvestigateButton leg={leg} ev={ev} scanAt="2026-11-19T21:00:00Z" />
      <InvestigationHost />
    </>
  );
}

beforeEach(() => { investigation.reset(); slip.clear(); });
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe("hypotheses are exact", () => {
  it("YES and NO, and different lines, are different hypotheses with different statements", () => {
    const yes = buildHypothesis(WIN, undefined, null);
    const no = buildHypothesis({ ...WIN, side: "no" }, undefined, null);
    expect(hypothesisKey(yes)).not.toBe(hypothesisKey(no));
    expect(yes.statement).toBe("Golden State wins");
    expect(no.statement).toMatch(/^NOT: Golden State wins/);
    const r12 = buildHypothesis(REB12, towns, null);
    const r10 = buildHypothesis(REB10, undefined, null);
    expect(hypothesisKey(r12)).not.toBe(hypothesisKey(r10));
    expect(r12).toMatchObject({ market_type: "player_prop", threshold: 11.5, subject: "Karl-Anthony Towns" });
    expect(r10.threshold).toBe(10); // from the ticker when evidence isn't loaded
  });

  it("moneyline and spread on the same game are different market types", () => {
    expect(buildHypothesis(WIN, undefined, null).market_type).toBe("moneyline");
    const winEv: LegEvidence = { ticker: WIN.ticker, side: "yes", label: "GSW", supported: true, kind: "team_win", line: 0 };
    expect(buildHypothesis(WIN, winEv, null).threshold).toBeNull(); // no "line 0" on a winner
    const s = buildHypothesis(SPREAD, undefined, null);
    expect(s.market_type).toBe("spread");
    expect(s.threshold).toBe(4);
  });

  it("results follow the exact side and line", () => {
    const a = fixtureInvestigation(buildHypothesis(WIN, undefined, null));
    const b = fixtureInvestigation(buildHypothesis({ ...WIN, side: "no" }, undefined, null));
    expect(a.summary.takeaway).toContain("for Golden State wins");
    expect(b.summary.takeaway).toContain("for NOT Golden State wins");
    expect(a.quote.ask).not.toBe(b.quote.ask);
    expect(fixtureInvestigation(buildHypothesis(REB12, towns, null)).summary.takeaway).toContain("(line 11.5)");
  });

  it("supports men's and women's college basketball game lines", () => {
    const spread = { ticker: "KXNCAAMBSPREAD-26NOV19TARLUSC-USC28", side: "yes" as const,
      label: "USC wins by over 27.5 points", event: "KXNCAAMBSPREAD-26NOV19TARLUSC" };
    expect(supportFor(spread).ok).toBe(true);
    const h = buildHypothesis(spread, undefined, null);
    expect(h).toMatchObject({ league: "NCAA men's", market_type: "spread" });
    const win = { ticker: "KXNCAAWBGAME-26NOV23VCUPROV-VCU", side: "no" as const, label: "VCU",
      event: "KXNCAAWBGAME-26NOV23VCUPROV" };
    expect(supportFor(win).ok).toBe(true);
    expect(buildHypothesis(win, undefined, null)).toMatchObject({ league: "NCAA women's", market_type: "moneyline", threshold: null });
    expect(supportFor({ ticker: "KXWNBAGAME-27MAY20LVANYL-LVA", side: "yes", label: "Aces",
      event: "KXWNBAGAME-27MAY20LVANYL" }).ok).toBe(true);
  });

  it("supports NHL game winner, puck line and totals with the right lines, not periods or props", () => {
    const ev = "26NOV19BOSNYR";
    const win = { ticker: `KXNHLGAME-${ev}-BOS`, side: "yes" as const, label: "Boston", event: `KXNHLGAME-${ev}` };
    expect(supportFor(win).ok).toBe(true);
    expect(buildHypothesis(win, undefined, null)).toMatchObject({ sport: "hockey", league: "NHL", market_type: "moneyline", threshold: null });
    const tot = { ticker: `KXNHLTOTAL-${ev}-6`, side: "no" as const, label: "Over 5.5", event: `KXNHLTOTAL-${ev}` };
    expect(buildHypothesis(tot, undefined, null)).toMatchObject({ market_type: "total", threshold: 5.5 });
    const pl = { ticker: `KXNHLSPREAD-${ev}-BOS2`, side: "yes" as const, label: "BOS by 1.5", event: `KXNHLSPREAD-${ev}` };
    expect(buildHypothesis(pl, undefined, null)).toMatchObject({ market_type: "spread", threshold: 1.5 });
    for (const t of ["KXNHL1P", "KXNHL2PTOTAL", "KXNHLGOAL", "KXNHLPTS", "KXNHLOT"]) {
      const r = supportFor({ ticker: `${t}-${ev}-BOS`, side: "yes", label: t, event: `${t}-${ev}` });
      expect(r.ok, t).toBe(false);
    }
  });

  it("supports NFL game winner, spread and totals with the right lines, not halves or props", () => {
    const ev = "26NOV26KCBUF";
    const win = { ticker: `KXNFLGAME-${ev}-BUF`, side: "yes" as const, label: "Buffalo", event: `KXNFLGAME-${ev}` };
    expect(supportFor(win).ok).toBe(true);
    expect(buildHypothesis(win, undefined, null)).toMatchObject({ sport: "football", league: "NFL", market_type: "moneyline", threshold: null });
    const sp = { ticker: `KXNFLSPREAD-${ev}-BUF8`, side: "yes" as const, label: "BUF by 7.5", event: `KXNFLSPREAD-${ev}` };
    expect(buildHypothesis(sp, undefined, null)).toMatchObject({ market_type: "spread", threshold: 7.5 });
    const tot = { ticker: `KXNFLTOTAL-${ev}-46`, side: "no" as const, label: "Over 45.5", event: `KXNFLTOTAL-${ev}` };
    expect(buildHypothesis(tot, undefined, null)).toMatchObject({ market_type: "total", threshold: 45.5 });
    const tt = { ticker: `KXNFLTEAMTOTAL-${ev}-KC21`, side: "yes" as const, label: "KC over 20.5", event: `KXNFLTEAMTOTAL-${ev}` };
    expect(supportFor(tt).ok).toBe(true);
    expect(buildHypothesis(tt, undefined, null)).toMatchObject({ market_type: "team_total", threshold: 20.5 });
    for (const t of ["KXNFL1HTEAMTOTAL", "KXNFL2QBTTS", "KXNFLPASSYDS", "KXNFLFIRSTTD", "KXNFLTOTALPRECISE"]) {
      const r = supportFor({ ticker: `${t}-${ev}-KC10`, side: "yes", label: t, event: `${t}-${ev}` });
      expect(r.ok, t).toBe(false);
    }
    expect(supportFor({ ticker: "KXNFLWINS-27-BUF", side: "yes", label: "wins", event: "KXNFLWINS-27" }).ok).toBe(false);
  });

  it("supports soccer winner (incl. Tie), spread, totals and BTTS, not halves or corners", () => {
    const ev = "26NOV29ARSMCI";
    const win = { ticker: `KXEPLGAME-${ev}-ARS`, side: "yes" as const, label: "Arsenal", event: `KXEPLGAME-${ev}` };
    expect(supportFor(win).ok).toBe(true);
    expect(buildHypothesis(win, undefined, null)).toMatchObject({ sport: "soccer", league: "EPL", market_type: "moneyline", threshold: null });
    const tie = { ticker: `KXEPLGAME-${ev}-TIE`, side: "yes" as const, label: "Tie", event: `KXEPLGAME-${ev}` };
    expect(supportFor(tie).ok).toBe(true);
    const tot = { ticker: `KXUCLTOTAL-${ev}-3`, side: "no" as const, label: "Over 2.5", event: `KXUCLTOTAL-${ev}` };
    expect(buildHypothesis(tot, undefined, null)).toMatchObject({ league: "Champions League", market_type: "total", threshold: 2.5 });
    const sp = { ticker: `KXLALIGASPREAD-${ev}-MCI2`, side: "yes" as const, label: "by 1.5", event: `KXLALIGASPREAD-${ev}` };
    expect(buildHypothesis(sp, undefined, null)).toMatchObject({ league: "La Liga", market_type: "spread", threshold: 1.5 });
    const btts = { ticker: `KXSERIEABTTS-${ev}-BTTS`, side: "yes" as const, label: "BTTS", event: `KXSERIEABTTS-${ev}` };
    expect(supportFor(btts).ok).toBe(true);
    expect(buildHypothesis(btts, undefined, null)).toMatchObject({ market_type: "btts", threshold: null });
    expect(MARKET_LABEL.btts).toBe("Both teams to score");
    for (const t of ["KXUCL1HTOTAL", "KXUCL2HSPREAD", "KXLALIGACORNERS", "KXUCLSCORE", "KXUCLFTTS", "KXLALIGA2GAME"]) {
      const r = supportFor({ ticker: `${t}-${ev}-ARS`, side: "yes", label: t, event: `${t}-${ev}` });
      expect(r.ok, t).toBe(false);
    }
  });

  it("unsupported markets explain why instead of offering the action", () => {
    expect(supportFor({ ...WIN, ticker: "KXNHLSEASONPTS-27-MCDAVID", event: "KXNHLSEASONPTS-27" }).ok).toBe(false);
    expect(supportFor({ ticker: "KXNBAMVP-27-SGA", side: "yes", label: "SGA MVP", event: "KXNBAMVP-27" }).ok).toBe(false);
    expect(supportFor({ ticker: "KXCPI-26DEC-T3", side: "yes", label: "CPI", event: "KXCPI-26DEC" }).ok).toBe(false);
    // College halves and season-long markets stay out; full-game college lines are in.
    expect(supportFor({ ticker: "KXNCAAMB1HSPREAD-26NOV19TARLUSC-USC5", side: "yes", label: "1H",
      event: "KXNCAAMB1HSPREAD-26NOV19TARLUSC" }).ok).toBe(false);
    expect(supportFor({ ticker: "KXNCAAMBAPRANK-26-KU", side: "yes", label: "rank", event: "KXNCAAMBAPRANK-26" }).ok).toBe(false);
    render(<Harness leg={{ ticker: "KXCPI-26DEC-T3", side: "yes", label: "CPI", event: "KXCPI-26DEC" }} />);
    expect(screen.queryByRole("button", { name: /^Investigate/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "can't investigate" })).toBeInTheDocument();
  });
});

describe("summary limits", () => {
  it("keeps at most 2 sentences and 3 findings whatever the source returns", () => {
    const r = fixtureInvestigation(buildHypothesis(WIN, undefined, null));
    expect(r.summary.findings).toHaveLength(4); // the fixture deliberately over-supplies
    const c = clampSummary(r.summary);
    expect(c.takeaway.split(/(?<=[.!?])\s+/)).toHaveLength(2);
    expect(c.takeaway).not.toContain("never be shown");
    expect(c.findings).toHaveLength(3);
  });
});

describe("<InvestigationDrawer>", () => {
  it("opens without touching the slip, shows the contract, and runs only on click", async () => {
    const user = userEvent.setup();
    slip.add(WIN);
    const run = vi.spyOn(fixtureSource, "run");
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Investigate YES: Golden State wins" });
    await user.click(trigger);
    const dlg = screen.getByRole("dialog", { name: "Golden State wins" });
    expect(screen.getByRole("heading", { name: "Golden State wins" })).toHaveFocus();
    expect(within(dlg).getByText(/Preview with sample research/)).toBeInTheDocument();
    expect(within(dlg).getByText("Game winner")).toBeInTheDocument();
    expect(within(dlg).getByText("KXNBAGAME-26NOV19GSWMEM-GSW")).toBeInTheDocument();
    expect(await within(dlg).findByText(/34¢ ask/)).toBeInTheDocument();
    expect(within(dlg).getByText(/Uses up to 5 news searches \(56 left today on this app's cap/)).toBeInTheDocument();
    expect(run).not.toHaveBeenCalled(); // opening is free
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(slip.get()).toEqual([WIN]);
  });

  it("shows the summary by default with the full research collapsed, and expanding costs nothing", async () => {
    const user = userEvent.setup();
    const run = vi.spyOn(fixtureSource, "run");
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /Investigate YES/ }));
    const dlg = screen.getByRole("dialog");
    await user.click(await within(dlg).findByRole("button", { name: "Run investigation" }));
    expect(within(dlg).getByRole("status")).toHaveTextContent("Investigating…");
    const three = await within(dlg).findByRole("region", { name: "Three things that matter" });
    expect(within(three).getAllByRole("listitem")).toHaveLength(3);
    expect(within(dlg).getByText(/^Sample takeaway: the evidence is mixed/).textContent).not.toContain("third sentence");
    // missing model / edge states are explicit, never invented
    const price = within(dlg).getByRole("region", { name: "Price lens" });
    expect(price).toHaveTextContent("No calibrated model for this market");
    expect(price).toHaveTextContent("Not enough evidence to estimate an edge");
    expect(within(dlg).getByText("Still unknown:").parentElement).toHaveTextContent("Starting lineup not confirmed");
    const full = within(dlg).getByText("View full research").closest("details")!;
    expect(full).not.toHaveAttribute("open");
    expect(run).toHaveBeenCalledTimes(1);
    await user.click(within(dlg).getByText("View full research"));
    expect(full).toHaveAttribute("open");
    expect(within(full).getByRole("heading", { name: "What could make me wrong?" })).toBeInTheDocument();
    expect(within(full).getByText(/same report as S2: not independent/)).toBeInTheDocument();
    expect(run).toHaveBeenCalledTimes(1); // expansion reads the same canonical result
    expect(investigation.get().runs).toBe(1);
  });

  it("source markers link out; a finding with an unknown source is marked unverified", async () => {
    const user = userEvent.setup();
    const base = fixtureSource.run;
    vi.spyOn(fixtureSource, "run").mockImplementation(async (h: InvestigationHypothesis) => {
      const r = await base(h);
      r.summary.findings[0] = { ...r.summary.findings[0]!, source_ids: ["S9"] }; // invented id
      return r;
    });
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /Investigate YES/ }));
    await user.click(await screen.findByRole("button", { name: "Run investigation" }));
    const three = await screen.findByRole("region", { name: "Three things that matter" });
    expect(within(three).getByText("unverified")).toBeInTheDocument();
    const mark = within(three).getByRole("link", { name: /Source 2: example.org/ });
    expect(mark).toHaveAttribute("rel", "noopener noreferrer nofollow");
  });

  it("double clicks, re-renders and reopening never start a second job", async () => {
    const user = userEvent.setup();
    const run = vi.spyOn(fixtureSource, "run");
    const { rerender } = render(<Harness />);
    await user.click(screen.getByRole("button", { name: /Investigate YES/ }));
    const btn = await screen.findByRole("button", { name: "Run investigation" });
    act(() => { btn.click(); });
    act(() => { void investigation.run(investigation.get().open!); });
    rerender(<Harness />);
    await screen.findByRole("region", { name: "Three things that matter" });
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: /Investigate YES/ }));
    expect(await screen.findByRole("region", { name: "Three things that matter" })).toBeInTheDocument();
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("explains each degraded mode", async () => {
    const user = userEvent.setup();
    investigation.setScenario("ollama_offline");
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /Investigate YES/ }));
    await user.click(await screen.findByRole("button", { name: "Run investigation" }));
    expect(await screen.findByText(/Box-score history only \(the local model is offline\)/)).toBeInTheDocument();
    expect(screen.getByText(/Local model offline: summary is box-score only/)).toBeInTheDocument();
    await user.keyboard("{Escape}");

    investigation.reset();
    investigation.setScenario("brave_unconfigured");
    await user.click(screen.getByRole("button", { name: /Investigate YES/ }));
    expect(await screen.findByText(/Brave Search isn't set up: the investigation will use box scores only/)).toBeInTheDocument();
    await user.keyboard("{Escape}");

    investigation.reset();
    investigation.setScenario("budget_exhausted");
    await user.click(screen.getByRole("button", { name: /Investigate YES/ }));
    expect(await screen.findByText(/Today's Brave budget is used up/)).toBeInTheDocument();
    // App-wide usage, with a per-feature breakdown on expand; never a "$ remaining" figure.
    const usage = screen.getByText("Brave requests: 127 / 800 this month");
    await user.click(usage);
    expect(screen.getByText(/Headlines here: 5 this month/)).toBeInTheDocument();
    expect(screen.getByText(/Every Brave feature in the app shares these caps/)).toBeInTheDocument();
    expect(screen.getByRole("dialog").textContent).not.toMatch(/\$\s?\d+(\.\d+)? (left|remaining)/i);
  });

  it("Escape closes even when focus has left the drawer, and Run hands focus to the title", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /Investigate YES/ }));
    await user.click(await screen.findByRole("button", { name: "Run investigation" }));
    await screen.findByRole("region", { name: "Three things that matter" });
    expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);
    act(() => { (document.activeElement as HTMLElement).blur(); });
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("traps Tab inside the drawer", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /Investigate YES/ }));
    const dlg = screen.getByRole("dialog");
    await within(dlg).findByRole("button", { name: "Run investigation" });
    for (let i = 0; i < 6; i++) {
      await user.tab();
      expect(dlg.contains(document.activeElement)).toBe(true);
    }
  });
});

describe("API source (Phase B)", () => {
  const usage = { configured: false, used_today: 0, daily_cap: 20, used_month: 0, monthly_cap: 200, max_searches_per_investigation: 3 };
  let calls: { url: string; method: string; headers: Record<string, string>; body: unknown }[];

  function stub(pre: Record<string, unknown>, result: (h: InvestigationHypothesis) => unknown) {
    calls = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const u = new URL(String(input), "http://127.0.0.1");
      calls.push({ url: u.pathname + u.search, method: init?.method ?? "GET",
        headers: (init?.headers ?? {}) as Record<string, string>, body: init?.body ? JSON.parse(String(init.body)) : null });
      if (u.pathname === "/api/research/preflight") return new Response(JSON.stringify(pre), { status: 200 });
      const h = buildHypothesis(REB12, towns, null);
      const job = { id: "job-1", kind: "investigate", ticker: h.ticker, side: h.side, created_at: "", started_at: null,
        finished_at: null, error: null };
      // Background jobs: the POST answers at once (running); the first poll has the result.
      if (u.pathname === "/api/research/jobs") {
        return new Response(JSON.stringify({ ...job, status: "running", phase: "searching", position: 0, result: null }), { status: 202 });
      }
      if (u.pathname.startsWith("/api/research/jobs/")) {
        return new Response(JSON.stringify({ ...job, status: "done", phase: "done", position: 0, result: result(h) }), { status: 200 });
      }
      return new Response(JSON.stringify(result(h)), { status: 200 });
    }));
  }
  afterEach(() => vi.unstubAllGlobals());

  it("pasted excerpts: added, shown as unverified, never linked when no URL, removable", async () => {
    const user = userEvent.setup();
    const text = "Coach says Curry will play tonight after a full practice; the line moved late.";
    const added: unknown[] = [];
    const withExcerpt = (r: ReturnType<typeof fixtureInvestigation>) => ({
      ...r,
      sources: [...r.sources, { id: "U1", url: "", title: "Excerpt you pasted from The Athletic", publisher: "The Athletic",
        author: null, published_at: "2026-11-19", retrieved_at: new Date().toISOString(), access: "user_provided" as const,
        duplicate_of: null, line_match: "unknown" as const, excerpt: text }],
      summary: { ...r.summary, coverage: "1 factual dataset · 0 commentary links · 1 excerpt you pasted" },
    });
    let base: ReturnType<typeof fixtureInvestigation> | null = null;
    investigation.useSource({
      ...fixtureSource,
      run: async (h) => { base = fixtureInvestigation(h); return base; },
      addExcerpt: async (id, body) => { added.push({ id, body }); return withExcerpt(base!); },
      removeExcerpt: async () => base!,
    });
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /Investigate YES/ }));
    const dlg = screen.getByRole("dialog");
    await user.click(await within(dlg).findByRole("button", { name: "Run investigation" }));
    await user.click(await within(dlg).findByText(/Add an excerpt you've read/));
    const add = within(dlg).getByRole("button", { name: "Add excerpt" });
    expect(add).toBeDisabled(); // needs 20+ characters and a source
    expect(within(dlg).getByText(/the app never\s+opens the link/)).toBeInTheDocument();
    await user.type(within(dlg).getByLabelText("Excerpt"), text);
    await user.type(within(dlg).getByLabelText("Source"), "The Athletic");
    await user.type(within(dlg).getByLabelText(/Published/), "2026-11-19");
    await user.click(add);
    expect(await within(dlg).findByText(/Excerpt added\. It's marked unverified/)).toBeInTheDocument();
    expect(added).toEqual([{ id: base!.investigation_id,
      body: { text, source: "The Athletic", url: null, published_on: "2026-11-19" } }]);
    expect(within(dlg).getByText(/1 excerpt you pasted/)).toBeInTheDocument();
    expect(within(dlg).getByText(/Add an excerpt you've read \(1 added\)/)).toBeInTheDocument();
    // In the sources list: labelled, not a link (no URL given), text available, removable.
    await user.click(within(dlg).getByText("View full research"));
    expect(within(dlg).getByText(/you pasted · unverified/)).toBeInTheDocument();
    expect(within(dlg).queryByRole("link", { name: "Excerpt you pasted from The Athletic" })).not.toBeInTheDocument();
    await user.click(within(dlg).getByText("Show your excerpt"));
    expect(within(dlg).getByText(text)).toBeInTheDocument();
    await user.click(within(dlg).getByRole("button", { name: "Remove your excerpt from The Athletic" }));
    await waitFor(() => expect(within(dlg).queryByText(/1 excerpt you pasted/)).not.toBeInTheDocument());
  });

  it("background run: shows each stage, can cancel while waiting, and resumes a running job", async () => {
    const user = userEvent.setup();
    let progress: ((p: Progress) => void) | undefined;
    let finish: (() => void) | undefined;
    const cancelled: string[] = [];
    const runs: RunOptions[] = [];
    let preJob: ResearchJob | null = null;
    investigation.useSource({
      ...fixtureSource,
      preview: false,
      preflight: async (h) => ({ ...(await fixtureSource.preflight(h)), job: preJob }),
      run: (h, opts) => {
        runs.push(opts ?? {});
        progress = opts?.onProgress;
        return new Promise((resolve) => { finish = () => resolve(fixtureInvestigation(h)); });
      },
      cancel: async (id) => { cancelled.push(id); },
    });
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /Investigate YES/ }));
    const dlg = screen.getByRole("dialog");
    await user.click(await within(dlg).findByRole("button", { name: "Run investigation" }));
    expect(within(dlg).getByText("Investigating…")).toBeInTheDocument();
    act(() => progress!({ jobId: "job-9", phase: "queued", position: 2 }));
    expect(within(dlg).getByText("Waiting: 2 investigations ahead…")).toBeInTheDocument();
    expect(within(dlg).getByText(/you can close this and come back/)).toBeInTheDocument();
    await user.click(within(dlg).getByRole("button", { name: "Cancel" }));
    expect(cancelled).toEqual(["job-9"]);
    act(() => progress!({ jobId: "job-9", phase: "searching", position: 0 }));
    expect(within(dlg).getByText("Searching news…")).toBeInTheDocument();
    expect(within(dlg).queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument(); // running: can't cancel
    act(() => progress!({ jobId: "job-9", phase: "summarising", position: 0 }));
    expect(within(dlg).getByText(/Summarising with your local model/)).toBeInTheDocument();
    await act(async () => { finish!(); });
    expect(await within(dlg).findByText("View full research")).toBeInTheDocument();
    expect(runs).toHaveLength(1);
    // Reopening while a job is running: follow it (no Run button, no new job counted).
    investigation.reset();
    investigation.useSource({
      ...fixtureSource, preview: false,
      preflight: async (h) => ({ ...(await fixtureSource.preflight(h)), job: preJob }),
      run: (_h, opts) => { runs.push(opts ?? {}); return new Promise(() => {}); },
    });
    preJob = { id: "job-7", kind: "investigate", ticker: WIN.ticker, side: "yes", status: "running", phase: "searching",
      position: 0, created_at: "", started_at: null, finished_at: null, error: null, result: null };
    render(<Harness />);
    await user.click(screen.getAllByRole("button", { name: /Investigate YES/ }).at(-1)!);
    const dlg2 = screen.getAllByRole("dialog").at(-1)!;
    await waitFor(() => expect(runs.at(-1)?.jobId).toBe("job-7"));
    expect(within(dlg2).queryByRole("button", { name: "Run investigation" })).not.toBeInTheDocument();
    expect(investigation.get().runs).toBe(0); // resuming isn't a new run
  });

  it("the sample source has no paste box", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /Investigate YES/ }));
    const dlg = screen.getByRole("dialog");
    await user.click(await within(dlg).findByRole("button", { name: "Run investigation" }));
    await within(dlg).findByText("View full research");
    expect(within(dlg).queryByText(/Add an excerpt you've read/)).not.toBeInTheDocument();
  });

  it("runs with the CSRF header and the exact contract, and refreshes by id", async () => {
    const { apiSource } = await import("./store");
    stub({ quote: { ask: 0.66, side: "yes", observed_at: new Date().toISOString(), fresh: true, snapshot_ref: "c" },
      model: "Box-score history (frequency, checked when you run it)", cached: false, unsupported: null, usage },
    (h) => {
      const r = fixtureInvestigation(h);
      r.price_assessment = { ...r.price_assessment, model_p: 0.71, model_band: [0.58, 0.82],
        model_name: "Box-score history (frequency, not calibrated)", raw_diff: 0.034, conservative_edge: null };
      r.investigation_id = "inv-1";
      return r;
    });
    investigation.useSource(apiSource);
    investigation.setPollInterval(5);
    const user = userEvent.setup();
    render(<Harness leg={REB12} ev={towns} />);
    await user.click(screen.getByRole("button", { name: /Investigate YES/ }));
    const dlg = screen.getByRole("dialog");
    expect(within(dlg).queryByText(/Preview with sample research/)).not.toBeInTheDocument();
    expect(await within(dlg).findByText(/Box-score history \(frequency, checked when you run it\)/)).toBeInTheDocument();
    await user.click(within(dlg).getByRole("button", { name: "Run investigation" }));
    const price = await within(dlg).findByRole("region", { name: "Price lens" });
    expect(price).toHaveTextContent("History71¢ (range 58¢–82¢)");
    expect(price).toHaveTextContent("Box-score history (frequency, not calibrated)");
    expect(price).toHaveTextContent("+3.4 pts raw, not an edge");
    expect(price).toHaveTextContent("Not enough evidence to estimate an edge");
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.url).toBe("/api/research/jobs");
    expect(post.headers["X-KRT-Request"]).toBe("research");
    expect(post.body).toEqual({ kind: "investigate", ticker: REB12.ticker, side: "yes", label: REB12.label, investigation_id: null });
    expect(calls.some((c) => c.method === "GET" && c.url === "/api/research/jobs/job-1")).toBe(true); // polled, free
    await user.click(within(dlg).getByRole("button", { name: "Refresh research" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "POST")).toHaveLength(2));
    const again = calls.filter((c) => c.method === "POST")[1]!;
    expect(again.url).toBe("/api/research/jobs");
    expect(again.body).toMatchObject({ kind: "refresh", investigation_id: "inv-1" });
  });

  it("an unsupported answer from the server disables Run and says why", async () => {
    const { apiSource } = await import("./store");
    stub({ quote: { ask: 0.5, side: "yes", observed_at: null, fresh: false, snapshot_ref: null }, model: null,
      cached: false, unsupported: "Only single-game markets can be investigated.", usage }, (h) => fixtureInvestigation(h));
    investigation.useSource(apiSource);
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /Investigate YES/ }));
    expect(await screen.findByText("Only single-game markets can be investigated.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run investigation" })).toBeDisabled();
    expect(screen.getByText("stale")).toBeInTheDocument();
  });
});


describe("broader entry points (Phase E)", () => {
  it("browsing surfaces show no action for unsupported markets, and Investigate for NBA games", () => {
    const { container, rerender } = render(
      <InvestigateButton quiet leg={{ ticker: "KXCPI-26DEC-T3", side: "yes", label: "CPI", event: "KXCPI-26DEC" }} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<InvestigateButton quiet leg={SPREAD} />);
    expect(screen.getByRole("button", { name: "Investigate YES: Memphis wins by over 4.5 points" })).toBeInTheDocument();
  });
});
