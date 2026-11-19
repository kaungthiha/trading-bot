import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { FeeScheduleInfo, Signal } from "../api/types";
import { LineageView } from "./LineageView";
import { MetricLabel } from "./MetricLabel";
import { Term } from "./Term";
import { formatPrice, formatUtc } from "./format";
import { useDataRefresh } from "./useDataRefresh";
import { href } from "../router";

const pct = (p: number | null | undefined) => (p == null ? "—" : `${(p * 100).toFixed(1)}%`);

function DecisionBadge({ s }: { s: Signal }) {
  if (s.validity !== "VALID") {
    return <span className="badge stale">{s.validity.replaceAll("_", " ")}</span>;
  }
  if (s.decision === "ABSTAIN") {
    return (
      <span className="badge stale">
        <Term id="abstention">ABSTAIN</Term>
      </span>
    );
  }
  return <span className="badge candidate">{s.decision.replace("_", " ")} (research only)</span>;
}

function SignalCard({ s }: { s: Signal }) {
  return (
    <article className="signal-card" aria-labelledby={`sig-${s.id}`}>
      <header>
        <h4 id={`sig-${s.id}`}><a href={href.research("sig", s.id)} title="Open the research page">{s.market_title}</a></h4>
        <DecisionBadge s={s} />
      </header>
      <p className="ticker">
        {s.market_ticker} · {s.contract_key ?? "no contract mapping"} · mapping{" "}
        {s.mapping_status ?? "none"}
      </p>
      <dl className="quote-grid">
        <dt>Model P(YES)</dt>
        <dd>
          {pct(s.p_yes)}
          {s.p_lower != null && (
            <span className="ticker">
              {" "}
              band {pct(s.p_lower)}–{pct(s.p_upper)} ({s.model})
            </span>
          )}
        </dd>
        <dt>Side evaluated</dt>
        <dd>
          {s.side ?? "—"} × {s.quantity ?? "—"} contracts
        </dd>
        <dt>Entry (VWAP of derived asks)</dt>
        <dd>{formatPrice(s.entry)}</dd>
        <dt>
          <MetricLabel termId="fees">Fee</MetricLabel> / contract
        </dt>
        <dd>
          {formatPrice(s.fee)} <span className="ticker">{s.fee_schedule_version}</span>
        </dd>
        <dt>
          <MetricLabel termId="slippage">Slippage</MetricLabel> / contract
        </dt>
        <dd>{formatPrice(s.slippage)}</dd>
        <dt>
          <MetricLabel termId="expected-value">EV</MetricLabel> / contract
        </dt>
        <dd>{formatPrice(s.ev)}</dd>
        <dt>
          Lower-bound <MetricLabel termId="edge">edge</MetricLabel>
        </dt>
        <dd>{formatPrice(s.lower_edge)}</dd>
        {s.details.model_market_divergence != null && (
          <>
            <dt>Model vs market gap</dt>
            <dd>{s.details.model_market_divergence}</dd>
          </>
        )}
      </dl>
      {s.reasons.length > 0 && (
        <p className="small">
          <strong>Reasons:</strong>{" "}
          {s.reasons.map((r) => (
            <code key={r} className="reason">
              {r}
            </code>
          ))}
        </p>
      )}
      <p className="ticker">
        Created {formatUtc(s.created_at)} · expires {formatUtc(s.expires_at)} · quote{" "}
        {s.quote_observed_at ? formatUtc(s.quote_observed_at) : "none"} (id {s.quote_id?.slice(0, 8) ?? "—"}) ·
        model run {s.model_run_id?.slice(0, 8) ?? "—"}
        {s.rules_source_url && (
          <>
            {" · "}
            <a href={s.rules_source_url} target="_blank" rel="noopener noreferrer">
              contract terms
            </a>
          </>
        )}
      </p>
      <LineageView signalId={s.id} />
      <details className="small">
        <summary>Caveats</summary>
        <ul>
          {s.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </details>
    </article>
  );
}

export function SignalsPanel() {
  const [signals, setSignals] = useState<Signal[] | null>(null);
  const [fees, setFees] = useState<FeeScheduleInfo[]>([]);
  const [onlyCandidates, setOnlyCandidates] = useState(false);

  const load = useCallback(() => {
    api.signals().then(setSignals, () => setSignals([]));
    api.feeSchedules().then(setFees, () => setFees([]));
  }, []);
  useEffect(load, [load]);
  useDataRefresh(load);

  if (signals === null) return <p>Loading signals…</p>;
  // Warn only when no verified schedule exists (older unverified versions are kept so past
  // signals stay traceable).
  const unverified = fees.length > 0 && !fees.some((f) => f.verified) ? fees : [];
  const shown = onlyCandidates
    ? signals.filter((s) => s.decision !== "ABSTAIN" && s.validity === "VALID")
    : signals;

  return (
    <div className="signals">
      <p className="disclaimer">
        Signals are research hypotheses. Nothing here places, queues or authorizes an order.
      </p>
      {unverified.length > 0 && (
        <p role="status" className="small">
          <span className="badge stale">FEES UNVERIFIED</span> {unverified.map((f) => f.version).join(", ")}:
          verify against the{" "}
          <a href={unverified[0]!.source_url} target="_blank" rel="noopener noreferrer">
            official fee schedule
          </a>{" "}
          and mark it verified in <code>backend/app/signals/fee_schedules.json</code>. Until
          then every signal abstains.
        </p>
      )}
      <label className="small">
        <input
          type="checkbox"
          checked={onlyCandidates}
          onChange={(e) => setOnlyCandidates(e.target.checked)}
        />{" "}
        Show only valid candidates
      </label>
      {signals.length === 0 ? (
        <p className="muted small">
          No signals yet. Run <code>propose-mappings</code>, confirm a mapping with{" "}
          <code>confirm-mapping &lt;TICKER&gt; --yes</code>, then <code>generate-signals</code>.
        </p>
      ) : shown.length === 0 ? (
        <p className="muted small">No valid candidates.</p>
      ) : (
        <div className="signal-grid">
          {shown.map((s) => (
            <SignalCard key={s.id} s={s} />
          ))}
        </div>
      )}
    </div>
  );
}
