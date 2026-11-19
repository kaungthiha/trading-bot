import { api } from "../../api/client";
import type { GameSummary, OpenPosition, OpportunityCard, Signal } from "../../api/types";
import { href } from "../../router";
import type { Tone } from "../design/StatusLabel";
import { formatPrice } from "../format";
import { gameRef } from "../games/format";
import { triageKey } from "./triage";

/** One row on Today. `measure` is the source's OWN number with its own label; rows from
 * different sources are never sorted or compared against each other. */
export type Candidate = {
  key: string;
  title: string;
  sub: string | null;
  kind: string;
  tone: Tone;
  measureLabel: string;
  measure: string;
  measureSign: "pos" | "neg" | null;
  asOfLabel: string;
  asOf: string | null;
  closeLabel: string;
  closes: string | null;
  research: string;
  researchLabel: string;
};

export type SectionData = { items: Candidate[]; asOf: string | null; note: string | null };

export type SourceId = "positions" | "scanner" | "signals" | "games";

const num = (s: string | null | undefined) => (s == null || s === "" ? null : Number(s));
const cents = (s: string | null | undefined) => {
  const n = num(s);
  return n == null || Number.isNaN(n) ? "—" : `${Math.round(n * 100)}¢`;
};
const signed = (s: string | null | undefined) => {
  const n = num(s);
  if (n == null || Number.isNaN(n)) return { text: "—", sign: null };
  return { text: `${n > 0 ? "+" : n < 0 ? "−" : ""}$${Math.abs(n).toFixed(2)}`,
    sign: n > 0 ? "pos" as const : n < 0 ? "neg" as const : null };
};

// --- Your open positions: only the ones that need a look --------------------------------

export function needsAttention(p: OpenPosition): boolean {
  return p.flags.some((f) => f.level === "warn") || (p.hours_to_close != null && p.hours_to_close <= 24);
}

export function positionRow(p: OpenPosition): Candidate | null {
  const key = triageKey("pos", p.ticker);
  if (!key) return null;
  const u = signed(p.unrealized);
  const warn = p.flags.find((f) => f.level === "warn");
  return {
    key, title: p.title, sub: warn?.text ?? p.event_title,
    kind: [p.side.toUpperCase(), p.type && p.type !== "other" ? p.type.replace(/_/g, " ") : null]
      .filter(Boolean).join(" · "), tone: warn ? "warn" : "neutral",
    measureLabel: "Paid → now (mid)",
    measure: `${cents(p.avg_cost)} → ${cents(p.mid)} · ${u.text}`, measureSign: u.sign,
    asOfLabel: "priced", asOf: null, closeLabel: "closes", closes: p.close_at,
    research: p.game ? href.game(gameRef(p.game.prefix, p.game.game_key))
      : p.event_ticker ? href.research("event", p.event_ticker) : href.journal(),
    researchLabel: p.game ? "Open game" : p.event_ticker ? "Research event" : "Open journal",
  };
}

export async function loadPositions(): Promise<SectionData> {
  const a = await api.historyOpen();
  const items = a.positions.filter(needsAttention).map(positionRow)
    .filter((c): c is Candidate => c !== null);
  const rest = a.positions.length - items.length;
  return { items, asOf: a.as_of,
    note: a.positions.length === 0 ? "No open positions synced."
      : rest > 0 ? `${rest} other open position${rest === 1 ? "" : "s"} look on track.` : null };
}

// --- Scanner ideas (model-free mispricings) ---------------------------------------------

export function scannerRow(c: OpportunityCard): Candidate | null {
  const key = triageKey("opp", c.id);
  if (!key) return null;
  const pr = signed(c.profit);
  return {
    key, title: c.title, sub: c.event_ticker,
    kind: c.guaranteed ? "Guaranteed if rules hold" : "Conditional",
    tone: c.guaranteed ? "paper" : "warn",
    measureLabel: "Scanner profit after fees",
    measure: `${pr.text} · ${c.return_pct}% on ${formatPrice(c.cost)}`, measureSign: pr.sign,
    asOfLabel: "detected", asOf: c.detected_at, closeLabel: "expires", closes: c.expires_at,
    research: href.research("opp", c.id), researchLabel: "Research",
  };
}

