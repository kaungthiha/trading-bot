import { useEffect, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { DayBet, DayDetail, DayLeg, DayReview, DaySummary, LegRecord, Lesson, Side } from "../../api/types";
import { EmptyState } from "../Hairline";
import { Tile } from "./OpenPositions";
import "./review.css";

const money = (s: string | null | undefined) => {
  if (s == null) return "—";
  const n = Number(s);
  return `${n < 0 ? "−" : n > 0 ? "+" : ""}$${Math.abs(n).toFixed(2)}`;
};
const tone = (s: string | null | undefined) => (s == null ? "" : Number(s) > 0 ? "ev-pos" : Number(s) < 0 ? "ev-neg" : "");
const cents = (s: string | null) => (s == null ? "—" : `${(Number(s) * 100).toFixed(1)}¢`);
const dayName = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
const STATS = ["PTS", "REB", "AST", "3PT", "PRA", "STL", "BLK", "GAME", "SPREAD", "TOTAL", "TEAMTOTAL"];
const MARK: Record<DayLeg["status"], string> = { won: "✓", lost: "✗", open: "·" };

function Leg({ lg }: { lg: DayLeg }) {
  return (
    <li className={`dr-leg ${lg.status}`}>
      <span aria-label={lg.status} className="dr-mark">{MARK[lg.status]}</span>{" "}
      <span>{lg.side.toUpperCase()} · {lg.title}</span>
      {lg.what_happened && <span className="small muted"> — {lg.what_happened}</span>}
    </li>
  );
}

export function BetCard({ b }: { b: DayBet }) {
  return (
    <li className="dr-bet">
      <details>
        <summary>
          <span className="dr-bet-title">{b.title}</span>
          <span className="small muted">
            {b.avg_price != null && <>paid {cents(b.avg_price)} · </>}
            {b.cost != null && <>cost ${b.cost} · </>}
            {b.max_payout != null && <>pays ${b.max_payout} if it hits · </>}
            {b.status === "open" ? "open" : b.sold_early ? "sold early" : b.status}
          </span>
          <b className={`dr-pnl ${tone(b.pnl)}`}>{b.pnl == null ? "open" : money(b.pnl)}</b>
          {b.sunk_by_one && <span className="badge stale small">lost by one leg</span>}
        </summary>
        {b.journal?.note && <p className="small dr-note"><b>Your reason:</b> {b.journal.note}</p>}
        {b.legs.length > 0 && <ul className="dr-legs small">{b.legs.map((lg) => <Leg key={`${lg.ticker}:${lg.side}`} lg={lg} />)}</ul>}
      </details>
    </li>
  );
}

function Review({ date }: { date: string }) {
  const [r, setR] = useState<DayReview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setR(null); setErr(null); }, [date]);
  const run = () => {
    setBusy(true);
    setErr(null);
    api.dayReview(date).then(setR, (e) => setErr(e instanceof ApiError ? e.message : "Review failed"))
      .finally(() => setBusy(false));
  };
  const news = new Map((r?.news ?? []).map((n) => [n.id, n]));
  return (
    <section className="panel dr-review" aria-labelledby="dr-rev">
      <h3 id="dr-rev" className="kicker">Coach's review of {dayName(date)}</h3>
      {!r && (
        <p className="small">
          <button type="button" className="primary-button" onClick={run} disabled={busy}>
            {busy ? "Reviewing… (about a minute)" : "Review this day with the local model"}
          </button>{" "}
          <span className="muted">Reads every bet and leg, what the players actually did, and recap news for the legs that
            sank you (up to 8 Brave searches). Saves lessons that warn you on future bets.</span>
        </p>
      )}
      {err && <p role="alert" className="small">{err}</p>}
      {r && (
        <>
          <p>{r.summary}</p>
          {r.went_right.length > 0 && <><h4 className="small">What went right</h4><ul className="small">{r.went_right.map((x) => <li key={x}>{x}</li>)}</ul></>}
          {r.went_wrong.length > 0 && (
            <>
              <h4 className="small">What went wrong</h4>
              <ul className="small">
                {r.went_wrong.map((w) => (
                  <li key={w.text}><span className={`badge small ${w.kind === "process" ? "stale" : ""}`}>{w.kind === "process" ? "process" : w.kind === "luck" ? "variance" : "unclear"}</span>{" "}
                    {w.text}{" "}
                    {w.sources.map((id) => news.get(id)).filter((n) => n != null).map((n) => (
                      <a key={n.id} className="cite" href={n.url} target="_blank" rel="noopener noreferrer nofollow" title={n.title}>{n.id}</a>
                    ))}
                  </li>
                ))}
              </ul>
            </>
          )}
          {r.lessons.length > 0 && (
            <>
              <h4 className="small">Lessons {r.lessons_saved > 0 ? `(${r.lessons_saved} saved)` : "(already on file)"}</h4>
              <ul className="small">{r.lessons.map((l) => <li key={l.text}>{l.text}{(l.player || l.stat) && <span className="muted"> · flags {l.side === "no" ? "unders" : l.side === "yes" ? "overs" : "bets"} on {l.player ?? "any player"}{l.stat ? ` ${l.stat}` : ""}</span>}</li>)}</ul>
            </>
          )}
          {r.next_time.length > 0 && <><h4 className="small">Next time</h4><ul className="small">{r.next_time.map((x) => <li key={x}>{x}</li>)}</ul></>}
          {r.news.length > 0 && (
            <details className="small"><summary>Recap news ({r.news.length})</summary>
              <ul>{r.news.map((n) => <li key={n.id}><span className="muted">{n.id}</span> <a href={n.url} target="_blank" rel="noopener noreferrer nofollow">{n.title}</a> <span className="muted">{n.source} · {n.age}</span></li>)}</ul>
            </details>
          )}
          <p className="fine muted">
            {r.model} · {r.seconds}s · {r.news_info.status === "no_key" ? "no Brave key, so no recap news"
              : `${r.news_info.searched} recap searches${r.news_info.status === "budget" ? ` (stopped: ${r.news_info.message ?? "Brave cap"})` : ""}`}
            {r.cached ? " · from the last 30 minutes" : ""}
          </p>
        </>
      )}
    </section>
  );
}

