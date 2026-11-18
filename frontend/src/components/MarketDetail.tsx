import type { BookLevel, MarketDetail as MarketDetailT } from "../api/types";
import { Term } from "./Term";
import { formatAge, formatPrice, formatUtc } from "./format";

function Ladder({ title, levels }: { title: string; levels: BookLevel[] }) {
  return (
    <div className="ladder">
      <h4>{title}</h4>
      {levels.length === 0 ? (
        <p className="muted">No bids — no counterparty on this side.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th scope="col">Price</th>
              <th scope="col">Qty</th>
            </tr>
          </thead>
          <tbody>
            {levels.map((l) => (
              <tr key={l.price}>
                <td>{formatPrice(l.price)}</td>
                <td>{l.quantity}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function MarketDetail({ market }: { market: MarketDetailT }) {
  const q = market.quote;
  return (
    <article className="market-detail" aria-labelledby="market-title">
      <h2 id="market-title">{market.title}</h2>
      <p className="ticker">
        {market.external_ticker} · event {market.event_ticker} · {market.category}{" "}
        {market.is_mock && <span className="badge mock">MOCK DATA</span>}
      </p>
      <p>
        A <Term id="binary-contract">binary contract</Term> paying {formatPrice(market.notional_value)}{" "}
        per winning contract. Status: <strong>{market.status}</strong>. Closes{" "}
        {formatUtc(market.close_at)}.
      </p>

      <section aria-labelledby="quote-h">
        <h3 id="quote-h">Quote</h3>
        {q ? (
          <>
            <dl className="quote-grid">
              <dt>YES bid</dt>
              <dd>{formatPrice(q.yes_bid)}</dd>
              <dt>YES ask (derived)</dt>
              <dd>{formatPrice(q.yes_ask)}</dd>
              <dt>NO bid</dt>
              <dd>{formatPrice(q.no_bid)}</dd>
              <dt>NO ask (derived)</dt>
              <dd>{formatPrice(q.no_ask)}</dd>
              <dt>
                YES <Term id="spread">spread</Term>
              </dt>
              <dd>{formatPrice(q.spread_yes)}</dd>
              <dt>Observed</dt>
              <dd>
                {formatUtc(q.observed_at)} ({formatAge(q.age_seconds)} ago)
                {q.is_stale && (
                  <span className="badge stale" role="status">
                    STALE (older than {q.max_age_seconds}s)
                  </span>
                )}
              </dd>
            </dl>
            <p className="muted small">
              Asks are derived from the opposite side&apos;s best bid; a missing opposite bid means no
              ask. A displayed quote is a snapshot, not a guaranteed executable price.
            </p>
          </>
        ) : (
          <p>No quote recorded.</p>
        )}
      </section>

      <section aria-labelledby="depth-h">
        <h3 id="depth-h">
          <Term id="orderbook-depth">Orderbook depth</Term>
        </h3>
        <div className="ladders">
          <Ladder title="YES bids" levels={market.yes_bids} />
          <Ladder title="NO bids" levels={market.no_bids} />
        </div>
        <p className="small">
          <Term id="tick-size">Price grid</Term>:{" "}
          {market.price_ranges.map((r) => `${r.start}–${r.end} step ${r.step}`).join("; ")}
        </p>
      </section>

      <section aria-labelledby="rules-h">
        <h3 id="rules-h">
          Official <Term id="resolution">resolution</Term> rules
        </h3>
        {market.rules ? (
          <>
            <blockquote className="rules">{market.rules.text}</blockquote>
            <p className="small muted">
              Rules hash {market.rules.hash.slice(0, 12)}… recorded {formatUtc(market.rules.observed_at)}
              {market.rules.official_source_url && (
                <>
                  {" · "}
                  <a href={market.rules.official_source_url} target="_blank" rel="noopener noreferrer">
                    source
                  </a>
                </>
              )}
            </p>
          </>
        ) : (
          <p role="alert">No rules recorded — do not rely on the title alone.</p>
        )}
      </section>
    </article>
  );
}
