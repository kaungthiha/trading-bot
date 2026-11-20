import { useEffect, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { ComboLeg, SlipCheck as SlipCheckT } from "../../api/types";
import { Term } from "../Term";

const VERDICT = {
  reasonable: { cls: "v-ok", text: "Reasonable" },
  stretch: { cls: "v-thin", text: "Stretch" },
  avoid: { cls: "v-down", text: "Avoid" },
  single: { cls: "v-thin", text: "Single leg" },
} as const;
const c = (s: string | null | undefined) => (s == null ? "—" : `${Math.round(Number(s) * 100)}¢`);

function useDebounced<T>(v: T, ms: number): T {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

/** Stake + quote in; verdict, walk-away price, sizing and cheaper alternatives out. */
export function SlipCheck({ legs, quote, onQuote, refPrice }: {
  legs: ComboLeg[]; quote: string; onQuote: (v: string) => void; refPrice: number | null }) {
  const [stake, setStake] = useState("");
  const [res, setRes] = useState<SlipCheckT | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const key = useDebounced(`${legs.map((l) => `${l.ticker}:${l.side}`).join(",")}|${stake}|${quote}`, 400);

  useEffect(() => {
    if (legs.length === 0) { setRes(null); return; }
    let cancel = false;
    const s = Number(stake), q = Number(quote) / 100;
    api.slipCheck(legs, s > 0 ? s : undefined, q > 0 && q < 1 ? q : undefined)
      .then((r) => { if (!cancel) { setRes(r); setErr(null); } },
        (e) => { if (!cancel) setErr(e instanceof ApiError ? e.message : "Check unavailable"); });
    return () => { cancel = true; };
  }, [key]);

  const v = res ? VERDICT[res.verdict] : null;
  const sz = res?.sizing;
  const value = res?.singles.filter((s) => s.value) ?? [];
  const exp = sz?.expected != null ? Number(sz.expected) : null;
  return (
    <section className="slip-check" aria-label="Slip check">
      <div className="money-row">
        <label>
          <span className="small">Stake</span>
          <span className="prefix">$<input type="number" inputMode="decimal" min={0} max={1000} step={0.5}
            value={stake} placeholder={sz?.cap ?? ""} aria-label="Stake in dollars" onChange={(e) => setStake(e.target.value)} /></span>
        </label>
        {legs.length >= 2 && (
          <label>
            <span className="small">Kalshi quote</span>
            <span className="prefix"><input type="number" inputMode="numeric" min={1} max={99} step={1} value={quote}
              placeholder="¢" aria-label="Kalshi's quote in cents" onChange={(e) => onQuote(e.target.value)} />¢</span>
          </label>
        )}
        {legs.length >= 2 && refPrice != null && Number(quote) > 0 && Number(quote) < 100 && (
          <span className={`quote-verdict ${Number(quote) / 100 > refPrice ? "bad" : "good"}`}>
            {Number(quote) / 100 > refPrice ? `+${((Number(quote) / 100 / refPrice - 1) * 100).toFixed(0)}% over fair`
              : `${((1 - Number(quote) / 100 / refPrice) * 100).toFixed(0)}% under fair`}
          </span>
        )}
      </div>
      {err && <p role="alert" className="small">{err}</p>}
      {res && v && (
        <div className="check-body">
          <p className="check-head">
            <span className={`verdict big ${v.cls}`}>{v.text}</span>
            {res.combo.walk_away && <span className="small"><Term id="walk-away-price">walk away</Term> above <b>{c(res.combo.walk_away)}</b></span>}
          </p>
          <ul className="reasons">
            {res.reasons.slice(0, 4).map((r) => <li key={r.text} className={r.level}>{r.text}</li>)}
          </ul>
          {res.reasons.length > 4 && (
            <details className="small"><summary>{res.reasons.length - 4} more</summary>
              <ul className="reasons">{res.reasons.slice(4).map((r) => <li key={r.text} className={r.level}>{r.text}</li>)}</ul>
            </details>
          )}
          {sz?.contracts && (
            <p className="small sizing-line">
              {sz.contracts} contracts · ${sz.cost} in · pays ${Number(sz.pays).toFixed(2)} ·{" "}
              expected <b className={exp != null && exp < 0 ? "ev-neg" : "ev-pos"}>{exp != null && exp < 0 ? "−" : "+"}${Math.abs(exp ?? 0).toFixed(2)}</b>
            </p>
          )}
          {sz && (
            <p className="small muted">
              cap ${sz.cap}{sz.kelly_quarter != null && <> · ¼-Kelly ${sz.kelly_quarter}</>}
              {sz.open_cost != null && Number(sz.open_cost) > 0 && <> · ${sz.open_cost} already open</>}
              {sz.cash != null && <> · cash ${sz.cash}</>}
            </p>
          )}
          <details className="alts" open={value.length > 0}>
            <summary className="small">Cheaper ways{value.length > 0 ? ` · ${value.length} value single${value.length > 1 ? "s" : ""}` : ""}</summary>
            <ul className="singles">
              {res.singles.map((s) => (
                <li key={s.ticker} className={s.value ? "value" : ""}>
                  <div className="single-top">
                    <span className="leg-side">{s.side.toUpperCase()}</span>
                    <span className="single-label">{s.label}</span>
                    {s.value && <span className="verdict v-up">value</span>}
                  </div>
                  <div className="small muted">
                    ask {c(s.ask)}{s.history != null ? <> · history {c(s.history)}</> : s.mid != null ? <> · mid {c(s.mid)}</> : null}
                    {s.edge_pts != null && s.history != null && <> · <span className={s.edge_pts >= 0 ? "ev-pos" : "ev-neg"}>{s.edge_pts > 0 ? "+" : ""}{s.edge_pts} pts</span></>}
                  </div>
                  {s.limit && (
                    <div className="small">
                      {s.limit.behind_bid
                        ? <>Only worth it at <b>≤{c(s.limit.price)}</b>: rest a limit there or skip.</>
                        : <>Limit at <b>{c(s.limit.price)}</b> instead of {c(s.ask)}: saves ~{Number(s.limit.saves_per_100).toFixed(1)}¢ a contract{Number(s.limit.maker_fee_per_100) === 0 ? ", no fee" : ""}. May not fill.</>}
                    </div>
                  )}
                </li>
              ))}
            </ul>
            {res.trim && (
              <p className="small trim">Drop <b>{res.trim.label}</b> → {res.trim.legs_after} legs, fair {(res.trim.fair_after * 100).toFixed(1)}%
                {res.trim.history_after?.return_per_dollar != null && <> (past {res.trim.history_after.bucket}: ${res.trim.history_after.return_per_dollar.toFixed(2)}/$1)</>}</p>
            )}
            <p className="fine muted">Combo quotes are take-it-or-leave-it on Kalshi, so the combo gets a walk-away price; limit orders apply to single legs.</p>
          </details>
        </div>
      )}
    </section>
  );
}
