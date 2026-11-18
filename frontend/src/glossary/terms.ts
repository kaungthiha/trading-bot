// Central glossary registry (milestone-01 placeholder subset).
//
// Canonical IDs and wording come from the spec pack's docs/GLOSSARY.md. Milestone 07
// expands this to the full 42+ term registry with deep explanations and sources.
// Never write ad-hoc definitions in components -- reference a TermId instead.

export type TermCategory = "market" | "trading" | "quant" | "risk" | "contract";

export interface GlossaryEntry {
  id: string;
  label: string;
  aliases: readonly string[];
  category: TermCategory;
  shortDefinition: string;
  example: string;
  deepExplanation?: string;
  formula?: string;
  sourceUrls?: readonly string[];
  reviewedAt: string; // ISO date of last editorial review
  relatedTermIds: readonly string[];
}

const REVIEWED = "2026-11-18";

export const TERMS = {
  bid: {
    id: "bid",
    label: "Bid",
    aliases: ["best bid"],
    category: "market",
    shortDefinition: "Highest advertised price a buyer currently offers for a contract.",
    example: "A YES bid of $0.54 means someone is offering $0.54 for YES.",
    reviewedAt: REVIEWED,
    relatedTermIds: ["ask", "spread"],
  },
  ask: {
    id: "ask",
    label: "Ask",
    aliases: ["offer", "best ask"],
    category: "market",
    shortDefinition:
      "Lowest price currently available to a buyer, when an opposing order exists. Here, asks are derived from the opposite side's best bid.",
    example: "A YES ask of $0.56 is the price a buyer might pay for one YES contract.",
    formula: "YES ask = payout − best NO bid",
    reviewedAt: REVIEWED,
    relatedTermIds: ["bid", "spread"],
  },
  spread: {
    id: "spread",
    label: "Spread",
    aliases: ["bid-ask spread"],
    category: "market",
    shortDefinition: "Difference between best ask and best bid for the same contract.",
    example: "Bid $0.54, ask $0.56 → a $0.02 spread.",
    formula: "spread = ask − bid",
    reviewedAt: REVIEWED,
    relatedTermIds: ["bid", "ask"],
  },
  "orderbook-depth": {
    id: "orderbook-depth",
    label: "Orderbook depth",
    aliases: ["depth", "book depth"],
    category: "market",
    shortDefinition: "Quantity available at each quoted price level.",
    example: "Ten contracts at $0.56 and five at $0.57 give limited depth.",
    reviewedAt: REVIEWED,
    relatedTermIds: ["bid", "ask"],
  },
  "tick-size": {
    id: "tick-size",
    label: "Tick size",
    aliases: ["price grid", "price increment"],
    category: "market",
    shortDefinition: "Smallest permitted price increment for that market and price range.",
    example: "A venue may permit fractional-cent increments; inspect the contract grid.",
    reviewedAt: REVIEWED,
    relatedTermIds: [],
  },
  "binary-contract": {
    id: "binary-contract",
    label: "Binary contract",
    aliases: ["event contract"],
    category: "contract",
    shortDefinition: "Contract that pays according to a YES/NO event resolution.",
    example: "One winning contract may pay $1 under the specified contract terms.",
    reviewedAt: REVIEWED,
    relatedTermIds: ["resolution"],
  },
  resolution: {
    id: "resolution",
    label: "Resolution",
    aliases: ["outcome determination"],
    category: "contract",
    shortDefinition: "Determination of the contract outcome according to official rules.",
    example: "A market can close before its final YES/NO outcome is determined.",
    reviewedAt: REVIEWED,
    relatedTermIds: ["binary-contract"],
  },
} as const satisfies Record<string, GlossaryEntry>;

/** Only IDs present in TERMS type-check; unknown IDs are compile-time errors. */
export type TermId = keyof typeof TERMS;

export function getTerm(id: TermId): GlossaryEntry {
  return TERMS[id];
}

export const ALL_TERMS: readonly GlossaryEntry[] = Object.values(TERMS);
