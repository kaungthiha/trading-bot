import type {
  ApiErrorBody,
  BookSnapshot,
  CatalogCategory,
  CatalogEventDetail,
  CatalogEventList,
  CatalogSeries,
  CatalogSort,
  CatalogStatus,
  ComboResult,
  ComboStudy,
  GameIdeas,
  SlateState,
  IdeasAi,
  OpenReview,
  ExpectedValue,
  HistoryFill,
  HistoryReport,
  HistorySimilar,
  HistoryStatus,
  Side,
  CollectionGap,
  CpiForecast,
  Diagnostics,
  ExecutionIntent,
  ExecutionStatus,
  EvidenceAsOf,
  EvidenceSource,
  FeeScheduleInfo,
  Health,
  JobName,
  JobsSnapshot,
  IngestionRun,
  MarketDetail,
  MarketFilters,
  MarketList,
  ModelCard,
  ModelEvaluation,
  OpportunityCard,
  PaperAccount,
  PaperOrder,
  PaperOrderInput,
  PaperSettlement,
  ReplayReport,
  ScannerStatus,
  EvidenceResult,
  GameDetail,
  GameInjuries,
  GameList,
  NewsResult,
  OpenAnalysis,
  ReviewResult,
  ReviewStatus,
  LlmStatus,
  CoachResult,
  SlipCheck,
  Scorecard,
  SetupStatus,
  Signal,
  SignalLineage,
  ExcerptInput,
  InvestigationResult,
  ResearchJob,
  ResearchPreflight,
  ResearchUsage,
} from "./types";

/** Query string from defined, non-empty values. */
function qs(params: Record<string, string | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) u.set(k, v);
  const s = u.toString();
  return s ? `?${s}` : "";
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

// Same-origin relative URLs only; the Vite dev server proxies /api to the loopback backend.
// No credentials or auth headers are ever attached from the browser.
async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: "application/json" }, credentials: "omit" });
  if (!res.ok) {
    let code = "HTTP_ERROR";
    let message = `Request failed (${res.status})`;
    try {
      const body = (await res.json()) as ApiErrorBody;
      code = body.error.code;
      message = body.error.message;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, code, message);
  }
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body: unknown, purpose = "paper"): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    credentials: "omit",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      // CSRF defence: custom header forces a CORS preflight the backend denies cross-origin.
      "X-KRT-Request": purpose,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let code = "HTTP_ERROR";
    let message = `Request failed (${res.status})`;
    try {
      const b = (await res.json()) as ApiErrorBody;
      code = b.error.code;
      message = b.error.message;
    } catch {
      /* non-JSON */
    }
    throw new ApiError(res.status, code, message);
  }
  return (await res.json()) as T;
}

function newClientOrderId(): string {
  return `ui-${crypto.randomUUID().replaceAll("-", "").slice(0, 24)}`;
}

