import { useEffect, useState } from "react";

/** Typed hash router (no dependency). Every link that worked before Phase 2 still works:
 *   #/            -> Today (was Terminal; Terminal moved to #/terminal, "Tools")
 *   #/terminal    -> Tools, optional ?tab=<scanner|watchlist|signals|paper|models|system>
 *   #/games[?game=KX…-…], #/markets[?event=…]   -> Explore (unchanged URLs)
 *   #/history | #/journal                      -> Journal
 *   #/glossary[?term=id] | #/learn[?term=id]   -> Learn
 *   #/research/(opp|sig)/<id>, #/research/event/<event ticker> -> Research workspace
 * Anything unrecognised falls back to Today. Query values are validated, never trusted. */

export type TermTab = "scanner" | "watchlist" | "signals" | "paper" | "models" | "system";
export const TERM_TABS: readonly TermTab[] = ["scanner", "watchlist", "signals", "paper", "models", "system"];

export type Page = "today" | "games" | "markets" | "journal" | "learn" | "tools" | "research";
export type ResearchKind = "opp" | "sig" | "event";
/** Which rail item a page belongs to. */
export type Section = "today" | "explore" | "journal" | "learn" | "tools";

export type Route = {
  page: Page; term: string | null; event: string | null; game: string | null; tab: TermTab | null;
  research: { kind: ResearchKind; id: string } | null;
};

const base: Omit<Route, "page"> = { term: null, event: null, game: null, tab: null, research: null };
const ID_RE = /^[A-Za-z0-9-]{1,36}$/;
const EVENT_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$/;

export function sectionOf(page: Page): Section {
  if (page === "research") return "today"; // research is reached from Today's rows
  return page === "games" || page === "markets" ? "explore" : page;
}

export function parseHash(hash: string): Route {
  if (hash === "" || hash === "#" || hash === "#/" || hash === "#/today") return { ...base, page: "today" };
  if (hash === "#/history" || hash === "#/journal") return { ...base, page: "journal" };
  const t = /^#\/(?:terminal|tools)(?:\?tab=([a-z]{1,12}))?$/.exec(hash);
  if (t) {
    const tab = TERM_TABS.find((x) => x === t[1]) ?? null;
    return { ...base, page: "tools", tab };
  }
  const m = /^#\/(?:glossary|learn)(?:\?term=([a-z0-9-]{1,64}))?$/.exec(hash);
  if (m) return { ...base, page: "learn", term: m[1] ?? null };
  if (hash === "#/explore") return { ...base, page: "games" };
  const r = /^#\/research\/(opp|sig|event)\/([A-Za-z0-9._%-]{1,200})$/.exec(hash);
  if (r) {
    let id = "";
    try { id = decodeURIComponent(r[2]!); } catch { id = ""; }
    const kind = r[1] as ResearchKind;
    if (kind === "event" ? EVENT_RE.test(id) : ID_RE.test(id)) return { ...base, page: "research", research: { kind, id } };
    return { ...base, page: "today" };
  }
  const mg = /^#\/games(?:\?game=(KX[A-Z0-9]{2,20}-[A-Z0-9]{4,40}))?$/.exec(hash);
  if (mg) return { ...base, page: "games", game: mg[1] ?? null };
  const mk = /^#\/markets(?:\?event=([A-Za-z0-9._%-]{1,200}))?$/.exec(hash);
  if (mk) {
    let event: string | null = null;
    try { event = mk[1] ? decodeURIComponent(mk[1]) : null; } catch { event = null; }
    return { ...base, page: "markets",
      event: event && /^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$/.test(event) ? event : null };
  }
  return { ...base, page: "today" };
}

/** Canonical links. Builders validate their input the same way the parser does. */
export const href = {
  today: () => "#/",
  tools: (tab?: TermTab) => (tab ? `#/terminal?tab=${tab}` : "#/terminal"),
  game: (ref?: string | null) =>
    ref && /^KX[A-Z0-9]{2,20}-[A-Z0-9]{4,40}$/.test(ref) ? `#/games?game=${ref}` : "#/games",
  market: (event?: string | null) =>
    event && /^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$/.test(event)
      ? `#/markets?event=${encodeURIComponent(event)}` : "#/markets",
  journal: () => "#/journal",
  research: (kind: ResearchKind, id: string) =>
    (kind === "event" ? EVENT_RE.test(id) : ID_RE.test(id)) ? `#/research/${kind}/${encodeURIComponent(id)}` : "#/",
  learn: (term?: string) => (term && /^[a-z0-9-]{1,64}$/.test(term) ? `#/glossary?term=${term}` : "#/glossary"),
};

export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
