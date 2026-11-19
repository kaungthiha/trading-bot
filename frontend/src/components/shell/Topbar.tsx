import { useEffect, useState } from "react";

import type { Health } from "../../api/types";
import { StatusLabel } from "../design/StatusLabel";
import { Figure } from "../Hairline";
import { exact, rel } from "../today/time";
import { useScanTime } from "../docket/scanTime";
import { useDensity } from "./useDensity";

/** Scans older than this get a "stale" label. The full-catalog scan runs every few minutes
 * when auto-scan is on, so 30 minutes means it has stopped. */
export const SCAN_STALE_MIN = 30;

/** Re-render once a minute so relative times ("12m ago") stay true. */
export function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(t);
  }, []);
  return now;
}

/** When every Kalshi price on Explore and Today was last refreshed (the catalog scan).
 * Pages with their own quotes (signals, slips) still show their own as-of time. */
export function ScanFreshness() {
  const at = useScanTime();
  const now = useNow();
  if (at === undefined) return null;
  if (at === null) return <StatusLabel tone="warn">Prices: never scanned</StatusLabel>;
  const stale = now - Date.parse(at) > SCAN_STALE_MIN * 60_000;
  return (
    <StatusLabel tone={stale ? "stale" : "neutral"}
      title={`Last full Kalshi market scan: ${exact(at)}. Run "Scan now" to refresh every price.`}>
      Prices scanned {rel(at, now)}{stale ? " · stale" : ""}
    </StatusLabel>
  );
}

export type HealthLoad =
  | { state: "loading" } | { state: "ok"; data: Health } | { state: "error"; message: string };

/** One place for "what am I looking at": data source, mode, execution and backend state.
 * Each price on the pages still carries its own as-of time; this is the global heartbeat. */
export function DataHeartbeat({ health }: { health: HealthLoad }) {
  if (health.state === "loading") {
    return <div className="heartbeat" role="status"><span className="muted">Connecting…</span></div>;
  }
  if (health.state === "error") {
    return (
      <div className="heartbeat" role="status">
        <StatusLabel tone="stale">Backend: {health.message}</StatusLabel>
      </div>
    );
  }
  const h = health.data;
  const source = `Market data: ${h.market_data_source}${h.market_data_source === "kalshi_public"
    ? ` (${h.kalshi_env})` : ""} · database ${h.database}`;
  return (
    <div className="heartbeat" role="status">
      {h.env === "demo" && <StatusLabel tone="demo">DEMO · synthetic data</StatusLabel>}
      <StatusLabel tone="paper"
        title="Research and paper trading. No real orders are placed by this app.">
        {h.trading_mode.toUpperCase()} MODE
      </StatusLabel>
      <ScanFreshness />
      <span className="hb-item">Live execution: {h.live_execution_enabled ? "ON" : "disabled"}</span>
      {h.database === "ok"
        ? <StatusLabel tone="ok" title={source}>connected</StatusLabel>
        : <StatusLabel tone="stale" title={source}>DB: {h.database}</StatusLabel>}
    </div>
  );
}

export function Topbar({ health }: { health: HealthLoad }) {
  const [density, setDensity] = useDensity();
  return (
    <header className="topbar">
      <h1 className="wordmark"><Figure name="terrain" size={30} /> <span>Kalshi <em>Research</em></span></h1>
      <DataHeartbeat health={health} />
      <button type="button" className="density-toggle" aria-pressed={density === "compact"}
        onClick={() => setDensity(density === "compact" ? "comfortable" : "compact")}
        title="Tighter rows in tables and grids. Saved in this browser.">
        Compact rows
      </button>
    </header>
  );
}
