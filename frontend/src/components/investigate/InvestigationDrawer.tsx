import { useEffect, useRef, useState } from "react";

import type { InvestigationFinding, InvestigationHypothesis, InvestigationResult, InvestigationSource, ResearchUsage } from "../../api/types";
import { ExcerptBox, ExcerptText } from "./ExcerptBox";
import { StatusLabel } from "../design/StatusLabel";
import { Term } from "../Term";
import { useNow } from "../shell/Topbar";
import { exact, rel } from "../today/time";
import { hypothesisKey, MARKET_LABEL } from "./hypothesis";
import "./investigate.css";
import { investigation, type Preflight, type Progress, useInvestigation } from "./store";

/** Hard limits on what the summary may show, whatever the source returns. */
export function clampSummary(r: InvestigationResult["summary"]) {
  const sentences = r.takeaway.trim().split(/(?<=[.!?])\s+/).filter(Boolean);
  return { takeaway: sentences.slice(0, 2).join(" "), findings: r.findings.slice(0, 3), gap: r.gaps[0] ?? null };
}

const STANCE: Record<InvestigationFinding["stance"], { label: string; cls: string }> = {
  supports: { label: "Supports", cls: "for" },
  opposes: { label: "Against", cls: "against" },
  neutral: { label: "Open question", cls: "open" },
};
const ACCESS: Record<InvestigationSource["access"], string> = {
  headline: "headline only", snippet: "headline and snippet", full_text: "full article (licensed)", internal: "app data",
  user_provided: "you pasted · unverified",
};
const LINE: Record<InvestigationSource["line_match"], string | null> = {
  exact: null, unknown: null, different_line: "different line: not direct support", past_matchup: "past matchup: not direct support",
};
const cents = (p: number | null | undefined, d = 0) => (p == null ? "—" : `${(p * 100).toFixed(d)}¢`);
const signedPts = (p: number) => `${p > 0 ? "+" : p < 0 ? "−" : ""}${Math.abs(p * 100).toFixed(1)} pts`;

export function InvestigationHost() {
  const { open } = useInvestigation();
  return open ? <InvestigationDrawer h={open} /> : null;
}

function SourceMarks({ ids, sources, verified }: { ids: string[]; sources: InvestigationSource[]; verified: boolean }) {
  const known = ids.map((id) => sources.findIndex((s) => s.id === id)).filter((i) => i >= 0);
  return (
    <>
      {known.map((i) => {
        const s = sources[i]!;
        const label = `Source ${i + 1}: ${s.publisher}, ${s.title}`;
        return s.url ? (
          <a key={s.id} className="inv-mark" href={s.url} target="_blank" rel="noopener noreferrer nofollow"
            aria-label={label}>[{i + 1}]</a>
        ) : <span key={s.id} className="inv-mark" aria-label={label}>[{i + 1}]</span>;
      })}
      {(!verified || (ids.length > 0 && known.length === 0)) && <span className="inv-unverified">unverified</span>}
    </>
  );
}

function FindingList({ items, sources, ordered = false }: {
  items: InvestigationFinding[]; sources: InvestigationSource[]; ordered?: boolean }) {
  const List = ordered ? "ol" : "ul";
  if (items.length === 0) return <p className="small muted">Nothing found.</p>;
  return (
    <List className="inv-findings">
      {items.map((f, i) => (
        <li key={`${i}-${f.text}`}>
          <span className={`inv-stance ${STANCE[f.stance].cls}`}>{STANCE[f.stance].label}</span>{" "}
          <span>{f.text}</span> <SourceMarks ids={f.source_ids} sources={sources} verified={f.verified} />
        </li>
      ))}
    </List>
  );
}

function PriceLens({ r }: { r: InvestigationResult }) {
  const p = r.price_assessment;
  const now = useNow();
  return (
    <section className="inv-block" aria-labelledby="inv-price">
      <h3 id="inv-price">Price lens</h3>
      <dl className="inv-price">
        <dt>Market ask ({r.quote.side.toUpperCase()})</dt>
        <dd>{cents(p.ask)} <span className="small muted">{r.quote.observed_at ? <>· {rel(r.quote.observed_at, now)}{r.quote.fresh ? "" : " · stale"}</> : "· no time"}</span></dd>
        <dt>{p.model_p != null ? "History" : "Model"}</dt>
        <dd>{p.model_p != null ? <>{cents(p.model_p, 0)}{p.model_band && <span className="small muted"> (range {cents(p.model_band[0])}–{cents(p.model_band[1])})</span>}
          <span className="small muted inv-sub">{p.model_name ?? "frequency from past games"}</span></>
          : <span className="muted">No calibrated model for this market</span>}</dd>
        {p.raw_diff != null && <><dt>History − all-in</dt><dd>{signedPts(p.raw_diff)} <span className="small muted">raw, not an edge</span></dd></>}
        <dt><Term id="edge">Conservative edge</Term></dt>
        <dd>{p.conservative_edge != null ? <>{signedPts(p.conservative_edge)} <span className="small muted">history low end − all-in</span></>
          : <span className="muted">Not enough evidence to estimate an edge</span>}</dd>
        {p.break_even != null && <><dt>Break-even</dt><dd>{cents(p.break_even, 1)}</dd></>}
      </dl>
    </section>
  );
}

