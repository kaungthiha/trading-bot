import type { ComboLeg, InvestigationHypothesis, LegEvidence, MarketKind } from "../../api/types";

/** Turn the exact selected contract into a hypothesis. YES and NO, and different lines, are
 * different hypotheses: the key includes ticker AND side, and the statement says which.
 * Market type and line come from the box-score evidence when it's loaded, otherwise from the
 * ticker; never from the team name alone. */

const PROP = /^(PTS|REB|AST|3PT|BLK|STL|PRA|STOCK|2D|3D)/;
// Halves, quarters and hockey periods: full-game data can't check them (NFL "2QBTTS" too).
const PERIOD = /^(1H|2H|1Q|2Q|3Q|4Q|1P|2P|3P)/;

/** Kalshi prefix -> league code. Longest first, so KXNCAAMB isn't read as anything shorter. */
const LEAGUE_PREFIXES: [string, string][] = [
  ["KXNCAAMB", "NCAAMB"], ["KXNCAAWB", "NCAAWB"], ["KXWNBA", "WNBA"], ["KXNBA", "NBA"], ["KXNHL", "NHL"], ["KXNFL", "NFL"],
];

/** Kind from the series suffix after the league prefix. Halves and quarters are "other":
 * full-game box scores can't check them. */
export function marketKindFromSeries(series: string): MarketKind {
  const s = series.toUpperCase();
  const pre = LEAGUE_PREFIXES.find(([p]) => s.startsWith(p))?.[0] ?? "";
  const rest = s.slice(pre.length);
  if (PERIOD.test(rest)) return "other";
  if (rest.endsWith("TEAMTOTAL")) return "team_total";
  if (rest.endsWith("SPREAD")) return "spread";
  if (rest.endsWith("TOTAL")) return "total";
  if (rest === "GAME") return "moneyline";
  if (PROP.test(rest)) return "player_prop";
  return "other";
}

const KIND_FROM_EVIDENCE: Record<string, MarketKind> = {
  team_win: "moneyline", team_margin: "spread", game_total: "total", team_total: "team_total",
  player_stat: "player_prop",
};

export function leagueOf(ticker: string): string | null {
  return LEAGUE_PREFIXES.find(([p]) => ticker.startsWith(p))?.[1] ?? null;
}

/** Leagues whose box scores and team matching are tested. Others fail gracefully with a reason. */
export const SUPPORTED_LEAGUES = new Set(["NBA", "WNBA", "NCAAMB", "NCAAWB", "NHL", "NFL"]);
export const LEAGUE_NAME: Record<string, string> = {
  NBA: "NBA", WNBA: "WNBA", NCAAMB: "NCAA men's", NCAAWB: "NCAA women's", NHL: "NHL", NFL: "NFL",
};
const SUPPORTED_KINDS = new Set<MarketKind>(["moneyline", "spread", "total", "team_total", "player_prop"]);
/** NHL and NFL: game winner, spread and totals only (no periods, halves or player props yet). */
const TEAM_KINDS = new Set<MarketKind>(["moneyline", "spread", "total", "team_total"]);

export function supportFor(leg: ComboLeg): { ok: true } | { ok: false; reason: string } {
  const league = leagueOf(leg.ticker);
  if (!league) {
    return { ok: false, reason: "Investigation covers NBA, WNBA, college basketball, NHL and NFL game markets; this market isn't one." };
  }
  if (!SUPPORTED_LEAGUES.has(league)) {
    return { ok: false, reason: `${league} isn't supported yet: player and team matching for it isn't tested.` };
  }
  const kind = marketKindFromSeries(leg.ticker.split("-")[0]!);
  if (league === "NHL" && !TEAM_KINDS.has(kind)) {
    return { ok: false, reason: "Only NHL game winner, puck line and totals can be investigated (no periods or player props yet)." };
  }
  if (league === "NFL" && !TEAM_KINDS.has(kind)) {
    return { ok: false, reason: "Only NFL game winner, spread and totals can be investigated (no halves, quarters or player props yet)." };
  }
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
  const league = leagueOf(leg.ticker);
  const nhl = league === "NHL";
  const nfl = league === "NFL";
  const tick = lineFromTicker(leg.ticker);
  // Kalshi NHL and NFL suffixes are "over N-0.5" (TOTAL-6 = over 5.5, SPREAD-BUF8 = by over 7.5).
  const threshold = market_type === "moneyline" ? null
    : ev?.line ?? ((nhl || nfl) && tick != null ? tick - 0.5 : tick);
  const statement = leg.side === "yes" ? leg.label : `NOT: ${leg.label} (betting it doesn't happen)`;
  return {
    ticker: leg.ticker, event_ticker: leg.event, side: leg.side, sport: nhl ? "hockey" : nfl ? "football" : "basketball",
    league: LEAGUE_NAME[leagueOf(leg.ticker) ?? ""] ?? "unknown", market_type, threshold,
    subject: ev?.subject?.name ?? null, label: leg.label, statement, snapshot_at: snapshotAt, rules_url: null,
  };
}

/** Cache / dedupe key: exact contract + side (+ line, implied by the ticker). */
export const hypothesisKey = (h: Pick<InvestigationHypothesis, "ticker" | "side">) => `${h.ticker}:${h.side}`;

export const MARKET_LABEL: Record<MarketKind, string> = {
  moneyline: "Game winner", spread: "Spread", total: "Game total", team_total: "Team total",
  player_prop: "Player prop", other: "Other",
};
