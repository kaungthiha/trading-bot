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
  "base-rate": {
    id: "base-rate",
    label: "Base rate",
    aliases: ["prior frequency"],
    category: "quant",
    shortDefinition:
      "Historical frequency of an outcome before considering case-specific evidence.",
    example: "If similar events happened 30 of 100 times, starting base rate is 30%.",
    reviewedAt: REVIEWED,
    relatedTermIds: ["calibration"],
  },
  calibration: {
    id: "calibration",
    label: "Calibration",
    aliases: ["reliability"],
    category: "quant",
    shortDefinition: "How well forecast frequencies match realized outcome frequencies.",
    example: "Events forecast near 70% should occur about 70% of the time over many cases.",
    reviewedAt: REVIEWED,
    relatedTermIds: ["brier-score"],
  },
  "brier-score": {
    id: "brier-score",
    label: "Brier score",
    aliases: ["brier"],
    category: "quant",
    shortDefinition:
      "Mean squared difference between predicted probability and binary outcome; lower is better.",
    example: "A 0.70 forecast with a YES outcome contributes (0.70−1)^2 = 0.09.",
    formula: "mean((p − y)²)",
    reviewedAt: REVIEWED,
    relatedTermIds: ["log-loss", "calibration"],
  },
  "log-loss": {
    id: "log-loss",
    label: "Log loss",
    aliases: ["logarithmic score", "cross-entropy"],
    category: "quant",
    shortDefinition:
      "Scoring rule that strongly penalizes very confident wrong probability forecasts.",
    example: "Calling an impossible event 0% when it happens is penalized heavily.",
    formula: "−mean(y·ln p + (1−y)·ln(1−p))",
    reviewedAt: REVIEWED,
    relatedTermIds: ["brier-score"],
  },
  uncertainty: {
    id: "uncertainty",
    label: "Uncertainty",
    aliases: ["model uncertainty"],
    category: "quant",
    shortDefinition:
      "How unsure the model is about its estimate, distinct from the probability of the event.",
    example:
      "A 60% forecast based on five observations is less defensible than one with strong validation.",
    reviewedAt: REVIEWED,
    relatedTermIds: [],
  },
  "walk-forward-validation": {
    id: "walk-forward-validation",
    label: "Walk-forward validation",
    aliases: ["rolling-origin evaluation"],
    category: "quant",
    shortDefinition: "Repeatedly train on past periods and test on subsequent periods.",
    example: "Train Jan–Jun, test Jul; then train Jan–Jul, test Aug.",
    reviewedAt: REVIEWED,
    relatedTermIds: ["out-of-sample", "look-ahead-bias"],
  },
  "out-of-sample": {
    id: "out-of-sample",
    label: "Out-of-sample",
    aliases: ["holdout"],
    category: "quant",
    shortDefinition: "Data not used to fit or select a model in the relevant evaluation.",
    example: "Hold out later events to judge real forecasting performance.",
    reviewedAt: REVIEWED,
    relatedTermIds: ["walk-forward-validation"],
  },
  abstention: {
    id: "abstention",
    label: "Abstention",
    aliases: ["abstain"],
    category: "risk",
    shortDefinition:
      "Explicit decision not to issue a trade candidate because evidence or risk checks are insufficient.",
    example: "A stale quote or unclear resolution rule forces ABSTAIN.",
    reviewedAt: REVIEWED,
    relatedTermIds: [],
  },
  edge: {
    id: "edge",
    label: "Edge",
    aliases: ["model edge"],
    category: "trading",
    shortDefinition:
      "Estimated advantage of a trade over its current cost, after relevant assumptions.",
    example:
      "If modeled EV is $0.05 per contract, that is estimated edge, not guaranteed profit.",
    reviewedAt: REVIEWED,
    relatedTermIds: ["expected-value", "fees", "slippage"],
  },
  "expected-value": {
    id: "expected-value",
    label: "Expected value",
    aliases: ["EV"],
    category: "quant",
    shortDefinition: "Probability-weighted average gain or loss across possible outcomes.",
    example: "With p=.64, YES ask=.56 and costs=.03, modeled EV=$0.05.",
    formula: "EV_yes = p − ask − fee − slippage",
    reviewedAt: REVIEWED,
    relatedTermIds: ["edge"],
  },
  fees: {
    id: "fees",
    label: "Fees",
    aliases: ["trading fees"],
    category: "trading",
    shortDefinition:
      "Charges or rebates related to exchange trading or settlement under specific rules.",
    example: "A positive model edge can disappear after trading costs.",
    reviewedAt: REVIEWED,
    relatedTermIds: ["edge"],
  },
  slippage: {
    id: "slippage",
    label: "Slippage",
    aliases: ["execution slippage"],
    category: "trading",
    shortDefinition:
      "Difference between assumed and actual execution price, often due to depth or market movement.",
    example: "A $0.56 quoted ask could yield an average $0.57 fill for larger quantity.",
    reviewedAt: REVIEWED,
    relatedTermIds: ["orderbook-depth"],
  },
  "look-ahead-bias": {
    id: "look-ahead-bias",
    label: "Look-ahead bias",
    aliases: ["lookahead bias"],
    category: "quant",
    shortDefinition:
      "Using information in a historical simulation that was unavailable at decision time.",
    example:
      "Using revised inflation numbers before their revision date creates look-ahead bias.",
    reviewedAt: REVIEWED,
    relatedTermIds: [],
  },
} as const satisfies Record<string, GlossaryEntry>;

/** Only IDs present in TERMS type-check; unknown IDs are compile-time errors. */
export type TermId = keyof typeof TERMS;

export function getTerm(id: TermId): GlossaryEntry {
  return TERMS[id];
}

export const ALL_TERMS: readonly GlossaryEntry[] = Object.values(TERMS);