function FullResearch({ r, h }: { r: InvestigationResult; h: InvestigationHypothesis }) {
  const p = r.price_assessment;
  const now = useNow();
  return (
    <details className="inv-full">
      <summary>View full research</summary>
      <section aria-labelledby="inv-sup"><h3 id="inv-sup">What supports the pick?</h3>
        <FindingList items={r.details.supports} sources={r.sources} /></section>
      <section aria-labelledby="inv-opp"><h3 id="inv-opp">What could make me wrong?</h3>
        <FindingList items={r.details.against} sources={r.sources} />
        {r.details.data_gaps.length > 0 && <p className="small">Still unknown: {r.details.data_gaps.join("; ")}.</p>}
      </section>
      <section aria-labelledby="inv-just"><h3 id="inv-just">Is the price justified?</h3>
        <dl className="inv-price">
          <dt>Ask</dt><dd>{cents(p.ask, 1)}</dd>
          <dt>Fee per contract</dt><dd>{cents(p.fee_per_contract, 2)}</dd>
          <dt>Slippage allowance</dt><dd>{cents(p.slippage_per_contract, 2)}</dd>
          <dt>Break-even chance</dt><dd>{cents(p.break_even, 1)}</dd>
          <dt><Term id="walk-away-price">Walk-away</Term></dt><dd>{p.walk_away != null ? cents(p.walk_away) : "—"}</dd>
        </dl>
        {p.assumptions.length > 0 && <><h4>Assumptions</h4><ul className="small">{p.assumptions.map((a) => <li key={a}>{a}</li>)}</ul></>}
        {r.details.rules_excerpt && <><h4>How it resolves (Kalshi rules excerpt)</h4>
          <p className="small inv-rules">{r.details.rules_excerpt}</p>
          {r.hypothesis.rules_url && <a className="small" href={r.hypothesis.rules_url} target="_blank" rel="noopener noreferrer">Full rules on Kalshi</a>}</>}
        {p.abstain_reasons.length > 0 && <><h4>Caveats and why an edge may be withheld</h4><ul className="small">{p.abstain_reasons.map((a) => <li key={a}>{a}</li>)}</ul></>}
      </section>
      <section aria-labelledby="inv-src"><h3 id="inv-src">Sources and methodology</h3>
        {r.sources.length === 0 ? <p className="small muted">No external sources were checked.</p> : (
          <ol className="inv-sources">
            {r.sources.map((s) => (
              <li key={s.id}>
                {s.url ? <a href={s.url} target="_blank" rel="noopener noreferrer nofollow">{s.title}</a> : <span>{s.title}</span>}
                <span className="small muted"> · {s.publisher}{s.author ? `, ${s.author}` : ""}
                  {s.published_at && <> · published {rel(s.published_at, now)}</>} · retrieved {rel(s.retrieved_at, now)}
                  {" · "}{ACCESS[s.access]}</span>
                {s.duplicate_of && <span className="small inv-dup"> · same report as {s.duplicate_of}: not independent</span>}
                {LINE[s.line_match] && <span className="small inv-dup"> · {LINE[s.line_match]}</span>}
                {s.access === "user_provided" && <ExcerptText r={r} h={h} s={s} />}
              </li>
            ))}
          </ol>
        )}
        <ul className="small">{r.details.methodology.map((m) => <li key={m}>{m}</li>)}</ul>
        <p className="small muted">
          Model: {r.processing.model ?? "none (box-score only)"} · searches: {r.processing.searches} · cache: {r.processing.cache}
          {r.completed_at && <> · finished {exact(r.completed_at)}</>}
        </p>
      </section>
    </details>
  );
}

