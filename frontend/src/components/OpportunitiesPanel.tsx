import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api, ApiError } from "../api/client";
import type { OpportunityCard, ScannerStatus, Scorecard } from "../api/types";
import { formatPrice, formatUtc } from "./format";

function errText(e: unknown): string {
  return e instanceof ApiError ? e.message : "Request failed";
}

function ExecuteForm({ card, onDone }: { card: OpportunityCard; onDone: () => void }) {
  const [legs, setLegs] = useState(
    card.legs.map((l) => ({ ticker: l.ticker, side: l.side, quantity: Number(l.quantity),
                            avg_price: l.limit_price.replace(/0+$/, "").replace(/\.$/, ".0"),
                            fee: "" })),
  );
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.journal(card.id, {
        action: "EXECUTED",
        legs: legs.map((l) => ({ ...l, fee: l.fee || "0" })),
        note: "",
      });
      onDone();
    } catch (err) {
      setError(errText(err));
    }
  }

  return (
    <form className="small execute-form" onSubmit={submit} aria-label="Record what you filled">
      <p className="muted">Enter what actually filled on Kalshi (edit if different):</p>
      {legs.map((l, i) => (
        <div key={l.ticker} className="filters">
          <span className="ticker">
            {l.side} {l.ticker}
          </span>
          <label>
            Qty
            <input type="number" min={1} value={l.quantity}
              onChange={(e) => setLegs(legs.map((x, j) => (j === i ? { ...x, quantity: Number(e.target.value) } : x)))} />
          </label>
          <label>
            Avg price
            <input value={l.avg_price}
              onChange={(e) => setLegs(legs.map((x, j) => (j === i ? { ...x, avg_price: e.target.value } : x)))} />
          </label>
          <label>
            Fee paid
            <input value={l.fee} placeholder="0.00"
              onChange={(e) => setLegs(legs.map((x, j) => (j === i ? { ...x, fee: e.target.value } : x)))} />
          </label>
        </div>
      ))}
      <button type="submit">Save to journal</button>
      {error && <p role="alert">{error}</p>}
    </form>
  );
}

function Card({ card, onChange }: { card: OpportunityCard; onChange: () => void }) {
  const [checked, setChecked] = useState<boolean[]>(card.checklist.map(() => false));
  const [executing, setExecuting] = useState(false);
  const allChecked = checked.every(Boolean);
  const open = card.status === "OPEN";

  return (
    <article className={`thesis-card ${card.guaranteed ? "guaranteed" : "conditional"}`}
      aria-labelledby={`opp-${card.id}`}>
      <header>
        <h4 id={`opp-${card.id}`}>{card.title}</h4>
        <span className={`badge ${card.guaranteed ? "paper" : "stale"}`}>
          {card.guaranteed ? "GUARANTEED (if rules hold)" : "CONDITIONAL"}
        </span>
      </header>
      <p className="ticker">
        {card.kind} · {card.event_ticker} · detected {formatUtc(card.detected_at)} · status{" "}
        <strong>{card.status}</strong>
      </p>
      <p>{card.claim}</p>
      <table className="market-table">
        <thead>
          <tr>
            <th scope="col">Buy</th>
            <th scope="col">Market</th>
            <th scope="col">Limit</th>
            <th scope="col">Qty</th>
            <th scope="col">Cost (incl. fee)</th>
          </tr>
        </thead>
        <tbody>
          {card.legs.map((l) => (
            <tr key={l.ticker + l.side}>
              <td>{l.side}</td>
              <td>
                {l.title}
                <div className="ticker">{l.ticker}</div>
              </td>
              <td>{formatPrice(l.limit_price)}</td>
              <td>
                {l.quantity}
                <div className="ticker">{l.available} available</div>
              </td>
              <td>{formatPrice(l.cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="small">
        Total {formatPrice(card.cost)} (fees {formatPrice(card.fees)}) → worst-case payout{" "}
        {formatPrice(card.min_payoff)} · profit <strong>{formatPrice(card.profit)}</strong> (
        {card.return_pct}%) · cap {card.budget_cap ? formatPrice(card.budget_cap) : "n/a"}
      </p>
      <fieldset className="checklist-box small">
        <legend>Verify before trading</legend>
        {card.checklist.map((c, i) => (
          <label key={c} className="check-item">
            <input type="checkbox" checked={checked[i]} disabled={!open}
              onChange={(e) => setChecked(checked.map((v, j) => (j === i ? e.target.checked : v)))} />{" "}
            {c}
          </label>
        ))}
      </fieldset>
      {open && (
        <p className="small">
          <button type="button" disabled={!allChecked} onClick={() => setExecuting(true)}>
            I executed this on Kalshi
          </button>{" "}
          <button type="button" className="link-button"
            onClick={() => api.journal(card.id, { action: "SKIPPED", legs: [], note: "" }).then(onChange, onChange)}>
            Skip
          </button>{" "}
          <span className="muted">expires {formatUtc(card.expires_at)}</span>
        </p>
      )}
      {executing && <ExecuteForm card={card} onDone={() => { setExecuting(false); onChange(); }} />}
    </article>
  );
}

export function OpportunitiesPanel() {
  const [cards, setCards] = useState<OpportunityCard[] | null>(null);
  const [status, setStatus] = useState<ScannerStatus | null>(null);
  const [score, setScore] = useState<Scorecard | null>(null);

  const refresh = useCallback(() => {
    api.opportunities().then(setCards, () => setCards([]));
    api.scannerStatus().then(setStatus, () => setStatus(null));
    api.scorecard().then(setScore, () => setScore(null));
  }, []);
  useEffect(refresh, [refresh]);

  return (
    <div className="opportunities">
      <p className="disclaimer">
        Suggestions only. Each card is a mispricing the scanner found in Kalshi&apos;s public
        order books, re-checked against live books. Verify the checklist, then trade on Kalshi
        yourself. Real money: only what you are prepared to lose.
      </p>
      {status && (
        <p className="small">
          Budget {status.budget ? formatPrice(status.budget) : "not set"} · available{" "}
          {status.available ? formatPrice(status.available) : "—"} · per-idea caps{" "}
          {formatPrice(status.caps.guaranteed)} guaranteed / {formatPrice(status.caps.conditional)} conditional
          {status.note && <span className="badge stale">{status.note}</span>}
          {status.last_scan && (
            <>
              {" "}· last scan {formatUtc(status.last_scan.at)}: {status.last_scan.events} events,{" "}
              {status.last_scan.markets} markets, {status.last_scan.candidates} candidates,{" "}
              {status.last_scan.confirmed} confirmed
            </>
          )}
        </p>
      )}
      {score && (score.all.executed > 0 || score.skipped > 0) && (
        <p className="small">
          Scorecard: {score.all.executed} executed ({score.all.settled} settled, {score.all.wins} wins) ·
          realized P&amp;L {formatPrice(score.realized_pnl)} · open {formatPrice(score.open_cost)} ·{" "}
          {score.skipped} skipped
        </p>
      )}
      {cards === null ? (
        <p>Loading…</p>
      ) : cards.length === 0 ? (
        <p className="muted small">
          No ideas yet. Run <code>python -m app.cli scan</code>, or keep the worker running with
          live Kalshi data enabled (see the README &ldquo;Opportunity scanner&rdquo;). Most scans
          find nothing, and that is normal: genuine gaps are rare and brief.
        </p>
      ) : (
        <div className="thesis-grid">
          {cards.map((c) => (
            <Card key={c.id} card={c} onChange={refresh} />
          ))}
        </div>
      )}
    </div>
  );
}
