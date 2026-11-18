import type {
  ApiErrorBody,
  CollectionGap,
  CpiForecast,
  Diagnostics,
  EvidenceAsOf,
  EvidenceSource,
  FeeScheduleInfo,
  Health,
  IngestionRun,
  MarketDetail,
  MarketFilters,
  MarketList,
  ModelCard,
  ModelEvaluation,
  PaperAccount,
  PaperOrder,
  PaperOrderInput,
  PaperSettlement,
  ReplayReport,
  SetupStatus,
  Signal,
  SignalLineage,
} from "./types";

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

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    credentials: "omit",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      // CSRF defence: custom header forces a CORS preflight the backend denies cross-origin.
      "X-KRT-Request": "paper",
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
  feeSchedules: () => getJson<FeeScheduleInfo[]>("/api/fee-schedules"),
  models: () => getJson<ModelCard[]>("/api/models"),
  modelMetrics: () => getJson<ModelEvaluation[]>("/api/models/metrics"),
  cpiForecast: (threshold: string) =>
    getJson<CpiForecast>(
      `/api/research/cpi-mom/forecast?threshold=${encodeURIComponent(threshold)}`,
    ),
};
