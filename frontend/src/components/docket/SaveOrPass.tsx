import { useState } from "react";

import type { ComboLeg } from "../../api/types";
import { slip, useSlip } from "../games/slip";
import { useNow } from "../shell/Topbar";
import { exact, rel } from "../today/time";
import { type Decision, docketTitle, NOTE_MAX, saved, useSaved } from "./saved";

/** Record a decision on this docket: keep watching, or pass, and why. Local only. */
export function SaveOrPass({ legs, fair }: { legs: ComboLeg[]; fair: number | null }) {
  const [note, setNote] = useState("");
  const [done, setDone] = useState<Decision | null>(null);
  const save = (decision: Decision) => {
    if (saved.add({ decision, note, legs, fair })) { setDone(decision); setNote(""); }
  };
  return (
    <section className="dk-section dk-save" aria-labelledby="dk-save">
      <h3 id="dk-save">Save or pass</h3>
      <label className="small" htmlFor="dk-note">Why you'd buy, or why you'd pass</label>
      <textarea id="dk-note" rows={2} maxLength={NOTE_MAX} value={note}
        onChange={(e) => { setNote(e.target.value); setDone(null); }}
        placeholder="e.g. walk away above 16¢; KAT minutes uncertain" />
      <div className="dk-save-actions">
        <button type="button" className="ghost-button" onClick={() => save("watch")}>Save to watch</button>
        <button type="button" className="ghost-button" onClick={() => save("pass")}>Pass</button>
        <span role="status" className="small muted">
          {done === "watch" ? "Saved. It's on Today under Saved research." : done === "pass" ? "Logged as passed." : ""}
        </span>
      </div>
      <p className="fine muted">Saved in this browser only, with the price at the time (not live).</p>
    </section>
  );
}

/** Your saved dockets: reload one into the docket, or delete it. */
export function SavedList({ limit = 5 }: { limit?: number }) {
  const items = useSaved();
  const current = useSlip();
  const now = useNow();
  if (items.length === 0) return null;
  const curKey = current.map((l) => `${l.ticker}:${l.side}`).join(",");
  return (
    <details className="dk-section dk-saved">
      <summary><h3>Saved research ({items.length})</h3></summary>
      <ul className="dk-saved-list">
        {items.slice(0, limit).map((d) => {
          const same = d.legs.map((l) => `${l.ticker}:${l.side}`).join(",") === curKey;
          return (
            <li key={d.id}>
              <span className="dk-saved-title">{docketTitle(d.legs)}</span>
              <span className="small muted">
                <span className={`badge ${d.decision === "watch" ? "paper" : ""}`}>{d.decision === "watch" ? "Watching" : "Passed"}</span>{" "}
                saved <time dateTime={d.at} title={exact(d.at)}>{rel(d.at, now)}</time>
                {d.fair != null && <> · fair {(d.fair * 100).toFixed(1)}¢ then</>}
              </span>
              {d.note && <span className="small dk-saved-note">{d.note}</span>}
              <span className="dk-saved-actions">
                <button type="button" className="link-button small" disabled={same}
                  onClick={() => slip.replace(d.legs)}>
                  {same ? "On the docket" : current.length ? "Replace docket with this" : "Load into docket"}
                </button>
                <button type="button" className="link-button small" aria-label={`Delete saved: ${docketTitle(d.legs)}`}
                  onClick={() => saved.remove(d.id)}>Delete</button>
              </span>
            </li>
          );
        })}
      </ul>
    </details>
  );
}