/** What a background run is doing right now. */
export function phaseText(p: Progress | undefined): string {
  if (!p) return "Investigating…";
  switch (p.phase) {
    case "queued": return p.position > 0 ? `Waiting: ${p.position} investigation${p.position === 1 ? "" : "s"} ahead…` : "Waiting to start…";
    case "searching": return "Searching news…";
    case "summarising": return "Summarising with your local model (can take a minute)…";
    case "saving": return "Saving…";
    default: return "Investigating…";
  }
}

const PURPOSE_LABEL: Record<string, string> = {
  research: "Investigate", news: "Headlines here", headlines: "AI review headlines", slate: "Tonight's combos",
};

/** App-wide Brave request count (what the caps apply to), with a per-feature breakdown.
 * Counted by this app; never a "$ remaining" figure, which the API doesn't expose. */
function BraveUsage({ u }: { u: ResearchUsage }) {
  const parts = Object.entries(u.by_purpose ?? {});
  return (
    <details className="inv-usage fine muted">
      <summary>Brave requests: {u.used_month} / {u.monthly_cap} this month</summary>
      <p>Today {u.used_today} / {u.daily_cap}. Every Brave feature in the app shares these caps.</p>
      {parts.length > 0 && (
        <ul>
          {parts.map(([k, v]) => (
            <li key={k}>{PURPOSE_LABEL[k] ?? k}: {v.month} this month · {v.today} today</li>
          ))}
        </ul>
      )}
      <p>Counted by this app. Your Brave balance isn't visible here; check the Brave dashboard.</p>
    </details>
  );
}

