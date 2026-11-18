import type {
  ApiErrorBody,
  CollectionGap,
  EvidenceAsOf,
  EvidenceSource,
  Health,
  IngestionRun,
  MarketDetail,
  MarketFilters,
  MarketList,
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

export const api = {
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
};
