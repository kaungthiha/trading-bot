# Quantitative Models, Edge and Abstention

## Objects
**Forecast** = calibrated p(YES) estimate with timestamp, model version and uncertainty. **Quote** = contemporaneous bid-side data, derived executable ask when available. **Signal** = evaluated research hypothesis, not an order. **Paper order** = simulated action. **Live approval** = separate explicit user authorization; no autonomous submission.

## Cost-adjusted edge
Simplified YES expected value per $1-payout contract: `EV_yes = p_yes - yes_entry - fees - slippage`. For NO: `EV_no = (1-p_yes) - no_entry - fees - slippage`. `yes_entry` and `no_entry` use the executable ask (or conservative depth-aware simulated price), not last price or midpoint. Compare the correct exchange fee rules and market-specific price grid; quote may expire. For a YES forecast p=.64, ask=.56, fees=.02, slippage=.01, EV=.05/contract **under these assumptions**. Positive EV estimates are uncertain and not guarantees.

Use a defensible conservative probability bound if validated: `lower_edge_yes = p_yes_lower - ask_yes - fees - slippage`. For NO, use lower bound on p(NO), e.g. `1 - p_yes_upper`. Avoid labeling heuristic bounds as confidence intervals.

## Model registry
`ProbabilityModel.predict(market, evidence_as_of, feature_snapshot, config) -> Forecast`. Category strategies: economic data vintage-aware historical baselines and nowcast; NBA pregame Elo/logistic and documented lineup/rest features; culture and technology base rates, scenario models and structured milestone evidence. If no credible evidence, `ABSTAIN`.

## Gates
Market open; rules validated; source provenance; quote freshness; adequate depth; bounded spread; model has minimum out-of-sample observations; model calibration accepted; fee schedule known; derived ask available; uncertainty robust to cost assumptions; overlap/exposure checked. Any unresolved failure yields `ABSTAIN` with enumerated codes; do not replace missing data with guesses.

## Testing and evaluation
Walk-forward splits, grouped events, point-in-time features and release vintages. Measure Brier score `mean((p-y)^2)`, log loss, calibration curves, coverage by category, count of predictions, net paper P&L under conservative fill/fees, drawdown, adverse-selection sensitivity, performance vs market-implied and base-rate baselines. Separate cross-validation from final holdout; archive model/version/config and dataset hashes. Beware selective sampling and post-event quote collection.
