import { useEffect, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { GameIdeas, IdeaCombo, IdeaSingle, IdeasAi, LlmStatus } from "../../api/types";
import { EmptyState, Figure } from "../Hairline";
import { cents, pct } from "./format";
import { offReason } from "./SecondOpinion";
import { slip, useSlip } from "./slip";
import { Tip } from "../design/Tip";
import { InvestigateButton } from "../investigate/InvestigateButton";

const plain = (bet: string) => bet.replace(/^(YES|NO) · /, "");
const num = (s: string | null | undefined) => (s == null ? null : Number(s));
const HOW = { limit: "rest a limit", take_ask: "take the ask", quote_at_or_below: "accept quote at or under" } as const;

function SingleRow({ x, inSlip }: { x: IdeaSingle; inSlip: boolean }) {
  const w = x.windows;
  return (
    <li className="idea">
      <Tip className={`strength ${x.strength}`} text={x.strength === "strong"
        ? "History's whole 80% range is above the all-in price" : "History beats the price, but its range overlaps it"}>
        {x.strength}</Tip>
      <div className="idea-main">
        <span className="idea-bet"><b className={`side-chip ${x.side}`}>{x.side.toUpperCase()}</b> {plain(x.bet)}</span>
        <span className="small muted">
          history {pct(num(x.history))} vs {cents(num(x.all_in ?? null))} all-in
          {w && ` · L10 ${w.last10[0]}/${w.last10[1]} · season ${w.season[0]}/${w.season[1]}`}
          {x.injury && <em className="inj-note"> · {x.injury.status}</em>}
        </span>
        {x.caution && <span className="small inj-note">{x.caution}</span>}
      </div>
      <span className="idea-edge ev-pos">+{x.edge_pts?.toFixed(0)} pts</span>
      <span className="small idea-how">
        {x.limit ? <>limit {cents(num(x.limit.price))}</> : <>ask {cents(num(x.ask))}</>}
        <span className="muted"> · {x.contracts_at_cap} at cap</span>
      </span>
      <span className="idea-actions">
        <button type="button" className="link-button small" aria-pressed={inSlip}
          onClick={() => slip.toggle({ ticker: x.ticker, side: x.side, label: plain(x.bet), event: x.event_ticker })}>
          {inSlip ? "On docket" : "Add"}
        </button>
        <InvestigateButton quiet leg={{ ticker: x.ticker, side: x.side, label: plain(x.bet), event: x.event_ticker }} />
      </span>
    </li>
  );
}

function ComboRow({ c, singles }: { c: IdeaCombo; singles: Map<string, IdeaSingle> }) {
  const use = () => {
    slip.clear();
    c.legs.forEach((id) => {
      const x = singles.get(id);
      if (x) slip.add({ ticker: x.ticker, side: x.side, label: plain(x.bet), event: x.event_ticker });
    });
  };
  return (
    <li className="idea combo-idea">
      <span className="strength combo">{c.legs.length} legs</span>
      <div className="idea-main">
        <span className="idea-bet">{c.legs.join(" + ")} <span className="small muted">· {c.bets.map(plain).join(" · ")}</span></span>
        <span className="small muted">
          history {pct(c.history, 1)} vs market {pct(c.fair, 1)}
          {c.lift != null && ` · together ×${c.lift}`}
          {c.past?.return_per_dollar != null && ` · past ${c.past.bucket}: $${c.past.return_per_dollar.toFixed(2)} per $1`}
        </span>
      </div>
      <span className="idea-edge">×{c.ratio}</span>
      <span className="small idea-how">{c.walk_away ? <>quote ≤ {cents(num(c.walk_away))}</> : "no fair quote"}</span>
      <button type="button" className="link-button small" onClick={use}>Put on docket</button>
    </li>
  );
}

function AiPicks({ prefix, gameKey, ideas, singles }: {
  prefix: string; gameKey: string; ideas: GameIdeas; singles: Map<string, IdeaSingle> }) {
  const [status, setStatus] = useState<LlmStatus | null>(null);
  const [res, setRes] = useState<IdeasAi | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.reviewStatus().then(setStatus, () => setStatus(null)); }, []);
  useEffect(() => { setRes(null); setErr(null); }, [prefix, gameKey]);
  const combos = new Map(ideas.combos.map((c) => [c.id, c]));
  const name = (id: string) => (singles.get(id) ? plain(singles.get(id)!.bet)
    : combos.get(id)?.bets.map(plain).join(" + ") ?? id);
  const run = () => {
    setBusy(true);
    setErr(null);
    api.ideasAi(prefix, gameKey).then(setRes, (e) => setErr(e instanceof ApiError ? e.message : "AI unavailable"))
      .finally(() => setBusy(false));
  };
  if (!res) {
    return (
      <div className="ai-panel ai-idle">
        <Figure name={busy ? "sieve" : "plug"} size={56} play={busy} />
        <div className="small">
          {status && status.provider !== "Ollama" ? <p className="muted">Picks run on the local model only.</p>
            : status && !status.configured ? <p className="muted">{offReason(status)}</p> : (
              <button type="button" className="ghost-button" onClick={run} disabled={busy || !status}>
                {busy ? "Weighing the list…" : "Ask the local model to pick (or pass)"}
              </button>
            )}
          {err && <p role="alert">{err}</p>}
        </div>
      </div>
    );
  }
  return (
    <div className="ai-panel">
      <p className="small">{res.summary}</p>
      {res.picks.length === 0 ? <p className="small muted">No picks: it passed.</p> : (
        <ol className="ai-picks">
          {res.picks.map((p) => (
            <li key={p.id}>
              <b>{p.id}</b> {name(p.id)}
              <span className="small muted"> · {HOW[p.how]}{p.how === "quote_at_or_below" && combos.get(p.id)?.walk_away
                ? ` ${cents(num(combos.get(p.id)!.walk_away))}` : p.how === "limit" && singles.get(p.id)?.limit
                ? ` at ${cents(num(singles.get(p.id)!.limit!.price))}` : ""} · ${p.stake.toFixed(2)}</span>
              {p.why.length > 0 && <ul className="reasons">{p.why.map((w) => <li key={w} className="good">{w}</li>)}</ul>}
              {p.risks.length > 0 && <ul className="reasons">{p.risks.map((w) => <li key={w} className="warn">{w}</li>)}</ul>}
            </li>
          ))}
        </ol>
      )}
      {res.skip.length > 0 && (
        <details className="small"><summary>Rejected ({res.skip.length})</summary>
          <ul>{res.skip.map((k) => <li key={k.id}><b>{k.id}</b> {k.why}</li>)}</ul></details>
      )}
      {res.sources.length > 0 && (
        <details className="small"><summary>Headlines it read ({res.sources.length})</summary>
          <ul>{res.sources.map((s) => <li key={s.id}>{s.id} <a href={s.url} target="_blank" rel="noreferrer noopener">{s.title}</a> <span className="muted">{s.source} {s.age}</span></li>)}</ul></details>
      )}
      <p className="fine muted">{res.model ? `AI-written by ${res.model}${res.seconds ? ` in ${res.seconds}s` : ""}${res.cached ? " (cached)" : ""}` : "No model call"}: it can only choose from the list above, and it can be wrong.{" "}
        <button type="button" className="link-button fine" onClick={() => setRes(null)}>clear</button></p>
    </div>
  );
}

