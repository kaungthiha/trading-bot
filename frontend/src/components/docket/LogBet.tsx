import { useState } from "react";

import { api, ApiError } from "../../api/client";
import type { ComboLeg, JournalStatus } from "../../api/types";
import { href } from "../../router";

export const NOTE_MAX = 500;

/** Put this docket in your bet queue (to place later) or log it as placed: the price you'll
 * pay, the stake, and your reason. Stored in the local database; once your Kalshi history
 * syncs, the entry links to the market you actually bought. Never places an order. */
export function LogBet({ legs, fair, quoteCents }: { legs: ComboLeg[]; fair: number | null; quoteCents?: string }) {
  const [price, setPrice] = useState("");
  const [stake, setStake] = useState("");
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const priceNow = price || quoteCents || "";
  const p = Number(priceNow);
  const s = Number(stake);
  const badPrice = priceNow !== "" && !(p > 0 && p < 100);
  const badStake = stake !== "" && !(s > 0 && s <= 1000);

  const log = (status: JournalStatus) => {
    setBusy(true);
    setMsg(null);
    api.addBet({
      legs, status, source: "docket", note,
      market_price: fair != null ? fair.toFixed(4) : null,
      my_price: priceNow && !badPrice ? (p / 100).toFixed(4) : null,
      stake: stake && !badStake ? s.toFixed(2) : null,
    }).then(() => {
      setMsg(status === "placed" ? "Logged as placed. It links to your Kalshi fill after the next sync."
        : "Queued. Find it under My trades → Bet queue.");
      setNote("");
    }, (e) => setMsg(e instanceof ApiError ? e.message : "Couldn't save")).finally(() => setBusy(false));
  };
  return (
    <section className="dk-section dk-log" aria-labelledby="dk-log">
      <h3 id="dk-log">Log this bet</h3>
      <div className="dk-log-row">
        <label className="small">Price you'll pay (¢)
          <input inputMode="decimal" value={priceNow} onChange={(e) => setPrice(e.target.value)}
            aria-invalid={badPrice} placeholder={fair != null ? (fair * 100).toFixed(1) : "e.g. 14"} />
        </label>
        <label className="small">Stake ($)
          <input inputMode="decimal" value={stake} onChange={(e) => setStake(e.target.value)}
            aria-invalid={badStake} placeholder="e.g. 1.50" />
        </label>
      </div>
      <label className="small" htmlFor="dk-log-note">Why this bet</label>
      <textarea id="dk-log-note" rows={2} maxLength={NOTE_MAX} value={note} onChange={(e) => setNote(e.target.value)}
        placeholder="e.g. Duren's rebounds vs a small Orlando front line; Cade under because he's cold" />
      <div className="dk-save-actions">
        <button type="button" className="ghost-button" disabled={busy || badPrice || badStake} onClick={() => log("queued")}>Add to bet queue</button>
        <button type="button" className="ghost-button" disabled={busy || badPrice || badStake} onClick={() => log("placed")}>I placed it</button>
        <span role="status" className="small muted">{msg}</span>
      </div>
      <p className="fine muted">Saved in the local database for your daily review. <a href={href.journal()}>My trades</a></p>
    </section>
  );
}
