import { useSyncExternalStore } from "react";

import type { ComboLeg } from "../../api/types";
import { isLeg } from "../games/slip";

/** Research you saved from the Docket: the legs, your decision (watch / pass), why, and a
 * snapshot of the price at the time. Browser-only (localStorage), never sent anywhere.
 * Read back as untrusted: shapes are validated, notes capped, old entries pruned. */
export type Decision = "watch" | "pass";
export type SavedDocket = {
  id: string; at: string; decision: Decision; note: string; legs: ComboLeg[];
  /** Fair price when saved (independent, from market prices): a snapshot, not live. */
  fair: number | null;
};

export const SAVED_KEY = "krt.dockets.v1";
export const SAVED_MAX = 25;
export const NOTE_MAX = 280;
const MAX_AGE_MS = 60 * 24 * 3600 * 1000;
const ID = /^[a-z0-9]{6,24}$/;

function parse(now = Date.now()): SavedDocket[] {
  let raw: unknown;
  try { raw = JSON.parse(localStorage.getItem(SAVED_KEY) ?? "[]"); } catch { return []; }
  if (!Array.isArray(raw)) return [];
  const out: SavedDocket[] = [];
  for (const x of raw) {
    if (!x || typeof x !== "object") continue;
    const e = x as Record<string, unknown>;
    const t = typeof e.at === "string" ? Date.parse(e.at) : NaN;
    if (typeof e.id !== "string" || !ID.test(e.id) || Number.isNaN(t) || now - t > MAX_AGE_MS) continue;
    if (e.decision !== "watch" && e.decision !== "pass") continue;
    const legs = Array.isArray(e.legs) ? e.legs.filter(isLeg).slice(0, 12) : [];
    if (legs.length === 0) continue;
    const fair = typeof e.fair === "number" && e.fair > 0 && e.fair < 1 ? e.fair : null;
    out.push({ id: e.id, at: e.at as string, decision: e.decision, legs, fair,
      note: typeof e.note === "string" ? e.note.slice(0, NOTE_MAX) : "" });
  }
  return out.slice(0, SAVED_MAX);
}

let items: SavedDocket[] = parse();
const subs = new Set<() => void>();
function write(next: SavedDocket[]) {
  items = next.slice(0, SAVED_MAX);
  try { localStorage.setItem(SAVED_KEY, JSON.stringify(items)); } catch { /* memory only */ }
  subs.forEach((f) => f());
}

function newId(): string {
  const a = new Uint32Array(2);
  crypto.getRandomValues(a);
  return Array.from(a, (n) => n.toString(36)).join("").padEnd(6, "0").slice(0, 16);
}

export const saved = {
  get: () => items,
  add(d: { decision: Decision; note: string; legs: ComboLeg[]; fair: number | null }): SavedDocket | null {
    const legs = d.legs.filter(isLeg).slice(0, 12);
    if (legs.length === 0) return null;
    const e: SavedDocket = { id: newId(), at: new Date().toISOString(), decision: d.decision,
      note: d.note.trim().slice(0, NOTE_MAX), legs,
      fair: d.fair != null && d.fair > 0 && d.fair < 1 ? d.fair : null };
    write([e, ...items]);
    return e;
  },
  remove: (id: string) => write(items.filter((x) => x.id !== id)),
  /** Re-read storage (another tab, or tests). */
  reload: () => { items = parse(); subs.forEach((f) => f()); },
};

function subscribe(f: () => void) {
  subs.add(f);
  const onStorage = (e: StorageEvent) => { if (e.key === SAVED_KEY) saved.reload(); };
  window.addEventListener("storage", onStorage);
  return () => { subs.delete(f); window.removeEventListener("storage", onStorage); };
}

export function useSaved(): SavedDocket[] {
  return useSyncExternalStore(subscribe, saved.get, saved.get);
}

export const docketTitle = (legs: ComboLeg[]) =>
  legs.length === 1 ? legs[0]!.label : `${legs.length}-leg combo: ${legs.map((l) => l.label).join(" + ")}`;
