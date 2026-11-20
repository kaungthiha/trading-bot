import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api, ApiError } from "../api/client";
import type { OpportunityCard, ScannerStatus, Scorecard } from "../api/types";
import { formatPrice, formatUtc } from "./format";
import { EmptyState } from "./Hairline";
import { useDataRefresh } from "./useDataRefresh";
import { href } from "../router";
import { InvestigateButton } from "./investigate/InvestigateButton";

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
    <article className={`thesis-card ${card.guaranteed ? "guaranteed" : "conditional"}${open ? "" : " expired"}`}
      aria-labelledby={`opp-${card.id}`}>
      <header>
        <h3 id={`opp-${card.id}`}><a href={href.research("opp", card.id)} title="Open the research page">{card.title}</a></h3>
        <span className={`badge ${card.guaranteed ? "paper" : "stale"}`}>
          {card.guaranteed ? "GUARANTEED (if rules hold)" : "CONDITIONAL"}
        </span>
      </header>
      <p className="thesis-profit"><b>{formatPrice(card.profit)}</b> <span className="muted small">profit · {card.return_pct}% on {formatPrice(card.cost)}</span></p>
      <p className="ticker">
        {card.kind} · {card.event_ticker} · detected {formatUtc(card.detected_at)} · status{" "}
        <strong>{card.status}</strong>
      </p>
      <p className="small">{card.claim}</p>
      <div className="table-scroll" tabIndex={0} role="region" aria-label={`Legs: ${card.title}`}>
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
                <InvestigateButton quiet leg={{ ticker: l.ticker, side: l.side === "YES" ? "yes" : "no", label: l.title,
                  event: card.event_ticker }} />
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
      </div>
      <p className="small">
        Total {formatPrice(card.cost)} (fees {formatPrice(card.fees)}) → worst-case payout{" "}
        {formatPrice(card.min_payoff)} · profit <strong>{formatPrice(card.profit)}</strong> (
        {card.return_pct}%) · cap {card.budget_cap ? formatPrice(card.budget_cap) : "n/a"}
      </p>
      <details className="checklist-box small">
        <summary>Verify before trading · {checked.filter(Boolean).length}/{checked.length} checked</summary>
        {card.checklist.map((c, i) => (
          <label key={c} className="check-item">
            <input type="checkbox" checked={checked[i]} disabled={!open}
              onChange={(e) => setChecked(checked.map((v, j) => (j === i ? e.target.checked : v)))} />{" "}
            {c}
          </label>
        ))}
      </details>
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

function ScanCoverage({ scan }: { scan: NonNullable<ScannerStatus["last_scan"]> }) {
  const cov = scan.coverage!;
  return (
    <details className="small coverage">
      <summary>
        What the last scan looked at ({scan.events.toLocaleString()} events,{" "}
        {scan.markets.toLocaleString()} markets) and how close anything came
      </summary>
      <div className="coverage-grid">
        <table className="market-table">
          <caption>By category</caption>
          <thead><tr><th scope="col">Category</th><th scope="col">Events</th><th scope="col">Markets</th></tr></thead>
          <tbody>
            {cov.categories.slice(0, 10).map((c) => (
              <tr key={c.name}><td>{c.name}</td><td>{c.events}</td><td>{c.markets}</td></tr>
            ))}
          </tbody>
        </table>
        <table className="market-table">
          <caption>Largest series</caption>
          <thead><tr><th scope="col">Series</th><th scope="col">Events</th><th scope="col">Markets</th></tr></thead>
          <tbody>
            {cov.top_series.map((c) => (
              <tr key={c.name}><td className="ticker">{c.name}</td><td>{c.events}</td><td>{c.markets}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      {scan.near_misses && scan.near_misses.length > 0 && (
        <table className="market-table">
          <caption>Closest to a mispricing. Gap = payout minus cost, before fees: every leg pays its own fee (about 1¢ a contract), so a positive gap across many legs is usually still a loss</caption>
          <thead>
            <tr>
              <th scope="col">Event</th><th scope="col">Structure</th>
              <th scope="col">Cost / set</th><th scope="col">Pays</th><th scope="col">Gap</th>
            </tr>
          </thead>
          <tbody>
            {scan.near_misses.map((n) => (
              <tr key={n.event_ticker}>
                <td>{n.title}<div className="ticker">{n.event_ticker} · {n.category}</div></td>
                <td className="small">{n.kind}: {n.detail}</td>
                <td>{formatPrice(n.raw_cost_per_set)}</td>
                <td>{formatPrice(n.payoff_per_set)}</td>
                <td>{n.gap}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </details>
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
  useDataRefresh(refresh);

  return (
    <div className="opportunities">
      <p className="disclaimer">
        Suggestions only: verify the checklist, then trade on Kalshi yourself, with money you can lose.
      </p>
      {status && (
        <div className="stat-chips">
          <div className="stat-chip"><span className="tile-label">Budget</span><b>{status.budget ? formatPrice(status.budget) : "not set"}</b></div>
          <div className="stat-chip"><span className="tile-label">Available</span><b>{status.available ? formatPrice(status.available) : "—"}</b></div>
          <div className="stat-chip"><span className="tile-label">Per-idea cap (largest stake per idea)</span>
            <b className="small">{formatPrice(status.caps.guaranteed)} guaranteed / {formatPrice(status.caps.conditional)} conditional</b></div>
          {status.last_scan && (
            <div className="stat-chip">
              <span className="tile-label">Last scan {formatUtc(status.last_scan.at)}</span>
              <b className="small">{status.last_scan.markets} markets · {status.last_scan.confirmed} confirmed</b></div>
          )}
          {status.note && <span className="badge stale">{status.note}</span>}
        </div>
      )}
      {score && (score.all.executed > 0 || score.skipped > 0) && (
        <p className="small">
          Scorecard: {score.all.executed} executed ({score.all.settled} settled, {score.all.wins} wins) ·
          realized P&amp;L {formatPrice(score.realized_pnl)} · open {formatPrice(score.open_cost)} ·{" "}
          {score.skipped} skipped
        </p>
      )}
      {status?.last_scan?.coverage && <ScanCoverage scan={status.last_scan} />}
      {cards === null ? (
        <p>Loading…</p>
      ) : cards.length === 0 ? (
        <EmptyState figure="sieve" title="No ideas right now">
          Most scans find nothing, and that is normal: genuine gaps are rare and brief. Press Scan now, or turn on auto-scan.
        </EmptyState>
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
