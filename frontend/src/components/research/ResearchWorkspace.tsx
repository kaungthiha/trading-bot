import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { OpportunityCard, Signal } from "../../api/types";
import type { ResearchKind } from "../../router";
import { href } from "../../router";
import { EmptyState } from "../Hairline";
import { useDataRefresh } from "../useDataRefresh";
import { EventResearch } from "./EventResearch";
import { OppResearch } from "./OppResearch";
import "./research.css";
import { SignalResearch } from "./SignalResearch";

type Load = { state: "loading" } | { state: "missing" } | { state: "error"; message: string }
  | { state: "opp"; card: OpportunityCard } | { state: "sig"; s: Signal };

/** Deep-linkable research page: #/research/(opp|sig|event)/<id>. Reloading the link
 * re-fetches everything (nothing about the page is kept in the URL except the id). */
export function ResearchWorkspace({ kind, id }: { kind: ResearchKind; id: string }) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [tick, setTick] = useState(0);
  useDataRefresh(useCallback(() => setTick((t) => t + 1), []));

  useEffect(() => {
    if (kind === "event") return;
    let cancel = false;
    setLoad((l) => (l.state === "loading" ? l : { state: "loading" }));
    const p = kind === "opp" ? api.opportunity(id).then((card) => ({ state: "opp", card }) as const)
      : api.signal(id).then((s) => ({ state: "sig", s }) as const);
    p.then((v) => { if (!cancel) setLoad(v); }, (e) => {
      if (cancel) return;
      if (e instanceof ApiError && e.status === 404) setLoad({ state: "missing" });
      else setLoad({ state: "error", message: e instanceof ApiError ? e.message : "Backend unreachable" });
    });
    return () => { cancel = true; };
  }, [kind, id, tick]);

  if (kind === "event") return <EventResearch ticker={id} />;
  if (load.state === "loading") return <div className="research"><p className="ideas-loading">Loading research…</p></div>;
  if (load.state === "missing") {
    return (
      <div className="research">
        <h2 className="visually-hidden">Not found</h2>
        <EmptyState figure="loupe" title="Not found">
          This {kind === "opp" ? "scanner idea" : "signal"} no longer exists (it may have been cleared).{" "}
          <a href={href.today()}>Back to Today</a>
        </EmptyState>
      </div>
    );
  }
  if (load.state === "error") {
    return (
      <div className="research" role="alert">
        <h2>Couldn't load this page</h2>
        <p className="small">{load.message}</p>
        <button type="button" className="ghost-button" onClick={() => setTick((t) => t + 1)}>Retry</button>
      </div>
    );
  }
  return load.state === "opp" ? <OppResearch card={load.card} /> : <SignalResearch s={load.s} />;
}
