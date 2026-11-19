import type { ReactNode } from "react";

/** A status pill. Colour is never the only signal: the text says the state, and tones that
 * mean "act on this" (stale, warn) also carry a glyph. Reuses the existing .badge classes. */
export type Tone = "neutral" | "paper" | "ok" | "warn" | "stale" | "demo";

const MARK: Partial<Record<Tone, string>> = { ok: "●", warn: "▲", stale: "!" };

export function StatusLabel({ tone = "neutral", title, children }: {
  tone?: Tone; title?: string; children: ReactNode }) {
  const mark = MARK[tone];
  return (
    <span className={`badge status ${tone}`} title={title}>
      {mark && <span className="status-mark" aria-hidden="true">{mark}</span>}
      {children}
    </span>
  );
}
