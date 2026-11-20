// Central glossary registry -- the single source of truth for every definition in the UI.
//
// Canonical IDs, `shortDefinition` and `example` come from the spec pack's docs/GLOSSARY.md
// (a test enforces that each short definition starts with the canonical wording). Deep
// explanations answer: What does it mean? Why does it matter here? What could mislead me?
// The backend serves an exported copy (npm run glossary:export -> backend/app/glossary.json);
// a test fails if that copy is stale. Never write ad-hoc definitions in components.

export type TermCategory = "market" | "trading" | "quant" | "risk" | "contract" | "data";

export interface GlossaryEntry {
  id: string;
  label: string;
  aliases: readonly string[];
  category: TermCategory;
  shortDefinition: string; // <= 200 chars, plain English
  example: string;
  deepExplanation: string;
  formula?: string;
  sourceUrls?: readonly string[];
  reviewedAt: string; // ISO date of last editorial review
  relatedTermIds: readonly string[];
}

const REVIEWED = "2026-11-18";
const KALSHI_ORDERBOOK = "https://docs.kalshi.com/getting_started/orderbook_responses.md";
const KALSHI_FEES = "https://docs.kalshi.com/getting_started/fee_rounding.md";
const KALSHI_LIFECYCLE = "https://docs.kalshi.com/getting_started/market_lifecycle.md";
const ALFRED = "https://fred.stlouisfed.org/docs/api/fred/realtime_period.html";

