import type { MarketSummary } from "../api/types";
import { Term } from "./Term";
import { formatAge, formatPrice, formatUtc } from "./format";

interface Props {
  markets: MarketSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function MarketList({ markets, selectedId, onSelect }: Props) {
  if (markets.length === 0) return <p>No markets loaded.</p>;
  return (
    <table className="market-table">
      <caption className="visually-hidden">Markets</caption>
      <thead>
        <tr>
          <th scope="col">Market</th>
          <th scope="col">Status</th>
          <th scope="col">Closes</th>
          {/* Explain headers once, not every cell. */}
          <th scope="col">
            YES <Term id="bid">bid</Term>
          </th>
          <th scope="col">
            YES <Term id="ask">ask</Term>
          </th>
          <th scope="col">Quote age</th>
        </tr>
      </thead>
      <tbody>
        {markets.map((m) => (
          <tr key={m.id} aria-selected={m.id === selectedId}>
            <td>
              <button type="button" className="link-button" onClick={() => onSelect(m.id)}>
                {m.title}
              </button>
              <div className="ticker">
                {m.external_ticker} {m.is_mock && <span className="badge mock">MOCK</span>}
              </div>
            </td>
            <td>{m.status}</td>
            <td>{formatUtc(m.close_at)}</td>
            <td>{formatPrice(m.quote?.yes_bid)}</td>
            <td>{formatPrice(m.quote?.yes_ask)}</td>
            <td>
              {m.quote ? (
                <>
                  {formatAge(m.quote.age_seconds)}{" "}
                  {m.quote.is_stale && <span className="badge stale">STALE</span>}
                </>
              ) : (
                "no quote"
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
