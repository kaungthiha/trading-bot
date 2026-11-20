import type { ComboLeg, ComboResult, EvidenceResult, LegEvidence } from "../../api/types";
import { pct } from "../games/format";
import { exact, rel } from "../today/time";
import { Term } from "../Term";

/** Plain-language side: YES = "this happens", NO = "this does not happen". */
export function phrase(l: ComboLeg): string {
  return l.side === "yes" ? l.label : `Not: ${l.label}`;
}

const evKey = (l: { ticker: string; side: string }) => `${l.ticker}:${l.side}`;

/** What has to happen for the slip to pay. Always visible: it is the bet. */
export function MustHappen({ legs }: { legs: ComboLeg[] }) {
  return (
    <section className="dk-section" aria-labelledby="dk-must">
      <h3 id="dk-must">What would have to happen</h3>
      <ol className="dk-must">
        {legs.map((l) => (
          <li key={l.ticker}>
            <span className={`dk-side ${l.side}`}>{l.side === "yes" ? "Happens" : "Doesn't happen"}</span>{" "}
            {l.label}
          </li>
        ))}
      </ol>
      <p className="small muted">
        {legs.length === 1 ? "If it does, each contract pays $1."
          : <>All {legs.length} must go your way for the <Term id="combo">combo</Term> to pay $1 per contract; one miss loses it all.</>}
      </p>
    </section>
  );
}

/** Everything that could make the numbers wrong. Never collapsed (material risks stay visible). */
export function risks(legs: ComboLeg[], combo: ComboResult | null, ev: EvidenceResult | null): string[] {
  const out: string[] = [];
  const by = new Map((ev?.legs ?? []).map((e) => [evKey(e), e]));
  for (const l of legs) {
    const e = by.get(evKey(l));
    if (!e) continue;
    if (e.injury) out.push(`${e.injury.player}: ${e.injury.status}. ${e.injury.detail}`.trim());
    if (!e.supported) out.push(`${l.label}: no box-score check${e.reason ? ` (${e.reason})` : ""}.`);
    else if (e.verdict === "thin") out.push(`${l.label}: fewer than 8 games on record, so history says little.`);
  }
  for (const c of ev?.correlation ?? []) {
    if (c.lift != null && Math.abs(c.lift - 1) >= 0.05) {
      out.push(`${c.team} legs are linked (same game): they landed together ${c.together}/${c.games} times, ` +
        `×${c.lift.toFixed(2)} vs independent, so the plain fair price is off.`);
    }
  }
  if (legs.length >= 2 && combo?.kalshi && !combo.kalshi.eligible) {
    out.push("Kalshi can't combine these legs into one combo; you'd have to buy them separately.");
  }
  for (const w of combo?.warnings ?? []) out.push(w);
  if ((ev?.legs ?? []).some((e) => e.supported)) {
    out.push("Box-score history ignores tonight's matchup, minutes and role changes.");
  }
  return [...new Set(out)];
}

export function WhereWrong({ items, loading }: { items: string[]; loading: boolean }) {
  return (
    <section className="dk-section dk-risks" aria-labelledby="dk-risks">
      <h3 id="dk-risks">Where this may be wrong</h3>
      {loading && items.length === 0 ? <span className="shimmer wide" aria-hidden="true" />
        : items.length === 0 ? <p className="small muted">Nothing flagged. That's not the same as safe.</p>
        : <ul className="reasons">{items.map((r) => <li key={r} className="warn">{r}</li>)}</ul>}
    </section>
  );
}

/** Market-implied numbers, with their source time. */
export function PriceImplies({ legs, combo, adjusted, scanAt, now }: {
  legs: ComboLeg[]; combo: ComboResult | null; adjusted: number | null;
  scanAt: string | null | undefined; now: number }) {
  const prob = (t: string) => combo?.legs.find((x) => x.ticker === t)?.probability;
  return (
    <details className="dk-section" open>
      <summary><h3>What the price implies</h3></summary>
      <ul className="dk-rows">
        {legs.map((l) => (
          <li key={l.ticker}><span>{phrase(l)}</span><span>{combo ? pct(prob(l.ticker)) : "…"}</span></li>
        ))}
      </ul>
      {legs.length >= 2 && combo?.fair_price != null && (
        <p className="small">
          <b>{(combo.fair_price * 100).toFixed(1)}¢</b> fair if the legs were unrelated
          (market prices multiplied).
          {adjusted != null && Math.abs(adjusted - combo.fair_price) >= 0.005 && (
            <> <b>{(adjusted * 100).toFixed(1)}¢</b> after adjusting for how often these legs landed together.</>
          )}
        </p>
      )}
      <p className="fine muted">
        <Term id="implied-probability">Market-implied</Term> = what Kalshi's mid price says.{" "}
        {scanAt ? <>Prices from the scan <time dateTime={scanAt} title={exact(scanAt)}>{rel(scanAt, now)}</time>.</>
          : scanAt === null ? "Prices have never been scanned." : null}
      </p>
    </details>
  );
}

function evidenceLine(e: LegEvidence): string {
  const w = e.windows;
  const parts: string[] = [];
  if (w) parts.push(`last 10: ${w.last10[0]}/${w.last10[1]}`, `season: ${w.season[0]}/${w.season[1]}`);
  if (e.estimate != null) {
    parts.push(`history estimate ${pct(e.estimate)}${e.interval ? ` (range ${pct(e.interval[0])}–${pct(e.interval[1])})` : ""}`);
  }
  return parts.join(" · ");
}

/** Box-score evidence, labelled as frequency (not a calibrated probability). */
export function MyEvidence({ legs, ev, loading, error }: {
  legs: ComboLeg[]; ev: EvidenceResult | null; loading: boolean; error: string | null }) {
  const by = new Map((ev?.legs ?? []).map((e) => [evKey(e), e]));
  return (
    <details className="dk-section" open>
      <summary><h3>My evidence</h3></summary>
      {error && <p role="alert" className="small">{error}</p>}
      <ul className="dk-rows dk-evidence">
        {legs.map((l) => {
          const e = by.get(evKey(l));
          return (
            <li key={l.ticker}>
              <span>{phrase(l)}</span>
              <span className="small muted">
                {loading && !e ? <span className="shimmer" aria-hidden="true" />
                  : !e ? "—" : !e.supported ? (e.reason ?? "No check for this market") : evidenceLine(e)}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="fine muted">
        How often this happened in past games: a frequency from a small sample, not a calibrated
        probability.
      </p>
    </details>
  );
}
