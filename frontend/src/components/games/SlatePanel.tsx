import { useEffect, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { SlateCombo, SlateResult, SlateState } from "../../api/types";
import { EmptyState } from "../Hairline";
import { BriefCard, LeanChip } from "./BriefCard";
import { ago, pct } from "./format";
import { slip, useSlip } from "./slip";

const POLL_MS = 2000;
const legOf = (x: { ticker: string; side: "yes" | "no"; label: string; event_ticker: string }) =>
  ({ ticker: x.ticker, side: x.side, label: x.label, event: x.event_ticker });

function ComboCard({ c, n }: { c: SlateCombo; n: number }) {
  const put = () => { slip.clear(); c.legs.forEach((x) => slip.add(legOf(x))); };
  return (
    <li className="slate-combo">
      <header className="slate-combo-head">
        <h4>Combo {n} · {c.legs.length} legs · {c.games} game{c.games > 1 ? "s" : ""}</h4>
        <span className="small">
          market <b>{pct(c.adjusted, 1)}</b>{c.pays != null && <> · pays about <b>{c.pays}×</b></>}
          {c.together.length > 0 && <span className="muted"> · same-game legs adjusted</span>}
        </span>
        <button type="button" className="link-button small" onClick={put}>Put on docket</button>
      </header>
      <ol className="slate-legs">
        {c.legs.map((x) => (
          <li key={x.ticker}>
            <div className="slate-leg-top">
              <b className={`side-chip ${x.side}`}>{x.side.toUpperCase()}</b>
              <span className="slate-leg-label">{x.label}</span>
              <span className="small muted">{x.game} · {pct(x.price)}</span>
            </div>
            <ul className="brief-list for small">
              {x.why.map((p) => <li key={p.text}><span aria-hidden="true">+</span> {p.text}</li>)}
            </ul>
          </li>
        ))}
      </ol>
      {c.risks.length > 0 && (
        <details className="slate-risks small" open>
          <summary>What could sink it ({c.risks.length})</summary>
          <ul className="brief-list against">
            {c.risks.map((r) => <li key={`${r.leg}-${r.text}`}><span aria-hidden="true">−</span> <b>{r.leg}:</b> {r.text}</li>)}
          </ul>
        </details>
      )}
      {c.past?.return_per_dollar != null && (
        <p className="small muted">Past {c.past.bucket} combos on Kalshi paid ${c.past.return_per_dollar.toFixed(2)} per $1
          ({c.past.n.toLocaleString()} settled, all users, before fees).</p>
      )}
    </li>
  );
}

function Result({ r }: { r: SlateResult }) {
  const legs = useSlip();
  const on = new Set(legs.map((l) => l.ticker));
  const [lo, hi] = r.rules.leg_price;
  return (
    <>
      <p className="small muted">
        {r.briefed} legs briefed across {r.games.length} game{r.games.length === 1 ? "" : "s"}
        {" "}· {r.leans.strong ?? 0} strong, {r.leans.mixed ?? 0} mixed, {r.leans.weak ?? 0} weak
        {" "}· built {ago(r.generated_at)}
      </p>
      {r.skipped.length > 0 && <p className="small inj-note">Skipped: {r.skipped.map((s) => s.game).join(", ")}</p>}
      {r.combos.length === 0 ? (
        <EmptyState figure="sieve" title="No combo passed tonight">
          Not enough legs had a clear case (at least {r.rules.min_score} more points for than against, at most one
          against, priced {Math.round(lo * 100)}–{Math.round(hi * 100)}%). Passing is a fine outcome.
        </EmptyState>
      ) : (
        <ol className="slate-combos">{r.combos.map((c, i) => <ComboCard key={c.legs.map((x) => x.ticker).join()} c={c} n={i + 1} />)}</ol>
      )}
      {r.pool.length > 0 && (
        <details className="slate-pool">
          <summary className="small">Clear-case legs ({r.pool.length}): build your own</summary>
          <ul className="slate-pool-list">
            {r.pool.map((x) => (
              <li key={`${x.ticker}:${x.side}`}>
                <div className="slate-leg-top">
                  <LeanChip lean={x.brief.lean} />
                  <b className={`side-chip ${x.side}`}>{x.side.toUpperCase()}</b>
                  <span className="slate-leg-label">{x.label}</span>
                  <span className="small muted">{x.game} · {pct(x.price)}</span>
                  <button type="button" className="link-button small" aria-pressed={on.has(x.ticker)}
                    onClick={() => slip.toggle(legOf(x))}>{on.has(x.ticker) ? "On docket" : "Add"}</button>
                </div>
                <BriefCard brief={x.brief} compact />
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

/** Tonight's NBA slate: 3-4 leg combos built only from legs with a clear case, each leg shown
 * with the facts for it and everything against the combo. Built on click, in the background. */
export function SlatePanel({ prefix = "KXNBA" }: { prefix?: string }) {
  const [st, setSt] = useState<SlateState | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancel = false;
    api.slate(prefix).then((s) => { if (!cancel) setSt(s); },
      (e) => { if (!cancel) setErr(e instanceof ApiError ? e.message : "Backend unreachable"); });
    return () => { cancel = true; };
  }, [prefix]);

  const building = st?.status === "building";
  useEffect(() => {
    if (!building) return;
    const t = setInterval(() => {
      api.slate(prefix).then(setSt, () => { /* keep polling */ });
    }, POLL_MS);
    return () => clearInterval(t);
  }, [building, prefix]);

  const build = () => {
    setErr(null);
    api.buildSlate(prefix).then(setSt, (e) => setErr(e instanceof ApiError ? e.message : "Couldn't start"));
  };
  const r = st?.result ?? null;
  return (
    <section className="slate" aria-labelledby="slate-h">
      <header className="slate-head">
        <h3 id="slate-h">Tonight's combos</h3>
        <button type="button" className="primary-button" onClick={build} disabled={building}>
          {building ? "Building…" : r ? "Rebuild" : "Build tonight's combos"}
        </button>
      </header>
      <p className="small muted">
        Each leg gets a brief: recent form against its price, minutes, what tonight's opponent allows, head-to-head,
        rest, injuries. Combos use only legs with a clear case. These are leads to research, not forecasts.
      </p>
      {err && <p role="alert" className="small">{err}</p>}
      {building && <p className="small" aria-live="polite">{st?.progress ?? "Starting"}… (first build reads every game's box scores: about a minute)</p>}
      {st?.status === "failed" && <p role="alert" className="small">Build failed: {st.error}</p>}
      {r ? <Result r={r} /> : !building && st?.status !== "failed" && (
        <EmptyState figure="loupe" title="Not built yet">
          Build reads ESPN box scores for every game tonight (free, no search spend), then suggests up to three
          combos. Or pick a game on the left for one game's markets.
        </EmptyState>
      )}
    </section>
  );
}
