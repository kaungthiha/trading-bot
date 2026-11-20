import { useEffect, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { ComboLeg, ReviewResult, ReviewStatus } from "../../api/types";

const LEAN = { supports: { icon: "▲", cls: "v-up", text: "supports" },
  against: { icon: "▼", cls: "v-down", text: "against" },
  unclear: { icon: "•", cls: "v-thin", text: "unclear" } } as const;
const OVERALL = { reasonable: "v-ok", stretch: "v-thin", avoid: "v-down" } as const;

export function offReason(s: { provider: string; model: string; reachable: boolean | null }): string {
  if (s.provider === "Ollama") {
    return s.reachable ? `AI is off: model ${s.model} isn't installed (run: ollama pull ${s.model}).`
      : "AI is off: start Ollama on this machine to turn it on.";
  }
  return "AI second opinion is off: add a key in .env (see README).";
}

/** On-demand AI critique of the slip, grounded in the app's own numbers and headlines. */
export function SecondOpinion({ legs, quoteCents }: { legs: ComboLeg[]; quoteCents?: number }) {
  const [status, setStatus] = useState<ReviewStatus | null>(null);
  const [res, setRes] = useState<ReviewResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const key = legs.map((l) => `${l.ticker}:${l.side}`).join(",");

  useEffect(() => { api.reviewStatus().then(setStatus, () => setStatus(null)); }, []);
  useEffect(() => { setRes(null); setErr(null); }, [key, quoteCents]);

  if (!status) return null;
  if (!status.configured) {
    return <p className="small muted second-off">{offReason(status)}</p>;
  }
  const label = (t: string) => legs.find((l) => l.ticker === t)?.label ?? t;
  const run = () => {
    setBusy(true);
    setErr(null);
    api.review(legs, quoteCents).then((r) => {
      setRes(r);
      if (!r.cached) setStatus((s) => (s ? { ...s, used_today: s.used_today + 1 } : s));
    }, (e) => setErr(e instanceof ApiError ? e.message : "Review failed")).finally(() => setBusy(false));
  };
  return (
    <section className="second-opinion" aria-label="AI second opinion">
      {!res && (
        <button type="button" className="ghost-button" onClick={run} disabled={busy || legs.length === 0}
          title={status.local
            ? `Runs ${status.model} on this machine with this slip's prices, box-score stats${status.headlines ? " and headlines" : ""}. Nothing leaves your computer except the headline search.`
            : `Sends this slip's prices, box-score stats${status.headlines ? " and headlines" : ""} to ${status.provider} (${status.model}). One paid call.`}>
          {busy ? `Asking ${status.model}…` : "Get a second opinion (AI)"}
        </button>
      )}
      {!res && (status.daily_cap != null
        ? <span className="small muted"> {status.used_today}/{status.daily_cap} today</span>
        : <span className="small muted"> {status.model} · local</span>)}
      {busy && <span className="shimmer wide" aria-hidden="true" />}
      {err && <p role="alert" className="small">{err}</p>}
      {res && (
        <div className="review">
          <p className="review-head">
            <span className={`verdict ${OVERALL[res.overall]}`}>{res.overall}</span>{" "}
            <span className="small">{res.summary}</span>
          </p>
          <ul className="review-legs small">
            {res.legs.map((l) => (
              <li key={l.ticker}>
                <span className={`verdict ${LEAN[l.lean].cls}`}>{LEAN[l.lean].icon} {LEAN[l.lean].text}</span>{" "}
                <b>{label(l.ticker)}</b>
                {l.points.length > 0 && <ul>{l.points.map((p) => <li key={p}>{p}</li>)}</ul>}
                {l.sources.length > 0 && <span className="muted"> [{l.sources.join(", ")}]</span>}
              </li>
            ))}
          </ul>
          {res.risks.length > 0 && <details className="small" open><summary>Risks</summary><ul>{res.risks.map((r) => <li key={r}>{r}</li>)}</ul></details>}
          {res.check_before_betting.length > 0 && <details className="small"><summary>Check before you bet</summary><ul>{res.check_before_betting.map((r) => <li key={r}>{r}</li>)}</ul></details>}
          {res.sources.length > 0 && (
            <details className="small"><summary>Sources ({res.sources.length})</summary>
              <ul>{res.sources.map((s) => <li key={s.id}>{s.id}: <a href={s.url} target="_blank" rel="noopener noreferrer nofollow">{s.title}</a> <span className="muted">{s.source} · {s.age}</span></li>)}</ul>
            </details>
          )}
          <p className="fine muted">AI-written by {res.model}{res.seconds ? ` in ${res.seconds}s` : ""}{res.cached ? " (cached)" : ""}. It can be wrong. Check its claims against the numbers above.{" "}
            <button type="button" className="link-button fine" onClick={() => setRes(null)}>close</button></p>
        </div>
      )}
    </section>
  );
}