export const TERMS = {
  // --- Market structure -----------------------------------------------------------------
  bid: {
    id: "bid", label: "Bid", aliases: ["best bid"], category: "market",
    shortDefinition: "Highest advertised price a buyer currently offers for a contract.",
    example: "A YES bid of $0.54 means someone is offering $0.54 for YES.",
    deepExplanation:
      "The bid is what you could SELL into right now. Kalshi publishes only bids (for YES and for NO), so this app shows raw bids and derives asks from them. Why it matters: open positions are valued at the bid, not the last trade, because that is what you could actually get. What could mislead you: a bid for one contract tells you little about selling fifty -- check depth.",
    sourceUrls: [KALSHI_ORDERBOOK], reviewedAt: REVIEWED,
    relatedTermIds: ["ask", "spread", "orderbook-depth"],
  },
  ask: {
    id: "ask", label: "Ask", aliases: ["offer", "best ask"], category: "market",
    shortDefinition:
      "Lowest price currently available to a buyer, when an opposing order exists. Here, asks are derived from the opposite side's best bid.",
    example: "A YES ask of $0.56 is the price a buyer might pay for one YES contract.",
    deepExplanation:
      "The ask is what you would PAY to buy now. Because a NO bid at p is economically an offer to sell YES at $1 − p, the YES ask is derived from the best NO bid (and vice versa). Why it matters: every expected-value calculation here uses the ask, never the midpoint. What could mislead you: if the opposite side has no bids, there is no ask at all -- the app shows a dash rather than inventing one.",
    formula: "YES ask = payout − best NO bid; NO ask = payout − best YES bid",
    sourceUrls: [KALSHI_ORDERBOOK], reviewedAt: REVIEWED,
    relatedTermIds: ["bid", "spread", "derived-ask"],
  },
  spread: {
    id: "spread", label: "Spread", aliases: ["bid-ask spread"], category: "market",
    shortDefinition: "Difference between best ask and best bid for the same contract.",
    example: "Bid $0.54, ask $0.56 → a $0.02 spread.",
    deepExplanation:
      "The spread is the round-trip cost of trading immediately: buy at the ask, sell at the bid. Why it matters: signals abstain when the spread is too wide, and a new position starts with an unrealized loss roughly equal to the spread. What could mislead you: a narrow spread with tiny size behind it is not cheap liquidity.",
    formula: "spread = ask − bid", reviewedAt: REVIEWED,
    relatedTermIds: ["bid", "ask", "liquidity"],
  },
  liquidity: {
    id: "liquidity", label: "Liquidity", aliases: ["market liquidity"], category: "market",
    shortDefinition: "How readily you can trade without materially changing the price.",
    example: "A deep orderbook may support a larger order than one with only two contracts.",
    deepExplanation:
      "Liquidity combines tight spreads with meaningful size at nearby prices. Why it matters: the signal engine computes a volume-weighted price for a fixed quantity, so thin books raise the effective entry price or block the signal entirely. What could mislead you: liquidity can disappear right before scheduled releases such as CPI.",
    reviewedAt: REVIEWED, relatedTermIds: ["orderbook-depth", "spread", "slippage"],
  },
  "orderbook-depth": {
    id: "orderbook-depth", label: "Orderbook depth", aliases: ["depth", "book depth"],
    category: "market",
    shortDefinition: "Quantity available at each quoted price level.",
    example: "Ten contracts at $0.56 and five at $0.57 give limited depth.",
    deepExplanation:
      "Depth is the list of price levels and the size resting at each. Why it matters: paper fills walk this ladder level by level and, by default, assume you can take only half the displayed size (others may be ahead in the queue). What could mislead you: displayed size can be cancelled instantly; depth is a snapshot, not a promise.",
    sourceUrls: [KALSHI_ORDERBOOK], reviewedAt: REVIEWED,
    relatedTermIds: ["liquidity", "queue-position", "partial-fill"],
  },
  midpoint: {
    id: "midpoint", label: "Midpoint", aliases: ["mid", "mid price"], category: "market",
    shortDefinition: "Average of the best bid and ask, not a guaranteed execution price.",
    example: "A $0.54 bid and $0.56 ask have a $0.55 midpoint.",
    deepExplanation:
      "The midpoint is a convenient summary of where a market sits. Why it matters: this app deliberately never prices trades at the midpoint -- it uses executable asks for buys and bids for sells. What could mislead you: backtests that fill at the midpoint overstate profits by about half the spread on every trade.",
    formula: "mid = (bid + ask) / 2", reviewedAt: REVIEWED,
    relatedTermIds: ["bid", "ask", "spread"],
  },
  "implied-probability": {
    id: "implied-probability", label: "Implied probability", aliases: ["market probability"],
    category: "market",
    shortDefinition:
      "A price interpreted as a rough market probability before adjustments for fees, spread and structure.",
    example: "A $0.60 YES price is often interpreted as roughly 60%, but is not an unbiased forecast.",
    deepExplanation:
      "On a $1 binary contract, a price in dollars reads naturally as a probability. Why it matters: the model-market divergence check compares the model's probability with the market's bid-ask range. What could mislead you: prices embed fees, risk preferences and thin trading; and a liquid market usually knows more than a simple model.",
    reviewedAt: REVIEWED, relatedTermIds: ["model-market-divergence", "calibration"],
  },
  "tick-size": {
    id: "tick-size", label: "Tick size", aliases: ["price grid", "price increment"],
    category: "market",
    shortDefinition: "Smallest permitted price increment for that market and price range.",
    example: "A venue may permit fractional-cent increments; inspect the contract grid.",
    deepExplanation:
      "Each Kalshi market publishes price_ranges with a step for each segment; some use $0.001 near the extremes and $0.01 in the middle. Why it matters: off-grid limit prices are rejected, and the conservative paper scenario worsens fills by one tick. What could mislead you: assuming a universal 1¢ grid.",
    sourceUrls: ["https://docs.kalshi.com/getting_started/fixed_point_migration.md"],
    reviewedAt: REVIEWED, relatedTermIds: ["limit-order"],
  },
  // --- Trading mechanics ----------------------------------------------------------------
  "limit-order": {
    id: "limit-order", label: "Limit order", aliases: ["limit"], category: "trading",
    shortDefinition: "Order that will not execute above your buy price limit or below your sell limit.",
    example: "A YES buy limit of $0.56 cannot buy above $0.56.",
    deepExplanation:
      "A limit caps the worst price you accept. Why it matters: paper orders here are immediate-or-cancel limit orders -- they fill only at prices within your limit, and any remainder is cancelled. What could mislead you: a limit guarantees price, not execution.",
    reviewedAt: REVIEWED, relatedTermIds: ["market-order", "partial-fill"],
  },
  "market-order": {
    id: "market-order", label: "Market order", aliases: [], category: "trading",
    shortDefinition: "Order intended to execute promptly against available prices; final price can vary.",
    example: "A thin book can make immediate execution expensive.",
    deepExplanation:
      "A market order prioritises speed over price. Why it matters: this app does not simulate market orders, because in thin books they can walk far through the ladder. What could mislead you: 'market' does not mean 'fair price'.",
    reviewedAt: REVIEWED, relatedTermIds: ["limit-order", "slippage"],
  },
  maker: {
    id: "maker", label: "Maker", aliases: ["liquidity provider"], category: "trading",
    shortDefinition: "Trader whose resting order adds liquidity to the orderbook.",
    example: "An unfilled limit order waiting on the book typically adds liquidity.",
    deepExplanation:
      "Makers post orders and wait. Why it matters: some Kalshi series charge makers a fraction of the taker fee; this app conservatively assumes taker fees because its paper orders cross the spread. What could mislead you: resting orders tend to fill exactly when the market moves against them (adverse selection).",
    sourceUrls: ["https://docs.kalshi.com/api-reference/market/get-series.md"],
    reviewedAt: REVIEWED, relatedTermIds: ["taker", "adverse-selection", "fees"],
  },
  taker: {
    id: "taker", label: "Taker", aliases: ["liquidity taker"], category: "trading",
    shortDefinition: "Trader whose order matches existing book liquidity.",
    example: "Buying at an available ask generally removes liquidity.",
    deepExplanation:
      "Takers trade immediately against resting orders and usually pay the higher fee. Why it matters: every cost estimate here assumes taker fees. What could mislead you: comparing a taker's costs with a maker's fills mixes two different trades.",
    reviewedAt: REVIEWED, relatedTermIds: ["maker", "fees"],
  },
  slippage: {
    id: "slippage", label: "Slippage", aliases: ["execution slippage"], category: "trading",
    shortDefinition:
      "Difference between assumed and actual execution price, often due to depth or market movement.",
    example: "A $0.56 quoted ask could yield an average $0.57 fill for larger quantity.",
    deepExplanation:
      "Slippage covers the gap between the price you planned on and the price you get. Why it matters: signals subtract a per-contract slippage allowance and must stay positive with that allowance doubled. What could mislead you: slippage is largest exactly when you most want to trade (news, releases).",
    reviewedAt: REVIEWED, relatedTermIds: ["orderbook-depth", "edge"],
  },
  "partial-fill": {
    id: "partial-fill", label: "Partial fill", aliases: ["partially filled"], category: "trading",
    shortDefinition: "When only part of an order executes.",
    example: "Five of ten requested contracts might fill.",
    deepExplanation:
      "If the book cannot absorb your full quantity within your limit, only part executes. Why it matters: paper orders show PARTIAL status and only the filled quantity becomes a position; the rest is cancelled. What could mislead you: treating the unfilled remainder as if it were bought.",
    reviewedAt: REVIEWED, relatedTermIds: ["orderbook-depth", "queue-position"],
  },
  "queue-position": {
    id: "queue-position", label: "Queue position", aliases: ["queue priority"],
    category: "trading",
    shortDefinition: "Place in the matching priority at a given price level.",
    example: "An order behind others might never fill even if the displayed price trades.",
    deepExplanation:
      "At one price, earlier orders usually fill first. Why it matters: the conservative paper scenario assumes you can take only half of each level's displayed size, approximating others ahead of you. What could mislead you: simulations that assume you are always first in line.",
    reviewedAt: REVIEWED, relatedTermIds: ["orderbook-depth", "partial-fill"],
  },
  "adverse-selection": {
    id: "adverse-selection", label: "Adverse selection", aliases: [], category: "risk",
    shortDefinition:
      "Risk that fills occur disproportionately when the other side has better information.",
    example: "A cheap-looking resting bid might fill just before bad news.",
    deepExplanation:
      "If someone happily trades with you, ask why. Why it matters: it is one reason this app treats large model-versus-market gaps as a warning rather than an opportunity. What could mislead you: your fill rate looks great precisely on the trades that lose.",
    reviewedAt: REVIEWED, relatedTermIds: ["maker", "model-market-divergence"],
  },
  fees: {
    id: "fees", label: "Fees", aliases: ["trading fees"], category: "trading",
    shortDefinition:
      "Charges or rebates related to exchange trading or settlement under specific rules.",
    example: "A positive model edge can disappear after trading costs.",
    deepExplanation:
      "Kalshi fees depend on each series' fee type and multiplier, are rounded up per fill, and balances are rounded to the cent. Why it matters: signals abstain until the fee schedule in fee_schedules.json is verified against Kalshi's official PDF. What could mislead you: a hard-coded percentage -- fees are price-dependent and change by series.",
    sourceUrls: [KALSHI_FEES, "https://kalshi.com/docs/kalshi-fee-schedule.pdf"],
    reviewedAt: REVIEWED, relatedTermIds: ["edge", "taker", "maker"],
  },
  edge: {
    id: "edge", label: "Edge", aliases: ["model edge"], category: "trading",
    shortDefinition:
      "Estimated advantage of a trade over its current cost, after relevant assumptions.",
    example:
      "If modeled EV is $0.05 per contract, that is estimated edge, not guaranteed profit.",
    deepExplanation:
      "Edge here is the model probability minus the executable price, fees and slippage. The lower-bound edge uses the cautious end of the model's band. Why it matters: a candidate needs the lower-bound edge above a margin and robust to doubled costs. What could mislead you: a huge edge usually means the model is missing information.",
    formula: "lower_edge_yes = p_lower − ask − fee − slippage", reviewedAt: REVIEWED,
    relatedTermIds: ["expected-value", "fees", "slippage", "model-market-divergence"],
  },
  "expected-value": {
    id: "expected-value", label: "Expected value", aliases: ["EV"], category: "quant",
    shortDefinition: "Probability-weighted average gain or loss across possible outcomes.",
    example: "With p=.64, YES ask=.56 and costs=.03, modeled EV=$0.05.",
    deepExplanation:
      "EV averages outcomes by their probabilities. For a $1 YES contract: win (1 − cost) with probability p, lose the cost otherwise. Why it matters: every signal card shows EV per contract after costs. What could mislead you: EV is only as good as p; positive EV can still lose many times in a row.",
    formula: "EV_yes = p − ask − fee − slippage", reviewedAt: REVIEWED,
    relatedTermIds: ["edge"],
  },
  arbitrage: {
    id: "arbitrage", label: "Arbitrage", aliases: ["arb"], category: "trading",
    shortDefinition:
      "Trade combining prices to lock in gain under truly executable terms, after all costs and constraints.",
    example: "Apparent YES/NO price gaps can vanish with fees, spread, limits or missing fills.",
    deepExplanation:
      "True arbitrage requires identical payoffs in every state of the world. Why it matters: two contracts that sound alike can have different rules, sources or timing. What could mislead you: legs that fill partially or at different moments turn 'free money' into ordinary risk.",
    reviewedAt: REVIEWED, relatedTermIds: ["fees", "partial-fill"],
  },
  // --- Quantitative ---------------------------------------------------------------------
  "base-rate": {
    id: "base-rate", label: "Base rate", aliases: ["prior frequency"], category: "quant",
    shortDefinition:
      "Historical frequency of an outcome before considering case-specific evidence.",
    example: "If similar events happened 30 of 100 times, starting base rate is 30%.",
    deepExplanation:
      "The base_rate model forecasts the share of past CPI first prints that exceeded the threshold. Why it matters: it is the benchmark other models must beat on holdout Brier score before signals are allowed. What could mislead you: base rates assume the future resembles the past window.",
    reviewedAt: REVIEWED, relatedTermIds: ["calibration", "bayesian-updating"],
  },
  "bayesian-updating": {
    id: "bayesian-updating", label: "Bayesian updating", aliases: ["Bayes"], category: "quant",
    shortDefinition: "Revising prior beliefs as new evidence arrives.",
    example: "A stronger official forecast can change the probability assigned to a contract.",
    deepExplanation:
      "Start from a prior, observe evidence, end with a posterior. Why it matters: the base-rate model's interval is a Bayesian (Jeffreys) posterior. What could mislead you: a confident prior can drown out weak but real evidence.",
    reviewedAt: REVIEWED, relatedTermIds: ["base-rate", "credible-interval"],
  },
  calibration: {
    id: "calibration", label: "Calibration", aliases: ["reliability"], category: "quant",
    shortDefinition: "How well forecast frequencies match realized outcome frequencies.",
    example: "Events forecast near 70% should occur about 70% of the time over many cases.",
    deepExplanation:
      "Group forecasts into bins and compare each bin's average forecast with how often YES happened. Why it matters: the calibration charts plot exactly that; points near the dashed diagonal are well calibrated. What could mislead you: bins with few forecasts are noisy.",
    reviewedAt: REVIEWED, relatedTermIds: ["brier-score", "log-loss"],
  },
  "brier-score": {
    id: "brier-score", label: "Brier score", aliases: ["brier"], category: "quant",
    shortDefinition:
      "Mean squared difference between predicted probability and binary outcome; lower is better.",
    example: "A 0.70 forecast with a YES outcome contributes (0.70−1)^2 = 0.09.",
    deepExplanation:
      "A proper scoring rule: honest probabilities minimise it. A constant 50% forecast scores 0.25. Why it matters: a model must beat the base-rate model's holdout Brier before it can drive signals. What could mislead you: Brier rewards calibration and sharpness together; compare models on the same events.",
    formula: "mean((p − y)²)", reviewedAt: REVIEWED,
    relatedTermIds: ["log-loss", "calibration"],
  },
  "log-loss": {
    id: "log-loss", label: "Log loss", aliases: ["logarithmic score", "cross-entropy"],
    category: "quant",
    shortDefinition:
      "Scoring rule that strongly penalizes very confident wrong probability forecasts.",
    example: "Calling an impossible event 0% when it happens is penalized heavily.",
    deepExplanation:
      "Log loss punishes overconfidence much harder than Brier. Why it matters: it is reported alongside Brier, with probabilities clipped at 1e-6 so one extreme forecast cannot produce infinity. What could mislead you: a few disasters can dominate the average.",
    formula: "−mean(y·ln p + (1−y)·ln(1−p))", reviewedAt: REVIEWED,
    relatedTermIds: ["brier-score"],
  },
  uncertainty: {
    id: "uncertainty", label: "Uncertainty", aliases: ["model uncertainty"], category: "quant",
    shortDefinition:
      "How unsure the model is about its estimate, distinct from the probability of the event.",
    example:
      "A 60% forecast based on five observations is less defensible than one with strong validation.",
    deepExplanation:
      "Each forecast carries a band and a stated method. Why it matters: signals use the cautious end of the band. What could mislead you: the Gaussian model's band is a heuristic sensitivity range, explicitly NOT a confidence interval.",
    reviewedAt: REVIEWED, relatedTermIds: ["confidence-interval", "credible-interval"],
  },
  "confidence-interval": {
    id: "confidence-interval", label: "Confidence interval", aliases: ["CI"], category: "quant",
    shortDefinition:
      "A frequentist interval procedure with specified long-run coverage under its assumptions.",
    example: "A nominal 95% procedure covers the true parameter in 95% of repeated samples.",
    deepExplanation:
      "The coverage statement is about the procedure across repeated samples. Why it matters: this app labels bands precisely and never calls a heuristic band a confidence interval. What could mislead you: reading a 95% interval as '95% chance of profit'.",
    reviewedAt: REVIEWED, relatedTermIds: ["credible-interval", "uncertainty"],
  },
  "credible-interval": {
    id: "credible-interval", label: "Credible interval", aliases: [], category: "quant",
    shortDefinition:
      "Bayesian interval expressing posterior probability under the chosen model and prior.",
    example: "A 95% credible interval summarizes 95% posterior mass.",
    deepExplanation:
      "The base-rate model reports a 90% equal-tailed credible interval from a Jeffreys Beta posterior. Why it matters: it widens when history is short. What could mislead you: it is only as valid as the assumption that months are exchangeable.",
    reviewedAt: REVIEWED, relatedTermIds: ["bayesian-updating", "confidence-interval"],
  },
  correlation: {
    id: "correlation", label: "Correlation", aliases: [], category: "quant",
    shortDefinition:
      "How two quantities or outcomes tend to move together; not necessarily causation.",
    example: "Two contracts about the same economic release may be highly correlated.",
    deepExplanation:
      "Thresholds on the same CPI release resolve together. Why it matters: evaluation reports months (not predictions) as the effective sample size. What could mislead you: eight correlated bets look like diversification but are mostly one bet.",
    reviewedAt: REVIEWED, relatedTermIds: ["concentration", "exposure"],
  },
  // --- Games, combos and your record (added 2026-11-19 with the Docket) -----------------
  "fair-price": {
    id: "fair-price", label: "Fair price", aliases: ["fair value", "independent fair price"],
    category: "trading",
    shortDefinition:
      "What a contract or combo is worth at the market's own probabilities, before fees. For a combo, the legs' prices multiplied as if they were unrelated.",
    example: "Two legs priced 50¢ each give a 25¢ fair combo price.",
    deepExplanation:
      "Fair price turns market prices into a single number you can compare with a quote. Why it matters: Kalshi prices combos privately, so the fair price is your yardstick for whether a quote is generous or marked up. What could mislead you: legs from the same game move together, so multiplying their prices understates or overstates the true chance; the Docket shows a history-adjusted figure when it can.",
    formula: "combo fair price = p1 × p2 × … × pn", reviewedAt: "2026-11-19",
    relatedTermIds: ["implied-probability", "correlation", "walk-away-price", "combo"],
  },
  "walk-away-price": {
    id: "walk-away-price", label: "Walk-away price", aliases: ["walk away", "max price"],
    category: "trading",
    shortDefinition:
      "The most you should pay. Above it, the expected value after fees turns negative, so you pass rather than haggle yourself into a bad price.",
    example: "Walk away above 16¢: a 19¢ quote means skip it.",
    deepExplanation:
      "Deciding your limit before seeing the quote protects you from anchoring on whatever price you're offered. Why it matters: on small stakes, fees and markups are a large share of any edge. What could mislead you: the walk-away price is only as good as the probability behind it; a wrong estimate gives a confident but wrong limit.",
    reviewedAt: "2026-11-19", relatedTermIds: ["fair-price", "expected-value", "fees"],
  },
  combo: {
    id: "combo", label: "Combo", aliases: ["parlay", "multivariate market"], category: "contract",
    shortDefinition:
      "One contract that pays only if every leg wins. Kalshi builds and prices combos on request; there is no public order book for them.",
    example: "Knicks win AND Towns 12+ rebounds: one miss and the whole combo loses.",
    deepExplanation:
      "A combo multiplies chances, so even likely legs add up to a long shot. Why it matters: combos are where markups hide, because each quote is private. What could mislead you: a run of near-misses feels like bad luck, but losing by one leg is the most common way a combo loses.",
    reviewedAt: "2026-11-19", relatedTermIds: ["fair-price", "correlation"],
  },
  overround: {
    id: "overround", label: "Overround", aliases: ["vig", "book margin"], category: "market",
    shortDefinition:
      "How far the prices of every outcome add up above 100%. The extra is what it costs to buy all outcomes, before fees.",
    example: "Outcomes priced 52¢ + 51¢ add to 103%: a 3-point overround.",
    deepExplanation:
      "In a list where exactly one outcome wins, fair prices would sum to $1. Why it matters: the overround is a built-in cost on every side you take. What could mislead you: if the listed outcomes don't cover every possibility, prices can sum below 100% without being a free lunch.",
    reviewedAt: "2026-11-19", relatedTermIds: ["implied-probability", "spread", "arbitrage"],
  },
  "closing-line-value": {
    id: "closing-line-value", label: "Closing line value", aliases: ["CLV", "entry vs close"],
    category: "quant",
    shortDefinition:
      "Your entry price compared with the last price before the market closed. Buying below where it closed is a sign of good entries, win or lose.",
    example: "You paid 40¢ and it closed at 46¢: +6 points of closing line value.",
    deepExplanation:
      "Results are noisy; prices near the close have absorbed the most information. Why it matters: consistently beating the close is better evidence of skill than a short winning streak. What could mislead you: on thin markets the last price can be one stale trade.",
    reviewedAt: "2026-11-19", relatedTermIds: ["calibration", "edge", "sample-size"],
  },
  "sample-size": {
    id: "sample-size", label: "Sample size", aliases: ["small sample"], category: "quant",
    shortDefinition:
      "How many independent results a number rests on. With few, luck dominates, and a winning or losing streak says little about what comes next.",
    example: "3 wins in 4 bets is far weaker evidence than 30 in 40.",
    deepExplanation:
      "Every record here is checked against what luck alone would produce. Why it matters: the app won't call anything a pattern under 10 closed trades, and calls larger records noise unless they beat luck clearly. What could mislead you: related bets (same game, same night) count as fewer independent results than they look.",
    reviewedAt: "2026-11-19", relatedTermIds: ["uncertainty", "confidence-interval", "calibration"],
  },
  // --- Risk -----------------------------------------------------------------------------
  exposure: {
    id: "exposure", label: "Exposure", aliases: ["risk exposure"], category: "risk",
    shortDefinition: "Amount at risk or connected to a specific outcome, event, or factor.",
    example: "Multiple correlated contracts can create concentrated event exposure.",
    deepExplanation:
      "Exposure is what you stand to lose if an outcome goes against you. Why it matters: on a binary contract, the most you can lose is what you paid. What could mislead you: per-position limits can hide total exposure to one release.",
    reviewedAt: REVIEWED, relatedTermIds: ["concentration", "correlation"],
  },
  drawdown: {
    id: "drawdown", label: "Drawdown", aliases: ["max drawdown"], category: "risk",
    shortDefinition: "Drop from a previous portfolio-value peak to a subsequent low.",
    example: "Going from $1,000 to $800 is a 20% drawdown.",
    deepExplanation:
      "Drawdown measures the pain path, not just the end point. Why it matters: good long-run EV can include long losing streaks. What could mislead you: short paper histories understate how deep drawdowns get.",
    formula: "drawdown = (peak − trough) / peak", reviewedAt: REVIEWED,
    relatedTermIds: ["exposure"],
  },
  concentration: {
    id: "concentration", label: "Concentration", aliases: [], category: "risk",
    shortDefinition: "Share of risk tied to one outcome, issuer, market, or theme.",
    example: "Five nearly identical CPI wagers are not five independent risks.",
    deepExplanation:
      "Concentration is exposure clustered on one driver. Why it matters: all current markets depend on the same monthly CPI print. What could mislead you: counting positions instead of underlying events.",
    reviewedAt: REVIEWED, relatedTermIds: ["correlation", "exposure"],
  },
  abstention: {
    id: "abstention", label: "Abstention", aliases: ["abstain"], category: "risk",
    shortDefinition:
      "Explicit decision not to issue a trade candidate because evidence or risk checks are insufficient.",
    example: "A stale quote or unclear resolution rule forces ABSTAIN.",
    deepExplanation:
      "ABSTAIN is a first-class outcome with listed reason codes. Why it matters: it is the default whenever data, rules, fees or validation are uncertain. What could mislead you: treating abstentions as 'missed opportunities' instead of risk avoided.",
    reviewedAt: REVIEWED, relatedTermIds: ["stale-quote", "model-market-divergence"],
  },
  "model-drift": {
    id: "model-drift", label: "Model drift", aliases: ["concept drift"], category: "risk",
    shortDefinition:
      "Change in relationships or input patterns that degrades a model over time.",
    example: "An NBA rating model may deteriorate after major roster turnover.",
    deepExplanation:
      "Models fitted on one regime can fail in another. Why it matters: CPI behaved very differently in 2021–22; dev and holdout periods are reported separately so you can see shifts. What could mislead you: a strong historical score is no guarantee in a new regime.",
    reviewedAt: REVIEWED, relatedTermIds: ["out-of-sample", "walk-forward-validation"],
  },
  // --- Contracts ------------------------------------------------------------------------
  "binary-contract": {
    id: "binary-contract", label: "Binary contract", aliases: ["event contract"],
    category: "contract",
    shortDefinition: "Contract that pays according to a YES/NO event resolution.",
    example: "One winning contract may pay $1 under the specified contract terms.",
    deepExplanation:
      "YES pays the notional if the event happens; NO pays if it doesn't. Why it matters: asks are derived only for binary markets, whose complement relation is documented. What could mislead you: the title is a summary -- the official rules decide.",
    reviewedAt: REVIEWED, relatedTermIds: ["resolution", "settlement"],
  },
  resolution: {
    id: "resolution", label: "Resolution", aliases: ["outcome determination"],
    category: "contract",
    shortDefinition: "Determination of the contract outcome according to official rules.",
    example: "A market can close before its final YES/NO outcome is determined.",
    deepExplanation:
      "Kalshi's lifecycle separates closed, determined, disputed, amended and finalized. Why it matters: paper payouts wait for 'finalized' and are cross-checked against our own CPI evidence. What could mislead you: 'closed' does not mean 'resolved'.",
    sourceUrls: [KALSHI_LIFECYCLE], reviewedAt: REVIEWED,
    relatedTermIds: ["settlement", "binary-contract"],
  },
  settlement: {
    id: "settlement", label: "Settlement", aliases: ["payout"], category: "contract",
    shortDefinition: "Final processing of proceeds/obligations after outcome determination.",
    example: "A winning contract may settle after the event has resolved.",
    deepExplanation:
      "Settlement turns a resolved outcome into cash. Why it matters: paper settlements are SETTLED only on finalized results our evidence does not contradict; otherwise HELD for review. What could mislead you: an exchange result can be disputed and amended before it is final.",
    sourceUrls: [KALSHI_LIFECYCLE], reviewedAt: REVIEWED,
    relatedTermIds: ["resolution"],
  },
  // --- Evaluation & data ------------------------------------------------------------------
  backtesting: {
    id: "backtesting", label: "Backtesting", aliases: ["backtest"], category: "data",
    shortDefinition:
      "Testing a strategy on historical data as if each decision were made at the time.",
    example: "Train through 2024 and evaluate later forecasts using only then-known inputs.",
    deepExplanation:
      "A backtest replays history decision by decision. Why it matters: this app's evaluations use only data published before each cutoff (vintages). What could mislead you: any leak of later information makes results look better than reality.",
    reviewedAt: REVIEWED, relatedTermIds: ["look-ahead-bias", "walk-forward-validation"],
  },
  "look-ahead-bias": {
    id: "look-ahead-bias", label: "Look-ahead bias", aliases: ["lookahead bias"],
    category: "data",
    shortDefinition:
      "Using information in a historical simulation that was unavailable at decision time.",
    example:
      "Using revised inflation numbers before their revision date creates look-ahead bias.",
    deepExplanation:
      "The classic backtest error. Why it matters: every evidence row records when it became available (vintage date at the agency's release time), and queries exclude anything later than the cutoff. What could mislead you: 'final' historical data is usually revised data that nobody had at the time.",
    sourceUrls: [ALFRED], reviewedAt: REVIEWED,
    relatedTermIds: ["vintage", "data-leakage", "backtesting"],
  },
  "data-leakage": {
    id: "data-leakage", label: "Data leakage", aliases: ["leakage"], category: "data",
    shortDefinition:
      "Information from evaluation targets or future records unintentionally enters training or features.",
    example: "Using a final game score indirectly in a pregame model leaks the answer.",
    deepExplanation:
      "Leakage is any path by which the answer sneaks into the inputs. Why it matters: the walk-forward code raises an error if a target month is visible before its release. What could mislead you: leaks often come through innocent-looking features.",
    reviewedAt: REVIEWED, relatedTermIds: ["look-ahead-bias"],
  },
  "walk-forward-validation": {
    id: "walk-forward-validation", label: "Walk-forward validation",
    aliases: ["rolling-origin evaluation"], category: "data",
    shortDefinition: "Repeatedly train on past periods and test on subsequent periods.",
    example: "Train Jan–Jun, test Jul; then train Jan–Jul, test Aug.",
    deepExplanation:
      "Each month is forecast using only prints published before its release, then scored. Why it matters: it mimics real use and is how every model here is evaluated. What could mislead you: tuning settings after peeking at holdout results quietly turns holdout into training data.",
    reviewedAt: REVIEWED, relatedTermIds: ["out-of-sample", "look-ahead-bias"],
  },
  "out-of-sample": {
    id: "out-of-sample", label: "Out-of-sample", aliases: ["holdout"], category: "data",
    shortDefinition: "Data not used to fit or select a model in the relevant evaluation.",
    example: "Hold out later events to judge real forecasting performance.",
    deepExplanation:
      "Holdout here starts in 2015; model settings were fixed in advance. Why it matters: signal validation requires enough holdout months and a holdout Brier better than the base rate. What could mislead you: a small holdout can flatter or punish a model by luck.",
    reviewedAt: REVIEWED, relatedTermIds: ["walk-forward-validation"],
  },
  // --- App-specific -----------------------------------------------------------------------
  vintage: {
    id: "vintage", label: "Vintage", aliases: ["data vintage", "real-time period"],
    category: "data",
    shortDefinition: "The version of a data series as published on a specific date, before later revisions.",
    example: "August CPI as first published on Sep 11 is one vintage; its revision on Oct 15 is another.",
    deepExplanation:
      "FRED/ALFRED keeps every published version of each value. Why it matters: models use only vintages available at the cutoff, and evidence rows are never overwritten. What could mislead you: today's data series is the latest vintage, not what was known then.",
    sourceUrls: [ALFRED], reviewedAt: REVIEWED,
    relatedTermIds: ["first-print", "look-ahead-bias"],
  },
  "first-print": {
    id: "first-print", label: "First print", aliases: ["initial release"], category: "data",
    shortDefinition: "The first published value of a statistic for a period, before revisions.",
    example: "Kalshi CPI markets settle on the single-decimal value BLS publishes on release day.",
    deepExplanation:
      "The first print is rebuilt from vintages: the month's first value compared with the previous month as published in the same release. Why it matters: it is the value these contracts resolve on, and the target the models forecast. What could mislead you: rounding from 3-decimal indexes can rarely differ from BLS's percentage by 0.1.",
    reviewedAt: REVIEWED, relatedTermIds: ["vintage", "resolution"],
  },
  "derived-ask": {
    id: "derived-ask", label: "Derived ask", aliases: ["complementary ask"], category: "market",
    shortDefinition: "An ask computed from the opposite side's best bid, because the exchange publishes bids only.",
    example: "Best NO bid $0.55 → derived YES ask $0.45.",
    deepExplanation:
      "Each derived ask is labelled with its provenance. Why it matters: it is the executable buy price used for EV and paper fills. What could mislead you: if there is no opposite bid, there is no ask -- never fill a gap with a guess.",
    formula: "YES ask = 1 − best NO bid", sourceUrls: [KALSHI_ORDERBOOK], reviewedAt: REVIEWED,
    relatedTermIds: ["ask", "bid"],
  },
  "stale-quote": {
    id: "stale-quote", label: "Stale quote", aliases: ["stale"], category: "risk",
    shortDefinition: "A price snapshot older than the configured maximum age, so it may no longer be executable.",
    example: "With a 60-second limit, a quote observed 3 minutes ago is stale.",
    deepExplanation:
      "Quotes are timestamped when received. Why it matters: stale quotes force signals to ABSTAIN and paper orders to be rejected. What could mislead you: a price that looks fine on screen may have moved minutes ago.",
    reviewedAt: REVIEWED, relatedTermIds: ["abstention"],
  },
  "paper-trading": {
    id: "paper-trading", label: "Paper trading", aliases: ["simulated trading"], category: "trading",
    shortDefinition: "Simulated orders and P&L with no real money and no exchange contact.",
    example: "A paper BUY fills against a stored order-book snapshot under conservative assumptions.",
    deepExplanation:
      "Paper fills use half the displayed depth and a one-tick price penalty by default, and settle only on finalized results. Why it matters: it tests ideas safely. What could mislead you: simulated profits are not evidence of real returns -- real fills, queues and fees differ.",
    reviewedAt: REVIEWED, relatedTermIds: ["partial-fill", "settlement"],
  },
  "model-market-divergence": {
    id: "model-market-divergence", label: "Model–market divergence",
    aliases: ["divergence"], category: "risk",
    shortDefinition: "How far a model's probability sits outside the market's bid–ask range.",
    example: "Model 80% vs YES bid 1¢ / ask 3¢ → a 77-point divergence.",
    deepExplanation:
      "The CPI models know only past prints; liquid markets know far more. Why it matters: divergence above the limit forces ABSTAIN. What could mislead you: a huge gap feels like a huge opportunity, but it is usually the model that is wrong.",
    reviewedAt: REVIEWED, relatedTermIds: ["implied-probability", "adverse-selection", "edge"],
  },
} as const satisfies Record<string, GlossaryEntry>;

/** Only IDs present in TERMS type-check; unknown IDs are compile-time errors. */
export type TermId = keyof typeof TERMS;

export function getTerm(id: TermId): GlossaryEntry {
  return TERMS[id];
}

export const ALL_TERMS: readonly GlossaryEntry[] = Object.values(TERMS);

export const CATEGORY_LABELS: Record<TermCategory, string> = {
  market: "Market structure",
  trading: "Trading",
  quant: "Quantitative",
  risk: "Risk",
  contract: "Contracts",
  data: "Data & evaluation",
};

/** Case-insensitive search over label, aliases, id, category and short definition. */
export function searchTerms(query: string, category?: TermCategory): GlossaryEntry[] {
  const q = query.trim().toLowerCase();
  return ALL_TERMS.filter((t) => {
    if (category && t.category !== category) return false;
    if (!q) return true;
    const hay = [t.label, t.id, t.category, ...t.aliases].map((s) => s.toLowerCase());
    return hay.some((h) => h.includes(q)) || t.shortDefinition.toLowerCase().includes(q);
  }).sort((a, b) => a.label.localeCompare(b.label));
}
