import { useEffect, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { ComboLeg, ComboResult } from "../../api/types";

interface Props {
  legs: ComboLeg[];
  onRemove: (ticker: string) => void;
  onClear: () => void;
}

/** Price a parlay from its legs, assuming independence, and say when that's wrong. */
export function ComboTray({ legs, onRemove, onClear }: Props) {
  const [res, setRes] = useState<ComboResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [quote, setQuote] = useState("");

  useEffect(() => {
    if (legs.length === 0) { setRes(null); return; }
    api.catalogCombo(legs).then((r) => { setRes(r); setErr(null); },
      (e) => setErr(e instanceof ApiError ? e.message : "Could not price the combo"));
  }, [legs]);

  if (legs.length === 0) return null;
  const probOf = (t: string) => res?.legs.find((l) => l.ticker === t)?.probability;
  return (
    <aside className="combo-tray" aria-label="Combo builder">
      <header>
        <strong>Combo builder ({legs.length} leg{legs.length > 1 ? "s" : ""})</strong>
        <button type="button" className="link-button small" onClick={onClear}>Clear</button>
      </header>
      <ul>
        {legs.map((l) => {
          const p = probOf(l.ticker);
          return (
            <li key={l.ticker}>
              <span className={`badge ${l.side === "yes" ? "paper" : "stale"}`}>{l.side.toUpperCase()}</span>{" "}
              {l.label} <span className="ticker">{l.ticker}</span>{" "}
              {p != null && <span className="small">({(p * 100).toFixed(1)}%)</span>}{" "}
              <button type="button" className="link-button small" aria-label={`Remove ${l.label}`}
                onClick={() => onRemove(l.ticker)}>remove</button>
            </li>
          );
        })}
      </ul>
      {err && <p role="alert" className="small">{err}</p>}
      {res && (
        <>
          {res.fair_price != null ? (
            <p>
              All legs win: <strong>{(res.fair_price * 100).toFixed(2)}%</strong> if independent, so a fair
              combo price is about <strong>${res.fair_price.toFixed(2)}</strong> per $1
              {res.fair_multiple != null && <> ({res.fair_multiple}× payout)</>}. Kalshi quotes combos
              on request in its app: <em>a quote below this is good only if the legs really are independent.</em>
            </p>
          ) : <p className="muted small">No joint probability (some legs lack a two-sided quote).</p>}
          {res.kalshi && legs.length >= 2 && (
            <p className="small">
              {res.kalshi.eligible
                ? <><span className="badge paper">Kalshi can build this</span> ({res.kalshi.collections.join(", ")})</>
                : <><span className="badge stale">Not combinable on Kalshi</span>{res.kalshi.ineligible_events.length > 0 && <> ({res.kalshi.ineligible_events.join(", ")} not in any combo collection)</>}</>}
            </p>
          )}
          {res.kalshi?.history && (
            <p className="small">
              History: settled {res.kalshi.history.bucket} combos traded at {(res.kalshi.history.avg_price * 100).toFixed(1)}%
              and hit {(res.kalshi.history.hit_rate * 100).toFixed(1)}% (n = {res.kalshi.history.n.toLocaleString()}),
              so buyers got <strong>${res.kalshi.history.return_per_dollar?.toFixed(2)} back per $1</strong>.
            </p>
          )}
          {res.fair_price != null && legs.length >= 2 && (
            <label className="small quote-check">
              Kalshi's quote for this combo (¢){" "}
              <input type="number" min={1} max={99} step={1} value={quote} onChange={(e) => setQuote(e.target.value)} />
              {Number(quote) > 0 && (
                <span> → you pay {Number(quote).toFixed(0)}¢ for a {(res.fair_price * 100).toFixed(1)}¢ independent fair value:{" "}
                  <strong className={Number(quote) / 100 > res.fair_price ? "ev-neg" : "ev-pos"}>
                    {Number(quote) / 100 > res.fair_price
                      ? `${((Number(quote) / 100 / res.fair_price - 1) * 100).toFixed(0)}% markup`
                      : `${((1 - Number(quote) / 100 / res.fair_price) * 100).toFixed(0)}% below fair`}
                  </strong>
                  {res.warnings.some((w) => w.startsWith("Same game")) && " (legs are correlated, so the true fair value differs)"}
                </span>
              )}
            </label>
          )}
          {res.warnings.length > 0 && (
            <div className="warning-box small"><ul>{res.warnings.map((w) => <li key={w}>{w}</li>)}</ul></div>
          )}
        </>
      )}
    </aside>
  );
}
