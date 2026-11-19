import { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { ComboResult, EvidenceResult, LegEvidence, Verdict } from "../../api/types";
import { EmptyState } from "./Figure";
import { cents, pct } from "./format";
import { LegResearch } from "./LegResearch";
import { SecondOpinion } from "./SecondOpinion";
import { SlipCheck } from "./SlipCheck";
import { slip, useSlip } from "./slip";
import { useTween } from "./useTween";

const VERDICT: Record<Verdict, { text: string; cls: string; tip: string }> = {
  agrees: { text: "fits history", cls: "v-ok", tip: "The price sits inside the range past games suggest." },
  market_lower: { text: "history: likelier", cls: "v-up", tip: "Past games say this happens more often than the price implies." },
  market_higher: { text: "history: less likely", cls: "v-down", tip: "The price implies more than past games support." },
  thin: { text: "thin data", cls: "v-thin", tip: "Fewer than 8 games on record." },
  no_price: { text: "no price", cls: "v-thin", tip: "No two-sided quote." },
};

function useDebounced<T>(v: T, ms: number): T {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

export function BetSlip() {
  const legs = useSlip();
  const key = legs.map((l) => `${l.ticker}:${l.side}`).join(",");
  const dkey = useDebounced(key, 350);
  const [combo, setCombo] = useState<ComboResult | null>(null);
  const [ev, setEv] = useState<EvidenceResult | null>(null);
  const [evKey, setEvKey] = useState("");
  const [evErr, setEvErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [quote, setQuote] = useState("");

  useEffect(() => {
    if (!key) { setCombo(null); return; }
    let cancel = false;
    api.catalogCombo(slip.get()).then((r) => { if (!cancel) setCombo(r); }, () => { if (!cancel) setCombo(null); });
    return () => { cancel = true; };
  }, [key]);

  useEffect(() => {
    if (!dkey) { setEv(null); setEvKey(""); return; }
    let cancel = false;
    setEvErr(null);
    api.legEvidence(slip.get()).then((r) => { if (!cancel) { setEv(r); setEvKey(dkey); } },
      (e) => { if (!cancel) { setEvErr(e instanceof ApiError ? e.message : "Evidence unavailable"); setEvKey(dkey); } });
    return () => { cancel = true; };
  }, [dkey]);

  const evBy = useMemo(() => new Map((ev?.legs ?? []).map((l) => [`${l.ticker}:${l.side}`, l])), [ev]);
  const loading = !!key && evKey !== key;
  const fair = combo?.fair_price ?? null;
  const adj = ev && evKey === key ? ev.adjusted_probability : null;
  const fairT = useTween(fair);
  const adjT = useTween(adj);
  const q = Number(quote) / 100;
  const ref = adj ?? fair;
  const n = legs.length;

  return (
    <aside className="slip" aria-label="Bet slip">
      <header className="slip-head">
        <strong>Slip</strong>
        <span className="count" key={n} aria-label={`${n} legs`}>{n}</span>
        {n > 0 && <button type="button" className="link-button small" onClick={() => slip.clear()}>Clear</button>}
      </header>
      {n === 0 ? (
        <EmptyState figure="basket" title="Empty slip">Tap any price on a game to add a leg.</EmptyState>
      ) : (
        <>
          <ul className="slip-legs">
            {legs.map((l) => {
              const e: LegEvidence | undefined = evBy.get(`${l.ticker}:${l.side}`);
              const cl = combo?.legs.find((x) => x.ticker === l.ticker);
              const v = e?.verdict ? VERDICT[e.verdict] : null;
              const isOpen = open === l.ticker;
              return (
                <li key={l.ticker} className="slip-leg">
                  <div className="leg-main">
                    <div className="side-toggle" role="group" aria-label={`Side for ${l.label}`}>
                      {(["yes", "no"] as const).map((s) => (
                        <button key={s} type="button" aria-pressed={l.side === s}
                          onClick={() => slip.setSide(l.ticker, s)}>{s.toUpperCase()}</button>
                      ))}
                    </div>
                    <button type="button" className="leg-label" aria-expanded={isOpen}
                      onClick={() => setOpen(isOpen ? null : l.ticker)} title={l.ticker}>
                      {l.label}
                    </button>
                    <span className="leg-p">{pct(cl?.probability)}</span>
                    <button type="button" className="x" aria-label={`Remove ${l.label}`}
                      onClick={() => slip.remove(l.ticker)}>×</button>
                  </div>
                  <div className="leg-sub">
                    {loading && !e ? <span className="shimmer" aria-hidden="true" />
                      : v ? <span className={`verdict ${v.cls}`} title={v.tip}>{v.text}</span>
                      : e && !e.supported ? <span className="verdict v-thin" title={e.reason}>no check</span> : null}
                    {e?.windows && <span className="muted small">L10 {e.windows.last10[0]}/{e.windows.last10[1]}</span>}
                    {e?.injury && <span className="inj small" title={e.injury.detail}>{e.injury.status}</span>}
                  </div>
                  <div className={`drawer${isOpen ? " open" : ""}`}>
                    <div>{isOpen && <LegResearch ev={e} loading={loading} />}</div>
                  </div>
                </li>
              );
            })}
          </ul>
          {evErr && <p role="alert" className="small">{evErr}</p>}
          <div className="slip-summary">
            {n >= 2 ? (
              <>
                <div className="big-num" aria-live="polite">
                  <span className="label">Fair price</span>
                  <span className="value">{fairT == null ? "—" : `${(fairT * 100).toFixed(1)}¢`}</span>
                  {fair ? <span className="muted small">pays {(1 / fair).toFixed(1)}×</span> : null}
                </div>
                {adjT != null && fair != null && Math.abs((adj ?? 0) - fair) >= 0.005 && (
                  <div className="big-num alt">
                    <span className="label" title="Market prices × how often these legs actually landed together in past games">History-adjusted</span>
                    <span className="value">{(adjT * 100).toFixed(1)}¢</span>
                    <span className="muted small">{(adj ?? 0) > fair ? "legs move together" : "legs pull apart"}</span>
                  </div>
                )}
                {ev?.correlation.map((c) => c.lift != null && (
                  <p key={`${c.game_key}-${c.team}`} className="small corr-line">
                    {c.team} legs all hit <b>{c.together}/{c.games}</b> past games (independent: {c.expected?.toFixed(1)}) → ×{c.lift.toFixed(2)}
                  </p>
                ))}
                {combo?.kalshi && (
                  <p className="small">
                    {combo.kalshi.eligible
                      ? <span className="badge paper">Combinable on Kalshi</span>
                      : <span className="badge stale" title={combo.kalshi.ineligible_events.join(", ")}>Not combinable on Kalshi</span>}
                    {combo.kalshi.history?.return_per_dollar != null && (
                      <span className="muted" title={`${combo.kalshi.history.n.toLocaleString()} settled ${combo.kalshi.history.bucket} combos`}>
                        {" "}· past {combo.kalshi.history.bucket} combos paid ${combo.kalshi.history.return_per_dollar.toFixed(2)}/$1
                      </span>
                    )}
                  </p>
                )}
                {combo && combo.warnings.length > 0 && (
                  <details className="small notes">
                    <summary>{combo.warnings.length} note{combo.warnings.length > 1 ? "s" : ""}</summary>
                    <ul>{combo.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
                  </details>
                )}
              </>
            ) : (
              <p className="small muted">Single leg: price {cents(combo?.legs[0]?.probability)}. Add another leg to price a combo.</p>
            )}
            <SlipCheck legs={legs} quote={quote} onQuote={setQuote} refPrice={ref} />
            <SecondOpinion legs={legs} quoteCents={q > 0 && q < 1 ? Math.round(q * 100) : undefined} />
          </div>
        </>
      )}
      <p className="fine small muted">Estimates, not advice. You place any trade yourself on Kalshi.</p>
    </aside>
  );
}
