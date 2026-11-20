import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "./api/client";
import type {
  Health,
  IngestionRun,
  MarketDetail as MarketDetailT,
  MarketFilters,
  MarketSummary,
} from "./api/types";
import { ControlBar } from "./components/ControlBar";
import { ResearchDocket } from "./components/docket/ResearchDocket";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { GamesPage } from "./components/games/GamesPage";
import { EmptyState, PageHead } from "./components/Hairline";
import { MarketDetail } from "./components/MarketDetail";
import { MarketFiltersBar } from "./components/MarketFiltersBar";
import { MarketList } from "./components/MarketList";
import { ExploreSwitch } from "./components/shell/ExploreSwitch";
import { LeftRail } from "./components/shell/LeftRail";
import { Topbar } from "./components/shell/Topbar";
import { formatUtc } from "./components/format";
import { TodayPage } from "./components/today/TodayPage";
import { useDataRefresh } from "./components/useDataRefresh";
import { GlossaryProvider } from "./glossary/GlossaryContext";
import { href, sectionOf, type TermTab, useHashRoute } from "./router";
import { InvestigationHost } from "./components/investigate/InvestigationDrawer";

// Pages and Tools panels you don't open first load on demand (keeps the first load small).
const EvidencePanel = lazy(() => import("./components/EvidencePanel").then((m) => ({ default: m.EvidencePanel })));
const ExecutionPanel = lazy(() => import("./components/ExecutionPanel").then((m) => ({ default: m.ExecutionPanel })));
const GlossaryPage = lazy(() => import("./components/GlossaryPage").then((m) => ({ default: m.GlossaryPage })));
const HistoryPage = lazy(() => import("./components/history/HistoryPage").then((m) => ({ default: m.HistoryPage })));
const MarketsPage = lazy(() => import("./components/markets/MarketsPage").then((m) => ({ default: m.MarketsPage })));
const ModelsPanel = lazy(() => import("./components/ModelsPanel").then((m) => ({ default: m.ModelsPanel })));
const OpportunitiesPanel = lazy(() => import("./components/OpportunitiesPanel").then((m) => ({ default: m.OpportunitiesPanel })));
const PaperPanel = lazy(() => import("./components/PaperPanel").then((m) => ({ default: m.PaperPanel })));
const SignalsPanel = lazy(() => import("./components/SignalsPanel").then((m) => ({ default: m.SignalsPanel })));
const ResearchWorkspace = lazy(() => import("./components/research/ResearchWorkspace").then((m) => ({ default: m.ResearchWorkspace })));
const GettingStarted = lazy(() => import("./components/OpsPanels").then((m) => ({ default: m.GettingStarted })));
const HealthPanel = lazy(() => import("./components/OpsPanels").then((m) => ({ default: m.HealthPanel })));

function PageLoading() {
  return <p className="page-loading small muted" role="status">Loading…</p>;
}

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
    if (route.tab) return route.tab;
    const v = sessionStorage.getItem("krt.termTab");
    return TERMINAL_TABS.some((t) => t.id === v) ? (v as TermTab) : "scanner";
  });
  useEffect(() => { if (route.tab) setTermTab(route.tab); }, [route.tab]);
  useEffect(() => { sessionStorage.setItem("krt.termTab", termTab); }, [termTab]);
  // The Docket follows you across the research pages (audit Phase 3).
  const showDocket = route.page === "today" || route.page === "games" || route.page === "markets"
    || route.page === "research";
  const pickTab = (t: TermTab) => {
    setTermTab(t);
    // Keep the address shareable without adding a history entry per tab click.
    if (route.page === "tools") window.history.replaceState(null, "", href.tools(t));
  };

  // On navigation between pages, move focus to the new page's title so keyboard and
  // screen-reader users start at the top (not mid-page). Not on first load.
  const lastPage = useRef(route.page);
  const seenTitle = useRef<Element | null>(null);
  useEffect(() => {
    const first = lastPage.current === route.page; // first load (and StrictMode's re-run)
    lastPage.current = route.page;
    const old = seenTitle.current;
    // Wait for THIS page's title: while a lazy page loads, the old page can still be shown.
    const take = () => {
      const h = document.querySelector<HTMLElement>("#main h2");
      if (!h || h === old) return false;
      seenTitle.current = h;
      if (!first) { h.tabIndex = -1; h.focus(); }
      return true;
    };
    if (take()) return;
    const obs = new MutationObserver(() => { if (take()) obs.disconnect(); });
    obs.observe(document.body, { childList: true, subtree: true });
    const stop = setTimeout(() => obs.disconnect(), 3000);
    return () => { obs.disconnect(); clearTimeout(stop); };
  }, [route.page]);

  return (
    <GlossaryProvider>
    <div className={`app shell${showDocket ? " has-docket" : ""}`}>
      <a className="skip-link" href="#main">Skip to content</a>
      <Topbar health={health} />
      <LeftRail section={sectionOf(route.page)} />
      <div className="work">

      <Suspense fallback={<PageLoading />}>
      <ErrorBoundary resetKey={`${route.page}:${route.research?.kind ?? ""}:${route.research?.id ?? ""}`}>
      {route.page === "research" && route.research ? (
        <main id="main"><ResearchWorkspace kind={route.research.kind} id={route.research.id} /></main>
      ) : route.page === "today" ? (
        <main id="main"><TodayPage /></main>
      ) : route.page === "learn" ? (
        <main id="main"><GlossaryPage focusTerm={route.term} /></main>
      ) : route.page === "journal" ? (
        <main id="main"><HistoryPage /></main>
      ) : route.page === "games" ? (
        <main id="main">
          <ExploreSwitch page="games" />
          <GamesPage gameRef={route.game}
            onOpenGame={(r) => { window.location.hash = href.game(r); }} />
        </main>
      ) : route.page === "markets" ? (
        <main id="main">
          <ExploreSwitch page="markets" />
          <MarketsPage eventTicker={route.event}
            onOpenEvent={(t) => { window.location.hash = href.market(t); }} />
        </main>
      ) : (
      <main id="main">
        <PageHead figure="terrain" title="Tools" actions={<ControlBar compact />}>
          The full scanner, your watchlist, model signals, paper trading and approval-gated
          execution, models and evidence, setup and health.
        </PageHead>
        <div className="subtabs" role="tablist" aria-label="Tools sections">
          {TERMINAL_TABS.map((t) => (
            <button key={t.id} type="button" role="tab" aria-selected={termTab === t.id}
              onClick={() => pickTab(t.id)}>{t.label}</button>
          ))}
        </div>
        <div className="subtab-panel" role="tabpanel" key={termTab}>
        <Suspense fallback={<PageLoading />}>
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
        </Suspense>
        </div>
      </main>
      )}
      </ErrorBoundary>
      </Suspense>
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
      {showDocket && <ResearchDocket />}
      <InvestigationHost />
    </div>
    </GlossaryProvider>
  );
}

const TERMINAL_TABS: { id: TermTab; label: string }[] = [
  { id: "scanner", label: "Scanner" }, { id: "watchlist", label: "Watchlist" },
  { id: "signals", label: "Signals" }, { id: "paper", label: "Paper & execution" },
  { id: "models", label: "Models & evidence" }, { id: "system", label: "Setup & health" },
];