function Lessons({ tick }: { tick: number }) {
  const [items, setItems] = useState<Lesson[]>([]);
  const [text, setText] = useState("");
  const [player, setPlayer] = useState("");
  const [stat, setStat] = useState("");
  const [side, setSide] = useState<"" | Side>("");
  const [msg, setMsg] = useState<string | null>(null);
  const load = () => api.lessons().then((r) => setItems(r.items), () => setItems([]));
  useEffect(() => { void load(); }, [tick]);
  const add = () => {
    api.addLesson({ text, player: player || null, stat: stat || null, side: (player || stat) && side ? side : null })
      .then(() => { setText(""); setPlayer(""); setStat(""); setSide(""); setMsg(null); void load(); },
        (e) => setMsg(e instanceof ApiError ? e.message : "Couldn't save"));
  };
  return (
    <section className="panel" aria-labelledby="dr-les">
      <h3 id="dr-les" className="kicker">Lessons ({items.length})</h3>
      <p className="small muted">Tagged lessons (a player, or a stat and side like “unders on points”) warn you on the Docket and in tonight's combos when a new bet repeats them.</p>
      {items.length > 0 && (
        <ul className="dr-lessons small">
          {items.map((l) => (
            <li key={l.id}>
              <span>{l.text}</span>{" "}
              <span className="muted">{l.player || l.stat ? `${l.player ?? "any player"}${l.stat ? ` ${l.stat}` : ""}${l.side ? ` ${l.side === "no" ? "under" : "over"}` : ""} · ` : ""}{l.author === "model" ? "model" : "you"}, {l.day}</span>{" "}
              <button type="button" className="link-button small" aria-label={`Remove lesson: ${l.text}`}
                onClick={() => api.removeLesson(l.id).then(load, load)}>Remove</button>
            </li>
          ))}
        </ul>
      )}
      <div className="dr-add">
        <input aria-label="New lesson" placeholder="Add your own lesson, e.g. No unders on stars at home" value={text}
          maxLength={240} onChange={(e) => setText(e.target.value)} />
        <input aria-label="Player (optional)" placeholder="Player (optional)" value={player} maxLength={120}
          onChange={(e) => setPlayer(e.target.value)} />
        <select aria-label="Stat" value={stat} onChange={(e) => setStat(e.target.value)}>
          <option value="">any stat</option>{STATS.map((s) => <option key={s}>{s}</option>)}
        </select>
        <select aria-label="Side" value={side} onChange={(e) => setSide(e.target.value as "" | Side)} disabled={!player && !stat}>
          <option value="">any side</option><option value="yes">over (YES)</option><option value="no">under (NO)</option>
        </select>
        <button type="button" className="ghost-button" disabled={text.trim().length < 3} onClick={add}>Save lesson</button>
      </div>
      {msg && <p role="alert" className="small">{msg}</p>}
    </section>
  );
}

