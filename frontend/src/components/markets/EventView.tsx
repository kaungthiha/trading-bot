import { Fragment, useEffect, useMemo, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { CatalogEventDetail, CatalogMarket, ComboLeg, LadderStats, Side } from "../../api/types";
import { formatPrice, formatUtc } from "../format";
import { DistributionChart } from "./DistributionChart";
import { EvCalculator } from "./EvCalculator";
import { Tip } from "../design/Tip";
import { Term } from "../Term";
import { InvestigateButton } from "../investigate/InvestigateButton";

const pct = (p: number | null | undefined, d = 1) => (p == null ? "—" : `${(p * 100).toFixed(d)}%`);
const qty = (s: string | null) => (s == null ? "—" : Math.round(Number(s)).toLocaleString());
const num = (x: number | null) => (x == null ? "beyond listed strikes" : x.toLocaleString());

interface Props {
  ticker: string;
  legs: ComboLeg[];
  onAddLeg: (leg: ComboLeg) => void;
  onBack: () => void;
}

export function EventView({ ticker, legs, onAddLeg, onBack }: Props) {
  const [ev, setEv] = useState<CatalogEventDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    setEv(null); setErr(null); setOpen(null); setFilter("");
    api.catalogEvent(ticker).then(setEv, (e) => setErr(e instanceof ApiError ? e.message : "Could not load"));
  }, [ticker]);

  const rows = useMemo(() => {
    if (!ev) return [];
    const f = filter.trim().toLowerCase();
    return f ? ev.markets.filter((m) => `${m.title} ${m.yes_sub_title} ${m.ticker}`.toLowerCase().includes(f))
      : ev.markets;
  }, [ev, filter]);

  if (err) return <div><button type="button" className="link-button" onClick={onBack}>← All events</button><p role="alert">{err}</p></div>;
  if (!ev) return <p>Loading event…</p>;

  const excl = ev.stats.exclusive;
  const inCombo = (t: string, s: Side) => legs.some((l) => l.ticker === t && l.side === s);
  const add = (m: CatalogMarket, side: Side) =>
    onAddLeg({ ticker: m.ticker, side, label: m.yes_sub_title || m.title, event: ev.event_ticker });

  return (
    <article className="event-view" aria-labelledby="event-title">
      <button type="button" className="link-button" onClick={onBack}>← All events</button>
      <h3 id="event-title">{ev.title}</h3>
      {ev.game && (
        <a className="primary-button game-link" href={`#/games?game=${encodeURIComponent(`${ev.game.prefix}-${ev.game.game_key}`)}`}>
          Whole game: every line and player prop →
        </a>
      )}
      <p className="ticker">
        {ev.sub_title && <>{ev.sub_title} · </>}{ev.series_title} ({ev.series_ticker}) · {ev.category}
        {ev.competition && <> · {ev.competition}</>} · {ev.event_ticker}
      </p>
      <p className="small">
        {ev.market_count} markets · 24h volume {ev.volume_24h.toLocaleString()} · open interest{" "}
        {ev.open_interest.toLocaleString()} · closes {formatUtc(ev.close_at)} ·{" "}
        <span className="muted">prices from the scan at {formatUtc(ev.refreshed_at)}</span>
        {ev.fee.multiplier !== "1" && <> · <strong>fee multiplier {ev.fee.multiplier}×</strong></>}
        {ev.combo_collections?.length > 0 && <> · <Tip text={`Kalshi combo collections: ${ev.combo_collections.join(", ")}`} className="badge paper">combo-eligible on Kalshi</Tip></>}
      </p>

      {excl && (
        <div className="stat-box small">
          <strong>Exactly one outcome wins.</strong> Implied probabilities add up to{" "}
          {pct(excl.sum_implied)}{excl.overround != null && <> (<Term id="overround">overround</Term> {(excl.overround * 100).toFixed(1)} pts)</>}.
          {excl.sum_yes_ask && <> Buying YES on every outcome costs ${excl.sum_yes_ask} per $1 before fees.</>}{" "}
          The "Normalized" column rescales prices to sum to 100%, which only makes sense if the list
          covers every possible result.
        </div>
      )}

      {ev.stats.ladders.map((l) => <LadderView key={l.label} ladder={l} />)}

      <details className="small rules-sample">
        <summary>Resolution rules (first market)</summary>
        <blockquote className="rules">{ev.rules_sample || "No rules text in the snapshot."}</blockquote>
      </details>

      {ev.markets.length > 8 && (
        <label className="small">Filter markets{" "}
          <input type="search" value={filter} placeholder="player, strike, ticker" maxLength={60}
            onChange={(e) => setFilter(e.target.value)} />
        </label>
      )}
      <div className="table-scroll">
        <table className="market-table catalog-markets">
          <thead>
            <tr>
              <th scope="col">Outcome</th><th scope="col">YES bid</th><th scope="col">YES ask</th>
              <th scope="col">NO ask</th><th scope="col">Implied</th>
              {excl && <th scope="col">Normalized</th>}
              <th scope="col">Spread</th><th scope="col">Last</th><th scope="col">24h Δ</th>
              <th scope="col">24h vol</th><th scope="col">Open int.</th><th scope="col">Add / analyze</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => (
              <Fragment key={m.ticker}>
                <tr aria-selected={open === m.ticker}>
                  <td>{m.yes_sub_title || m.title}<div className="ticker">{m.ticker}</div></td>
                  <td>{formatPrice(m.yes_bid)}</td>
                  <td>{formatPrice(m.yes_ask)}</td>
                  <td>{formatPrice(m.no_ask)}</td>
                  <td title={m.implied_quality === "tail" ? "One-sided quote: estimated" : "Mid of bid and ask"}>
                    {pct(m.implied)}{m.implied_quality === "tail" && "*"}
                  </td>
                  {excl && <td>{pct(excl.normalized[m.ticker])}</td>}
                  <td>{m.spread == null ? "—" : `${Math.round(m.spread * 100)}¢`}</td>
                  <td>{formatPrice(m.last_price)}</td>
                  <td className={m.change_24h == null ? "" : Number(m.change_24h) > 0 ? "ev-pos" : Number(m.change_24h) < 0 ? "ev-neg" : ""}>
                    {m.change_24h == null ? "—" : `${Number(m.change_24h) > 0 ? "+" : ""}${Math.round(Number(m.change_24h) * 100)}¢`}
                  </td>
                  <td>{qty(m.volume_24h)}</td>
                  <td>{qty(m.open_interest)}</td>
                  <td className="row-actions">
                    <button type="button" disabled={inCombo(m.ticker, "yes")} onClick={() => add(m, "yes")}
                      aria-label={`Add YES ${m.yes_sub_title || m.title} to combo`}>+YES</button>
                    <button type="button" disabled={inCombo(m.ticker, "no")} onClick={() => add(m, "no")}
                      aria-label={`Add NO ${m.yes_sub_title || m.title} to combo`}>+NO</button>
                    <button type="button" aria-expanded={open === m.ticker}
                      onClick={() => setOpen(open === m.ticker ? null : m.ticker)}>EV</button>
                    <InvestigateButton quiet leg={{ ticker: m.ticker, side: "yes", label: m.yes_sub_title || m.title, event: ev.event_ticker }} />
                  </td>
                </tr>
                {open === m.ticker && (
                  <tr><td colSpan={excl ? 12 : 11}><EvCalculator market={m} /></td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <p className="small muted">* estimated from a one-sided quote in a deep tail. Prices are a
        snapshot from the last scan; fetch the orderbook (EV → bottom) before trading.</p>
    </article>
  );
}

function LadderView({ ladder: l }: { ladder: LadderStats }) {
  const off = l.points.filter((p) => p.off_curve);
  return (
    <section className="ladder-view" aria-label={`Implied distribution: ${l.label}`}>
      <DistributionChart title={l.label} buckets={l.buckets} />
      <p className="small">
        Median <strong>{num(l.median)}</strong> · middle 50%: {num(l.p25)} to {num(l.p75)} · 80%:{" "}
        {num(l.p10)} to {num(l.p90)} ·{" "}
        {l.mean_reliable ? <>mean {l.mean} ± {l.sd}</> : <span className="muted">mean unreliable ({pct(l.tail_mass, 0)} beyond the listed strikes)</span>}
      </p>
      {(off.length > 0 || l.monotonicity_violations > 0) && (
        <div className="warning-box small">
          {l.monotonicity_violations > 0 && (
            <p>{l.monotonicity_violations} strike(s) priced <em>above</em> a lower strike. A higher
              line can't be more likely, so one side of that pair is mispriced, or a quote is stale or thin.</p>
          )}
          {off.length > 0 && (
            <p>Off the smooth curve:{" "}
              {off.map((p) => `${p.label} (${pct(p.implied)} vs ${pct(p.fitted)} fitted)`).join("; ")}.
              {" "}Worth a look; a wide spread often explains it.</p>
          )}
        </div>
      )}
    </section>
  );
}
