import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "../../api/client";
import type {
  CatalogCategory,
  CatalogEventList,
  CatalogSeries,
  CatalogSort,
  CatalogStatus,
  ComboLeg,
} from "../../api/types";
import { ControlBar } from "../ControlBar";
import { ErrorBoundary } from "../ErrorBoundary";
import { PageHead } from "../Hairline";
import { formatUtc } from "../format";
import { slip, useSlip } from "../games/slip";
import { useDataRefresh } from "../useDataRefresh";
import { ComboStudyPanel } from "./ComboStudyPanel";
import { ComboTray } from "./ComboTray";
import { EventView } from "./EventView";

const SORTS: { v: CatalogSort; label: string }[] = [
  { v: "volume_24h", label: "Most traded (24h)" },
  { v: "open_interest", label: "Open interest" },
  { v: "closing", label: "Closing soonest" },
];

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

interface Props {
  eventTicker: string | null;
  onOpenEvent: (ticker: string | null) => void;
}

/** Every open Kalshi market from the last scan: browse, search, analyze, build combos. */
export function MarketsPage({ eventTicker, onOpenEvent }: Props) {
  const [status, setStatus] = useState<CatalogStatus | null>(null);
  const [cats, setCats] = useState<CatalogCategory[]>([]);
  const [category, setCategory] = useState<string | undefined>();
  const [seriesQ, setSeriesQ] = useState("");
  const [series, setSeries] = useState<CatalogSeries[]>([]);
  const [seriesSel, setSeriesSel] = useState<string | undefined>();
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<CatalogSort>("volume_24h");
  const [offset, setOffset] = useState(0);
  const [events, setEvents] = useState<CatalogEventList | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const legs = useSlip();
  const [tick, setTick] = useState(0);
  const dq = useDebounced(q);
  const dSeriesQ = useDebounced(seriesQ);

  useDataRefresh(useCallback(() => setTick((t) => t + 1), []));

  useEffect(() => {
    api.catalogStatus().then(setStatus, () => setStatus(null));
    api.catalogCategories().then((r) => setCats(r.items), () => setCats([]));
  }, [tick]);

  useEffect(() => {
    api.catalogSeries(category, dSeriesQ || undefined).then((r) => setSeries(r.items), () => setSeries([]));
  }, [category, dSeriesQ, tick]);

  useEffect(() => { setOffset(0); }, [category, seriesSel, dq, sort]);

  useEffect(() => {
    let cancelled = false;
    api.catalogEvents({ category, series: seriesSel, q: dq || undefined, sort, offset }).then(
      (r) => { if (!cancelled) { setEvents(r); setErr(null); } },
      (e) => { if (!cancelled) setErr(e instanceof ApiError ? e.message : "Backend unreachable"); });
    return () => { cancelled = true; };
  }, [category, seriesSel, dq, sort, offset, tick]);

  const addLeg = (leg: ComboLeg) => slip.add(leg);

  const empty = status != null && status.events === 0;
  return (
    <div className="markets-page">
      <PageHead figure="cabinet" title="Markets" actions={<ControlBar compact />}>
        Every open Kalshi market from the last scan, with implied odds and ladders.
      </PageHead>
      <p className="small muted">
        {status && !empty
          ? <>{status.events.toLocaleString()} open events · {status.markets.toLocaleString()} markets ·
            prices as of the last scan, {formatUtc(status.refreshed_at)}. "Scan now" refreshes everything.</>
          : null}
      </p>
      {empty && <p className="warning-box">No catalog yet. Click <strong>Scan now</strong> above; it takes about a
        minute and loads every open Kalshi market.</p>}
      <div className="markets-layout">
        <nav className="markets-nav" aria-label="Categories and series">
          <h3>Categories</h3>
          <ul className="pick-list">
            <li><button type="button" aria-pressed={!category}
              onClick={() => { setCategory(undefined); setSeriesSel(undefined); }}>All</button></li>
            {cats.map((c) => (
              <li key={c.name}>
                <button type="button" aria-pressed={category === c.name}
                  onClick={() => { setCategory(c.name); setSeriesSel(undefined); onOpenEvent(null); }}>
                  {c.name} <span className="muted small">{c.events.toLocaleString()}</span>
                </button>
              </li>
            ))}
          </ul>
          <h3>Series</h3>
          <input type="search" aria-label="Find a series" placeholder="e.g. NBA, CPI, Bitcoin"
            value={seriesQ} maxLength={100} onChange={(e) => setSeriesQ(e.target.value)} />
          <ul className="pick-list series-list">
            {seriesSel && <li><button type="button" onClick={() => setSeriesSel(undefined)}>× clear series</button></li>}
            {series.map((s) => (
              <li key={s.ticker}>
                <button type="button" aria-pressed={seriesSel === s.ticker} title={s.ticker}
                  onClick={() => { setSeriesSel(s.ticker); onOpenEvent(null); }}>
                  {s.title} <span className="muted small">{s.events}</span>
                </button>
              </li>
            ))}
          </ul>
        </nav>
        <div className="markets-main">
          <ErrorBoundary resetKey={eventTicker ?? ""}>
            {!eventTicker && <ComboStudyPanel />}
            {eventTicker ? (
              <EventView ticker={eventTicker} legs={legs} onAddLeg={addLeg} onBack={() => onOpenEvent(null)} />
            ) : (
              <>
                <form className="filters" role="search" onSubmit={(e) => e.preventDefault()}>
                  <label>Search events
                    <input type="search" value={q} maxLength={100} placeholder="team, player, topic, ticker"
                      onChange={(e) => setQ(e.target.value)} />
                  </label>
                  <label>Sort
                    <select value={sort} onChange={(e) => setSort(e.target.value as CatalogSort)}>
                      {SORTS.map((s) => <option key={s.v} value={s.v}>{s.label}</option>)}
                    </select>
                  </label>
                </form>
                {err && <p role="alert">{err}</p>}
                {events && (
                  <>
                    <p className="small muted">{events.total.toLocaleString()} event(s)</p>
                    <table className="market-table">
                      <thead><tr><th scope="col">Event</th><th scope="col">Markets</th>
                        <th scope="col">24h volume</th><th scope="col">Closes</th></tr></thead>
                      <tbody>
                        {events.items.map((e) => (
                          <tr key={e.event_ticker}>
                            <td>
                              <button type="button" className="link-button" onClick={() => onOpenEvent(e.event_ticker)}>
                                {e.title}
                              </button>
                              <div className="ticker">{e.sub_title && `${e.sub_title} · `}{e.event_ticker}</div>
                            </td>
                            <td>{e.market_count}</td>
                            <td>{e.volume_24h.toLocaleString()}</td>
                            <td>{formatUtc(e.close_at)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="pager small">
                      <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>← Previous</button>
                      <span>{events.total ? `${offset + 1}–${Math.min(offset + 50, events.total)}` : "0"} of {events.total.toLocaleString()}</span>
                      <button type="button" disabled={offset + 50 >= events.total} onClick={() => setOffset(offset + 50)}>Next →</button>
                    </div>
                  </>
                )}
              </>
            )}
          </ErrorBoundary>
          <ComboTray legs={legs} onRemove={(t) => slip.remove(t)} onClear={() => slip.clear()} />
        </div>
      </div>
    </div>
  );
}
