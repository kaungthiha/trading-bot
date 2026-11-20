import type { ComboLeg, InvestigationHypothesis, LegEvidence, MarketKind } from "../../api/types";

/** Turn the exact selected contract into a hypothesis. YES and NO, and different lines, are
 * different hypotheses: the key includes ticker AND side, and the statement says which.
 * Market type and line come from the box-score evidence when it's loaded, otherwise from the
 * ticker; never from the team name alone. */

const PROP = /(PTS|REB|AST|3PT|BLK|STL|PRA)/;

export function marketKindFromSeries(series: string): MarketKind {
  const s = series.toUpperCase();
  if (s.includes("SPREAD")) return "spread";
  if (s.includes("TEAMTOTAL")) return "team_total";
  if (s.includes("TOTAL")) return "total";
  if (PROP.test(s.replace(/^KXW?NBA/, ""))) return "player_prop";
  if (s.endsWith("GAME")) return "moneyline";
  return "other";
}

const KIND_FROM_EVIDENCE: Record<string, MarketKind> = {
  team_win: "moneyline", team_margin: "spread", game_total: "total", team_total: "team_total",
  player_stat: "player_prop",
};

export function leagueOf(ticker: string): string | null {
  if (/^KXNBA/.test(ticker)) return "NBA";
  if (/^KXWNBA/.test(ticker)) return "WNBA";
  if (/^KXNHL/.test(ticker)) return "NHL";
  if (/^KXNCAAMB/.test(ticker)) return "NCAAMB";
  return null;
}

/** NBA first (as specified). Other leagues fail gracefully with a reason. */
export const SUPPORTED_LEAGUES = new Set(["NBA"]);
const SUPPORTED_KINDS = new Set<MarketKind>(["moneyline", "spread", "total", "team_total", "player_prop"]);

export function supportFor(leg: ComboLeg): { ok: true } | { ok: false; reason: string } {
  const league = leagueOf(leg.ticker);
  if (!league) return { ok: false, reason: "Investigation covers NBA game markets for now; this market isn't one." };
  if (!SUPPORTED_LEAGUES.has(league)) {
    return { ok: false, reason: `${league} isn't supported yet: player and team matching for it isn't tested.` };
  }
  const kind = marketKindFromSeries(leg.ticker.split("-")[0]!);
  if (!SUPPORTED_KINDS.has(kind)) {
    return { ok: false, reason: "Only game winner, spread, totals and player props can be investigated." };
  }
  // Season-long markets (MVP, champion) have no game date in the event ticker.
  if (!/-\d{2}[A-Z]{3}\d{2}/.test(leg.event)) return { ok: false, reason: "Only single-game markets can be investigated." };
  return { ok: true };
}

function lineFromTicker(ticker: string): number | null {
  const m = /(\d+(?:\.\d+)?)$/.exec(ticker.split("-").pop() ?? "");
  return m ? Number(m[1]) : null;
}

export function buildHypothesis(leg: ComboLeg, ev: LegEvidence | undefined, snapshotAt: string | null): InvestigationHypothesis {
  const series = leg.ticker.split("-")[0]!;
  const market_type = (ev?.kind && KIND_FROM_EVIDENCE[ev.kind]) || marketKindFromSeries(series);
  // A game-winner market has no line (box-score evidence reports 0 for it).
  const threshold = market_type === "moneyline" ? null : ev?.line ?? lineFromTicker(leg.ticker);
  const statement = leg.side === "yes" ? leg.label : `NOT: ${leg.label} (betting it doesn't happen)`;
  return {
    ticker: leg.ticker, event_ticker: leg.event, side: leg.side, sport: "basketball",
    league: leagueOf(leg.ticker) ?? "unknown", market_type, threshold,
    subject: ev?.subject?.name ?? null, label: leg.label, statement, snapshot_at: snapshotAt, rules_url: null,
  };
}

/** Cache / dedupe key: exact contract + side (+ line, implied by the ticker). */
export const hypothesisKey = (h: Pick<InvestigationHypothesis, "ticker" | "side">) => `${h.ticker}:${h.side}`;

export const MARKET_LABEL: Record<MarketKind, string> = {
  moneyline: "Game winner", spread: "Spread", total: "Game total", team_total: "Team total",
  player_prop: "Player prop", other: "Other",
};
