import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { Diagnostics, SetupStatus } from "../api/types";
import { formatUtc } from "./format";

const DISMISS_KEY = "krt.onboarding.dismissed";

/** First-run checklist driven by the backend's /api/setup-status. Dismissible. */
export function GettingStarted() {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [dismissed, setDismissed] = useState(() => localStorage.getItem(DISMISS_KEY) === "1");

  useEffect(() => {
    api.setupStatus().then(setStatus, () => setStatus(null));
  }, []);

  if (!status) return null;
  if (dismissed) {
    return (
      <button type="button" className="link-button small" onClick={() => {
        localStorage.removeItem(DISMISS_KEY);
        setDismissed(false);
      }}>
        Show getting-started checklist
      </button>
    );
  }
  const done = status.steps.filter((s) => s.status === "ok").length;
  return (
    <section className="panel onboarding" aria-labelledby="gs-h">
      <header className="onboarding-header">
        <h2 id="gs-h">Getting started</h2>
        <button type="button" className="link-button small" onClick={() => {
          localStorage.setItem(DISMISS_KEY, "1");
          setDismissed(true);
        }}>
          Hide
        </button>
      </header>
      <p className="small">
        This is a <strong>local research and paper-trading</strong> tool. It never places real
        orders{status.paper_mode ? " (paper mode is enforced)" : ""}. {done} of{" "}
        {status.steps.length} setup steps done. Try the offline demo any time with{" "}
        <code>.\scripts\start-demo.ps1</code>.
      </p>
      <ol className="checklist">
        {status.steps.map((s) => (
          <li key={s.key} className={`check-${s.status}`}>
            <span className={`badge ${s.status === "ok" ? "paper" : "stale"}`}>
              {s.status === "ok" ? "DONE" : s.status === "warn" ? "CHECK" : "TO DO"}
            </span>{" "}
            {s.title}
            {s.status !== "ok" && <div className="ticker">{s.hint}</div>}
          </li>
        ))}
      </ol>
    </section>
  );
}

/** Ingestion and data-health diagnostics from /api/diagnostics. */
export function HealthPanel() {
  const [d, setD] = useState<Diagnostics | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    api.diagnostics().then(setD, () => setError(true));
  }, []);

  if (error) return <p role="alert">Diagnostics unavailable.</p>;
  if (!d) return <p>Loading diagnostics…</p>;
  return (
    <div className="health">
      <p className="small">
        App v{d.app_version} · schema {d.schema_revision ?? "unknown"} · database{" "}
        {d.database_bytes != null ? `${Math.round(d.database_bytes / 1024)} KiB` : "—"} · mode{" "}
        <strong>{d.safety.trading_mode}</strong>, live execution{" "}
        {d.safety.live_execution_enabled ? "ON" : "disabled"}
      </p>
      <table className="market-table">
        <caption className="visually-hidden">Ingestion runs by adapter</caption>
        <thead>
          <tr>
            <th scope="col">Source</th>
            <th scope="col">Last run</th>
            <th scope="col">Last success</th>
            <th scope="col">Recent failures</th>
            <th scope="col">Top error codes</th>
          </tr>
        </thead>
        <tbody>
          {d.ingestion.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">No ingestion runs yet.</td>
            </tr>
          )}
          {d.ingestion.map((a) => (
            <tr key={a.adapter}>
              <td className="ticker">{a.adapter}</td>
              <td>
                {a.last_status}{" "}
                <span className="ticker">{a.last_started_at ? formatUtc(a.last_started_at) : ""}</span>
              </td>
              <td className="ticker">{a.last_success_at ? formatUtc(a.last_success_at) : "never"}</td>
              <td>
                {a.recent_failures}/{a.recent_runs}
              </td>
              <td className="ticker">
                {a.top_error_codes.map(([c, n]) => `${c}×${n}`).join(", ") || "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="small">
        Quotes: {d.quotes.fresh} fresh / {d.quotes.stale} stale of {d.quotes.markets_with_quotes}{" "}
        markets · collection gaps: {d.collection_gaps} · signals (24h): {d.signals_24h.count}
        {d.signals_24h.top_reasons.length > 0 && (
          <> · top abstain reasons: {d.signals_24h.top_reasons.slice(0, 4).map(([r, n]) => `${r}×${n}`).join(", ")}</>
        )}
      </p>
      <p className="small">
        Evidence:{" "}
        {d.evidence.filter((e) => e.configured || e.records > 0).map((e) =>
          `${e.source_id} ${e.records} rows (${e.fresh ? "fresh" : "stale"})`).join(" · ") || "none"}
      </p>
    </div>
  );
}
