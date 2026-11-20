import { useEffect, useState } from "react";

import { api } from "../../api/client";
import type { HistorySimilar, Side, SimilarGroup } from "../../api/types";
import { href } from "../../router";
import { Term } from "../Term";

const TONE: Record<SimilarGroup["verdict"], string> = {
  none: "muted", too_few: "muted", noise: "", record: "", better: "hist-better", worse: "hist-worse",
};

/** How trades like these went for you, from your synced Kalshi history (local data only).
 * Under the sample threshold it shows counts only and says so; it never reads a streak as a
 * pattern (the backend applies one rule everywhere: app/history/similar.py). */
export function FromHistory({ legs, series, as = "details" }: {
  legs?: { ticker: string; side: Side }[]; series?: string[]; as?: "details" | "section" }) {
  const key = `${(legs ?? []).map((l) => `${l.ticker}:${l.side}`).join(",")}|${(series ?? []).join(",")}`;
  const [res, setRes] = useState<{ key: string; data: HistorySimilar | null } | null>(null);

  useEffect(() => {
    if (key === "|") { setRes(null); return; }
    let cancel = false;
    const t = setTimeout(() => {
      api.historySimilar({ legs, series }).then((d) => { if (!cancel) setRes({ key, data: d }); },
        () => { if (!cancel) setRes({ key, data: null }); });
    }, 300);
    return () => { cancel = true; clearTimeout(t); };
    // legs/series are captured through `key`
  }, [key]); // legs/series are captured through `key`

  const cur = res?.key === key ? res.data : undefined; // undefined = loading for these legs
  const groups = cur?.groups ?? [];
  const total = groups.filter((g) => g.kind === "series").reduce((n, g) => n + g.n, 0);
  const body = (
    <>
      {cur === undefined ? <span className="shimmer wide" aria-hidden="true" />
        : cur === null ? <p className="small muted">Your history isn't available (sync it on the Journal).</p>
        : groups.length === 0 ? <p className="small muted">Nothing comparable in your history.</p>
        : (
          <ul className="hist-groups">
            {groups.map((g) => (
              <li key={`${g.kind}:${g.key}`} className={TONE[g.verdict]}>
                <span className="hist-label">{g.label}</span>
                <span className="small">{g.text}</span>
              </li>
            ))}
          </ul>
        )}
      <p className="fine muted">
        Records under {cur?.min_sample ?? 10} closed trades show counts only (<Term id="sample-size">sample size</Term>).
        {" "}<a href={href.journal()}>Open the journal</a>
      </p>
    </>
  );
  if (as === "section") return <div className="hist">{body}</div>;
  return (
    <details className="dk-section hist">
      <summary><h3>From your history</h3>{cur && <span className="small muted">{total} similar closed</span>}</summary>
      {body}
    </details>
  );
}
