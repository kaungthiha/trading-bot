import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api, ApiError } from "../api/client";
import type {
  CalibrationBin,
  MarketSummary,
  PaperAccount,
  PaperOrder,
  PaperSettlement,
  ReplayReport,
} from "../api/types";
import { CalibrationChart } from "./CalibrationChart";
import { MetricLabel } from "./MetricLabel";
import { Term } from "./Term";
import { formatPrice, formatUtc } from "./format";

const SCENARIOS = ["conservative", "baseline", "harsh"] as const;

function bins(trades: ReplayReport["trades"]): CalibrationBin[] {
  const out: CalibrationBin[] = Array.from({ length: 10 }, (_, i) => ({
    lower: i / 10, upper: (i + 1) / 10, count: 0, mean_p: null, observed_rate: null,
  }));
  const acc = out.map(() => ({ p: 0, y: 0 }));
  for (const t of trades) {
    if (t.p_side == null || t.outcome == null || t.status === "CANCELLED" || t.status === "SKIPPED") continue;
    const won = (t.outcome === "yes") === (t.side === "YES");
    const i = Math.min(9, Math.floor(t.p_side * 10));
    out[i]!.count += 1;
    acc[i]!.p += t.p_side;
    acc[i]!.y += won ? 1 : 0;
  }
  return out.map((b, i) =>
    b.count ? { ...b, mean_p: acc[i]!.p / b.count, observed_rate: acc[i]!.y / b.count } : b,
  );
}

