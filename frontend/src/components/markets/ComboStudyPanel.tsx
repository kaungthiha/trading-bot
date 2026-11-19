import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { ComboStudy } from "../../api/types";
import { formatUtc } from "../format";

const pct = (x: number, d = 1) => `${(x * 100).toFixed(d)}%`;

/** How settled Kalshi combos actually paid off vs the price they traded at. */
export function ComboStudyPanel() {
  const [study, setStudy] = useState<ComboStudy | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const load = useCallback(() => {
    api.catalogComboStudy().then((r) => setStudy(r.study), () => setStudy(null));
  }, []);
  useEffect(load, [load]);
  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

  async function refresh() {
    setMsg(null);
    try {
      await api.runJob("combos");
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 409)) {
        setMsg(e instanceof ApiError ? e.message : "Could not start");
        return;
      }
    }
    setBusy(true);
    timer.current = setInterval(() => {
      api.jobs().then((s) => {
        const j = s.jobs.combos;
        if (j && !j.running) {
          if (timer.current) clearInterval(timer.current);
          setBusy(false);
          setMsg(j.last_message);
          load();
        }
      }, () => undefined);
    }, 2000);
  }

  const o = study?.overall;
  return (
    <details className="combo-study small" open={!study}>
      <summary><strong>Do combos pay?</strong>{" "}
        {o?.return_per_dollar != null
          ? <span className={o.return_per_dollar < 1 ? "ev-neg" : "ev-pos"}>${o.return_per_dollar.toFixed(2)} back per $1 staked, across {o.n.toLocaleString()} settled combos</span>
          : "Settled Kalshi combos vs the price they traded at"}</summary>
      <p>
        <button type="button" className="link-button" onClick={refresh} disabled={busy}>
          {busy ? "Studying settled combos… (about a minute)" : study ? "Refresh the study" : "Run the study"}
        </button>
        {study && <span className="muted"> · last run {formatUtc(study.generated_at)}, {study.markets_scanned.toLocaleString()} combos read</span>}
      </p>
      {msg && <p role="status">{msg}</p>}
      {o && (
        <>
          <p>
            Combos traded at <strong>{pct(o.avg_price)}</strong> on average but hit{" "}
            <strong>{pct(o.hit_rate)}</strong> of the time (n = {o.n.toLocaleString()}). A buyer of one
            contract in each got back <strong>${o.return_per_dollar?.toFixed(2)} per $1</strong> before fees.
          </p>
          <div className="coverage-grid">
            {(["by_legs", "by_price"] as const).map((k) => (
              <table className="market-table" key={k}>
                <caption>{k === "by_legs" ? "By number of legs" : "By price paid"}</caption>
                <thead><tr><th scope="col">{k === "by_legs" ? "Legs" : "Price"}</th><th scope="col">Combos</th>
                  <th scope="col">Price</th><th scope="col">Hit</th><th scope="col">Back per $1</th></tr></thead>
                <tbody>
                  {study[k].map((b) => (
                    <tr key={b.bucket}>
                      <td>{b.bucket}</td><td>{b.n.toLocaleString()}</td><td>{pct(b.avg_price)}</td>
                      <td>{pct(b.hit_rate)} <span className="muted">±{pct(b.se)}</span></td>
                      <td className={(b.return_per_dollar ?? 0) < 1 ? "ev-neg" : "ev-pos"}>${b.return_per_dollar?.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ))}
          </div>
          <p className="muted">Caveats: "price" is each combo's last trade, not every buyer's price, and
            late trades after some legs finished pull prices toward the result, which flatters combos.
            The sample is the most recently settled combos Kalshi returns.</p>
        </>
      )}
    </details>
  );
}