function Record() {
  const [rec, setRec] = useState<LegRecord | null>(null);
  const [top, setTop] = useState<{ winners: DayBet[]; losers: DayBet[] } | null>(null);
  useEffect(() => {
    api.historyLegs().then(setRec, () => setRec(null));
    api.historyTop().then(setTop, () => setTop(null));
  }, []);
  return (
    <>
      {top && (top.winners.length > 0 || top.losers.length > 0) && (
        <div className="two-col">
          <section className="panel" aria-labelledby="dr-win"><h3 id="dr-win" className="kicker">Top winners, all time</h3>
            <ul className="dr-bets">{top.winners.map((b) => <BetCard key={b.ticker} b={b} />)}</ul></section>
          <section className="panel" aria-labelledby="dr-lose"><h3 id="dr-lose" className="kicker">Top losers, all time</h3>
            <ul className="dr-bets">{top.losers.map((b) => <BetCard key={b.ticker} b={b} />)}</ul></section>
        </div>
      )}
      {rec && rec.legs > 0 && (
        <section className="panel" aria-labelledby="dr-rec">
          <h3 id="dr-rec" className="kicker">Your legs: {rec.legs} resolved, {rec.lost} lost ({Math.round((rec.overall_loss_rate ?? 0) * 100)}%)</h3>
          <div className="two-col">
            <div>
              <h4 className="small">Players and teams who sank you most</h4>
              <ul className="small dr-subjects">
                {(rec.hurt ?? []).map((x) => (
                  <li key={x.name}><b>{x.name}</b> {x.won}–{x.lost} <span className="muted">({x.combos_hurt} combos hurt)</span>
                    {x.recent_losses[0] && <div className="muted">last: {x.recent_losses[0].bet}{x.recent_losses[0].what_happened ? ` — ${x.recent_losses[0].what_happened}` : ""}</div>}
                  </li>
                ))}
              </ul>
              {(rec.carried ?? []).length > 0 && (
                <>
                  <h4 className="small">Never let you down (3+ legs, no losses)</h4>
                  <p className="small">{(rec.carried ?? []).map((x) => `${x.name} ${x.won}–0`).join(" · ")}</p>
                </>
              )}
            </div>
            <div>
              <h4 className="small">By leg type</h4>
              <table className="small dr-cats">
                <thead><tr><th>Leg type</th><th>Won–lost</th><th>Lost</th></tr></thead>
                <tbody>
                  {rec.by_category.map((c) => (
                    <tr key={c.name} className={c.pattern ? "dr-pattern" : ""}>
                      <td>{c.name}{c.pattern && <span className="badge stale small">loses more</span>}</td>
                      <td>{c.won}–{c.lost}</td>
                      <td>{c.loss_rate == null ? "—" : `${Math.round(c.loss_rate * 100)}%`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="fine muted">“Loses more”: at least {rec.min_pattern ?? 10} legs and 10+ points worse than your {Math.round((rec.overall_loss_rate ?? 0) * 100)}% overall.</p>
            </div>
          </div>
        </section>
      )}
    </>
  );
}

/** Review a day's bets to do better the next: every bet with what you paid and how each leg
 * ended (with the player's actual line), the legs that sank you, a local-model review that
 * saves lessons, your lessons, and your record by player and leg type. */
export function DailyReview() {
  const [days, setDays] = useState<DaySummary[] | null>(null);
  const [day, setDay] = useState<string | null>(null);
  const [detail, setDetail] = useState<DayDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    api.historyDays().then((r) => { setDays(r.days); setDay((d) => d ?? r.days[0]?.date ?? null); }, () => setDays([]));
  }, []);
  useEffect(() => {
    if (!day) return;
    let cancel = false;
    setLoading(true);
    api.historyDay(day).then((d) => { if (!cancel) setDetail(d); }, () => { if (!cancel) setDetail(null); })
      .finally(() => { if (!cancel) setLoading(false); });
    return () => { cancel = true; };
  }, [day, tick]);

  if (days == null) return <p className="small muted">Loading…</p>;
  if (days.length === 0) return <EmptyState figure="plot" title="No bets yet">Sync from Kalshi to review your days.</EmptyState>;
  const t = detail?.totals;
  return (
    <div className="daily-review">
      <div className="dr-days" role="group" aria-label="Pick a day">
        {days.slice(0, 14).map((d) => (
          <button key={d.date} type="button" aria-pressed={d.date === day} onClick={() => setDay(d.date)}>
            <span>{dayName(d.date)}</span> <span className={`small ${tone(d.pnl)}`}>{money(d.pnl)}</span>
          </button>
        ))}
      </div>
      {loading && !detail && <p className="small muted">Loading the day and looking up box scores…</p>}
      {detail && t && day && (
        <>
          <div className="tiles">
            <Tile label="Bets" value={String(t.bets)} />
            <Tile label="Won" value={`${t.won} of ${t.settled}`} />
            <Tile label="P&L" value={money(t.pnl)} cls={tone(t.pnl)} />
            <Tile label="Staked" value={`$${t.staked}`} />
            <Tile label="Lost by one leg" value={String(t.combos_sunk_by_one)} />
          </div>
          {detail.box_scores && detail.box_scores.pending > 0 && (
            <p className="small muted">Looked up {detail.box_scores.checked} legs' box scores; {detail.box_scores.pending} more on the next load.{" "}
              <button type="button" className="link-button small" onClick={() => setTick((n) => n + 1)}>Load more</button></p>
          )}
          {detail.breakers.length > 0 && (
            <section className="panel" aria-labelledby="dr-brk">
              <h3 id="dr-brk" className="kicker">Legs that sank you ({detail.breakers.length})</h3>
              <ul className="dr-legs small">
                {detail.breakers.map((x) => (
                  <li key={`${x.ticker}:${x.side}`} className="dr-leg lost">
                    <span className="dr-mark">✗</span> <b>{x.side.toUpperCase()} · {x.title}</b>
                    {x.what_happened && <span> — {x.what_happened}</span>}
                    <span className="muted"> · in {x.combos} combo{x.combos === 1 ? "" : "s"}{x.sunk_alone ? `, the only miss in ${x.sunk_alone}` : ""} · {x.category}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <Review date={day} />
          <section className="panel" aria-labelledby="dr-all">
            <h3 id="dr-all" className="kicker">Every bet on {dayName(day)}</h3>
            <ul className="dr-bets">{detail.bets.map((b) => <BetCard key={b.ticker} b={b} />)}</ul>
            {detail.skipped.length > 0 && (
              <p className="small muted">You skipped {detail.skipped.length} queued bet{detail.skipped.length === 1 ? "" : "s"} that day (see Bet queue).</p>
            )}
          </section>
        </>
      )}
      <Lessons tick={tick} />
      <Record />
    </div>
  );
}
