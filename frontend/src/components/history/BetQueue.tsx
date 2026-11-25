import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { JournalEntry, JournalLeg } from "../../api/types";
import { slip } from "../games/slip";
import { EmptyState } from "../Hairline";
import "./review.css";

const cents = (s: string | null) => (s == null ? "—" : `${(Number(s) * 100).toFixed(1)}¢`);
const money = (s: string | null) => {
  if (s == null) return "—";
  const n = Number(s);
  return `${n < 0 ? "−" : n > 0 ? "+" : ""}$${Math.abs(n).toFixed(2)}`;
};
const MARK: Record<NonNullable<JournalLeg["status"]>, string> = { won: "✓", lost: "✗", open: "·", unknown: "·" };
const title = (e: JournalEntry) => (e.legs.length === 1 ? e.legs[0]!.label : `${e.legs.length}-leg combo`);

function Entry({ e, onChange }: { e: JournalEntry; onChange: () => void }) {
  const [err, setErr] = useState<string | null>(null);
  const act = (p: Promise<unknown>) => p.then(onChange, (x) => setErr(x instanceof ApiError ? x.message : "Failed"));
  const k = e.kalshi;
  return (
    <li className={`bq-entry ${e.status}`}>
      <div className="bq-head">
        <b>{title(e)}</b>
        <span className="small muted">
          {new Date(e.created_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
          {" · "}{e.source === "slate" ? "from tonight's combos" : e.source === "docket" ? "from the docket" : "your own"}
        </span>
      </div>
      <ul className="dr-legs small">
        {e.legs.map((lg) => (
          <li key={`${lg.ticker}:${lg.side}`} className={`dr-leg ${lg.status ?? ""}`}>
            <span className="dr-mark">{MARK[lg.status ?? "unknown"]}</span> {lg.side.toUpperCase()} · {lg.label}
          </li>
        ))}
      </ul>
      <p className="small">
        {e.market_price != null && <>market {cents(e.market_price)} when logged · </>}
        {e.my_price != null && <>your price {cents(e.my_price)} · </>}
        {e.stake != null && <>stake ${e.stake}</>}
      </p>
      {e.note && <p className="small dr-note"><b>Why:</b> {e.note}</p>}
      {k ? (
        <p className="small">
          <span className="badge paper small">On Kalshi</span> paid {cents(k.avg_price)} for {k.contracts} contracts
          {k.pnl != null ? <> · <b className={Number(k.pnl) >= 0 ? "ev-pos" : "ev-neg"}>{money(k.pnl)}</b></> : " · open"}
          {e.my_price != null && k.avg_price != null && Math.abs(Number(k.avg_price) - Number(e.my_price)) >= 0.005 && (
            <span className="muted"> · {Number(k.avg_price) > Number(e.my_price) ? "paid more" : "paid less"} than you planned</span>
          )}
        </p>
      ) : e.status === "placed" ? (
        <p className="small muted">Placed: links to your Kalshi fill after the next sync.</p>
      ) : e.status === "skipped" && e.legs_outcome ? (
        <p className="small">Skipped: it would have <b className={e.legs_outcome === "won" ? "ev-pos" : "ev-neg"}>{e.legs_outcome}</b>.</p>
      ) : null}
      <div className="bq-actions">
        {e.status === "queued" && (
          <>
            <button type="button" className="link-button small" onClick={() => act(api.updateBet(e.id, { status: "placed" }))}>I placed it</button>
            <button type="button" className="link-button small" onClick={() => act(api.updateBet(e.id, { status: "skipped" }))}>Skip</button>
          </>
        )}
        {e.status === "skipped" && (
          <button type="button" className="link-button small" onClick={() => act(api.updateBet(e.id, { status: "queued" }))}>Back to queue</button>
        )}
        <button type="button" className="link-button small"
          onClick={() => slip.replace(e.legs.map((l) => ({ ticker: l.ticker, side: l.side, label: l.label, event: l.event || l.ticker.split("-").slice(0, 2).join("-") })))}>
          Load into docket
        </button>
        <button type="button" className="link-button small" aria-label={`Delete ${title(e)}`}
          onClick={() => act(api.removeBet(e.id))}>Delete</button>
      </div>
      {err && <p role="alert" className="small">{err}</p>}
    </li>
  );
}

/** Your bet queue: bets you logged from the Docket or tonight's combos. Queue them while you
 * research, mark them placed (or skip them), and see how each ended, matched to your Kalshi
 * fills after a sync. The app never places orders. */
export function BetQueue() {
  const [items, setItems] = useState<JournalEntry[] | null>(null);
  const load = useCallback(() => { api.betQueue().then((r) => setItems(r.items), () => setItems([])); }, []);
  useEffect(load, [load]);
  if (items == null) return <p className="small muted">Loading…</p>;
  if (items.length === 0) {
    return (
      <EmptyState figure="basket" title="Your bet queue is empty">
        On the Docket, use “Add to bet queue” (or “I placed it”) with your price, stake and reason. Tonight's combos have
        a button too.
      </EmptyState>
    );
  }
  const groups: [string, JournalEntry[]][] = [
    ["Queued: still to place", items.filter((x) => x.status === "queued")],
    ["Placed", items.filter((x) => x.status === "placed")],
    ["Skipped", items.filter((x) => x.status === "skipped")],
  ];
  return (
    <div className="bet-queue">
      {groups.filter(([, xs]) => xs.length > 0).map(([name, xs]) => (
        <section key={name} className="panel" aria-label={name}>
          <h3 className="kicker">{name} ({xs.length})</h3>
          <ul className="bq-list">{xs.map((e) => <Entry key={e.id} e={e} onChange={load} />)}</ul>
        </section>
      ))}
    </div>
  );
}
