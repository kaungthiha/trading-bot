import type { OpportunityCard } from "../../api/types";
import { href } from "../../router";
import { StatusLabel } from "../design/StatusLabel";
import { useNow } from "../shell/Topbar";
import { exact, rel } from "../today/time";
import { BeforeActing, Breadcrumbs, CopyLink, Layer, Metric, centsOf, money, signOf } from "./parts";

const STATUS_NOTE: Record<string, string> = {
  EXPIRED: "This idea has expired: the prices it was built on are old. Re-scan before trusting any number here.",
  EXECUTED: "You recorded this idea as executed.",
  SKIPPED: "You recorded this idea as skipped.",
};

/** A scanner idea: a set of separate buys that together pay if Kalshi's rules hold. */
export function OppResearch({ card }: { card: OpportunityCard }) {
  const now = useNow();
  const open = card.status === "OPEN";
  const before = [
    ...(card.guaranteed ? [] : ["Conditional: the payoff depends on an outcome, not only on the rules. You can lose the full cost."]),
    "The minimum payoff assumes every rule reads the way the scanner read it. If one doesn't, you can lose up to the full cost.",
    ...card.checklist,
  ];
  return (
    <article className="research" aria-labelledby="rs-title">
      <Breadcrumbs trail={[{ label: "Scanner idea" }, { label: card.title }]} />
      <header className="rs-head">
        <div>
          <h2 id="rs-title">{card.title}</h2>
          <p className="rs-meta">
            <StatusLabel tone={card.guaranteed ? "paper" : "warn"}>
              {card.guaranteed ? "Guaranteed if rules hold" : "Conditional"}
            </StatusLabel>{" "}
            <StatusLabel tone={open ? "ok" : "stale"}>{card.status}</StatusLabel>{" "}
            <span className="small muted">
              detected <time dateTime={card.detected_at} title={exact(card.detected_at)}>{rel(card.detected_at, now)}</time>
              {" · "}{open ? "expires" : "expired"} <time dateTime={card.expires_at} title={exact(card.expires_at)}>{rel(card.expires_at, now)}</time>
            </span>
          </p>
        </div>
        <CopyLink />
      </header>
      {!open && <p className="rs-stale" role="status">{STATUS_NOTE[card.status]}</p>}

      <Layer n={1} id="rs-l1" title="Decision summary">
        <div className="metrics">
          <Metric label="Total cost (incl. fees)" value={money(card.cost)} sub={`fees ${money(card.fees)}`} />
          <Metric label="Minimum payoff if rules hold" value={money(card.min_payoff)} />
          <Metric label="Profit if rules hold" value={money(card.profit)} sign={signOf(card.profit)}
            sub={`${card.return_pct}% on cost`} />
          <Metric label="Downside" value={`up to −${money(card.cost).replace("−", "")}`}
            sub="if a rule reads differently" sign="neg" />
        </div>
        <p className="small">{card.claim}</p>
        <BeforeActing items={before} />
      </Layer>

      <Layer n={2} id="rs-l2" title="Evidence and assumptions" open>
        <div className="table-scroll" tabIndex={0} role="region" aria-label="Legs of this idea (scrolls sideways on small screens)">
          <table className="market-table">
            <caption className="visually-hidden">Legs of this idea</caption>
            <thead><tr><th>Buy</th><th>Market</th><th>Limit</th><th>Qty</th><th>Cost</th><th>Fee</th><th>Depth then</th></tr></thead>
            <tbody>
              {card.legs.map((l) => (
                <tr key={`${l.ticker}-${l.side}`}>
                  <td><span className={`side-chip${l.side === "NO" ? " no" : ""}`}>{l.side}</span></td>
                  <td>{l.title}<br /><span className="ticker">{l.ticker}</span></td>
                  <td>{centsOf(l.limit_price, 0)}</td><td>{l.quantity}</td>
                  <td>{money(l.cost)}</td><td>{money(l.fee)}</td><td>{l.available}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="rs-assume small">
          <li>Prices and depth are from the scan at detection ({exact(card.detected_at)}), not live.</li>
          <li>Fees use Kalshi's schedule <code>{card.fee_schedule_version}</code>.</li>
          <li>Each leg is a separate order; this is not a Kalshi combo.</li>
          <li>{card.confirmed ? "Confirmed by a second, fresh look at the book." : "Not re-confirmed against a fresh book."}</li>
        </ul>
      </Layer>

      <Layer n={3} id="rs-l3" title="Audit details">
        <dl className="quote-grid small">
          <dt>Idea id</dt><dd><code>{card.id}</code></dd>
          <dt>Kind</dt><dd>{card.kind}</dd>
          <dt>Event</dt><dd><code>{card.event_ticker}</code></dd>
          <dt>Quantity</dt><dd>{card.quantity}</dd>
          <dt>Budget cap</dt><dd>{card.budget_cap ? money(card.budget_cap) : "none"}</dd>
          <dt>Fee schedule</dt><dd><code>{card.fee_schedule_version}</code></dd>
        </dl>
        {card.journal.length > 0 && (
          <>
            <h4>Your journal</h4>
            <ul className="small">{card.journal.map((j) => (
              <li key={j.at}>{exact(j.at)}: {j.action}{j.note && ` — ${j.note}`}</li>))}</ul>
          </>
        )}
      </Layer>

      <p className="rs-links small">
        <a href={href.research("event", card.event_ticker)}>Research the whole event</a>
        {" · "}<a href={href.tools("scanner")}>Open in the scanner (checklist and journal)</a>
      </p>
    </article>
  );
}
