import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { CoachResult, ComboBreakdown, HistoryFill, HistoryGroup, HistoryReport, HistoryStatus, LlmStatus, PlaybookRule } from "../../api/types";
import { formatPrice, formatUtc } from "../format";
import { offReason } from "../games/SecondOpinion";
import { EmptyState, Figure, PageHead } from "../Hairline";
import { OpenPositions, Tile } from "./OpenPositions";
import { PnlCharts } from "./PnlCharts";

const pct = (x: number | null | undefined, d = 0) => (x == null ? "—" : `${(x * 100).toFixed(d)}%`);
const money = (s: string | null | undefined) => {
  if (s == null) return "—";
  const n = Number(s);
  return `${n < 0 ? "−" : n > 0 ? "+" : ""}$${Math.abs(n).toFixed(2)}`;
};
const signClass = (s: string | null | undefined) =>
  s == null ? "" : Number(s) > 0 ? "ev-pos" : Number(s) < 0 ? "ev-neg" : "";

type Tab = "overview" | "open" | "behavior" | "ledger";

/** Your Kalshi history: P&L, open positions in context, behaviour, and a playbook. */
export function HistoryPage() {
  const [status, setStatus] = useState<HistoryStatus | null>(null);
  const [rep, setRep] = useState<HistoryReport | null>(null);
  const [fills, setFills] = useState<HistoryFill[]>([]);
  const [syncing, setSyncing] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [tick, setTick] = useState(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(() => {
    api.historyStatus().then(setStatus, () => setStatus(null));
    api.historyReport().then(setRep, () => setRep(null));
    api.historyFills(100).then((r) => setFills(r.items), () => setFills([]));
    setTick((t) => t + 1);
  }, []);
  useEffect(load, [load]);
  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

  async function sync() {
    setMsg(null);
    try {
      await api.runJob("history");
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 409)) {
        setMsg(e instanceof ApiError ? e.message : "Could not start the sync");
        return;
      }
    }
    setSyncing(true);
    timer.current = setInterval(() => {
      api.jobs().then((s) => {
        const h = s.jobs.history;
        if (h && !h.running) {
          if (timer.current) clearInterval(timer.current);
          setSyncing(false);
          setMsg(`${h.last_status}: ${h.last_message ?? ""}`);
          load();
        }
      }, () => undefined);
    }, 1500);
  }

  const sm = rep?.summary;
  const wr = sm?.win_rate;
  const rc = rep?.reconciliation;
  const has = !!(rep && sm && (rep.behavior.fills > 0 || sm.balance != null));
  const TABS: { id: Tab; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "open", label: `Open${sm ? ` (${sm.open_markets})` : ""}` },
    { id: "behavior", label: "Behavior" },
    { id: "ledger", label: "Ledger" },
  ];
  return (
    <div className="history-page">
      <PageHead figure="plot" title="My trades" actions={
        <>
          {rep?.last_sync && <span className="small muted" title={rep.last_sync.message}>synced {formatUtc(rep.last_sync.at)}</span>}
          <button type="button" className="primary-button" onClick={sync} disabled={syncing || !status?.configured}>
            {syncing ? "Syncing…" : "Sync from Kalshi"}
          </button>
        </>
      }>
        Read-only. Your history stays in the local database.
      </PageHead>
      {msg && <p role="status" className="small">{msg}</p>}
      {status && !status.configured && <KeySetup />}
      {rep && sm && rep.behavior.fills === 0 && sm.balance == null && status?.configured && (
        <EmptyState figure="plot" title="Nothing synced yet">Click Sync from Kalshi.</EmptyState>
      )}

      {has && rep && sm && (
        <>
          <div className="subtabs" role="tablist" aria-label="My trades sections">
            {TABS.map((t) => (
              <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}>
                {t.label}
              </button>
            ))}
          </div>
          <div className="subtab-panel" role="tabpanel" key={tab}>
            {tab === "overview" && (
              <>
                <div className="tiles">
                  <Tile label="Cash" value={sm.balance == null ? "—" : `$${sm.balance}`} />
                  <Tile label="Realized P&L" value={money(sm.realized_pnl)} cls={signClass(sm.realized_pnl)} />
                  <Tile label="Open, at mid" value={money(sm.unrealized_pnl)} cls={signClass(sm.unrealized_pnl)} />
                  <Tile label="Fees" value={`$${sm.fees}`} />
                  <Tile label="Won vs price paid" value={wr ? `${pct(wr.win_rate)} vs ${pct(wr.avg_price)}` : "—"}
                    note={wr ? `${wr.n} settled${wr.small_sample ? " · small sample" : ""}` : undefined} />
                </div>
                {rc && rc.checked > 0 && (
                  <p className={`small ${rc.net + rc.gross < rc.checked ? "warning-box" : "muted"}`}
                    title={rc.net + rc.gross < rc.checked
                      ? "Our P&L math vs Kalshi's per-market numbers. Mismatches usually mean fills older than Kalshi still serves, so those markets' P&L uses the settlement's cost basis."
                      : "Our P&L math matches Kalshi's per-market numbers"}>
                    {rc.net + rc.gross < rc.checked ? "⚠" : "✓"} {rc.net + rc.gross} of {rc.checked} markets match Kalshi's P&L
                  </p>
                )}
                <section className="panel" aria-labelledby="h-time">
                  <h3 id="h-time" className="kicker">P&L over time</h3>
                  <PnlCharts timeline={rep.timeline ?? []} />
                </section>
                <div className="two-col">
                  <section className="panel" aria-labelledby="h-play">
                    <h3 id="h-play" className="kicker">Your playbook</h3>
                    <Playbook rules={rep.playbook ?? []} />
                  </section>
                  <Coach />
                </div>
              </>
            )}

            {tab === "open" && <OpenPositions tick={tick} />}

            {tab === "behavior" && (
              <>
                <div className="two-col">
                  <section className="panel" aria-labelledby="h-ins">
                    <h3 id="h-ins" className="kicker">What your history says</h3>
                    <ul className="insights">
                      {rep.insights.map((i) => <li key={i.text} className={`insight ${i.level}`}>{i.text}</li>)}
                    </ul>
                  </section>
                  <section className="panel" aria-labelledby="h-combo">
                    <h3 id="h-combo" className="kicker">Your combos</h3>
                    <Combos b={rep.combo_breakdown ?? null} />
                  </section>
                </div>
                <section className="panel" aria-labelledby="h-beh">
                  <h3 id="h-beh" className="kicker">How you trade</h3>
                  <div className="stat-chips">
                    <Stat k="Avg entry" v={formatPrice(rep.behavior.avg_entry_price)} />
                    <Stat k="Longshots ≤20¢" v={pct(rep.behavior.longshot_share)} />
                    <Stat k="Favorites ≥80¢" v={pct(rep.behavior.favorite_share)} />
                    <Stat k="Taker volume" v={pct(rep.behavior.taker_share)} />
                    <Stat k="Fees / spend" v={pct(rep.behavior.fee_share_of_notional, 1)} />
                    <Stat k="Median stake" v={rep.behavior.median_stake == null ? "—" : `$${rep.behavior.median_stake}`} />
                    <Stat k="Max stake" v={rep.behavior.max_stake == null ? "—" : `$${rep.behavior.max_stake}`} />
                    {rep.entry_quality && <>
                      <Stat k="Entry vs close" v={rep.entry_quality.clv.avg_pts == null ? "builds over time" : `${rep.entry_quality.clv.avg_pts > 0 ? "+" : ""}${rep.entry_quality.clv.avg_pts} pts`}
                        tip="Your entry price vs the last price before the market closed (from stored marks). Positive = you bought cheaper than where it ended up." />
                      <Stat k="Held to end, lost" v={`${rep.entry_quality.held_to_settlement.lost}/${rep.entry_quality.held_to_settlement.n}`} />
                      <Stat k="Sold early, in profit" v={`${rep.entry_quality.early_exits.in_profit}/${rep.entry_quality.early_exits.n}`} />
                    </>}
                  </div>
                </section>
                <section className="panel" aria-labelledby="h-cal">
                  <h3 id="h-cal" className="kicker">Won vs price paid</h3>
                  {rep.calibration.length === 0 ? <p className="muted small">No settled picks yet.</p> : (
                    <table className="market-table">
                      <thead><tr><th scope="col">Price</th><th scope="col">Picks</th><th scope="col">Won</th>
                        <th scope="col">Edge</th></tr></thead>
                      <tbody>
                        {rep.calibration.map((b) => (
                          <tr key={b.range}>
                            <td>{b.range}</td><td>{b.n}{b.small_sample && "*"}</td><td>{pct(b.win_rate)}</td>
                            <td className={b.edge > 0 ? "ev-pos" : b.edge < 0 ? "ev-neg" : ""}
                              title={`±${((b.se ?? 0) * 100).toFixed(1)} pts standard error`}>
                              {b.edge > 0 ? "+" : ""}{(b.edge * 100).toFixed(1)} pts
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>
                <div className="two-col">
                  <section className="panel"><h3 className="kicker">By market type</h3><GroupTable rows={rep.by_type} /></section>
                  <section className="panel"><h3 className="kicker">By series</h3><GroupTable rows={rep.by_series} /></section>
                </div>
                {rep.suggestions.some((s) => s.events.length > 0) && (
                  <section className="panel" aria-labelledby="h-sug">
                    <h3 id="h-sug" className="kicker">Where you've done well: open now</h3>
                    {rep.suggestions.filter((s) => s.events.length > 0).map((s) => (
                      <div key={s.title} className="small">
                        <b title={s.why}>{s.title}</b>:{" "}
                        {s.events.map((e, i) => (
                          <span key={e.event_ticker}>{i > 0 && " · "}
                            <a href={`#/markets?event=${encodeURIComponent(e.event_ticker)}`}>{e.title}</a></span>
                        ))}
                      </div>
                    ))}
                  </section>
                )}
              </>
            )}

            {tab === "ledger" && (
              <>
                <section className="panel" aria-labelledby="h-mk">
                  <h3 id="h-mk" className="kicker">Closed markets</h3>
                  <div className="table-scroll">
                    <table className="market-table">
                      <thead><tr><th scope="col">Market</th><th scope="col">Type</th><th scope="col">Side</th>
                        <th scope="col">Result</th><th scope="col">Staked</th><th scope="col">P&L</th></tr></thead>
                      <tbody>
                        {rep.markets.map((m) => (
                          <tr key={m.ticker}>
                            <td>{m.series_title}<div className="ticker">{m.ticker}</div></td>
                            <td>{m.type}</td><td>{m.sides.join("+").toUpperCase() || "—"}</td>
                            <td>{m.status === "closed" ? "sold early" : (m.result || "—").toUpperCase()}</td>
                            <td>${m.staked}</td><td className={signClass(m.pnl)}>{money(m.pnl)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
                <section className="panel" aria-labelledby="h-fills">
                  <h3 id="h-fills" className="kicker">Recent fills</h3>
                  <div className="table-scroll">
                    <table className="market-table">
                      <thead><tr><th scope="col">Time</th><th scope="col">Market</th><th scope="col">Action</th>
                        <th scope="col">Qty</th><th scope="col">Price</th><th scope="col">Fee</th></tr></thead>
                      <tbody>
                        {fills.map((f) => (
                          <tr key={f.fill_id}>
                            <td>{formatUtc(f.created_at)}</td><td className="ticker">{f.ticker}</td>
                            <td>{f.action} {f.side.toUpperCase()}{f.is_taker ? "" : " (maker)"}</td><td>{f.count}</td>
                            <td>{formatPrice(f.price)}</td><td>{formatPrice(f.fee)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ k, v, tip }: { k: string; v: string; tip?: string }) {
  return <div className="stat-chip" title={tip}><span className="tile-label">{k}</span><b>{v}</b></div>;
}

const CONF = { standard: "rule of thumb", medium: "from your data", low: "early signal" } as const;

function Playbook({ rules }: { rules: PlaybookRule[] }) {
  if (rules.length === 0) return <p className="small muted">Rules appear as your history grows.</p>;
  return (
    <ol className="playbook">
      {rules.map((r) => (
        <li key={r.rule}>
          <b>{r.rule}</b> <span className={`conf ${r.confidence}`}>{CONF[r.confidence]}</span>
          <div className="small muted">{r.why}</div>
        </li>
      ))}
    </ol>
  );
}

function Combos({ b }: { b: ComboBreakdown | null }) {
  if (!b || !b.with_legs) return <p className="small muted">{b?.combos ? "Leg details load on your next sync." : "No settled combos."}</p>;
  const max = Math.max(...(b.by_size ?? []).map((x) => x.n), 1);
  const breakTotal = (b.breakers ?? []).reduce((a, x) => a + x.legs, 0);
  return (
    <div className="combo-break">
      <p className="small">Avg <b>{b.avg_legs}</b> legs · lost by one leg <b>{b.lost_by_one}/{b.lost}</b></p>
      <div className="size-bars" role="img"
        aria-label={(b.by_size ?? []).map((x) => `${x.legs} legs: ${x.won} of ${x.n} won`).join("; ")}>
        {(b.by_size ?? []).map((x) => (
          <div key={x.legs} className="size-row">
            <span className="small">{x.legs} legs</span>
            <span className="bar"><span className="n" style={{ width: `${(x.n / max) * 100}%` }} />
              <span className="w" style={{ width: `${(x.won / max) * 100}%` }} /></span>
            <span className="small muted">{x.won}/{x.n} won</span>
          </div>
        ))}
      </div>
      {breakTotal > 0 && (
        <p className="small">Legs that broke them: {(b.breakers ?? []).map((x) => `${x.type} ${Math.round((x.legs / breakTotal) * 100)}%`).join(" · ")}</p>
      )}
    </div>
  );
}

function Coach() {
  const [status, setStatus] = useState<LlmStatus | null>(null);
  const [res, setRes] = useState<CoachResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.coachStatus().then(setStatus, () => setStatus(null)); }, []);
  const run = () => {
    setBusy(true);
    setErr(null);
    api.coach().then(setRes, (e) => setErr(e instanceof ApiError ? e.message : "Coach unavailable"))
      .finally(() => setBusy(false));
  };
  return (
    <section className="panel coach" aria-labelledby="h-coach">
      <h3 id="h-coach" className="kicker">Coach{status?.local ? ` · ${status.model} (local)` : ""}</h3>
      {!res && (
        <div className="coach-body">
          <Figure name={busy ? "sieve" : "plug"} size={90} play={busy} />
          <div className="small">
            {status && !status.configured ? <p className="muted">{offReason(status)}</p> : (
              <>
                <p className="muted">Reads your record, playbook and open positions, and writes a short plan. Runs on this machine.</p>
                <button type="button" className="ghost-button" onClick={run} disabled={busy || !status}>
                  {busy ? "Reading your record…" : "Get coaching"}
                </button>
              </>
            )}
            {err && <p role="alert">{err}</p>}
          </div>
        </div>
      )}
      {res && (
        <div className="coach-out">
          <p className="small">{res.summary}</p>
          {res.rules_for_next_50.length > 0 && (<>
            <p className="kicker">Rules for your next $50</p>
            <ol className="coach-rules">{res.rules_for_next_50.map((r) => <li key={r}>{r}</li>)}</ol>
          </>)}
          {res.leaks.length > 0 && (<>
            <p className="kicker">Leaks</p>
            <ul className="reasons">{res.leaks.map((r) => <li key={r} className="warn">{r}</li>)}</ul>
          </>)}
          {res.strengths.length > 0 && (<>
            <p className="kicker">Strengths</p>
            <ul className="reasons">{res.strengths.map((r) => <li key={r} className="good">{r}</li>)}</ul>
          </>)}
          {res.questions.length > 0 && (
            <details className="small"><summary>Ask yourself before the next trade</summary>
              <ul>{res.questions.map((q) => <li key={q}>{q}</li>)}</ul></details>
          )}
          {res.open_positions.length > 0 && (
            <details className="small"><summary>On your open positions ({res.open_positions.length})</summary>
              <ul>{res.open_positions.map((o) => <li key={o.ticker}><span className="ticker">{o.ticker}</span> {o.note}</li>)}</ul></details>
          )}
          <p className="fine muted">AI-written by {res.model}{res.seconds ? ` in ${res.seconds}s` : ""}{res.cached ? " (cached)" : ""} from the numbers on this page. It can be wrong.{" "}
            <button type="button" className="link-button fine" onClick={() => setRes(null)}>close</button></p>
        </div>
      )}
    </section>
  );
}

function GroupTable({ rows }: { rows: HistoryGroup[] }) {
  if (rows.length === 0) return <p className="small muted">Nothing closed yet.</p>;
  return (
    <table className="market-table">
      <thead><tr><th scope="col">Name</th><th scope="col">Mkts</th><th scope="col">P&L</th><th scope="col">ROI</th></tr></thead>
      <tbody>
        {[...rows].reverse().map((r) => (
          <tr key={r.name}>
            <td>{r.name}</td><td>{r.markets}</td>
            <td className={signClass(r.pnl)}>{money(r.pnl)}</td><td>{pct(r.roi)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function KeySetup() {
  return (
    <section className="panel key-setup">
      <Figure name="vault" size={110} />
      <div className="small">
        <p><strong>Connect your account (read-only key)</strong></p>
        <ol>
          <li>Kalshi → Account → Profile → API Keys → create a <strong>read-only</strong> key. Save the private key it shows once.</li>
          <li>Put the key file <strong>outside this project folder</strong> (the app refuses paths inside it).</li>
          <li>In <code>.env</code>, fill in the Kalshi key id and key path (see README, "Your trade history").</li>
          <li>Restart with <code>scripts\dev.cmd</code>, then <strong>Sync from Kalshi</strong>.</li>
        </ol>
      </div>
    </section>
  );
}
