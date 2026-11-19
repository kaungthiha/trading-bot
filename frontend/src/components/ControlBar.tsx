import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import type { JobName, JobsSnapshot } from "../api/types";
import { formatUtc } from "./format";
import { announceDataUpdated } from "./useDataRefresh";

const BUTTONS: { job: JobName; label: string; help: string }[] = [
  { job: "refresh", label: "Refresh data", help: "Kalshi markets → mapping proposals → signals" },
  { job: "evidence", label: "Refresh FRED", help: "New CPI vintages → re-evaluate models" },
  { job: "scan", label: "Scan now", help: "Scan every open Kalshi market for mispricings" },
];

/** Buttons for the data flow, replacing the CLI for everyday use. `compact` shows only
 * "Scan now" (it refreshes every price) with a one-line status. */
export function ControlBar({ compact = false }: { compact?: boolean }) {
  const [snap, setSnap] = useState<JobsSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wasRunning = useRef<Set<string>>(new Set());

  const poll = useCallback(() => {
    api.jobs().then((s) => {
      const nowRunning = new Set<string>(
        Object.values(s.jobs).filter((j) => j.running).map((j) => j.name),
      );
      // A job just finished -> let every panel reload its data.
      if ([...wasRunning.current].some((n) => !nowRunning.has(n))) announceDataUpdated();
      wasRunning.current = nowRunning;
      setSnap(s);
    }, () => setSnap(null));
  }, []);

  // Poll once on mount, then on a timer that only resets when "anything running" flips.
  // (Depending on `snap` itself re-ran the effect -- and an immediate poll -- after every
  // poll: an endless request loop.)
  useEffect(poll, [poll]);
  const anyRunning = !!snap && Object.values(snap.jobs).some((j) => j.running);
  useEffect(() => {
    const t = setInterval(poll, anyRunning ? 1500 : 15000);
    return () => clearInterval(t);
  }, [poll, anyRunning]);

  async function run(job: JobName) {
    setError(null);
    try {
      setSnap(await api.runJob(job));
      wasRunning.current.add(job);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start the job");
      poll();
    }
  }

  async function toggleAuto(enabled: boolean) {
    setError(null);
    try {
      setSnap(await api.setAutoScan(enabled));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not change auto-scan");
    }
  }

  if (!snap) return null;
  if (compact) {
    const st = snap.jobs.scan;
    if (!st) return null;
    return (
      <section className="control-bar compact" aria-label="Data controls">
        <button type="button" onClick={() => run("scan")} disabled={st.running} title={BUTTONS[2]!.help}>
          {st.running ? "Scanning…" : "Scan now"}
        </button>
        <label className="auto-toggle small">
          <input type="checkbox" checked={snap.auto_scan.enabled} disabled={snap.worker_running}
            onChange={(e) => toggleAuto(e.target.checked)} /> auto every {Math.round(snap.auto_scan.interval_seconds / 60)} min
        </label>
        <span className="small muted" role="status">
          {st.running ? "Loading every open market (about a minute)…"
            : st.last_finished ? <>Last scan {formatUtc(st.last_finished)}{st.last_status === "failed" && <> · <span className="badge stale">failed</span> {st.last_message}</>}</>
            : "Prices are from the last scan. Scan now refreshes every market (about a minute)."}
        </span>
        {error && <span role="alert" className="small">{error}</span>}
      </section>
    );
  }
  return (
    <section className="control-bar" aria-label="Data controls">
      <div className="control-buttons">
        {BUTTONS.map((b) => {
          const st = snap.jobs[b.job];
          if (!st) return null; // job unknown to this backend version
          return (
            <button key={b.job} type="button" onClick={() => run(b.job)} disabled={st.running}
              title={b.help} aria-describedby={`job-${b.job}`}>
              {st.running ? `${b.label}: running…` : b.label}
            </button>
          );
        })}
        <label className="auto-toggle" title={snap.worker_running
          ? "The background worker is already scanning" : "Scan every few minutes while the app runs"}>
          <input type="checkbox" checked={snap.auto_scan.enabled} disabled={snap.worker_running}
            onChange={(e) => toggleAuto(e.target.checked)} />{" "}
          Auto-scan every {Math.round(snap.auto_scan.interval_seconds / 60)} min
        </label>
        {snap.worker_running && <span className="badge paper">worker running</span>}
      </div>
      <ul className="job-status small">
        {BUTTONS.map((b) => {
          const st = snap.jobs[b.job];
          if (!st) return null; // job unknown to this backend version
          return (
            <li key={b.job} id={`job-${b.job}`}>
              <strong>{b.label}:</strong>{" "}
              {st.running ? "running…" : st.last_finished ? (
                <>
                  <span className={`badge ${st.last_status === "failed" ? "stale" : "paper"}`}>
                    {st.last_status}
                  </span>{" "}
                  {st.last_message} <span className="ticker">({formatUtc(st.last_finished)})</span>
                </>
              ) : (
                <span className="muted">not run yet{b.job === "refresh" && ` (watchlist: ${snap.watchlist.join(", ")})`}</span>
              )}
            </li>
          );
        })}
      </ul>
      {error && <p role="alert" className="small">{error}</p>}
    </section>
  );
}