export async function loadScanner(): Promise<SectionData> {
  const [cards, status] = await Promise.all([api.opportunities(), api.scannerStatus()]);
  const items = cards.filter((c) => c.status === "OPEN").map(scannerRow)
    .filter((c): c is Candidate => c !== null);
  return { items, asOf: status.last_scan?.at ?? null,
    note: status.paused ? "Scanner is paused." : status.note };
}

// --- Model signals ----------------------------------------------------------------------

export function signalRow(s: Signal): Candidate | null {
  const key = triageKey("sig", s.id);
  if (!key) return null;
  const e = num(s.lower_edge);
  const edge = e == null || Number.isNaN(e) ? "—"
    : `${e > 0 ? "+" : e < 0 ? "−" : ""}${Math.abs(e * 100).toFixed(1)}¢ per contract`;
  return {
    key, title: s.market_title,
    sub: [s.side ? `Buy ${s.side.toUpperCase()}` : null, s.model].filter(Boolean).join(" · ") || null,
    kind: "Model signal", tone: "neutral",
    measureLabel: "Conservative edge (model, after costs)",
    measure: edge, measureSign: e == null ? null : e > 0 ? "pos" : e < 0 ? "neg" : null,
    asOfLabel: "quote", asOf: s.quote_observed_at, closeLabel: "signal expires", closes: s.expires_at,
    research: href.research("sig", s.id), researchLabel: "Research",
  };
}

export async function loadSignals(): Promise<SectionData> {
  const all = await api.signals();
  const items = all.filter((s) => s.validity === "VALID" && s.decision !== "ABSTAIN")
    .map(signalRow).filter((c): c is Candidate => c !== null);
  return { items, asOf: null, note: null };
}

// --- Games starting soon (not screened: the Ideas tab does that on demand) ----------------

export function gameRow(g: GameSummary): Candidate | null {
  const ref = gameRef(g.prefix, g.game_key);
  const key = triageKey("game", ref);
  if (!key) return null;
  return {
    key, title: g.title, sub: g.sub_title || null, kind: g.league, tone: "neutral",
    measureLabel: "Not screened yet",
    measure: `${g.markets.toLocaleString()} markets · $${Math.round(g.volume_24h).toLocaleString()} vol 24h`,
    measureSign: null,
    asOfLabel: "priced", asOf: null, closeLabel: "starts", closes: g.occurs_at,
    research: href.game(ref), researchLabel: "Open game",
  };
}

export async function loadGames(now = Date.now()): Promise<SectionData> {
  const list = await api.games();
  // Upcoming only (a game that started 15+ minutes ago is no longer a pre-game decision);
  // the 10 most traded, then shown in start order.
  const soon = list.items.filter((g) => {
    const t = g.occurs_at ? Date.parse(g.occurs_at) : NaN;
    return !Number.isNaN(t) && t > now - 15 * 60_000 && t < now + 36 * 3600_000;
  }).sort((a, b) => b.volume_24h - a.volume_24h).slice(0, 10)
    .sort((a, b) => Date.parse(a.occurs_at!) - Date.parse(b.occurs_at!));
  return { items: soon.map(gameRow).filter((c): c is Candidate => c !== null), asOf: null,
    note: "Open a game's Ideas tab to screen it against box-score history." };
}

export const SOURCES: { id: SourceId; title: string; blurb: string; load: () => Promise<SectionData> }[] = [
  { id: "positions", title: "Your open positions",
    blurb: "Only positions with a warning or closing within 24 hours.", load: loadPositions },
  { id: "scanner", title: "Scanner ideas",
    blurb: "Price structures that pay if Kalshi's rules hold. Check every rule before acting.",
    load: loadScanner },
  { id: "signals", title: "Model signals",
    blurb: "Model estimate vs the live quote, after fees and slippage. A model can be wrong.",
    load: loadSignals },
  { id: "games", title: "Games starting soon",
    blurb: "The 10 most-traded games starting in the next 36 hours, by start time.", load: loadGames },
];
