import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api, ApiError } from "../api/client";
import type { ExecutionIntent, ExecutionStatus, MarketSummary } from "../api/types";
import { formatPrice, formatUtc } from "./format";

function errText(e: unknown): string {
  return e instanceof ApiError ? `${e.code}: ${e.message}` : "Request failed";
}

function secondsLeft(iso: string, now: number): number {
  return Math.max(0, Math.round((new Date(iso).getTime() - now) / 1000));
}

/** Review-and-approve card for ONE proposed order. Shows exactly what would be sent. */
export function ApprovalCard({
  intent,
  onDone,
}: {
  intent: ExecutionIntent;
  onDone: (i: ExecutionIntent) => void;
}) {
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const left = secondsLeft(intent.expires_at, now);

  async function approve(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onDone(await api.approveIntent(intent.id, intent.payload_hash, pin));
    } catch (err) {
      setError(errText(err));
    } finally {
      setPin(""); // never keep the PIN around
      setBusy(false);
    }
  }

  return (
    <form className="approval-card" onSubmit={approve} aria-label="Approve this exact order">
      <p>
        <strong>{intent.summary}</strong>
      </p>
      <dl className="quote-grid small">
        <dt>Snapshot ask</dt>
        <dd>{formatPrice(intent.approved_ask)} (any worse price at send time blocks the order)</dd>
        <dt>Fee schedule</dt>
        <dd className="ticker">{intent.fee_schedule_version}</dd>
        <dt>Expires in</dt>
        <dd>{left > 0 ? `${left}s` : "expired: propose again"}</dd>
        <dt>Order hash</dt>
        <dd className="ticker">{intent.payload_hash.slice(0, 16)}…</dd>
      </dl>
      <details className="small">
        <summary>Exact payload that would be sent</summary>
        <pre className="payload">{JSON.stringify(intent.payload, null, 2)}</pre>
      </details>
      <label className="filters">
        <span>Approval PIN</span>
        <input
          type="password"
          autoComplete="off"
          value={pin}
          onChange={(e) => setPin(e.target.value)}
          required
          minLength={6}
          maxLength={128}
        />
      </label>
      <button type="submit" className="danger-button" disabled={busy || left === 0 || pin.length < 6}>
        Approve and send to {intent.env.toUpperCase()}
      </button>
      {error && (
        <p role="alert" className="small">
          {error}
        </p>
      )}
    </form>
  );
}

export function ExecutionPanel() {
  const [status, setStatus] = useState<ExecutionStatus | null>(null);
  const [intents, setIntents] = useState<ExecutionIntent[]>([]);
  const [markets, setMarkets] = useState<MarketSummary[]>([]);
  const [pending, setPending] = useState<ExecutionIntent | null>(null);
  const [last, setLast] = useState<ExecutionIntent | null>(null);
  const [form, setForm] = useState({
    market_id: "",
    side: "YES" as "YES" | "NO",
    quantity: 1,
    limit_price: "0.50",
  });
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.executionStatus().then(setStatus, () => setStatus(null));
    api.executionIntents().then(setIntents, () => setIntents([]));
  }, []);

  useEffect(() => {
    refresh();
    api.markets({ status: "active" }).then(
      (r) => {
        setMarkets(r.items);
        if (r.items[0]) setForm((f) => ({ ...f, market_id: r.items[0]!.id }));
      },
      () => setMarkets([]),
    );
  }, [refresh]);

  async function propose(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLast(null);
    try {
      setPending(await api.proposeIntent(form));
    } catch (err) {
      setError(errText(err));
    }
  }

  async function engage() {
    await api.engageKillSwitch("UI emergency stop").catch(() => undefined);
    setPending(null);
    refresh();
  }

  if (!status) return <p className="muted small">Execution status unavailable.</p>;
  return (
    <div className="execution">
      <div className="warning-box small" role="note">
        <strong>Approval-gated execution ({status.env.toUpperCase()} only).</strong> Production
        trading is {status.production}. Every order needs a fresh proposal, your PIN and a passing
        last-moment check. Results that come back ambiguous are looked up, never re-sent.
      </div>
      <p className="small">
        Enabled: <strong>{status.execution_enabled ? "yes" : "no"}</strong> · kill switch:{" "}
        <span className={`badge ${status.kill_switch_engaged ? "stale" : "paper"}`}>
          {status.kill_switch_engaged ? "ENGAGED" : "released"}
        </span>{" "}
        · PIN {status.pin_configured ? "set" : "not set"} · caps:{" "}
        {String(status.caps.max_contracts_per_order)} contracts / $
        {String(status.caps.max_cost_per_order)} per order, ${String(status.caps.max_daily_cost)}{" "}
        per day{" "}
        <button type="button" className="danger-button small" onClick={engage}>
          Emergency stop (engage kill switch)
        </button>
      </p>
      {!status.execution_enabled ? (
        <p className="muted small">
          Disabled (the default). To try the mock exchange, follow the README section
          &ldquo;Approval-gated execution&rdquo;: enable execution in your <code>.env</code>, run{" "}
          <code>python -m app.cli set-approval-pin --write-env</code>, then{" "}
          <code>python -m app.cli kill-switch release --yes</code>, and restart the backend.
        </p>
      ) : (
        <>
          <form className="filters paper-form" onSubmit={propose} aria-label="Propose an order">
            <label>
              Market
              <select
                value={form.market_id}
                onChange={(e) => setForm({ ...form, market_id: e.target.value })}
              >
                {markets.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.external_ticker}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Buy
              <select
                value={form.side}
                onChange={(e) => setForm({ ...form, side: e.target.value as "YES" | "NO" })}
              >
                <option>YES</option>
                <option>NO</option>
              </select>
            </label>
            <label>
              Qty
              <input
                type="number"
                min={1}
                step={1}
                value={form.quantity}
                onChange={(e) => setForm({ ...form, quantity: Number(e.target.value) })}
              />
            </label>
            <label>
              Limit ($)
              <input
                inputMode="decimal"
                value={form.limit_price}
                onChange={(e) => setForm({ ...form, limit_price: e.target.value })}
              />
            </label>
            <button type="submit">Propose (no order yet)</button>
          </form>
          {error && (
            <p role="alert" className="small">
              {error}
            </p>
          )}
          {pending && pending.status === "PROPOSED" && (
            <ApprovalCard
              intent={pending}
              onDone={(i) => {
                setPending(null);
                setLast(i);
                refresh();
              }}
            />
          )}
          {last && (
            <p role="status" className="small">
              Result: <strong>{last.status}</strong>
              {last.block_reason && <> ({last.block_reason})</>}
              {last.exchange_order && <> · filled {last.exchange_order.fill_count}</>}
              {last.status === "UNKNOWN" && (
                <> · outcome unknown: it will be looked up, never re-sent</>
              )}
            </p>
          )}
        </>
      )}
      {intents.length > 0 && (
        <table className="market-table">
          <caption className="visually-hidden">Recent execution intents</caption>
          <thead>
            <tr>
              <th scope="col">Created</th>
              <th scope="col">Order</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {intents.map((i) => (
              <tr key={i.id}>
                <td className="ticker">{formatUtc(i.created_at)}</td>
                <td className="small">{i.summary}</td>
                <td>
                  {i.status}
                  {i.block_reason && <div className="ticker">{i.block_reason}</div>}
                  {i.status === "UNKNOWN" && (
                    <button
                      type="button"
                      className="link-button small"
                      onClick={() => api.reconcileIntent(i.id).then(refresh, refresh)}
                    >
                      Look up (read-only)
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
