import { useSyncExternalStore } from "react";

import type { ComboLeg, Side } from "../../api/types";

/** One bet slip shared by the Games and Markets pages, kept in localStorage so it survives
 * a reload. Only tickers, sides and labels are stored: nothing sensitive. */
const KEY = "krt.slip.v1";
const MAX = 12;
const TICKER = /^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$/;

function valid(x: unknown): x is ComboLeg {
  if (!x || typeof x !== "object") return false;
  const l = x as Record<string, unknown>;
  return typeof l.ticker === "string" && TICKER.test(l.ticker) && (l.side === "yes" || l.side === "no")
    && typeof l.label === "string" && l.label.length <= 300 && typeof l.event === "string"
    && TICKER.test(l.event);
}

function load(): ComboLeg[] {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "[]") as unknown;
    return Array.isArray(raw) ? raw.filter(valid).slice(0, MAX) : [];
  } catch {
    return [];
  }
}

let legs: ComboLeg[] = load();
const subs = new Set<() => void>();

function set(next: ComboLeg[]) {
  legs = next;
  try { localStorage.setItem(KEY, JSON.stringify(legs)); } catch { /* private mode: memory only */ }
  subs.forEach((f) => f());
}

export const slip = {
  get: () => legs,
  has: (ticker: string) => legs.some((l) => l.ticker === ticker),
  add(leg: ComboLeg) {
    if (legs.length >= MAX && !slip.has(leg.ticker)) return;
    set([...legs.filter((l) => l.ticker !== leg.ticker), leg]);
  },
  toggle(leg: ComboLeg) {
    if (slip.has(leg.ticker)) slip.remove(leg.ticker);
    else slip.add(leg);
  },
  remove: (ticker: string) => set(legs.filter((l) => l.ticker !== ticker)),
  setSide: (ticker: string, side: Side) => set(legs.map((l) => (l.ticker === ticker ? { ...l, side } : l))),
  clear: () => set([]),
  max: MAX,
};

function subscribe(f: () => void) {
  subs.add(f);
  const onStorage = (e: StorageEvent) => { if (e.key === KEY) { legs = load(); f(); } };
  window.addEventListener("storage", onStorage);
  return () => { subs.delete(f); window.removeEventListener("storage", onStorage); };
}

export function useSlip(): ComboLeg[] {
  return useSyncExternalStore(subscribe, slip.get, slip.get);
}