export function InvestigationDrawer({ h }: { h: InvestigationHypothesis }) {
  const { entries } = useInvestigation();
  const entry = entries[hypothesisKey(h)];
  const [pre, setPre] = useState<Preflight | null>(null);
  const panel = useRef<HTMLDivElement>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const now = useNow();
  const src = investigation.source();

  useEffect(() => { title.current?.focus(); }, [h.ticker, h.side]);
  // Escape works wherever focus is (e.g. after the Run button is replaced by the result).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") investigation.close(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  // When a control that had focus disappears (Run → result), keep focus inside the drawer.
  useEffect(() => {
    if (!panel.current?.contains(document.activeElement)) title.current?.focus();
  }, [entry?.status]);
  useEffect(() => {
    let cancel = false;
    src.preflight(h).then((p) => {
      if (cancel) return;
      setPre(p);
      // A run already queued or running for this pick (drawer closed and reopened, or another
      // tab): follow it instead of offering Run again. Following is free (GET only).
      if (p.job && !investigation.get().entries[hypothesisKey(h)]) void investigation.resume(h, p.job.id);
    }, () => { if (!cancel) setPre(null); });
    return () => { cancel = true; };
  }, [h, src]);
  // After a run, re-read the request counts (free: no search) so the usage line is current.
  useEffect(() => {
    if (entry?.status !== "done") return;
    let cancel = false;
    src.usage().then((usage) => { if (!cancel) setPre((p) => (p ? { ...p, usage } : p)); }, () => {});
    return () => { cancel = true; };
  }, [entry?.status, src]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") return; // handled once, at document level
    if (e.key !== "Tab" || !panel.current) return;
    const f = panel.current.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), summary, input, textarea, [tabindex]:not([tabindex="-1"])');
    if (f.length === 0) return;
    const first = f[0]!, last = f[f.length - 1]!;
    if (e.shiftKey && (document.activeElement === first || document.activeElement === title.current)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };

  const result = entry?.status === "done" ? entry.result : null;
  const u = pre?.usage;
  // The caps are app-wide: every Brave feature draws from the same daily and monthly totals.
  const left = u ? Math.max(0, Math.min(u.daily_cap - u.used_today, u.monthly_cap - u.used_month)) : null;
  const sum = result ? clampSummary(result.summary) : null;

  return (
    <div className="inv-backdrop" onMouseDown={(e) => e.target === e.currentTarget && investigation.close()}>
      <div ref={panel} className="inv" role="dialog" aria-modal="true" aria-labelledby="inv-title" onKeyDown={onKeyDown}>
        <div className="inv-head">
          <p className="kicker">Investigate this pick</p>
          <h2 id="inv-title" ref={title} tabIndex={-1}>{h.statement}</h2>
          <button type="button" className="inv-close" aria-label="Close investigation" onClick={() => investigation.close()}>×</button>
        </div>
        {src.preview && (
          <p className="inv-preview" role="note">Preview with sample research: nothing below is real yet. Live search and summaries arrive in later phases.</p>
        )}

        <dl className="inv-contract small">
          <dt>Market</dt><dd>{MARKET_LABEL[h.market_type]}{h.threshold != null && <> · line {h.threshold}</>}</dd>
          <dt>Side</dt><dd>{h.side === "yes" ? "YES (it happens)" : "NO (it doesn't happen)"}</dd>
          {h.subject && <><dt>Subject</dt><dd>{h.subject}</dd></>}
          <dt>Contract</dt><dd><code>{h.ticker}</code></dd>
          <dt>Quote</dt>
          <dd>{pre ? <>{cents(pre.quote.ask)} ask <span className="muted">
            {pre.quote.observed_at && <>· <time dateTime={pre.quote.observed_at} title={exact(pre.quote.observed_at)}>{rel(pre.quote.observed_at, now)}</time></>}
          </span> <StatusLabel tone={pre.quote.fresh ? "ok" : "stale"}>{pre.quote.fresh ? "fresh" : "stale"}</StatusLabel></> : "…"}</dd>
          <dt>Estimate</dt><dd>{pre?.model ?? <span className="muted">No calibrated model for this market</span>}</dd>
        </dl>

        {!entry && (
          <div className="inv-run">
            <button type="button" className="primary-button" onClick={() => investigation.run(h)}
              disabled={!u || !!pre?.unsupported}>Run investigation</button>
            {pre?.unsupported && <p className="small" role="note">{pre.unsupported}</p>}
            <p className="small muted">
              {!u ? "Checking search budget…"
                : !u.configured ? "Brave Search isn't set up: the investigation will use box scores only."
                : pre?.cached ? "A cached result is available: no new search needed."
                : left === 0 ? (u.used_month >= u.monthly_cap ? "This month's" : "Today's") + " Brave budget is used up: box scores only."
                : `Uses up to ${Math.min(u.max_searches_per_investigation, left ?? 0)} news searches (${left} left today on this app's cap).`}
            </p>
          </div>
        )}
        {entry?.status === "running" && (
          <div className="inv-running" role="status" aria-live="polite">
            <p><span className="shimmer" aria-hidden="true" /> {phaseText(entry.progress)}</p>
            {entry.progress && <p className="small muted">Runs in the background: you can close this and come back.</p>}
            {entry.progress?.phase === "queued" && src.cancel && (
              <button type="button" className="link-button small" onClick={() => void investigation.cancel(h)}>Cancel</button>
            )}
          </div>
        )}
        {entry?.status === "error" && (
          <div role="alert" className="inv-error">
            <p className="small">{entry.message}</p>
            <button type="button" className="ghost-button" onClick={() => investigation.run(h, { refresh: true })}>Try again</button>
          </div>
        )}

        {result && sum && (
          <section className="inv-summary" aria-labelledby="inv-sum">
            <h3 id="inv-sum" className="visually-hidden">Summary</h3>
            <p className="inv-takeaway">{sum.takeaway}</p>
            {result.summary.coverage && <p className="inv-coverage small muted">{result.summary.coverage}</p>}
            {result.processing.errors.map((e) => <p key={e} className="small inv-note">{e}</p>)}
            <section className="inv-block" aria-labelledby="inv-three">
              <h3 id="inv-three">Three things that matter</h3>
              <FindingList items={sum.findings} sources={result.sources} ordered />
            </section>
            <PriceLens r={result} />
            {sum.gap && <p className="inv-gap"><b>Still unknown:</b> {sum.gap}</p>}
            <p className="inv-meta small muted">
              {result.sources.length} source{result.sources.length === 1 ? "" : "s"}
              {result.processing.model ? <> · summarised by {result.processing.model} (on this computer)</> : <> · no model summary</>}
              {result.completed_at && <> · last checked <time dateTime={result.completed_at}>{rel(result.completed_at, now)}</time></>}
              {result.stale_at && Date.parse(result.stale_at) < now && <> · <StatusLabel tone="stale">stale</StatusLabel></>}
              {" · "}<button type="button" className="link-button small" onClick={() => investigation.run(h, { refresh: true })}>Refresh research</button>
            </p>
            <FullResearch r={result} h={h} />
            {src.addExcerpt && <ExcerptBox r={result} h={h} />}
          </section>
        )}
        {u?.configured && <BraveUsage u={u} />}
        <p className="fine muted inv-foot">Research and education only. You decide; nothing here places orders.</p>
      </div>
    </div>
  );
}
