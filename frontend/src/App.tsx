import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "./api/client";
import type {
  Health,
  IngestionRun,
  MarketDetail as MarketDetailT,
  MarketFilters,
  MarketSummary,
} from "./api/types";
import { ControlBar } from "./components/ControlBar";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { EvidencePanel } from "./components/EvidencePanel";
import { ExecutionPanel } from "./components/ExecutionPanel";
import { GamesPage } from "./components/games/GamesPage";
import { GlossaryPage } from "./components/GlossaryPage";
import { EmptyState, Figure, PageHead } from "./components/Hairline";
import { HistoryPage } from "./components/history/HistoryPage";
import { MarketDetail } from "./components/MarketDetail";
import { MarketFiltersBar } from "./components/MarketFiltersBar";
import { MarketList } from "./components/MarketList";
import { MarketsPage } from "./components/markets/MarketsPage";
import { ModelsPanel } from "./components/ModelsPanel";
import { OpportunitiesPanel } from "./components/OpportunitiesPanel";
import { GettingStarted, HealthPanel } from "./components/OpsPanels";
import { PaperPanel } from "./components/PaperPanel";
import { SignalsPanel } from "./components/SignalsPanel";
import { formatUtc } from "./components/format";
import { useDataRefresh } from "./components/useDataRefresh";
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
  useDataRefresh(useCallback(() => {
    setFilters((f) => ({ ...f }));
    api.categories().then((r) => setCategories(r.items), () => undefined);
    api.ingestionRuns(1).then((r) => setLastRun(r.items[0] ?? null), () => undefined);
  }, []));
  const route = useHashRoute();
  const [termTab, setTermTab] = useState<TermTab>(() => {
    const v = sessionStorage.getItem("krt.termTab");
    return TERMINAL_TABS.some((t) => t.id === v) ? (v as TermTab) : "scanner";
  });
  useEffect(() => { sessionStorage.setItem("krt.termTab", termTab); }, [termTab]);

  return (
    <GlossaryProvider>
    <div className="app">
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="app-header">
        <h1><Figure name="terrain" size={30} /> Kalshi Research</h1>
        <nav aria-label="Primary" className="nav">
          <a href="#/" aria-current={route.page === "terminal" ? "page" : undefined}>Terminal</a>
          <a href="#/games" aria-current={route.page === "games" ? "page" : undefined}>Games</a>
          <a href="#/markets" aria-current={route.page === "markets" ? "page" : undefined}>Markets</a>
          <a href="#/history" aria-current={route.page === "history" ? "page" : undefined}>My trades</a>
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
              <span className="badge paper" title="Research and paper trading. No real orders are placed by this app.">{health.data.trading_mode.toUpperCase()} MODE</span>
              <span>Live execution: {health.data.live_execution_enabled ? "ON" : "disabled"}</span>
              <span title={`Market data: ${health.data.market_data_source}${health.data.market_data_source === "kalshi_public" ? ` (${health.data.kalshi_env})` : ""} · database ${health.data.database}`}>
                {health.data.database === "ok" ? "● connected" : `DB: ${health.data.database}`}
              </span>
            </>
          ) : health.state === "error" ? (
            <span className="badge stale">Backend: {health.message}</span>
          ) : (
            <span>Connecting…</span>
          )}
        </div>
      </header>

      <ErrorBoundary resetKey={route.page}>
      {route.page === "glossary" ? (
        <main id="main"><GlossaryPage focusTerm={route.term} /></main>
      ) : route.page === "history" ? (
        <main id="main"><HistoryPage /></main>
      ) : route.page === "games" ? (
        <main id="main">
          <GamesPage gameRef={route.game}
            onOpenGame={(r) => { window.location.hash = r ? `#/games?game=${encodeURIComponent(r)}` : "#/games"; }} />
        </main>
      ) : route.page === "markets" ? (
        <main id="main">
          <MarketsPage eventTicker={route.event}
            onOpenEvent={(t) => { window.location.hash = t ? `#/markets?event=${encodeURIComponent(t)}` : "#/markets"; }} />
        </main>
      ) : (
      <main id="main">
        <PageHead figure="terrain" title="Terminal" actions={<ControlBar compact />}>
          Scanner ideas, your watchlist, signals and paper trading.
        </PageHead>
        <div className="subtabs" role="tablist" aria-label="Terminal sections">
          {TERMINAL_TABS.map((t) => (
            <button key={t.id} type="button" role="tab" aria-selected={termTab === t.id}
              onClick={() => setTermTab(t.id)}>{t.label}</button>
          ))}
        </div>
        <div className="subtab-panel" role="tabpanel" key={termTab}>
        {termTab === "scanner" && (
          <section aria-labelledby="opps-h" className="panel">
            <h2 id="opps-h" className="visually-hidden">Opportunities (scanner)</h2>
            <OpportunitiesPanel />
          </section>
        )}
        {termTab === "watchlist" && (
          <div className="layout">
            <section aria-labelledby="discover-h" className="panel">
              <h2 id="discover-h">Watchlist</h2>
              {lastRun && (
                <p className="small muted">
                  Last ingestion: <strong>{lastRun.status}</strong> via {lastRun.adapter}, {lastRun.count} markets,{" "}
                  {formatUtc(lastRun.finished_at ?? lastRun.started_at)}
                  {lastRun.errors.length > 0 && <span className="badge stale">{lastRun.errors.length} errors</span>}
                </p>
              )}
              <MarketFiltersBar categories={categories} value={filters} onChange={onFilters} />
              {markets.state === "loading" && <p>Loading markets…</p>}
              {markets.state === "error" && <p role="alert">{markets.message}</p>}
              {markets.state === "ok" && (
                <MarketList markets={markets.data} selectedId={selectedId} onSelect={setSelectedId} />
              )}
            </section>
            <section aria-label="Market detail" className="panel">
              {detail === null && <EmptyState figure="loupe" title="Pick a market">Its rules and live quote show here.</EmptyState>}
              {detail?.state === "loading" && <p>Loading…</p>}
              {detail?.state === "error" && <p role="alert">{detail.message}</p>}
              {detail?.state === "ok" && <MarketDetail market={detail.data} />}
            </section>
          </div>
        )}
        {termTab === "signals" && (
          <section aria-labelledby="signals-h" className="panel"><h2 id="signals-h">Signals</h2><SignalsPanel /></section>
        )}
        {termTab === "paper" && (
          <>
            <section aria-labelledby="paper-h" className="panel"><h2 id="paper-h">Paper trading</h2><PaperPanel /></section>
            <section aria-labelledby="exec-h" className="panel"><h2 id="exec-h">Execution (approval-gated)</h2><ExecutionPanel /></section>
          </>
        )}
        {termTab === "models" && (
          <>
            <section aria-labelledby="models-h" className="panel"><h2 id="models-h">Models</h2><ModelsPanel /></section>
            <section aria-labelledby="evidence-h" className="panel"><h2 id="evidence-h">Evidence</h2><EvidencePanel /></section>
          </>
        )}
        {termTab === "system" && (
          <>
            <div className="panel"><ControlBar /></div>
            <GettingStarted />
            <section aria-labelledby="health-h" className="panel"><h2 id="health-h">Health</h2><HealthPanel /></section>
          </>
        )}
        </div>
      </main>
      )}
      </ErrorBoundary>
      <footer className="app-footer small muted">
        Research and paper-trading tool: model probabilities are not profits, and no orders are placed.{" "}
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