export const api = {
  setupStatus: () => getJson<SetupStatus>("/api/setup-status"),
  historyStatus: () => getJson<HistoryStatus>("/api/history/status"),
  historyReport: () => getJson<HistoryReport>("/api/history/report"),
  coachStatus: () => getJson<LlmStatus>("/api/history/coach/status"),
  coach: () => postJson<CoachResult>("/api/history/coach", {}, "review"),
  historyOpen: () => getJson<OpenAnalysis>("/api/history/open"),
  historySimilar: (p: { legs?: { ticker: string; side: Side }[]; series?: string[] }) =>
    getJson<HistorySimilar>(`/api/history/similar${qs({
      legs: p.legs?.length ? p.legs.map((l) => `${l.ticker}:${l.side}`).join(",") : undefined,
      series: p.series?.length ? p.series.join(",") : undefined })}`),
  openReview: () => postJson<OpenReview>("/api/history/open/review", {}, "review"),
  historyFills: (limit = 100) => getJson<{ items: HistoryFill[] }>(`/api/history/fills?limit=${limit}`),
  catalogStatus: () => getJson<CatalogStatus>("/api/catalog/status"),
  catalogCategories: () => getJson<{ items: CatalogCategory[] }>("/api/catalog/categories"),
  catalogSeries: (category?: string, q?: string) =>
    getJson<{ items: CatalogSeries[] }>(`/api/catalog/series${qs({ category, q })}`),
  catalogEvents: (p: { category?: string; series?: string; q?: string; sort?: CatalogSort; offset?: number }) =>
    getJson<CatalogEventList>(`/api/catalog/events${qs({ ...p, offset: p.offset ? String(p.offset) : undefined, limit: "50" })}`),
  catalogEvent: (ticker: string) =>
    getJson<CatalogEventDetail>(`/api/catalog/events/${encodeURIComponent(ticker)}`),
  catalogEv: (ticker: string, p: { side: Side; prob: string; contracts: number; price?: string }) =>
    getJson<ExpectedValue>(`/api/catalog/markets/${encodeURIComponent(ticker)}/ev${qs({
      side: p.side, prob: p.prob, contracts: String(p.contracts), price: p.price || undefined })}`),
  catalogCombo: (legs: { ticker: string; side: Side }[]) =>
    getJson<ComboResult>(`/api/catalog/combo${qs({ legs: legs.map((l) => `${l.ticker}:${l.side}`).join(",") })}`),
  catalogComboStudy: () => getJson<{ study: ComboStudy | null }>("/api/catalog/combo-study"),
  games: (league?: string) => getJson<GameList>(`/api/games${qs({ league })}`),
  game: (prefix: string, key: string, protectedProps = false) =>
    getJson<GameDetail>(`/api/games/${encodeURIComponent(prefix)}/${encodeURIComponent(key)}${qs({
      protected: protectedProps ? "true" : undefined })}`),
  gameInjuries: (prefix: string, key: string) =>
    getJson<GameInjuries>(`/api/games/${encodeURIComponent(prefix)}/${encodeURIComponent(key)}/injuries`),
  legEvidence: (legs: { ticker: string; side: Side }[]) =>
    getJson<EvidenceResult>(`/api/games/evidence${qs({ legs: legs.map((l) => `${l.ticker}:${l.side}`).join(",") })}`),
  slipCheck: (legs: { ticker: string; side: Side }[], stake?: number, quote?: number) =>
    getJson<SlipCheck>(`/api/games/check${qs({ legs: legs.map((l) => `${l.ticker}:${l.side}`).join(","),
      stake: stake ? stake.toFixed(2) : undefined, quote: quote ? quote.toFixed(2) : undefined })}`),
  // POST + header: spends one Brave request (app-wide cap), so only a click can trigger it.
  news: (q: string) => postJson<NewsResult>("/api/games/news", { q }, "research"),
  ideas: (prefix: string, key: string) =>
    getJson<GameIdeas>(`/api/games/${encodeURIComponent(prefix)}/${encodeURIComponent(key)}/ideas`),
  slate: (prefix: string) => getJson<SlateState>(`/api/games/slate/${encodeURIComponent(prefix)}`),
  // POST + header: starts a background build (ESPN only, free), so only a click starts one.
  buildSlate: (prefix: string) =>
    postJson<SlateState>(`/api/games/slate/${encodeURIComponent(prefix)}`, {}, "slate"),
  ideasAi: (prefix: string, key: string) =>
    postJson<IdeasAi>(`/api/games/${encodeURIComponent(prefix)}/${encodeURIComponent(key)}/ideas/ai`, {}, "review"),
  reviewStatus: () => getJson<ReviewStatus>("/api/games/review/status"),
  review: (legs: { ticker: string; side: Side }[], quoteCents?: number) =>
    postJson<ReviewResult>("/api/games/review", {
      legs: legs.map((l) => ({ ticker: l.ticker, side: l.side })),
      quote_cents: quoteCents ?? null }, "review"),
  catalogBook: (ticker: string) =>
    getJson<BookSnapshot>(`/api/catalog/markets/${encodeURIComponent(ticker)}/book`),
  jobs: () => getJson<JobsSnapshot>("/api/jobs"),
  runJob: (name: JobName) => postJson<JobsSnapshot>(`/api/jobs/${name}/run`, {}, "ops"),
  setAutoScan: (enabled: boolean) => postJson<JobsSnapshot>("/api/jobs/auto-scan", { enabled }, "ops"),
  opportunities: () => getJson<OpportunityCard[]>("/api/opportunities?limit=50"),
  opportunity: (id: string) => getJson<OpportunityCard>(`/api/opportunities/${encodeURIComponent(id)}`),
  scannerStatus: () => getJson<ScannerStatus>("/api/scanner/status"),
  scorecard: () => getJson<Scorecard>("/api/scorecard"),
  journal: (id: string, body: { action: "EXECUTED" | "SKIPPED" | "NOTE";
    legs: { ticker: string; side: string; quantity: number; avg_price: string; fee: string }[];
    note: string }) =>
    postJson<OpportunityCard>(`/api/opportunities/${encodeURIComponent(id)}/journal`, body, "journal"),
  executionStatus: () => getJson<ExecutionStatus>("/api/execution/status"),
  executionIntents: () => getJson<ExecutionIntent[]>("/api/execution/intents"),
  proposeIntent: (body: { market_id: string; side: "YES" | "NO"; quantity: number; limit_price: string }) =>
    postJson<ExecutionIntent>("/api/execution/intents", body, "execution"),
  approveIntent: (id: string, payload_hash: string, pin: string) =>
    postJson<ExecutionIntent>(`/api/execution/intents/${encodeURIComponent(id)}/approve`,
      { payload_hash, pin }, "execution"),
  reconcileIntent: (id: string) =>
    postJson<ExecutionIntent>(`/api/execution/intents/${encodeURIComponent(id)}/reconcile`, {}, "execution"),
  engageKillSwitch: (reason: string) =>
    postJson<{ kill_switch_engaged: boolean }>("/api/execution/kill-switch", { reason }, "execution"),
  diagnostics: () => getJson<Diagnostics>("/api/diagnostics"),
  signalLineage: (id: string) =>
    getJson<SignalLineage>(`/api/lineage/signal/${encodeURIComponent(id)}`),
  paperAccount: () => getJson<PaperAccount>("/api/paper/account"),
  paperOrders: () => getJson<PaperOrder[]>("/api/paper/orders?limit=100"),
  paperSettlements: () => getJson<PaperSettlement[]>("/api/paper/settlements"),
  paperReplay: (scenario?: string) =>
    getJson<ReplayReport>(
      scenario ? `/api/paper/replay?scenario=${encodeURIComponent(scenario)}` : "/api/paper/replay",
    ),
  placePaperOrder: (input: PaperOrderInput) =>
    postJson<PaperOrder>("/api/paper/orders", { ...input, client_order_id: newClientOrderId() }),
  health: () => getJson<Health>("/api/health"),
  markets: (filters: MarketFilters = {}) => {
    const params = new URLSearchParams({ limit: "200" });
    if (filters.category) params.set("category", filters.category);
    if (filters.status) params.set("status", filters.status);
    if (filters.q?.trim()) params.set("q", filters.q.trim());
    return getJson<MarketList>(`/api/markets?${params.toString()}`);
  },
  categories: () => getJson<{ items: string[] }>("/api/categories"),
  ingestionRuns: (limit = 1) =>
    getJson<{ items: IngestionRun[] }>(`/api/ingestion/runs?limit=${limit}`),
  market: (id: string) => getJson<MarketDetail>(`/api/markets/${encodeURIComponent(id)}`),
  evidenceSources: () => getJson<{ items: EvidenceSource[] }>("/api/evidence/sources"),
  evidenceAsOf: (sourceId: string, asOf?: string, limit = 12) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (asOf) params.set("as_of", asOf);
    return getJson<EvidenceAsOf>(
      `/api/evidence/${encodeURIComponent(sourceId)}/observations?${params.toString()}`,
    );
  },
  collectionGaps: () => getJson<{ items: CollectionGap[] }>("/api/collection-gaps?limit=20"),
  signals: () => getJson<Signal[]>("/api/signals?limit=50"),
  signal: (id: string) => getJson<Signal>(`/api/signals/${encodeURIComponent(id)}`),
  researchPreflight: (ticker: string, side: Side) =>
    getJson<ResearchPreflight>(`/api/research/preflight${qs({ ticker, side })}`),
  researchUsage: () => getJson<ResearchUsage>("/api/research/usage"),
  /** Queue an investigation (explicit click only); returns at once. */
  startResearchJob: (body: { kind: "investigate" | "refresh"; ticker: string; side: Side; label?: string | null;
    investigation_id?: string | null }) => postJson<ResearchJob>("/api/research/jobs", body, "research"),
  /** Job status: free, never starts work. */
  researchJob: (id: string) => getJson<ResearchJob>(`/api/research/jobs/${encodeURIComponent(id)}`),
  cancelResearchJob: (id: string) =>
    postJson<ResearchJob>(`/api/research/jobs/${encodeURIComponent(id)}/cancel`, {}, "research"),
  /** Your pasted excerpt: kept locally, link never fetched, no search spent. */
  addExcerpt: (id: string, body: ExcerptInput) =>
    postJson<InvestigationResult>(`/api/research/investigations/${encodeURIComponent(id)}/excerpts`, body, "research"),
  removeExcerpt: (id: string, excerptId: string) =>
    postJson<InvestigationResult>(
      `/api/research/investigations/${encodeURIComponent(id)}/excerpts/${encodeURIComponent(excerptId)}/remove`, {}, "research"),
  investigate: (ticker: string, side: Side, label?: string) =>
    postJson<InvestigationResult>("/api/research/investigations", { ticker, side, label: label ?? null }, "research"),
  refreshInvestigation: (id: string) =>
    postJson<InvestigationResult>(`/api/research/investigations/${encodeURIComponent(id)}/refresh`, {}, "research"),
  feeSchedules: () => getJson<FeeScheduleInfo[]>("/api/fee-schedules"),
  models: () => getJson<ModelCard[]>("/api/models"),
  modelMetrics: () => getJson<ModelEvaluation[]>("/api/models/metrics"),
  cpiForecast: (threshold: string) =>
    getJson<CpiForecast>(
      `/api/research/cpi-mom/forecast?threshold=${encodeURIComponent(threshold)}`,
    ),
};
