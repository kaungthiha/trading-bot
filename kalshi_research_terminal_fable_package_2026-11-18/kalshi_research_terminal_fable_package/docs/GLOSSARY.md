# Educational Glossary

Definitions are educational and contextual, not trade recommendations. These IDs are the canonical IDs the UI registry should use. Deep explanations and source links should be added and reviewed in the typed application registry.

## `bid`
**Meaning:** Highest advertised price a buyer currently offers for a contract.

**Example:** A YES bid of $0.54 means someone is offering $0.54 for YES.

## `ask`
**Meaning:** Lowest price currently available to a buyer, when an opposing order exists.

**Example:** A YES ask of $0.56 is the price a buyer might pay for one YES contract.

## `spread`
**Meaning:** Difference between best ask and best bid for the same contract.

**Example:** Bid $0.54, ask $0.56 → a $0.02 spread.

## `liquidity`
**Meaning:** How readily you can trade without materially changing the price.

**Example:** A deep orderbook may support a larger order than one with only two contracts.

## `orderbook-depth`
**Meaning:** Quantity available at each quoted price level.

**Example:** Ten contracts at $0.56 and five at $0.57 give limited depth.

## `midpoint`
**Meaning:** Average of the best bid and ask, not a guaranteed execution price.

**Example:** A $0.54 bid and $0.56 ask have a $0.55 midpoint.

## `implied-probability`
**Meaning:** A price interpreted as a rough market probability before adjustments for fees, spread and structure.

**Example:** A $0.60 YES price is often interpreted as roughly 60%, but is not an unbiased forecast.

## `tick-size`
**Meaning:** Smallest permitted price increment for that market and price range.

**Example:** A venue may permit fractional-cent increments; inspect the contract grid.

## `limit-order`
**Meaning:** Order that will not execute above your buy price limit or below your sell limit.

**Example:** A YES buy limit of $0.56 cannot buy above $0.56.

## `market-order`
**Meaning:** Order intended to execute promptly against available prices; final price can vary.

**Example:** A thin book can make immediate execution expensive.

## `maker`
**Meaning:** Trader whose resting order adds liquidity to the orderbook.

**Example:** An unfilled limit order waiting on the book typically adds liquidity.

## `taker`
**Meaning:** Trader whose order matches existing book liquidity.

**Example:** Buying at an available ask generally removes liquidity.

## `slippage`
**Meaning:** Difference between assumed and actual execution price, often due to depth or market movement.

**Example:** A $0.56 quoted ask could yield an average $0.57 fill for larger quantity.

## `partial-fill`
**Meaning:** When only part of an order executes.

**Example:** Five of ten requested contracts might fill.

## `queue-position`
**Meaning:** Place in the matching priority at a given price level.

**Example:** An order behind others might never fill even if the displayed price trades.

## `adverse-selection`
**Meaning:** Risk that fills occur disproportionately when the other side has better information.

**Example:** A cheap-looking resting bid might fill just before bad news.

## `fees`
**Meaning:** Charges or rebates related to exchange trading or settlement under specific rules.

**Example:** A positive model edge can disappear after trading costs.

## `edge`
**Meaning:** Estimated advantage of a trade over its current cost, after relevant assumptions.

**Example:** If modeled EV is $0.05 per contract, that is estimated edge, not guaranteed profit.

## `expected-value`
**Meaning:** Probability-weighted average gain or loss across possible outcomes.

**Example:** With p=.64, YES ask=.56 and costs=.03, modeled EV=$0.05.

## `base-rate`
**Meaning:** Historical frequency of an outcome before considering case-specific evidence.

**Example:** If similar events happened 30 of 100 times, starting base rate is 30%.

## `bayesian-updating`
**Meaning:** Revising prior beliefs as new evidence arrives.

**Example:** A stronger official forecast can change the probability assigned to a contract.

## `calibration`
**Meaning:** How well forecast frequencies match realized outcome frequencies.

**Example:** Events forecast near 70% should occur about 70% of the time over many cases.

## `brier-score`
**Meaning:** Mean squared difference between predicted probability and binary outcome; lower is better.

**Example:** A 0.70 forecast with a YES outcome contributes (0.70−1)^2 = 0.09.

## `log-loss`
**Meaning:** Scoring rule that strongly penalizes very confident wrong probability forecasts.

**Example:** Calling an impossible event 0% when it happens is penalized heavily.

## `uncertainty`
**Meaning:** How unsure the model is about its estimate, distinct from the probability of the event.

**Example:** A 60% forecast based on five observations is less defensible than one with strong validation.

## `confidence-interval`
**Meaning:** A frequentist interval procedure with specified long-run coverage under its assumptions.

**Example:** A nominal 95% procedure covers the true parameter in 95% of repeated samples.

## `credible-interval`
**Meaning:** Bayesian interval expressing posterior probability under the chosen model and prior.

**Example:** A 95% credible interval summarizes 95% posterior mass.

## `correlation`
**Meaning:** How two quantities or outcomes tend to move together; not necessarily causation.

**Example:** Two contracts about the same economic release may be highly correlated.

## `exposure`
**Meaning:** Amount at risk or connected to a specific outcome, event, or factor.

**Example:** Multiple correlated contracts can create concentrated event exposure.

## `drawdown`
**Meaning:** Drop from a previous portfolio-value peak to a subsequent low.

**Example:** Going from $1,000 to $800 is a 20% drawdown.

## `concentration`
**Meaning:** Share of risk tied to one outcome, issuer, market, or theme.

**Example:** Five nearly identical CPI wagers are not five independent risks.

## `binary-contract`
**Meaning:** Contract that pays according to a YES/NO event resolution.

**Example:** One winning contract may pay $1 under the specified contract terms.

## `resolution`
**Meaning:** Determination of the contract outcome according to official rules.

**Example:** A market can close before its final YES/NO outcome is determined.

## `settlement`
**Meaning:** Final processing of proceeds/obligations after outcome determination.

**Example:** A winning contract may settle after the event has resolved.

## `arbitrage`
**Meaning:** Trade combining prices to lock in gain under truly executable terms, after all costs and constraints.

**Example:** Apparent YES/NO price gaps can vanish with fees, spread, limits or missing fills.

## `backtesting`
**Meaning:** Testing a strategy on historical data as if each decision were made at the time.

**Example:** Train through 2024 and evaluate later forecasts using only then-known inputs.

## `look-ahead-bias`
**Meaning:** Using information in a historical simulation that was unavailable at decision time.

**Example:** Using revised inflation numbers before their revision date creates look-ahead bias.

## `data-leakage`
**Meaning:** Information from evaluation targets or future records unintentionally enters training or features.

**Example:** Using a final game score indirectly in a pregame model leaks the answer.

## `walk-forward-validation`
**Meaning:** Repeatedly train on past periods and test on subsequent periods.

**Example:** Train Jan–Jun, test Jul; then train Jan–Jul, test Aug.

## `out-of-sample`
**Meaning:** Data not used to fit or select a model in the relevant evaluation.

**Example:** Hold out later events to judge real forecasting performance.

## `model-drift`
**Meaning:** Change in relationships or input patterns that degrades a model over time.

**Example:** An NBA rating model may deteriorate after major roster turnover.

## `abstention`
**Meaning:** Explicit decision not to issue a trade candidate because evidence or risk checks are insufficient.

**Example:** A stale quote or unclear resolution rule forces ABSTAIN.
