import type { ComboLeg, InvestigationHypothesis, LegEvidence, MarketKind } from "../../api/types";

/** Turn the exact selected contract into a hypothesis. YES and NO, and different lines, are
 * different hypotheses: the key includes ticker AND side, and the statement says which.
 * Market type and line come from the box-score evidence when it's loaded, otherwise from the
 * ticker; never from the team name alone. */

const PROP = /^(PTS|REB|AST|3PT|BLK|STL|PRA|STOCK|2D|3D)/;
/** NFL stat props the backend covers ("Josh Allen: 250+"); PROT = protected, PRECISE = every yard. */
const NFL_PROP = /^(PASSYDS|RSHYDS|RECYDS|REC|PASSTDS|TD|PASSATT|PASSCOMP|PASSINT|RSHATT|RRYDS)(PROT|PRECISE)?$/;
// Halves, quarters and hockey periods: full-game data can't check them (NFL "2QBTTS" too).
const PERIOD = /^(1H|2H|1Q|2Q|3Q|4Q|1P|2P|3P)/;

/** Kalshi prefix -> league code. Longest first, so KXNCAAMB isn't read as anything shorter. */
const LEAGUE_PREFIXES: [string, string][] = [
  ["KXNCAAMB", "NCAAMB"], ["KXNCAAWB", "NCAAWB"], ["KXWNBA", "WNBA"], ["KXNBA", "NBA"], ["KXNHL", "NHL"], ["KXNFL", "NFL"],
  ["KXBUNDESLIGA", "BUNDESLIGA"], ["KXLALIGA", "LALIGA"], ["KXSERIEA", "SERIEA"], ["KXLIGUE1", "LIGUE1"],
  ["KXEPL", "EPL"], ["KXUCL", "UCL"], ["KXMLS", "MLS"],
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
  if (rest === "BTTS") return "btts";
  if (pre === "KXNFL") return NFL_PROP.test(rest) ? "player_prop" : "other";
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

/** Soccer leagues (top divisions and the Champions League). */
const SOCCER = ["EPL", "LALIGA", "BUNDESLIGA", "SERIEA", "LIGUE1", "UCL", "MLS"];
/** Soccer: match winner (three-way, incl. Tie), spread, totals, both teams to score. */
const SOCCER_KINDS = new Set<MarketKind>(["moneyline", "spread", "total", "team_total", "btts"]);

/** Leagues whose box scores and team matching are tested. Others fail gracefully with a reason. */
export const SUPPORTED_LEAGUES = new Set(["NBA", "WNBA", "NCAAMB", "NCAAWB", "NHL", "NFL", ...SOCCER]);
export const LEAGUE_NAME: Record<string, string> = {
  NBA: "NBA", WNBA: "WNBA", NCAAMB: "NCAA men's", NCAAWB: "NCAA women's", NHL: "NHL", NFL: "NFL",
  EPL: "EPL", LALIGA: "La Liga", BUNDESLIGA: "Bundesliga", SERIEA: "Serie A", LIGUE1: "Ligue 1",
  UCL: "Champions League", MLS: "MLS",
};
const SUPPORTED_KINDS = new Set<MarketKind>(["moneyline", "spread", "total", "team_total", "player_prop"]);
/** NHL: game winner, puck line and totals only (no periods or player props yet). */
const TEAM_KINDS = new Set<MarketKind>(["moneyline", "spread", "total", "team_total"]);

export function supportFor(leg: ComboLeg): { ok: true } | { ok: false; reason: string } {
  const league = leagueOf(leg.ticker);
  if (!league) {
    return { ok: false, reason: "Investigation covers NBA, WNBA, college basketball, NHL, NFL and soccer game markets; this market isn't one." };
  }
  if (!SUPPORTED_LEAGUES.has(league)) {
    return { ok: false, reason: `${league} isn't supported yet: player and team matching for it isn't tested.` };
  }
  const kind = marketKindFromSeries(leg.ticker.split("-")[0]!);
  if (league === "NHL" && !TEAM_KINDS.has(kind)) {
    return { ok: false, reason: "Only NHL game winner, puck line and totals can be investigated (no periods or player props yet)." };
  }
  if (league === "NFL" && !TEAM_KINDS.has(kind) && kind !== "player_prop") {
    return { ok: false, reason: "Only NFL game winner, spread, totals and player stat props can be investigated (no halves, quarters, first touchdown, ladders or longest plays)." };
  }
  // Defense/special-teams touchdown markets share the TD series but aren't player props.
  if (league === "NFL" && /DST-\d+$/.test(leg.ticker)) {
    return { ok: false, reason: "Defense/special-teams touchdown markets aren't covered." };
  }
  if (SOCCER.includes(league)) {
    if (!SOCCER_KINDS.has(kind)) {
      return { ok: false, reason: "Only soccer match winner, spread, totals and both-teams-to-score can be investigated (no halves, corners or correct score)." };
    }
  } else if (!SUPPORTED_KINDS.has(kind)) {
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
  const soc = SOCCER.includes(league ?? "");
  const tick = lineFromTicker(leg.ticker);
  // Kalshi NHL and NFL suffixes are "over N-0.5" (TOTAL-6 = over 5.5, SPREAD-BUF8 = by over 7.5).
  const threshold = market_type === "moneyline" || market_type === "btts" ? null
    : ev?.line ?? ((nhl || nfl || soc) && tick != null ? tick - 0.5 : tick);
  const statement = leg.side === "yes" ? leg.label : `NOT: ${leg.label} (betting it doesn't happen)`;
  return {
    ticker: leg.ticker, event_ticker: leg.event, side: leg.side, sport: nhl ? "hockey" : nfl ? "football" : soc ? "soccer" : "basketball",
    league: LEAGUE_NAME[leagueOf(leg.ticker) ?? ""] ?? "unknown", market_type, threshold,
    subject: ev?.subject?.name ?? null, label: leg.label, statement, snapshot_at: snapshotAt, rules_url: null,
  };
}

/** Cache / dedupe key: exact contract + side (+ line, implied by the ticker). */
export const hypothesisKey = (h: Pick<InvestigationHypothesis, "ticker" | "side">) => `${h.ticker}:${h.side}`;

export const MARKET_LABEL: Record<MarketKind, string> = {
  moneyline: "Game winner", spread: "Spread", total: "Game total", team_total: "Team total",
  player_prop: "Player prop", btts: "Both teams to score", other: "Other",
};