type TermTab = "scanner" | "watchlist" | "signals" | "paper" | "models" | "system";
const TERMINAL_TABS: { id: TermTab; label: string }[] = [
  { id: "scanner", label: "Scanner" }, { id: "watchlist", label: "Watchlist" },
  { id: "signals", label: "Signals" }, { id: "paper", label: "Paper & execution" },
  { id: "models", label: "Models & evidence" }, { id: "system", label: "Setup & health" },
];

type Route = { page: "terminal" | "glossary" | "markets" | "history" | "games"; term: string | null;
  event: string | null; game: string | null };

function parseHash(hash: string): Route {
  const m = /^#\/glossary(?:\?term=([a-z0-9-]{1,64}))?$/.exec(hash);
  if (m) return { page: "glossary", term: m[1] ?? null, event: null, game: null };
  if (hash === "#/history") return { page: "history", term: null, event: null, game: null };
  const mg = /^#\/games(?:\?game=(KX[A-Z0-9]{2,20}-[A-Z0-9]{4,40}))?$/.exec(hash);
  if (mg) return { page: "games", term: null, event: null, game: mg[1] ?? null };
  const mk = /^#\/markets(?:\?event=([A-Za-z0-9._%-]{1,200}))?$/.exec(hash);
  if (mk) {
    let event: string | null = null;
    try { event = mk[1] ? decodeURIComponent(mk[1]) : null; } catch { event = null; }
    return { page: "markets", term: null, game: null,
      event: event && /^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$/.test(event) ? event : null };
  }
  return { page: "terminal", term: null, event: null, game: null };
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
