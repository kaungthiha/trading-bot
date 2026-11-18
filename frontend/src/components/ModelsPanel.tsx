import { useEffect, useState } from "react";

import { api, ApiError } from "../api/client";
import type { CpiForecast, MetricSummary, ModelCard, ModelEvaluation } from "../api/types";
import { CalibrationChart } from "./CalibrationChart";
import { MetricLabel } from "./MetricLabel";
import { Term } from "./Term";

const THRESHOLDS = ["-0.1", "0.0", "0.1", "0.2", "0.3", "0.4", "0.5", "0.6"];

const pct = (p: number | null | undefined) => (p == null ? "—" : `${(p * 100).toFixed(1)}%`);
const num = (x: number | null | undefined, d = 4) => (x == null ? "—" : x.toFixed(d));

function MetricsRow({ label, m }: { label: string; m: MetricSummary }) {
  return (
    <tr>
      <td>{label}</td>
      <td>{m.n_predictions}</td>
      <td>{m.n_events}</td>
      <td>{m.n_abstained}</td>
      <td>{pct(m.base_rate)}</td>
      <td>{num(m.brier)}</td>
      <td>{num(m.log_loss)}</td>
    </tr>
  );
}

export function ModelsPanel() {
  const [cards, setCards] = useState<ModelCard[]>([]);
  const [evals, setEvals] = useState<ModelEvaluation[]>([]);
  const [threshold, setThreshold] = useState("0.3");
  const [forecast, setForecast] = useState<CpiForecast | null>(null);
  const [forecastError, setForecastError] = useState<string | null>(null);

  useEffect(() => {
    api.models().then(setCards, () => setCards([]));
    api.modelMetrics().then(setEvals, () => setEvals([]));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setForecastError(null);
    api.cpiForecast(threshold).then(
      (r) => !cancelled && setForecast(r),
      (e) => {
        if (cancelled) return;
        setForecast(null);
        setForecastError(e instanceof ApiError ? e.message : "Forecast unavailable");
      },
    );
    return () => {
      cancelled = true;
    };
  }, [threshold]);

  return (
    <div className="models">
      <section aria-labelledby="fc-h">
        <h3 id="fc-h">Next CPI release: month-over-month change above threshold</h3>
        <label className="filters">
          <span>Threshold (%, first print, SA, rounded to 0.1)</span>
          <select value={threshold} onChange={(e) => setThreshold(e.target.value)}>
            {THRESHOLDS.map((t) => (
              <option key={t} value={t}>
                &gt; {t}%
              </option>
            ))}
          </select>
        </label>
        {forecastError && <p role="alert">{forecastError}</p>}
        {forecast && (
          <>
            <p className="ticker">{forecast.contract_key}</p>
            <table className="market-table">
              <thead>
                <tr>
                  <th scope="col">Model</th>
                  <th scope="col">P(YES)</th>
                  <th scope="col">
                    <MetricLabel termId="uncertainty">Uncertainty band</MetricLabel>
                  </th>
                  <th scope="col">Decision</th>
                </tr>
              </thead>
              <tbody>
                {forecast.forecasts.map((f) => (
                  <tr key={f.model}>
                    <td>
                      {f.model} <span className="ticker">v{f.version}</span>
                    </td>
                    <td>{pct(f.p_yes)}</td>
                    <td>
                      {f.lower == null ? "—" : `${pct(f.lower)} – ${pct(f.upper)}`}
                      <div className="ticker">{f.uncertainty_method}</div>
                    </td>
                    <td>
                      {f.decision === "ABSTAIN" ? (
                        <>
                          <span className="badge stale">
                            <Term id="abstention">ABSTAIN</Term>
                          </span>
                          <div className="ticker">{f.reasons.join(", ")}</div>
                        </>
                      ) : (
                        "forecast"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="small muted">
              Recent first prints:{" "}
              {forecast.recent_prints
                .slice(0, 6)
                .map((p) => `${p.month} ${p.mom_rounded}%`)
                .join(" · ")}
            </p>
            <p className="small disclaimer">{forecast.caveat}</p>
            {cards.length > 0 && (
              <div className="warning-box small" role="note" aria-label="Model limitations">
                <strong>Model limitations</strong>
                <ul>
                  {Array.from(new Set(cards.flatMap((c) => c.limitations))).slice(0, 4).map((l) => (
                    <li key={l}>{l}</li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </section>

      <section aria-labelledby="eval-h">
        <h3 id="eval-h">
          <Term id="walk-forward-validation">Walk-forward</Term> evaluation
        </h3>
        {evals.length === 0 ? (
          <p className="muted small">
            No evaluation stored yet. Run <code>python -m app.cli evaluate-models</code>.
          </p>
        ) : (
          evals.map((ev) => (
            <div key={ev.id} className="eval">
              <h4>
                {ev.model} v{ev.version}{" "}
                <span className="ticker">dataset {ev.dataset_hash.slice(0, 12)}</span>
              </h4>
              <table className="market-table">
                <thead>
                  <tr>
                    <th scope="col">Period</th>
                    <th scope="col">Predictions</th>
                    <th scope="col">Months</th>
                    <th scope="col">Abstained</th>
                    <th scope="col">
                      <MetricLabel termId="base-rate">Base rate</MetricLabel>
                    </th>
                    <th scope="col">
                      <MetricLabel termId="brier-score">Brier</MetricLabel>
                    </th>
                    <th scope="col">
                      <MetricLabel termId="log-loss">Log loss</MetricLabel>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <MetricsRow
                    label={`Dev ${ev.config.dev_range?.join(" → ") ?? ""}`}
                    m={ev.dev}
                  />
                  <MetricsRow
                    label={`Holdout ${ev.config.holdout_range?.join(" → ") ?? ""}`}
                    m={ev.holdout}
                  />
                </tbody>
              </table>
              <details>
                <summary className="small">
                  Holdout <Term id="calibration">calibration</Term> (
                  <Term id="out-of-sample">out-of-sample</Term>)
                </summary>
                <CalibrationChart title={`${ev.model}: holdout calibration`}
                  bins={ev.holdout.calibration} />
                <table className="market-table">
                  <caption className="visually-hidden">Calibration table view</caption>
                  <thead>
                    <tr>
                      <th scope="col">Forecast bin</th>
                      <th scope="col">Count</th>
                      <th scope="col">Mean forecast</th>
                      <th scope="col">Observed YES rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ev.holdout.calibration
                      .filter((b) => b.count > 0)
                      .map((b) => (
                        <tr key={b.lower}>
                          <td>
                            {pct(b.lower)}–{pct(b.upper)}
                          </td>
                          <td>{b.count}</td>
                          <td>{pct(b.mean_p)}</td>
                          <td>{pct(b.observed_rate)}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </details>
              <p className="ticker">
                {ev.data_notes.first_prints_used} first prints used; excluded:{" "}
                {Object.entries(ev.data_notes.excluded)
                  .map(([k, v]) => `${k}=${v}`)
                  .join(", ") || "none"}
                . Predictions within a month are correlated; months is the effective sample.
              </p>
            </div>
          ))
        )}
      </section>

      <section aria-labelledby="cards-h">
        <h3 id="cards-h">Model cards</h3>
        {cards.map((c) => (
          <details key={c.name} className="small">
            <summary>
              <strong>{c.name}</strong> v{c.version}: {c.summary}
            </summary>
            <p>
              <strong>Contract:</strong> {c.contract_type}
            </p>
            <p>
              <strong>Features:</strong> {c.features}
            </p>
            <p>
              <strong>Uncertainty:</strong> {c.uncertainty_method}
            </p>
            <p>
              <strong>Limitations:</strong>
            </p>
            <ul>
              {c.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </details>
        ))}
      </section>
    </div>
  );
}