function OrderForm({ onPlaced }: { onPlaced: (o: PaperOrder) => void }) {
  const [markets, setMarkets] = useState<MarketSummary[]>([]);
  const [marketId, setMarketId] = useState("");
  const [side, setSide] = useState<"YES" | "NO">("YES");
  const [action, setAction] = useState<"BUY" | "SELL">("BUY");
  const [quantity, setQuantity] = useState(10);
  const [limit, setLimit] = useState("0.50");
  const [scenario, setScenario] = useState<string>("conservative");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    api.markets({ status: "active" }).then(
      (r) => {
        setMarkets(r.items);
        if (r.items[0]) setMarketId(r.items[0].id);
      },
      () => setMarkets([]),
    );
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const o = await api.placePaperOrder({
        market_id: marketId, side, action, quantity, limit_price: limit, scenario,
      });
      setMessage(
        `${o.status}: ${o.filled_quantity}/${o.quantity}` +
          (o.reject_reason ? ` (${o.reject_reason})` : "") +
          (!o.fee_schedule_verified && o.fills.length ? " · fees UNVERIFIED" : ""),
      );
      onPlaced(o);
    } catch (err) {
      setMessage(err instanceof ApiError ? `${err.code}: ${err.message}` : "Order failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="filters paper-form" onSubmit={submit} aria-label="Simulated order">
      <label>
        Market
        <select value={marketId} onChange={(e) => setMarketId(e.target.value)} required>
          {markets.map((m) => (
            <option key={m.id} value={m.id}>
              {m.external_ticker}
            </option>
          ))}
        </select>
      </label>
      <label>
        Side
        <select value={side} onChange={(e) => setSide(e.target.value as "YES" | "NO")}>
          <option>YES</option>
          <option>NO</option>
        </select>
      </label>
      <label>
        Action
        <select value={action} onChange={(e) => setAction(e.target.value as "BUY" | "SELL")}>
          <option>BUY</option>
          <option>SELL</option>
        </select>
      </label>
      <label>
        Qty
        <input type="number" min={1} max={1000} step={1} value={quantity}
          onChange={(e) => setQuantity(Number(e.target.value))} />
      </label>
      <label>
        Limit ($)
        <input inputMode="decimal" pattern="0\.[0-9]{1,4}" value={limit}
          onChange={(e) => setLimit(e.target.value)} />
      </label>
      <label>
        Fill scenario
        <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
          {SCENARIOS.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      <button type="submit" disabled={busy || !marketId}>
        Simulate order
      </button>
      {message && (
        <span role="status" className="small">
          {message}
        </span>
      )}
    </form>
  );
}

export function PaperPanel() {
  const [account, setAccount] = useState<PaperAccount | null>(null);
  const [orders, setOrders] = useState<PaperOrder[]>([]);
  const [settlements, setSettlements] = useState<PaperSettlement[]>([]);
  const [replay, setReplay] = useState<ReplayReport | null>(null);

  const refresh = useCallback(() => {
    api.paperAccount().then(setAccount, () => setAccount(null));
    api.paperOrders().then(setOrders, () => setOrders([]));
    api.paperSettlements().then(setSettlements, () => setSettlements([]));
    api.paperReplay().then(setReplay, () => setReplay(null));
  }, []);

  useEffect(refresh, [refresh]);

  return (
    <div className="paper">
      <p className="disclaimer">
        Simulated trading only. Orders fill against a stored order-book snapshot under
        conservative assumptions; no exchange is contacted. Simulated results are not evidence
        of real returns.
      </p>
      <OrderForm onPlaced={refresh} />
      <p className="small muted">
        Fill scenarios: <strong>conservative</strong> takes half the displayed{" "}
        <Term id="orderbook-depth">depth</Term> and pays one price step worse (queue and latency);{" "}
        <strong>harsh</strong> takes a quarter and two steps; <strong>baseline</strong> takes what
        is displayed. Unfilled quantity is cancelled, never assumed bought.
      </p>

      {account && (
        <section aria-labelledby="acct-h">
          <h3 id="acct-h">Account</h3>
          <div className="tiles">
            <div className="tile"><span className="tile-label">Cash</span>{formatPrice(account.cash)}</div>
            <div className="tile"><span className="tile-label">Open positions (liquidation value)</span>{formatPrice(account.open_value)}</div>
            <div className="tile"><span className="tile-label">Equity</span>{formatPrice(account.equity)}</div>
            <div className="tile"><span className="tile-label">Realized P&amp;L</span>{formatPrice(account.realized)}</div>
            <div className="tile"><span className="tile-label">Unrealized P&amp;L</span>{formatPrice(account.unrealized)}</div>
          </div>
          {account.notes.map((n) => (
            <p key={n} className="small"><span className="badge stale">NOTE</span> {n}</p>
          ))}
          {account.positions.length > 0 && (
            <table className="market-table">
              <thead>
                <tr>
                  <th scope="col">Market</th>
                  <th scope="col">Side</th>
                  <th scope="col">Open qty</th>
                  <th scope="col">Avg cost (incl. <MetricLabel termId="fees">fees</MetricLabel>)</th>
                  <th scope="col">Realized</th>
                  <th scope="col">Unrealized</th>
                  <th scope="col">State</th>
                </tr>
              </thead>
              <tbody>
                {account.positions.map((p) => (
                  <tr key={`${p.market_id}-${p.side}`}>
                    <td className="ticker">{p.market_ticker}</td>
                    <td>{p.side}</td>
                    <td>{p.open_qty}</td>
                    <td>{formatPrice(p.avg_cost)}</td>
                    <td>{formatPrice(p.realized)}</td>
                    <td>
                      {formatPrice(p.unrealized)}
                      {p.mark_note && <div className="ticker">{p.mark_note}</div>}
                    </td>
                    <td>{p.settled ? "settled" : p.held ? <span className="badge stale">HELD</span> : "open"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      <section aria-labelledby="orders-h">
        <h3 id="orders-h">Orders</h3>
        {orders.length === 0 ? (
          <p className="muted small">No simulated orders yet.</p>
        ) : (
          <table className="market-table">
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Market</th>
                <th scope="col">Order</th>
                <th scope="col">Status</th>
                <th scope="col">Fills (sim price / displayed)</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id}>
                  <td className="ticker">{formatUtc(o.submitted_at)}</td>
                  <td className="ticker">{o.market_ticker}</td>
                  <td>
                    {o.action} {o.quantity} {o.side} ≤ {formatPrice(o.limit_price)}
                    <div className="ticker">{o.scenario}</div>
                  </td>
                  <td>
                    {o.status} {o.filled_quantity}/{o.quantity}
                    {o.reject_reason && <div className="ticker">{o.reject_reason}</div>}
                  </td>
                  <td className="ticker">
                    {o.fills.map((f) => `${f.quantity} @ ${f.price} / ${f.displayed_price}`).join("; ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section aria-labelledby="settle-h">
        <h3 id="settle-h">Settlements</h3>
        <p className="small muted">
          Payouts happen only on a <strong>finalized</strong> exchange result, cross-checked
          against our own CPI first print. Disagreement → HELD for review. Run{" "}
          <code>python -m app.cli paper-settle</code>.
        </p>
        {settlements.length === 0 ? (
          <p className="muted small">None yet.</p>
        ) : (
          <ul className="small">
            {settlements.map((st) => (
              <li key={st.id}>
                <strong>{st.market_ticker}</strong>: {st.status} · exchange {st.exchange_result} ·
                evidence {st.evidence_check} {st.notes.length > 0 && <span className="muted">({st.notes.join("; ")})</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      {replay && (
        <section aria-labelledby="replay-h">
          <h3 id="replay-h">Signal replay ({replay.scenario})</h3>
          <p className="small">
            {replay.n_signals} candidate signals · {replay.n_resolved} resolved · cost{" "}
            {formatPrice(replay.total_cost)} · realized P&amp;L {formatPrice(replay.realized_pnl)} ·{" "}
            <MetricLabel termId="brier-score">Brier</MetricLabel>{" "}
            {replay.resolved_brier == null ? "—" : replay.resolved_brier.toFixed(4)}
          </p>
          <CalibrationChart title="Replayed signals: calibration" bins={bins(replay.trades)} />
          <p className="small disclaimer">{replay.caveat}</p>
        </section>
      )}
    </div>
  );
}
