import { useEffect, useState } from "react";

import { api } from "../../api/client";
import type { ComboLeg, HistoryWarning, HistoryWarnings } from "../../api/types";
import { href } from "../../router";

const LEVEL: Record<HistoryWarning["level"], string> = { high: "warn-high", medium: "warn-med", info: "warn-info" };

/** Warnings that a leg on the docket repeats a past mistake: the same bet on the same player
 * lost before (with what he actually did), a player who keeps sinking you, a leg type that
 * loses more often than your others, and lessons you or the local model saved. Local data. */
export function PastMistakes({ legs }: { legs: ComboLeg[] }) {
  const key = legs.map((l) => `${l.ticker}:${l.side}`).join(",");
  const [res, setRes] = useState<{ key: string; data: HistoryWarnings | null } | null>(null);

  useEffect(() => {
    if (!key) { setRes(null); return; }
    let cancel = false;
    const t = setTimeout(() => {
      api.historyWarnings(legs).then((d) => { if (!cancel) setRes({ key, data: d }); },
        () => { if (!cancel) setRes({ key, data: null }); });
    }, 300);
    return () => { cancel = true; clearTimeout(t); };
  }, [key]); // legs are captured through `key`

  const cur = res?.key === key ? res.data : null;
  if (!cur || cur.history_legs === 0) return null;
  const flagged = legs.map((l) => ({ l, ws: cur.legs[`${l.ticker}:${l.side}`] ?? [] })).filter((x) => x.ws.length > 0);
  const high = flagged.some((x) => x.ws.some((w) => w.level === "high"));
  return (
    <section className={`dk-section past-mistakes${high ? " has-high" : ""}`} aria-labelledby="dk-past">
      <h3 id="dk-past">{flagged.length ? `Your past mistakes (${flagged.length} leg${flagged.length === 1 ? "" : "s"})` : "Your past mistakes"}</h3>
      {flagged.length === 0 ? (
        <p className="small muted">Nothing in your {cur.history_legs} past legs flags these.</p>
      ) : (
        <ul className="pm-legs">
          {flagged.map(({ l, ws }) => (
            <li key={l.ticker}>
              <b className="small">{l.side.toUpperCase()} · {l.label}</b>
              <ul className="pm-list">
                {ws.map((w) => <li key={w.text} className={`small ${LEVEL[w.level]}`}>{w.text}</li>)}
              </ul>
            </li>
          ))}
        </ul>
      )}
      {cur.general_lessons.length > 0 && (
        <details className="small">
          <summary>Your general lessons ({cur.general_lessons.length})</summary>
          <ul className="pm-list">{cur.general_lessons.map((g) => <li key={g.id}>{g.text}</li>)}</ul>
        </details>
      )}
      <p className="fine muted">From your synced combos and lessons. <a href={href.journal()}>Daily review</a></p>
    </section>
  );
}
