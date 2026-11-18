import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { CollectionGap, EvidenceAsOf, EvidenceSource } from "../api/types";
import { Term } from "./Term";
import { formatUtc } from "./format";

/** Convert a local <input type="datetime-local"> value to an ISO string with offset. */
function localInputToIso(v: string): string | undefined {
  if (!v) return undefined;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

export function EvidencePanel() {
  const [sources, setSources] = useState<EvidenceSource[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [asOfInput, setAsOfInput] = useState("");
  const [view, setView] = useState<EvidenceAsOf | null>(null);
  const [gaps, setGaps] = useState<CollectionGap[]>([]);

  useEffect(() => {
    api.evidenceSources().then(
      (r) => {
        setSources(r.items);
        const first = r.items.find((s) => s.record_count > 0) ?? r.items.find((s) => s.configured);
        setSelected(first?.id ?? null);
      },
      () => setError("Could not load evidence sources"),
    );
    api.collectionGaps().then((r) => setGaps(r.items), () => setGaps([]));
  }, []);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    api.evidenceAsOf(selected, localInputToIso(asOfInput)).then(
      (r) => !cancelled && setView(r),
      () => !cancelled && setView(null),
    );
    return () => {
      cancelled = true;
    };
  }, [selected, asOfInput]);

  if (error) return <p role="alert">{error}</p>;
  if (!sources) return <p>Loading evidence…</p>;
  const current = sources.find((s) => s.id === selected) ?? null;

  return (
    <div className="evidence">
      <table className="market-table">
        <caption className="visually-hidden">Evidence sources</caption>
        <thead>
          <tr>
            <th scope="col">Source</th>
            <th scope="col">Records</th>
            <th scope="col">Latest vintage</th>
            <th scope="col">Freshness</th>
            <th scope="col">Last run</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((s) => (
            <tr key={s.id} aria-selected={s.id === selected}>
              <td>
                <button type="button" className="link-button" onClick={() => setSelected(s.id)}>
                  {s.title}
                </button>
                <div className="ticker">
                  {s.id} · {s.upstream_agency} {!s.configured && <span className="badge">not scheduled</span>}
                </div>
              </td>
              <td>{s.record_count}</td>
              <td>
                {s.latest_vintage ?? "—"}
                {s.latest_available_at && <div className="ticker">avail. {formatUtc(s.latest_available_at)}</div>}
              </td>
              <td>
                {s.record_count === 0 ? (
                  <span className="badge stale">NO DATA</span>
                ) : s.is_fresh ? (
                  <span className="badge paper">FRESH</span>
                ) : (
                  <span className="badge stale">STALE (&gt;{s.freshness_max_age_days}d)</span>
                )}
              </td>
              <td>
                {s.last_run ? (
                  <>
                    {s.last_run.status}
                    {s.last_run.errors.length > 0 && (
                      <span className="badge stale">{s.last_run.errors.length} errors</span>
                    )}
                  </>
                ) : (
                  "never"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {current && (
        <section aria-labelledby="asof-h" className="asof">
          <h3 id="asof-h">{current.series_id}: values known as of…</h3>
          <label className="filters">
            <span>
              As-of time (blank = now). Only values published by then are shown, which
              prevents <Term id="look-ahead-bias">look-ahead bias</Term>.
            </span>
            <input
              type="datetime-local"
              value={asOfInput}
              onChange={(e) => setAsOfInput(e.target.value)}
            />
          </label>
          {view && view.items.length === 0 && <p className="muted">Nothing had been published by then.</p>}
          {view && view.items.length > 0 && (
            <table className="market-table">
              <thead>
                <tr>
                  <th scope="col">Period</th>
                  <th scope="col">Value</th>
                  <th scope="col">Vintage (published)</th>
                  <th scope="col">Available at</th>
                </tr>
              </thead>
              <tbody>
                {view.items.map((o) => (
                  <tr key={o.observation_date}>
                    <td>{o.observation_date.slice(0, 7)}</td>
                    <td>{o.value ?? <span className="badge stale">MISSING</span>}</td>
                    <td>{o.vintage_date}</td>
                    <td>{formatUtc(o.available_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="small muted">
            {current.release_timing_note} Units: {view?.items[0]?.units ?? "—"}.{" "}
            <a href={current.source_page_url} target="_blank" rel="noopener noreferrer">
              Source page
            </a>
          </p>
          <p className="small muted">{current.license_notes}</p>
        </section>
      )}

      <section aria-labelledby="gaps-h">
        <h3 id="gaps-h">Collection gaps</h3>
        {gaps.length === 0 ? (
          <p className="muted small">No gaps recorded.</p>
        ) : (
          <ul className="small">
            {gaps.map((g) => (
              <li key={g.id}>
                <strong>{g.job}</strong>: {formatUtc(g.gap_start)} → {formatUtc(g.gap_end)}{" "}
                {g.backfillable ? (
                  <span className="badge paper">recoverable</span>
                ) : (
                  <span className="badge stale">not recoverable</span>
                )}
                <div className="muted">{g.reason}</div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
