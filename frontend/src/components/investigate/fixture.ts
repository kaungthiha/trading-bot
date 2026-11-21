import type { InvestigationHypothesis, InvestigationResult, ResearchUsage } from "../../api/types";

/** PHASE A ONLY: sample research so the drawer can be built and tested before any Brave or
 * Ollama call exists. Everything here is labelled as sample data in the UI. The text is
 * derived from the exact hypothesis (side, line, market) so tests can prove YES ≠ NO and
 * different lines give different results. Replaced by the API in Phases C–D. */

export type FixtureScenario = "ok" | "ollama_offline" | "brave_unconfigured" | "budget_exhausted" | "no_results";

const DAY = 86_400_000;

export function fixtureUsage(scenario: FixtureScenario = "ok"): ResearchUsage {
  return {
    configured: scenario !== "brave_unconfigured",
    used_today: scenario === "budget_exhausted" ? 60 : 4, daily_cap: 60,
    used_month: scenario === "budget_exhausted" ? 127 : 37, monthly_cap: 800,
    max_searches_per_investigation: 5,
    by_purpose: { research: { today: 3, month: 30 }, news: { today: 1, month: 5 }, headlines: { today: 0, month: 2 } },
  };
}

export function fixtureInvestigation(h: InvestigationHypothesis, scenario: FixtureScenario = "ok",
  now = Date.now()): InvestigationResult {
  const yes = h.side === "yes";
  const line = h.threshold != null ? ` (line ${h.threshold})` : "";
  const target = `${yes ? "" : "NOT "}${h.label}${line}`;
  const searched = scenario === "ok" || scenario === "ollama_offline";
  const llm = scenario !== "ollama_offline";
  const iso = (ms: number) => new Date(ms).toISOString();
  const sources = searched ? [
    { id: "S1", url: "https://example.com/sample-preview", title: `Sample preview article about ${h.label}`,
      publisher: "example.com", author: null, published_at: iso(now - 0.3 * DAY), retrieved_at: iso(now),
      access: "snippet" as const, duplicate_of: null, line_match: "exact" as const },
    { id: "S2", url: "https://example.org/sample-injury-report", title: "Sample injury report",
      publisher: "example.org", author: null, published_at: iso(now - 0.1 * DAY), retrieved_at: iso(now),
      access: "headline" as const, duplicate_of: null, line_match: "unknown" as const },
    { id: "S3", url: "https://example.net/sample-syndicated", title: "Sample injury report (syndicated)",
      publisher: "example.net", author: null, published_at: iso(now - 0.1 * DAY), retrieved_at: iso(now),
      access: "headline" as const, duplicate_of: "S2", line_match: "unknown" as const },
  ] : [];
  const supports = [
    { text: `Sample: box-score history leans toward ${target}.`, kind: "statistical" as const,
      stance: "supports" as const, source_ids: [], verified: true },
    ...(searched ? [{ text: `Sample: a preview argues for ${target}.`, kind: "analyst_opinion" as const,
      stance: "supports" as const, source_ids: ["S1"], verified: true }] : []),
  ];
  const against = [
    { text: "Sample: a key player is listed questionable; minutes could change the picture.", kind: "factual" as const,
      stance: "opposes" as const, source_ids: searched ? ["S2"] : [], verified: searched },
    { text: "Sample: history covers fewer than 15 games, so it is a weak guide.", kind: "interpretation" as const,
      stance: "opposes" as const, source_ids: [], verified: true },
  ];
  const takeaway = llm
    ? `Sample takeaway: the evidence is mixed for ${target}. History leans one way, but an unresolved injury could change it. This third sentence should never be shown.`
    : `Box-score history only (the local model is offline): it leans toward ${target}, with a small sample.`;
  return {
    investigation_id: `fx-${h.ticker}-${h.side}`, status: llm ? "done" : "partial",
    created_at: iso(now), completed_at: iso(now), stale_at: iso(now + 6 * 3600_000),
    hypothesis: h,
    quote: { ask: yes ? 0.34 : 0.67, side: h.side, observed_at: iso(now - 12 * 60_000), fresh: true, snapshot_ref: "sample" },
    summary: {
      takeaway,
      findings: [supports[0]!, against[0]!, against[1]!, supports[1] ?? supports[0]!],
      gaps: searched ? ["Starting lineup not confirmed yet."] : ["No news checked: search was not run."],
      stance: "insufficient", uncertainty: "Small sample; lineup unknown.",
    },
    price_assessment: {
      ask: yes ? 0.34 : 0.67, model_p: null, model_band: null, model_name: null, raw_diff: null,
      conservative_edge: null, break_even: yes ? 0.35 : 0.68, walk_away: null,
      fee_per_contract: 0.0155, slippage_per_contract: 0.005,
      assumptions: ["Ask from the last scan (12 minutes old)", "Taker fee at Kalshi's published rate"],
      abstain_reasons: ["No calibrated model for NBA single-game markets: box-score frequency is not a probability."],
    },
    details: {
      supports, against,
      methodology: ["Sample methodology: box scores (ESPN), then news search, then a local model summary.",
        "Claims without a valid source are dropped or marked unverified."],
      data_gaps: ["Starting lineup", "Late injury news"],
    },
    sources,
    processing: {
      model: llm ? "gemma4:12b (sample)" : null, searches: searched ? 2 : 0, cache: "miss",
      errors: scenario === "ollama_offline" ? ["Local model offline: summary is box-score only."]
        : scenario === "brave_unconfigured" ? ["Brave Search isn't configured: no news was checked."]
        : scenario === "budget_exhausted" ? ["Today's Brave request budget is used up: no news was checked."]
        : scenario === "no_results" ? ["No relevant articles found for this game."] : [],
      partial_reasons: llm ? [] : ["deterministic_only"],
    },
  };
}
