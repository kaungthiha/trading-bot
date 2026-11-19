import { useEffect, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { BookSnapshot, CatalogMarket, ExpectedValue, Side } from "../../api/types";
import { formatPrice } from "../format";

const pctOf = (p: number | null) => (p == null ? "" : String(Math.round(p * 1000) / 10));

/** "If I think this wins X% of the time, is it worth buying at the current ask?" */
export function EvCalculator({ market }: { market: CatalogMarket }) {
  const [side, setSide] = useState<Side>("yes");
  const [pct, setPct] = useState(pctOf(market.implied));
  const [contracts, setContracts] = useState(10);
  const [price, setPrice] = useState("");
  const [ev, setEv] = useState<ExpectedValue | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [book, setBook] = useState<BookSnapshot | null>(null);
  const [bookErr, setBookErr] = useState<string | null>(null);

  function flip(next: Side) {
    setSide(next);
    if (market.implied != null) setPct(pctOf(next === "yes" ? market.implied : 1 - market.implied));
  }

  useEffect(() => {
    const p = Number(pct);
    if (!(p > 0 && p < 100) || !(contracts >= 1)) {
      setEv(null);
      setErr("Enter a probability between 0 and 100% and at least 1 contract.");
      return;
    }
    const t = setTimeout(() => {
      api.catalogEv(market.ticker, { side, prob: (p / 100).toFixed(4), contracts,
                                     price: price ? Number(price).toFixed(4) : undefined })
        .then((r) => { setEv(r); setErr(null); },
              (e) => { setEv(null); setErr(e instanceof ApiError ? e.message : "Could not compute"); });
    }, 300);
    return () => clearTimeout(t);
  }, [market.ticker, side, pct, contracts, price]);

  function loadBook() {
    setBookErr(null);
    api.catalogBook(market.ticker).then(setBook,
      (e) => setBookErr(e instanceof ApiError ? e.message : "Could not reach Kalshi"));
  }

  const positive = ev && Number(ev.expected_value) > 0;
  return (
    <div className="ev-calc">
      <form className="filters" onSubmit={(e) => e.preventDefault()}>
        <label>
          Buy
          <select value={side} onChange={(e) => flip(e.target.value as Side)}>
            <option value="yes">YES ({market.yes_sub_title || "yes"})</option>
            {/* Kalshi often repeats the YES name in no_sub_title, so phrase it ourselves. */}
            <option value="no">NO (not {market.yes_sub_title || market.title})</option>
          </select>
        </label>
        <label>
          Your chance it wins (%)
          <input type="number" min={0.1} max={99.9} step={0.5} value={pct}
            onChange={(e) => setPct(e.target.value)} />
        </label>
        <label>
          Contracts
          <input type="number" min={1} max={10000} value={contracts}
            onChange={(e) => setContracts(Math.floor(Number(e.target.value)))} />
        </label>
        <label>
          Limit price (optional)
          <input type="number" min={0.01} max={0.99} step={0.01} value={price} placeholder="ask"
            onChange={(e) => setPrice(e.target.value)} />
        </label>
      </form>
      {err && <p className="small" role="alert">{err}</p>}
      {ev && (
        <dl className="quote-grid ev-grid">
          <dt>Pay (incl. fee)</dt>
          <dd>{formatPrice(ev.total_cost)} <span className="muted small">({ev.contracts} × {formatPrice(ev.price)}, fee {formatPrice(ev.fee)}{ev.price_source === "snapshot ask" ? ", at the last scan's ask" : ""})</span></dd>
          <dt>Break-even chance</dt>
          <dd>{(Number(ev.breakeven_probability) * 100).toFixed(1)}%</dd>
          <dt>Expected value</dt>
          <dd className={positive ? "ev-pos" : "ev-neg"}>
            {Number(ev.expected_value) >= 0 ? "+" : "−"}{formatPrice(String(Math.abs(Number(ev.expected_value)).toFixed(2)))}
            {ev.ev_per_dollar && <span className="small"> ({(Number(ev.ev_per_dollar) * 100).toFixed(1)}% of stake)</span>}
          </dd>
          <dt>Sizing</dt>
          <dd className="small">
            {ev.suggested_contracts != null
              ? <>Quarter-Kelly on your ${ev.budget} budget: {formatPrice(ev.quarter_kelly_stake)} (capped at {formatPrice(ev.cap_stake)}) ≈ <strong>{ev.suggested_contracts} contract(s)</strong></>
              : "No edge at this price: Kelly says don't bet."}
          </dd>
        </dl>
      )}
      {ev?.depth_warning && (
        <p className="small warning-box">Only {ev.depth_at_price} contracts were offered at this price when last scanned; more would fill at worse prices.</p>
      )}
      <p className="small muted">
        Expected value is only as good as your probability. The market's own estimate is
        prefilled, and at that estimate fees make almost every bet slightly negative.
      </p>
      <button type="button" className="link-button small" onClick={loadBook}>
        Fetch the current orderbook and full rules from Kalshi
      </button>
      {bookErr && <p className="small" role="alert">{bookErr}</p>}
      {book && <BookView book={book} />}
    </div>
  );
}

function BookView({ book }: { book: BookSnapshot }) {
  const m = book.market;
  return (
    <div className="book-view small">
      <div className="ladders">
        {(["yes_bids", "no_bids"] as const).map((k) => (
          <div className="ladder" key={k}>
            <h4>{k === "yes_bids" ? "YES bids" : "NO bids"}</h4>
            {book[k].length === 0 ? <p className="muted">None</p> : (
              <table><tbody>
                {book[k].map((l) => (
                  <tr key={l.price}><td>{formatPrice(l.price)}</td><td>{Number(l.quantity).toLocaleString()}</td></tr>
                ))}
              </tbody></table>
            )}
          </div>
        ))}
      </div>
      <p className="muted">Buying YES fills against the best NO bid (YES ask = $1 − best NO bid), and vice versa.</p>
      {m.rules_primary && <blockquote className="rules">{m.rules_primary}</blockquote>}
      {m.rules_secondary && <blockquote className="rules">{m.rules_secondary}</blockquote>}
      {m.early_close_condition && <p className="muted">{m.early_close_condition}</p>}
    </div>
  );
}
