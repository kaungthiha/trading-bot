import { useEffect, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { SlateCombo, SlateNote, SlateResult, SlateState } from "../../api/types";
import { EmptyState } from "../Hairline";
import { BriefCard, LeanChip } from "./BriefCard";
import { ago, pct } from "./format";
import { slip, useSlip } from "./slip";

const POLL_MS = 2000;
type NewsById = Map<string, SlateResult["news"][number]>;
const legOf = (x: { ticker: string; side: "yes" | "no"; label: string; event_ticker: string }) =>
  ({ ticker: x.ticker, side: x.side, label: x.label, event: x.event_ticker });

/** News ids as links to the source article (third-party text, shown as text). */
function Cites({ ids, news }: { ids: string[]; news: NewsById }) {
  if (ids.length === 0) return null;
  return (
    <span className="cites">
      {ids.map((id) => {
        const n = news.get(id);
        return n
          ? <a key={id} href={n.url} target="_blank" rel="noopener noreferrer nofollow" title={`${n.title} (${n.source})`}>{id}</a>
          : <span key={id}>{id}</span>;
      })}
    </span>
  );
}

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
      {c.case && <p className="small slate-case"><b>Case:</b> {c.case}</p>}
      {c.risk && <p className="small slate-case"><b>Biggest risk:</b> {c.risk}</p>}
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
        <details className="slate-risks small">
          <summary>Everything against it ({c.risks.length})</summary>
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

function Notes({ title, items, news, cls }: { title: string; items: SlateNote[]; news: NewsById; cls: string }) {
  if (items.length === 0) return null;
  return (
    <section className={`slate-notes ${cls}`} aria-label={title}>
      <h4 className="small">{title} ({items.length})</h4>
      <ul className="small">
        {items.map((x) => (
          <li key={x.bet}><b>{x.bet}</b> <span className="muted">({x.game})</span>: {x.note || "no reason given"} <Cites ids={x.sources} news={news} /></li>
        ))}
      </ul>
    </section>
  );
}

function Engine({ r }: { r: SlateResult }) {
  const e = r.engine, ni = r.news_info;
  if (e.mode === "rules") {
    return <p className="small engine rules"><b>Rules only.</b> {e.reason ?? "The local model wasn't used."}</p>;
  }
  const news = ni.status === "no_key" ? "no Brave key, so briefs only (no news)"
    : `${ni.searched} news search${ni.searched === 1 ? "" : "es"}, ${ni.items} item${ni.items === 1 ? "" : "s"}`
      + (ni.status === "budget" ? ` (stopped: ${ni.message ?? "Brave cap reached"})` : "");
  return (
    <p className="small engine model">
      <b>Synthesized by your local model</b> ({e.model}, {e.seconds}s) · {news}. Code computed every number and
      enforced the combo limits; the model weighed the briefs against the news.
    </p>
  );
}

function Result({ r }: { r: SlateResult }) {
  const legs = useSlip();
  const on = new Set(legs.map((l) => l.ticker));
  const news: NewsById = new Map(r.news.map((n) => [n.id, n]));
  const [lo, hi] = r.rules.leg_price;
  const model = r.engine.mode === "local_model";
  return (
    <>
      <Engine r={r} />
      <p className="small muted">
        {r.briefed} legs briefed across {r.games.length} game{r.games.length === 1 ? "" : "s"}
        {" "}· {r.leans.strong ?? 0} strong, {r.leans.mixed ?? 0} mixed, {r.leans.weak ?? 0} weak
        {" "}· built {ago(r.generated_at)}
      </p>
      {r.skipped.length > 0 && <p className="small inj-note">Skipped: {r.skipped.map((s) => s.game).join(", ")}</p>}
      {r.summary && <p className="slate-summary">{r.summary}</p>}
      {r.combos.length === 0 ? (
        <EmptyState figure="sieve" title="No combo tonight">
          {model ? (r.pass_reason || "The model passed.")
            : <>Not enough legs had a clear case (at least {r.rules.min_score} more points for than against, at most one
              against, priced {Math.round(lo * 100)}–{Math.round(hi * 100)}%).</>} Passing is a fine outcome.
        </EmptyState>
      ) : (
        <ol className="slate-combos">{r.combos.map((c, i) => <ComboCard key={c.legs.map((x) => x.ticker).join()} c={c} n={i + 1} />)}</ol>
      )}
      {model && r.combos.length > 0 && r.pass_reason && <p className="small muted">Fewer than three: {r.pass_reason}</p>}
      <Notes title="Stats vs news" items={r.conflicts} news={news} cls="conflicts" />
      <Notes title="Dropped by the model" items={r.dropped} news={news} cls="dropped" />
      {r.reviews.length > 0 && (
        <details className="slate-reviews">
          <summary className="small">What the news says, game by game ({r.news.length} items)</summary>
          <ul className="small">
            {r.reviews.map((g) => (
              <li key={g.game}><b>{g.game}:</b> {g.note}
                {g.news.length > 0 && (
                  <ul className="news">
                    {g.news.map((id) => news.get(id)).filter((n) => n != null).map((n) => (
                      <li key={n.id}><span className="muted">{n.id}</span>{" "}
                        <a href={n.url} target="_blank" rel="noopener noreferrer nofollow">{n.title}</a>{" "}
                        <span className="muted">{n.source} · {n.age}</span></li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
      {r.rule_combos.length > 0 && (
        <details className="slate-rules">
          <summary className="small">Rules-only combos, for comparison ({r.rule_combos.length})</summary>
          <ol className="slate-combos">{r.rule_combos.map((c, i) => <ComboCard key={c.legs.map((x) => x.ticker).join()} c={c} n={i + 1} />)}</ol>
        </details>
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

/** Tonight's NBA slate. Code briefs every leg; the local model weighs the briefs against each
 * game's news and assembles 3-4 leg combos; code enforces the limits and prices them. Falls
 * back to rule-only combos when the model is off. Built on click, in the background. */
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
        Code briefs every leg (form against its price, minutes, what tonight's opponent allows, head-to-head, rest,
        injuries). Your local model then reads each game's news, flags where it contradicts the numbers, and builds
        the combos. Up to 3 Brave searches per game (cached, under the app-wide cap). Leads to research, not forecasts.
      </p>
      {err && <p role="alert" className="small">{err}</p>}
      {building && <p className="small" aria-live="polite">{st?.progress ?? "Starting"}… (a few minutes with the local model)</p>}
      {st?.status === "failed" && <p role="alert" className="small">Build failed: {st.error}</p>}
      {r ? <Result r={r} /> : !building && st?.status !== "failed" && (
        <EmptyState figure="loupe" title="Not built yet">
          Build reads ESPN box scores and recent news for every game tonight, then the local model suggests up to
          three combos. Or pick a game on the left for one game's markets.
        </EmptyState>
      )}
    </section>
  );
}
