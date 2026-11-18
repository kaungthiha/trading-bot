import type { ApiErrorBody, Health, MarketDetail, MarketList } from "./types";

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
  markets: (category?: string) =>
    getJson<MarketList>(
      category ? `/api/markets?category=${encodeURIComponent(category)}` : "/api/markets",
    ),
  market: (id: string) => getJson<MarketDetail>(`/api/markets/${encodeURIComponent(id)}`),
};
