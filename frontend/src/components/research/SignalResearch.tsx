import type { Signal } from "../../api/types";
import { href } from "../../router";
import { StatusLabel } from "../design/StatusLabel";
import { LineageView } from "../LineageView";
import { useNow } from "../shell/Topbar";
import { exact, rel } from "../today/time";
import { BeforeActing, Breadcrumbs, CopyLink, Layer, Metric, centsOf, money, signOf } from "./parts";

const VALIDITY_NOTE: Record<Signal["validity"], string | null> = {
  VALID: null,
  EXPIRED: "Expired: the quote behind this signal is older than its freshness limit. Refresh data before using any number here.",
  INVALIDATED_RULES_CHANGED: "Invalidated: Kalshi changed this market's rules after the signal was made. Re-map and re-evaluate before using it.",
};

const pct = (p: number | null | undefined) => (p == null ? "—" : `${(p * 100).toFixed(1)}%`);

/** A model signal: model probability vs the live quote, after fees and slippage. */
export function SignalResearch({ s }: { s: Signal }) {
  const now = useNow();
  const side = s.side?.toUpperCase() ?? null;
  const pSide = s.p_yes == null ? null : side === "NO" ? 1 - s.p_yes : s.p_yes;
  const band = s.p_lower != null && s.p_upper != null
    ? side === "NO" ? [1 - s.p_upper, 1 - s.p_lower] : [s.p_lower, s.p_upper] : null;
  const allIn = [s.entry, s.fee, s.slippage].every((x) => x != null)
    ? (Number(s.entry) + Number(s.fee) + Number(s.slippage)).toFixed(4) : null;
  const stale = VALIDITY_NOTE[s.validity];
  const decision = s.decision === "ABSTAIN" ? "Abstain" : `Candidate: buy ${side ?? "?"}`;
  return (
    <article className="research" aria-labelledby="rs-title">
      <Breadcrumbs trail={[{ label: "Model signal" }, { label: s.market_title }]} />
      <header className="rs-head">
        <div>
          <h2 id="rs-title">{s.market_title}</h2>
          <p className="rs-meta">
            <StatusLabel tone={s.decision === "ABSTAIN" ? "neutral" : "paper"}>{decision}</StatusLabel>{" "}
            <StatusLabel tone={s.validity === "VALID" ? "ok" : "stale"}>{s.validity.replace(/_/g, " ")}</StatusLabel>{" "}
            <span className="small muted">
              quote {s.quote_observed_at
                ? <time dateTime={s.quote_observed_at} title={exact(s.quote_observed_at)}>{rel(s.quote_observed_at, now)}</time> : "—"}
              {" · "}signal expires <time dateTime={s.expires_at} title={exact(s.expires_at)}>{rel(s.expires_at, now)}</time>
            </span>
          </p>
        </div>
        <CopyLink />
      </header>
      {stale && <p className="rs-stale" role="status">{stale}</p>}

      <Layer n={1} id="rs-l1" title="Decision summary">
        {s.decision === "ABSTAIN" ? (
          <div className="rs-abstain">
            <p>The model <b>abstained</b>: it found no side worth pricing, so there is nothing to buy here.</p>
            {s.reasons.length > 0 && <p className="small muted">Why: {s.reasons.map((r) => r.replace(/_/g, " ").toLowerCase()).join("; ")}.</p>}
          </div>
        ) : (
        <div className="metrics">
          <Metric label={`Model chance of ${side ?? "YES"}`} value={pct(pSide)}
            sub={band ? `band ${pct(band[0])}–${pct(band[1])} · ${s.model ?? "model"}` : s.model ?? undefined} />
          <Metric label="Market: all-in cost per contract" value={centsOf(allIn)}
            sub={`entry ${centsOf(s.entry)} + fee ${centsOf(s.fee)} + slippage ${centsOf(s.slippage)}`} />
          <Metric label="Expected value per contract" value={centsOf(s.ev)} sign={signOf(s.ev)} />
          <Metric label="Conservative edge (lower band)" value={centsOf(s.lower_edge)} sign={signOf(s.lower_edge)}
            sub={`downside: lose ${centsOf(allIn)} a contract if wrong`} />
        </div>
        )}
        <BeforeActing title="Where the model may be wrong" items={[
          ...s.caveats,
          "A model probability is an estimate, not a profit. The band shows its uncertainty.",
        ]} />
      </Layer>

      <Layer n={2} id="rs-l2" title="Evidence and assumptions" open>
        {s.reasons.length > 0 && <ul className="small">{s.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
        <ul className="rs-assume small">
          <li>EV = model chance − entry − fee − slippage, per contract, for {s.quantity ?? "?"} contracts.</li>
          <li>Entry is the volume-weighted price of the asks you'd take, from the quote above.</li>
          <li>Fees use Kalshi's schedule <code>{s.fee_schedule_version ?? "unknown"}</code>.</li>
          <li>Mapping to an economic series: {s.mapping_status ?? "none"}{s.contract_key && <> (<code>{s.contract_key}</code>)</>}.</li>
          {s.rules_source_url && (
            <li><a href={s.rules_source_url} target="_blank" rel="noopener noreferrer">Kalshi's rules for this market</a></li>
          )}
        </ul>
        {(["yes", "no"] as const).map((k) => {
          const d = s.details[k];
          if (!d) return null;
          return (
            <p key={k} className="small">
              <b>{k.toUpperCase()} side:</b> entry {centsOf(d.entry)}, fee {centsOf(d.fee)}, slippage {centsOf(d.slippage)},
              EV {centsOf(d.ev)}, conservative edge {centsOf(d.lower_edge)} (stressed {centsOf(d.lower_edge_stressed)}).
            </p>
          );
        })}
      </Layer>

      <Layer n={3} id="rs-l3" title="Audit details">
        <dl className="quote-grid small">
          <dt>Signal id</dt><dd><code>{s.id}</code></dd>
          <dt>Market</dt><dd><code>{s.market_ticker}</code></dd>
          <dt>Quote id</dt><dd><code>{s.quote_id ?? "—"}</code></dd>
          <dt>Model run</dt><dd><code>{s.model_run_id ?? "—"}</code></dd>
          <dt>Mapping id</dt><dd><code>{s.mapping_id ?? "—"}</code></dd>
          <dt>Fee schedule</dt><dd><code>{s.fee_schedule_version ?? "—"}</code></dd>
          <dt>Created</dt><dd>{exact(s.created_at)}</dd>
          <dt>Stake shown</dt><dd>{money(s.quantity && s.entry ? String(Number(s.quantity) * Number(s.entry)) : null)}</dd>
        </dl>
        <LineageView signalId={s.id} />
      </Layer>

      <p className="rs-links small">
        {s.market_event_ticker && <><a href={href.research("event", s.market_event_ticker)}>Research the whole event</a>{" · "}</>}
        <a href={href.tools("signals")}>Open in signals</a>
      </p>
    </article>
  );
}
