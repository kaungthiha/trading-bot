import { useEffect, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { LlmStatus, OpenAnalysis, OpenPosition, OpenReview } from "../../api/types";
import { CHART } from "../../styles/palette";
import { offReason } from "../games/SecondOpinion";
import { EmptyState, Figure } from "../Hairline";

type Read = OpenReview["positions"][number];
const STANCE = { on_track: "on track", watch: "watch", reconsider: "reconsider" } as const;

const money = (s: string | null | undefined) => {
  if (s == null) return "—";
  const n = Number(s);
  return `${n < 0 ? "−" : n > 0 ? "+" : ""}$${Math.abs(n).toFixed(2)}`;
};
const cents = (s: string | number | null | undefined) => (s == null ? "—" : `${Math.round(Number(s) * 100)}¢`);
const sign = (s: string | null | undefined) => (s == null ? "" : Number(s) > 0 ? "ev-pos" : Number(s) < 0 ? "ev-neg" : "");
const VERDICT = { agrees: "fits history", market_lower: "history: likelier", market_higher: "history: less likely",
  thin: "thin data", no_price: "no price" } as const;
const VCLS = { agrees: "v-ok", market_lower: "v-up", market_higher: "v-down", thin: "v-thin", no_price: "v-thin" } as const;

function when(h: number | null): string {
  if (h == null) return "";
  if (h < 0) return "closed";
  if (h < 48) return `${Math.round(h)}h left`;
  if (h < 24 * 60) return `${Math.round(h / 24)}d left`;
  return `${Math.round(h / 24 / 30)}mo left`;
}

/** Price of your side over time (from stored marks) against what you paid. */
export function Sparkline({ trail, entry }: { trail: OpenPosition["trail"]; entry: number | null }) {
  const pts = trail.filter((t) => t.mid != null) as { at: string; mid: number }[];
  if (pts.length < 2) return <span className="small muted spark-empty">trail builds with each scan</span>;
  const W = 120, H = 30;
  const vals = pts.map((p) => p.mid).concat(entry != null ? [entry] : []);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const y = (v: number) => H - 3 - ((v - lo) / (hi - lo || 1)) * (H - 6);
  const x = (i: number) => (i / (pts.length - 1)) * (W - 4) + 2;
  const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.mid).toFixed(1)}`).join("");
  const last = pts[pts.length - 1]!.mid;
  const up = entry == null || last >= entry;
  return (
    <svg className="spark" width={W} height={H} role="img"
      aria-label={`Price went from ${cents(pts[0]!.mid)} to ${cents(last)}${entry != null ? `; you paid ${cents(entry)}` : ""}`}>
      {entry != null && <line x1={0} x2={W} y1={y(entry)} y2={y(entry)} stroke={CHART.base} strokeDasharray="3 3" strokeWidth={1} />}
      <path d={d} fill="none" stroke={CHART.ink} strokeWidth={1.25} />
      <circle cx={x(pts.length - 1)} cy={y(last)} r={2.5} fill={up ? CHART.gain : CHART.loss} />
    </svg>
  );
}

function PositionCard({ p, read }: { p: OpenPosition; read?: Read }) {
  const [open, setOpen] = useState(false);
  const ev = p.evidence;
  const link = p.game ? `#/games?game=${encodeURIComponent(`${p.game.prefix}-${p.game.game_key}`)}`
    : p.event_ticker ? `#/markets?event=${encodeURIComponent(p.event_ticker)}` : null;
  const details = !!(p.combo || p.flags.length > 1 || p.evidence_note);
  return (
    <article className="pos-card">
      <header>
        <span className={`side-chip ${p.side}`}>{p.side.toUpperCase()}</span>
        <div className="pos-title">
          {link ? <a href={link}>{p.title}</a> : p.title}
          <span className="ticker">{p.event_title ?? p.type} · {when(p.hours_to_close)}</span>
        </div>
        <div className="pos-pnl">
          <span className={sign(p.unrealized)}>{money(p.unrealized)}</span>
          <span className="small muted">{cents(p.avg_cost)} → {cents(p.mid)}</span>
        </div>
      </header>
      <div className="pos-row">
        <Sparkline trail={p.trail} entry={p.avg_cost == null ? null : Number(p.avg_cost)} />
        <span className="small muted">${p.cost} in · pays ${Number(p.max_payout).toFixed(2)} if right</span>
        {ev?.verdict && <span className={`verdict ${VCLS[ev.verdict]}`} title="Box-score check for your side">{VERDICT[ev.verdict]}</span>}
        {ev?.windows && <span className="small muted">L10 {ev.windows.last10[0]}/{ev.windows.last10[1]}</span>}
        {p.combo && <span className="small">{p.combo.won}✓ {p.combo.lost}✗ {p.combo.open} open</span>}
      </div>
      {read && (
        <div className={`ai-read ${read.stance}`}>
          <span className="stance">{STANCE[read.stance]}</span>
          <p className="small">{read.read}</p>
          {read.plan && <p className="small muted">Plan: {read.plan}</p>}
        </div>
      )}
      {p.flags[0] && <p className={`flag ${p.flags[0].level}`}>{p.flags[0].text}</p>}
      {details && (
        <>
          <button type="button" className="link-button small" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? "Less" : p.combo ? `Legs (${p.combo.legs.length})` : "More"}
          </button>
          {open && (
            <div className="pos-more">
              {p.flags.slice(1).map((f) => <p key={f.text} className={`flag ${f.level}`}>{f.text}</p>)}
              {p.evidence_note && <p className="small muted">{p.evidence_note}</p>}
              {p.combo && (
                <ul className="legs">
                  {p.combo.legs.map((l) => (
                    <li key={l.ticker} className={`leg ${l.status}`}>
                      <span className="leg-dot" aria-label={l.status} />
                      <span className="leg-side">{l.side.toUpperCase()}</span> {l.title}
                      <span className="muted small"> {l.status === "open" ? cents(l.probability) : l.status}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </>
      )}
    </article>
  );
}

/** The local model's read of every open position: stance, a short read and a plan. */
function AiRead({ review, onReview }: { review: OpenReview | null; onReview: (r: OpenReview | null) => void }) {
  const [status, setStatus] = useState<LlmStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.coachStatus().then(setStatus, () => setStatus(null)); }, []);
  const run = () => {
    setBusy(true);
    setErr(null);
    api.openReview().then(onReview, (e) => setErr(e instanceof ApiError ? e.message : "AI read unavailable"))
      .finally(() => setBusy(false));
  };
  if (review) {
    return (
      <section className="panel ai-panel" aria-label="AI read of open positions">
        <p className="small">{review.summary}</p>
        {review.portfolio.length > 0 && <ul className="reasons">{review.portfolio.map((r) => <li key={r} className="warn">{r}</li>)}</ul>}
        {review.check.length > 0 && (
          <details className="small"><summary>Look up before the games</summary>
            <ul>{review.check.map((c) => <li key={c}>{c}</li>)}</ul></details>
        )}
        {review.sources.length > 0 && (
          <details className="small"><summary>Headlines it read ({review.sources.length})</summary>
            <ul>{review.sources.map((s) => <li key={s.id}>{s.id} <a href={s.url} target="_blank" rel="noreferrer noopener">{s.title}</a> <span className="muted">{s.source} {s.age}</span></li>)}</ul></details>
        )}
        <p className="fine muted">AI-written by {review.model}{review.seconds ? ` in ${review.seconds}s` : ""}{review.cached ? " (cached)" : ""} from the numbers below. It can be wrong; you decide.{" "}
          <button type="button" className="link-button fine" onClick={() => onReview(null)}>clear</button></p>
      </section>
    );
  }
  return (
    <section className="panel ai-panel ai-idle" aria-label="AI read of open positions">
      <Figure name={busy ? "sieve" : "loupe"} size={56} play={busy} />
      <div className="small">
        {status && !status.configured ? <p className="muted">{offReason(status)}</p> : (
          <button type="button" className="ghost-button" onClick={run} disabled={busy || !status}>
            {busy ? "Reading your positions…" : "AI read of these positions"}
          </button>
        )}
        {!busy && !err && status?.configured && <span className="muted"> Price vs entry, box scores, injuries, headlines. Local model.</span>}
        {err && <p role="alert">{err}</p>}
      </div>
    </section>
  );
}

export function OpenPositions({ tick }: { tick: number }) {
  const [data, setData] = useState<OpenAnalysis | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [review, setReview] = useState<OpenReview | null>(null);
  useEffect(() => {
    api.historyOpen().then((d) => { setData(d); setErr(null); },
      (e) => setErr(e instanceof ApiError ? e.message : "Backend unreachable"));
  }, [tick]);
  if (err) return <p role="alert">{err}</p>;
  if (!data) return <div className="board skeleton" aria-busy="true" style={{ minHeight: 200 }} />;
  if (data.positions.length === 0) return <EmptyState figure="basket" title="No open positions">Sync after you trade.</EmptyState>;
  const pf = data.portfolio;
  return (
    <div className="open-positions">
      <div className="tiles">
        <Tile label="In play" value={`$${pf.cost}`} note={`${pf.count} positions`} />
        <Tile label="Worth now (mid)" value={`$${pf.value}`} />
        <Tile label="Unrealized" value={money(pf.unrealized)} cls={sign(pf.unrealized)} />
        <Tile label="Pays if all right" value={`$${Number(pf.max_payout).toFixed(2)}`} />
        {pf.budget_share != null && (
          <Tile label="Of your budget" value={`${Math.round(pf.budget_share * 100)}%`}
            cls={pf.budget_share > 1 ? "ev-neg" : ""} note={pf.budget_share > 1 ? "over budget" : undefined} />
        )}
      </div>
      {pf.games.map((g) => (
        <p key={g.game_key} className="flag warn">{g.tickers.length} positions ride on {g.title ?? g.game_key} ({Math.round((g.share ?? 0) * 100)}% of open cost).</p>
      ))}
      {data.correlation.map((c) => c.lift != null && (
        <p key={`${c.game_key}-${c.team}`} className="flag info">Your {c.team} legs all hit together in {c.together}/{c.games} past games: they win and lose as a group.</p>
      ))}
      <AiRead review={review} onReview={setReview} />
      <div className="pos-grid">
        {data.positions.map((p) => <PositionCard key={p.ticker} p={p} read={review?.positions.find((r) => r.ticker === p.ticker)} />)}
      </div>
      <p className="fine muted">Marked at the mid from the last scan, not a price you'd get selling. Flags are prompts to think, not instructions.</p>
    </div>
  );
}

export function Tile({ label, value, cls, note }: { label: string; value: string; cls?: string; note?: string }) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className={cls}>{value}</span>
      {note && <span className="tile-label">{note}</span>}
    </div>
  );
}
