import { useSyncExternalStore } from "react";

import { api } from "../../api/client";
import type { ExcerptInput, InvestigationHypothesis, InvestigationQuote, InvestigationResult, ResearchUsage } from "../../api/types";
import { type FixtureScenario, fixtureInvestigation, fixtureUsage } from "./fixture";
import { hypothesisKey } from "./hypothesis";

/** The drawer's state, and ONE canonical result per hypothesis. Running is explicit (a click)
 * and deduplicated: a second click, a re-render or StrictMode's double effects reuse the
 * in-flight job. Expanding "full research" only reads the stored result.
 *
 * Phase A uses a fixture source; `source` is the seam where the API plugs in (Phases C–D). */

/** What the drawer shows before running: unmetered (no search, no model call). */
export interface Preflight {
  quote: InvestigationQuote; model: string | null; usage: ResearchUsage; cached: boolean;
  unsupported?: string | null;
}

export interface ResearchSource {
  usage(): Promise<ResearchUsage>;
  preflight(h: InvestigationHypothesis): Promise<Preflight>;
  run(h: InvestigationHypothesis, opts?: { refreshId?: string }): Promise<InvestigationResult>;
  /** Pasted excerpts (absent on the sample source: the paste box is hidden). */
  addExcerpt?(id: string, body: ExcerptInput): Promise<InvestigationResult>;
  removeExcerpt?(id: string, excerptId: string): Promise<InvestigationResult>;
  readonly preview: boolean; // true = sample data, labelled in the UI
}

let scenario: FixtureScenario = "ok";
export const fixtureSource: ResearchSource = {
  preview: true,
  usage: async () => fixtureUsage(scenario),
  preflight: async (h) => ({
    quote: { ask: h.side === "yes" ? 0.34 : 0.67, side: h.side,
      observed_at: new Date(Date.now() - 12 * 60_000).toISOString(), fresh: true, snapshot_ref: "sample" },
    model: null, usage: fixtureUsage(scenario), cached: false,
  }),
  run: (h) => new Promise((resolve) => setTimeout(() => resolve(fixtureInvestigation(h, scenario)), 450)),
};

/** The real thing: the backend's canonical, stored result. */
export const apiSource: ResearchSource = {
  preview: false,
  usage: () => api.researchUsage(),
  preflight: (h) => api.researchPreflight(h.ticker, h.side),
  run: (h, opts) => (opts?.refreshId ? api.refreshInvestigation(opts.refreshId)
    : api.investigate(h.ticker, h.side, h.label)),
  addExcerpt: (id, body) => api.addExcerpt(id, body),
  removeExcerpt: (id, excerptId) => api.removeExcerpt(id, excerptId),
};

type Entry = { status: "running" } | { status: "done"; result: InvestigationResult } | { status: "error"; message: string };

type State = {
  open: InvestigationHypothesis | null;
  entries: Record<string, Entry>;
  runs: number; // jobs actually started (tests assert no duplicates)
};

let state: State = { open: null, entries: {}, runs: 0 };
let source: ResearchSource = apiSource;
let returnFocus: HTMLElement | null = null;
const inflight = new Map<string, Promise<void>>();
const subs = new Set<() => void>();
const set = (next: Partial<State>) => { state = { ...state, ...next }; subs.forEach((f) => f()); };

export const investigation = {
  get: () => state,
  source: () => source,
  open(h: InvestigationHypothesis, trigger?: HTMLElement | null) {
    returnFocus = trigger ?? (document.activeElement as HTMLElement | null);
    set({ open: h });
  },
  close() {
    set({ open: null });
    const el = returnFocus;
    returnFocus = null;
    if (el && document.contains(el)) setTimeout(() => el.focus(), 0);
  },
  /** Explicit user action only. Returns the existing job if one is running. */
  run(h: InvestigationHypothesis, opts: { refresh?: boolean } = {}): Promise<void> {
    const key = hypothesisKey(h);
    const cur = state.entries[key];
    if (inflight.has(key)) return inflight.get(key)!;
    if (cur?.status === "done" && !opts.refresh) return Promise.resolve();
    set({ entries: { ...state.entries, [key]: { status: "running" } }, runs: state.runs + 1 });
    const refreshId = opts.refresh && cur?.status === "done" ? cur.result.investigation_id : undefined;
    const job = source.run(h, refreshId ? { refreshId } : undefined).then(
      (result) => { set({ entries: { ...state.entries, [key]: { status: "done", result } } }); },
      (e: unknown) => { set({ entries: { ...state.entries, [key]: { status: "error",
        message: e instanceof Error ? e.message : "Investigation failed" } } }); },
    ).finally(() => { inflight.delete(key); });
    inflight.set(key, job);
    return job;
  },
  /** Replace a finished result (after adding or removing an excerpt). */
  update(h: InvestigationHypothesis, result: InvestigationResult) {
    set({ entries: { ...state.entries, [hypothesisKey(h)]: { status: "done", result } } });
  },
  /** Tests / Phase C wiring. */
  useSource(s: ResearchSource) { source = s; },
  setScenario(s: FixtureScenario) { scenario = s; },
  reset() { state = { open: null, entries: {}, runs: 0 }; inflight.clear(); returnFocus = null; source = fixtureSource; scenario = "ok"; subs.forEach((f) => f()); },
};

function subscribe(f: () => void) { subs.add(f); return () => { subs.delete(f); }; }
export function useInvestigation(): State {
  return useSyncExternalStore(subscribe, investigation.get, investigation.get);
}
