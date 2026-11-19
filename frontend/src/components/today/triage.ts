import { useCallback, useEffect, useState } from "react";

/** Your triage marks on Today's candidates: "researching", "passed" and a short note.
 * Stored only in this browser (localStorage); nothing is sent anywhere. The server has no
 * concept of these states, so the page never invents them: an unmarked item is "to review".
 * Stored data is treated as untrusted on read: wrong shapes are dropped, notes are capped and
 * rendered as plain text by React, and entries older than 30 days are pruned. */

export type TriageStatus = "researching" | "passed";
export type TriageEntry = { status: TriageStatus | null; note: string; at: string };
export type TriageMap = Record<string, TriageEntry>;

export const TRIAGE_KEY = "krt.triage.v1";
export const NOTE_MAX = 280;
const KEY_RE = /^(pos|opp|sig|game):[A-Za-z0-9._:-]{1,200}$/;
const MAX_AGE_MS = 30 * 24 * 3600 * 1000;
const EVENT = "krt:triage";

export function loadTriage(now = Date.now()): TriageMap {
  let raw: unknown;
  try {
    raw = JSON.parse(localStorage.getItem(TRIAGE_KEY) ?? "{}");
  } catch {
    return {};
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out: TriageMap = {};
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    if (!KEY_RE.test(k) || !v || typeof v !== "object") continue;
    const e = v as Record<string, unknown>;
    const status = e.status === "researching" || e.status === "passed" ? e.status : null;
    const note = typeof e.note === "string" ? e.note.slice(0, NOTE_MAX) : "";
    const at = typeof e.at === "string" ? e.at : "";
    const t = Date.parse(at);
    if (Number.isNaN(t) || now - t > MAX_AGE_MS) continue;
    if (status === null && !note) continue;
    out[k] = { status, note, at };
  }
  return out;
}

function save(map: TriageMap): void {
  try {
    localStorage.setItem(TRIAGE_KEY, JSON.stringify(map));
  } catch { /* storage full or blocked: marks just won't persist */ }
  window.dispatchEvent(new CustomEvent(EVENT));
}

export function triageKey(kind: "pos" | "opp" | "sig" | "game", id: string): string | null {
  const k = `${kind}:${id}`;
  return KEY_RE.test(k) ? k : null;
}

/** Shared across components and browser tabs. */
export function useTriage(): [TriageMap, (key: string, patch: Partial<Omit<TriageEntry, "at">>) => void] {
  const [map, setMap] = useState<TriageMap>(() => loadTriage());
  useEffect(() => {
    const reload = () => setMap(loadTriage());
    window.addEventListener(EVENT, reload);
    window.addEventListener("storage", reload);
    return () => {
      window.removeEventListener(EVENT, reload);
      window.removeEventListener("storage", reload);
    };
  }, []);
  const update = useCallback((key: string, patch: Partial<Omit<TriageEntry, "at">>) => {
    if (!KEY_RE.test(key)) return;
    const cur = loadTriage();
    const prev = cur[key] ?? { status: null, note: "" };
    const next = { ...prev, ...patch, note: (patch.note ?? prev.note).slice(0, NOTE_MAX),
      at: new Date().toISOString() };
    if (next.status === null && !next.note) delete cur[key];
    else cur[key] = next;
    save(cur);
  }, []);
  return [map, update];
}