/** Ranked ideas for one game: legs where history beats the all-in price, 2-3 leg combos built
 * from them, and cheaper limit entries from the order book alone. */
export function IdeasPanel({ prefix, gameKey }: { prefix: string; gameKey: string }) {
  const [ideas, setIdeas] = useState<GameIdeas | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const legs = useSlip();
  useEffect(() => {
    let cancel = false;
    setIdeas(null);
    api.ideas(prefix, gameKey).then((d) => { if (!cancel) { setIdeas(d); setErr(null); } },
      (e) => { if (!cancel) setErr(e instanceof ApiError ? e.message : "Backend unreachable"); });
    return () => { cancel = true; };
  }, [prefix, gameKey]);
  if (err) return <p role="alert">{err}</p>;
  if (!ideas) {
    return (
      <div className="ideas-loading">
        <Figure name="sieve" size={72} play />
        <p className="small muted">Screening every leg against box scores…</p>
      </div>
    );
  }
  const singles = new Map(ideas.singles.map((x) => [x.id, x]));
  const inSlip = new Set(legs.map((l) => l.ticker));
  const sk = ideas.skipped;
  return (
    <div className="ideas">
      <p className="small muted ideas-head">
        Screened {ideas.screened} legs · {ideas.singles.length} beat the price · cap ${ideas.cap} per idea
        {sk.priced_right > 0 && ` · ${sk.priced_right} priced about right`}
        {sk.injured > 0 && ` · ${sk.injured} skipped (injury)`}
      </p>
      {!ideas.evidence_enabled && <p className="flag info">Box scores are switched off, so only cheaper entries are shown: Kalshi's prices alone can't say which side is likelier.</p>}
      {ideas.evidence_error && <p className="flag warn">Box scores unavailable: {ideas.evidence_error}</p>}

      {ideas.singles.length > 0 ? (
        <>
          <h4 className="kicker">Singles</h4>
          <ul className="idea-list">{ideas.singles.map((x) => <SingleRow key={x.id} x={x} inSlip={inSlip.has(x.ticker)} />)}</ul>
        </>
      ) : ideas.evidence_enabled && (
        <EmptyState figure="sieve" title="Nothing beats the price">Every leg is priced at or above what history supports. Passing is a position.</EmptyState>
      )}

      {ideas.combos.length > 0 && (
        <>
          <h4 className="kicker">Small combos (only from the singles)</h4>
          <ul className="idea-list">{ideas.combos.map((c) => <ComboRow key={c.id} c={c} singles={singles} />)}</ul>
        </>
      )}

      {ideas.singles.length > 0 && <AiPicks prefix={prefix} gameKey={gameKey} ideas={ideas} singles={singles} />}

      {ideas.entries.length > 0 && (
        <details className="entries">
          <summary className="kicker">Cheaper entries ({ideas.entries.length}) · from Kalshi's book alone</summary>
          <p className="small muted">Not picks. If you already want one of these, a resting limit order beats paying the ask plus the taker fee (may not fill).</p>
          <ul className="idea-list">
            {ideas.entries.map((e) => (
              <li key={e.ticker} className="idea">
                <span className={`side-chip ${e.side}`}>{e.side.toUpperCase()}</span>
                <div className="idea-main"><span className="idea-bet">{plain(e.bet)}</span>
                  <span className="small muted">bid {cents(num(e.bid))} / ask {cents(num(e.ask))}</span></div>
                <span className="small idea-how">limit {cents(num(e.limit))}</span>
                <span className="small ev-pos">saves ${e.saves_per_100}/100</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="fine muted">History = past box scores, shrunk toward last season; it ignores tonight's matchup, minutes and rest. All-in = ask + taker fee. Ideas to research, not instructions.</p>
    </div>
  );
}
