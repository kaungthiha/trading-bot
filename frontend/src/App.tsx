import { useEffect, useState } from "react";

import { api, ApiError } from "./api/client";
import type { Health, MarketDetail as MarketDetailT, MarketSummary } from "./api/types";
import { MarketDetail } from "./components/MarketDetail";
import { MarketList } from "./components/MarketList";

type Load<T> = { state: "loading" } | { state: "ok"; data: T } | { state: "error"; message: string };

function errMsg(e: unknown): string {
  return e instanceof ApiError ? `${e.code}: ${e.message}` : "Backend unreachable";
}

export default function App() {
  const [health, setHealth] = useState<Load<Health>>({ state: "loading" });
  const [markets, setMarkets] = useState<Load<MarketSummary[]>>({ state: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Load<MarketDetailT> | null>(null);

  useEffect(() => {
    api.health().then(
      (data) => setHealth({ state: "ok", data }),
      (e) => setHealth({ state: "error", message: errMsg(e) }),
    );
    api.markets().then(
      (data) => setMarkets({ state: "ok", data: data.items }),
      (e) => setMarkets({ state: "error", message: errMsg(e) }),
    );
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    setDetail({ state: "loading" });
    api.market(selectedId).then(
      (data) => !cancelled && setDetail({ state: "ok", data }),
      (e) => !cancelled && setDetail({ state: "error", message: errMsg(e) }),
    );
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  return (
    <div className="app">
      <header className="app-header">
        <h1>Kalshi Research Terminal</h1>
        <div className="mode-banner" role="status">
          {health.state === "ok" ? (
            <>
              <span className="badge paper">{health.data.trading_mode.toUpperCase()} MODE</span>
              <span>Live execution: {health.data.live_execution_enabled ? "ON" : "disabled"}</span>
              <span>Data: {health.data.market_data_source}</span>
              <span>DB: {health.data.database}</span>
            </>
          ) : health.state === "error" ? (
            <span className="badge stale">Backend: {health.message}</span>
          ) : (
            <span>Connecting…</span>
          )}
        </div>
      </header>
      <p className="disclaimer">
        Research and paper-trading tool. Model probabilities are not profits; no orders are placed.
      </p>

      <main className="layout">
        <section aria-labelledby="discover-h" className="panel">
          <h2 id="discover-h">Discover</h2>
          {markets.state === "loading" && <p>Loading markets…</p>}
          {markets.state === "error" && <p role="alert">{markets.message}</p>}
          {markets.state === "ok" && (
            <MarketList markets={markets.data} selectedId={selectedId} onSelect={setSelectedId} />
          )}
        </section>
        <section aria-label="Market detail" className="panel">
          {detail === null && <p className="muted">Select a market to see its rules and quote.</p>}
          {detail?.state === "loading" && <p>Loading…</p>}
          {detail?.state === "error" && <p role="alert">{detail.message}</p>}
          {detail?.state === "ok" && <MarketDetail market={detail.data} />}
        </section>
      </main>
    </div>
  );
}
