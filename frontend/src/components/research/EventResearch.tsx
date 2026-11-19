import { type ReactNode, useEffect, useState } from "react";

import { api } from "../../api/client";
import type { ComboLeg, OpenPosition, OpportunityCard, Signal } from "../../api/types";
import { href } from "../../router";
import { docketTitle, useSaved } from "../docket/saved";
import { slip, useSlip } from "../games/slip";
import { EventView } from "../markets/EventView";
import { useNow } from "../shell/Topbar";
import { rel } from "../today/time";
import { Breadcrumbs, CopyLink, Layer, centsOf, money } from "./parts";

type Load<T> = { state: "loading" } | { state: "ok"; data: T } | { state: "error" };

function useLoad<T>(f: () => Promise<T>, deps: unknown[]): Load<T> {
  const [l, setL] = useState<Load<T>>({ state: "loading" });
  useEffect(() => {
    let cancel = false;
    setL({ state: "loading" });
    f().then((data) => { if (!cancel) setL({ state: "ok", data }); }, () => { if (!cancel) setL({ state: "error" }); });
    return () => { cancel = true; };
  }, deps);
  return l;
}

/** One event, everything about it in one place: your positions, scanner ideas, model
 * signals and saved research for it, then the event's markets (the same view as Explore). */
export function EventResearch({ ticker }: { ticker: string }) {
  const now = useNow();
  const legs = useSlip();
  const savedAll = useSaved();
  const opps = useLoad<OpportunityCard[]>(() => api.opportunities().then((x) => x.filter((c) => c.event_ticker === ticker)), [ticker]);
  const sigs = useLoad<Signal[]>(() => api.signals().then((x) => x.filter((s) => s.market_event_ticker === ticker)), [ticker]);
  const pos = useLoad<OpenPosition[]>(() => api.historyOpen().then((a) => a.positions.filter((p) => p.event_ticker === ticker)), [ticker]);
  const savedHere = savedAll.filter((d) => d.legs.some((l) => l.event === ticker));
  const onAddLeg = (leg: ComboLeg) => slip.add(leg);

  const block = <T,>(title: string, l: Load<T[]>, render: (x: T) => ReactNode, empty: string) => (
    <div className="rs-related-group">
      <h4>{title}</h4>
      {l.state === "loading" ? <span className="shimmer wide" aria-hidden="true" />
        : l.state === "error" ? <p className="small muted">Unavailable right now.</p>
        : l.data.length === 0 ? <p className="small muted">{empty}</p>
        : <ul>{l.data.map(render)}</ul>}
    </div>
  );

  return (
    <article className="research" aria-labelledby="rs-title">
      <Breadcrumbs trail={[{ label: "Event", href: href.market(ticker) }, { label: ticker }]} />
      <header className="rs-head">
        <div>
          <h2 id="rs-title">Event research</h2>
          <p className="rs-meta small muted"><code>{ticker}</code> · everything the app knows about this event, in one place</p>
        </div>
        <CopyLink />
      </header>

      <Layer n={1} id="rs-l1" title="What you already have here">
        <div className="rs-related">
          {block<OpenPosition>("Your open positions", pos, (p) => (
            <li key={p.ticker}>
              <span className={`side-chip${p.side === "no" ? " no" : ""}`}>{p.side.toUpperCase()}</span> {p.title}{" "}
              <span className="small muted">{p.contracts} @ {centsOf(p.avg_cost, 0)} → {centsOf(p.mid, 0)} · {money(p.unrealized)}</span>
            </li>), "No open positions in this event.")}
          {block<OpportunityCard>("Scanner ideas", opps, (c) => (
            <li key={c.id}>
              <a href={href.research("opp", c.id)}>{c.title}</a>{" "}
              <span className="small muted">{c.status} · {money(c.profit)} if rules hold · detected {rel(c.detected_at, now)}</span>
            </li>), "No scanner ideas for this event.")}
          {block<Signal>("Model signals", sigs, (s) => (
            <li key={s.id}>
              <a href={href.research("sig", s.id)}>{s.market_title}</a>{" "}
              <span className="small muted">{s.validity} · conservative edge {centsOf(s.lower_edge)}</span>
            </li>), "No model signals for this event.")}
          <div className="rs-related-group">
            <h4>Saved research</h4>
            {savedHere.length === 0 ? <p className="small muted">Nothing saved for this event.</p> : (
              <ul>{savedHere.map((d) => (
                <li key={d.id}>{docketTitle(d.legs)}{" "}
                  <span className="small muted">{d.decision === "watch" ? "watching" : "passed"} · saved {rel(d.at, now)}</span>{" "}
                  <button type="button" className="link-button small" onClick={() => slip.replace(d.legs)}>Load into docket</button>
                </li>))}</ul>
            )}
          </div>
        </div>
      </Layer>

      <Layer n={2} id="rs-l2" title="Markets, prices and rules" open>
        <EventView ticker={ticker} legs={legs} onAddLeg={onAddLeg}
          onBack={() => { window.location.hash = href.market(); }} />
      </Layer>
    </article>
  );
}
