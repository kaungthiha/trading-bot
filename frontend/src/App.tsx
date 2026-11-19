import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "./api/client";
import type {
  Health,
  IngestionRun,
  MarketDetail as MarketDetailT,
  MarketFilters,
  MarketSummary,
} from "./api/types";
import { EvidencePanel } from "./components/EvidencePanel";
import { ExecutionPanel } from "./components/ExecutionPanel";
import { GlossaryPage } from "./components/GlossaryPage";
import { MarketDetail } from "./components/MarketDetail";
import { MarketFiltersBar } from "./components/MarketFiltersBar";
import { MarketList } from "./components/MarketList";
import { ModelsPanel } from "./components/ModelsPanel";
import { OpportunitiesPanel } from "./components/OpportunitiesPanel";
import { GettingStarted, HealthPanel } from "./components/OpsPanels";
import { PaperPanel } from "./components/PaperPanel";
import { SignalsPanel } from "./components/SignalsPanel";
import { formatUtc } from "./components/format";
import { GlossaryProvider } from "./glossary/GlossaryContext";

type Load<T> = { state: "loading" } | { state: "ok"; data: T } | { state: "error"; message: string };

function errMsg(e: unknown): string {
  return e instanceof ApiError ? `${e.code}: ${e.message}` : "Backend unreachable";
}

export default function App() {
  const [health, setHealth] = useState<Load<Health>>({ state: "loading" });
  const [lastRun, setLastRun] = useState<IngestionRun | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [filters, setFilters] = useState<MarketFilters>({});
  const [markets, setMarkets] = useState<Load<MarketSummary[]>>({ state: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Load<MarketDetailT> | null>(null);

  useEffect(() => {
    api.health().then(
      (data) => setHealth({ state: "ok", data }),
      (e) => setHealth({ state: "error", message: errMsg(e) }),
    );
    api.categories().then((r) => setCategories(r.items), () => setCategories([]));
    api.ingestionRuns(1).then((r) => setLastRun(r.items[0] ?? null), () => setLastRun(null));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setMarkets({ state: "loading" });
    api.markets(filters).then(
      (data) => !cancelled && setMarkets({ state: "ok", data: data.items }),
      (e) => !cancelled && setMarkets({ state: "error", message: errMsg(e) }),
    );
    return () => {
      cancelled = true;
    };
  }, [filters]);

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

  const onFilters = useCallback((next: MarketFilters) => setFilters(next), []);
  const route = useHashRoute();

  return (
    <GlossaryProvider>
    <div className="app">
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="app-header">
        <h1>Kalshi Research Terminal</h1>
        <nav aria-label="Primary" className="nav">
          <a href="#/" aria-current={route.page === "terminal" ? "page" : undefined}>Terminal</a>
          <a href="#/glossary" aria-current={route.page === "glossary" ? "page" : undefined}>
            Glossary
          </a>
        </nav>
        <div className="mode-banner" role="status">
          {health.state === "ok" ? (
            <>
              {health.data.env === "demo" && (
                <span className="badge demo">DEMO · synthetic data</span>
              )}
              <span className="badge paper">{health.data.trading_mode.toUpperCase()} MODE</span>
              <span>Live execution: {health.data.live_execution_enabled ? "ON" : "disabled"}</span>
              <span>
                Data: {health.data.market_data_source}
                {health.data.market_data_source === "kalshi_public" && ` (${health.data.kalshi_env})`}
              </span>
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
        {lastRun && (
          <>
            {" "}
            Last ingestion: <strong>{lastRun.status}</strong> via {lastRun.adapter},{" "}
            {lastRun.count} markets, {formatUtc(lastRun.finished_at ?? lastRun.started_at)}
            {lastRun.errors.length > 0 && (
              <span className="badge stale">{lastRun.errors.length} errors</span>
            )}
          </>
        )}
      </p>

      {route.page === "glossary" ? (
        <main id="main"><GlossaryPage focusTerm={route.term} /></main>
      ) : (
      <main id="main" className="layout">
        <div className="panel-wide"><GettingStarted /></div>
        <section aria-labelledby="discover-h" className="panel">
          <h2 id="discover-h">Discover</h2>
          <MarketFiltersBar categories={categories} value={filters} onChange={onFilters} />
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
        <section aria-labelledby="opps-h" className="panel panel-wide">
          <h2 id="opps-h">Opportunities (scanner)</h2>
          <OpportunitiesPanel />
        </section>
        <section aria-labelledby="signals-h" className="panel panel-wide">
          <h2 id="signals-h">Signals</h2>
          <SignalsPanel />
        </section>
        <section aria-labelledby="paper-h" className="panel panel-wide">
          <h2 id="paper-h">Paper trading</h2>
          <PaperPanel />
        </section>
        <section aria-labelledby="exec-h" className="panel panel-wide">
          <h2 id="exec-h">Execution (approval-gated)</h2>
          <ExecutionPanel />
        </section>
        <section aria-labelledby="models-h" className="panel panel-wide">
          <h2 id="models-h">Models</h2>
          <ModelsPanel />
        </section>
        <section aria-labelledby="health-h" className="panel panel-wide">
          <h2 id="health-h">Health</h2>
          <HealthPanel />
        </section>
        <section aria-labelledby="evidence-h" className="panel panel-wide">
          <h2 id="evidence-h">Evidence</h2>
          <EvidencePanel />
        </section>
      </main>
      )}
      <footer className="app-footer small muted">
        {/* Required by the FRED API Terms of Use. */}
        This product uses the FRED® API but is not endorsed or certified by the Federal Reserve
        Bank of St. Louis.{" "}
        <a
          href="https://fred.stlouisfed.org/docs/api/terms_of_use.html"
          target="_blank"
          rel="noopener noreferrer"
        >
          FRED API Terms of Use
        </a>
        .
      </footer>
    </div>
    </GlossaryProvider>
  );
}

type Route = { page: "terminal" | "glossary"; term: string | null };

function parseHash(hash: string): Route {
  const m = /^#\/glossary(?:\?term=([a-z0-9-]{1,64}))?$/.exec(hash);
  return m ? { page: "glossary", term: m[1] ?? null } : { page: "terminal", term: null };
}

/** Minimal hash router (no dependency): #/ = terminal, #/glossary[?term=id]. */
function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
