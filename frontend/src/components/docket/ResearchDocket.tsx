import { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { ComboResult, EvidenceResult, LegEvidence, Verdict } from "../../api/types";
import { EmptyState } from "../Hairline";
import { cents, pct } from "../games/format";
import "../games/games.css";
import { LegResearch } from "../games/LegResearch";
import { SecondOpinion } from "../games/SecondOpinion";
import { SlipCheck } from "../games/SlipCheck";
import { slip, useSlip } from "../games/slip";
import { useTween } from "../games/useTween";
import { useNow } from "../shell/Topbar";
import { MustHappen, MyEvidence, PriceImplies, risks, WhereWrong } from "./Breakdown";
import "./docket.css";
import { FromHistory } from "./FromHistory";
import { SaveOrPass, SavedList } from "./SaveOrPass";
import { useScanTime } from "./scanTime";
import { Tip } from "../design/Tip";
import { Term } from "../Term";

const VERDICT: Record<Verdict, { text: string; cls: string; tip: string }> = {
  agrees: { text: "fits history", cls: "v-ok", tip: "The price sits inside the range past games suggest." },
  market_lower: { text: "history: likelier", cls: "v-up", tip: "Past games say this happens more often than the price implies." },
  market_higher: { text: "history: less likely", cls: "v-down", tip: "The price implies more than past games support." },
  thin: { text: "thin data", cls: "v-thin", tip: "Fewer than 8 games on record." },
  no_price: { text: "no price", cls: "v-thin", tip: "No two-sided quote." },
};
const COLLAPSE_KEY = "krt.docket.collapsed";

function useDebounced<T>(v: T, ms: number): T {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

function useCollapsed(): [boolean, (v: boolean) => void] {
  const [c, setC] = useState(() => { try { return localStorage.getItem(COLLAPSE_KEY) === "1"; } catch { return false; } });
  useEffect(() => { try { localStorage.setItem(COLLAPSE_KEY, c ? "1" : "0"); } catch { /* ignore */ } }, [c]);
  return [c, setC];
}

/** The Research Docket: the one slip, on every research page. A right rail on wide screens
 * (collapsible), a bottom sheet on narrow ones. It prices and checks; it never places orders.
 * Results are shown only for the legs they were computed for, so a quick change of legs never
 * flashes the previous slip's numbers. */
export function ResearchDocket() {
  const legs = useSlip();
  const key = legs.map((l) => `${l.ticker}:${l.side}`).join(",");
  const dkey = useDebounced(key, 350);
  const [combo, setCombo] = useState<{ key: string; res: ComboResult | null } | null>(null);
  const [ev, setEv] = useState<{ key: string; res: EvidenceResult | null; err: string | null } | null>(null);
  const [openLeg, setOpenLeg] = useState<string | null>(null);
  const [quote, setQuote] = useState("");
  const [collapsed, setCollapsed] = useCollapsed();
  const [sheetOpen, setSheetOpen] = useState(false);
  const scanAt = useScanTime();
  const now = useNow();

  useEffect(() => {
    if (!key) { setCombo(null); return; }
    let cancel = false;
    api.catalogCombo(slip.get()).then((r) => { if (!cancel) setCombo({ key, res: r }); },
      () => { if (!cancel) setCombo({ key, res: null }); });
    return () => { cancel = true; };
  }, [key]);

  useEffect(() => {
    if (!dkey) { setEv(null); return; }
    let cancel = false;
    api.legEvidence(slip.get()).then((r) => { if (!cancel) setEv({ key: dkey, res: r, err: null }); },
      (e) => { if (!cancel) setEv({ key: dkey, res: null, err: e instanceof ApiError ? e.message : "Evidence unavailable" }); });
    return () => { cancel = true; };
  }, [dkey]);

  // Only results computed for exactly these legs count.
  const comboNow = combo?.key === key ? combo.res : null;
  const comboLoading = !!key && combo?.key !== key;
  const evNow = ev?.key === key ? ev.res : null;
  const evLoading = !!key && ev?.key !== key;
  const evBy = useMemo(() => new Map((evNow?.legs ?? []).map((l) => [`${l.ticker}:${l.side}`, l])), [evNow]);
  const fair = comboNow?.fair_price ?? null;
  const adj = evNow?.adjusted_probability ?? null;
  const fairT = useTween(fair);
  const adjT = useTween(adj);
  const q = Number(quote) / 100;
  const n = legs.length;
  const riskItems = risks(legs, comboNow, evNow);
  const summary = n === 0 ? "empty" : `${n} leg${n === 1 ? "" : "s"}${n >= 2 && fair != null ? ` · fair ${(fair * 100).toFixed(1)}¢` : ""}`;

  return (
    <aside className="docket" aria-label="Research docket" data-collapsed={collapsed ? "true" : "false"}
      data-open={sheetOpen ? "true" : "false"}
      onKeyDown={(e) => { if (e.key === "Escape" && sheetOpen) setSheetOpen(false); }}>
      {/* Narrow screens: a handle that opens the sheet. */}
      <button type="button" className="docket-handle" aria-expanded={sheetOpen} aria-controls="docket-body"
        onClick={() => setSheetOpen(!sheetOpen)}>
        <span className="docket-handle-title">Docket</span>{" "}
        <span className="docket-handle-sum">{summary}</span>
        <span aria-hidden="true" className="docket-chevron">{sheetOpen ? "▾" : "▴"}</span>
      </button>
      {/* Wide screens, collapsed: a slim strip. */}
      <button type="button" className="docket-strip" aria-expanded={!collapsed} aria-controls="docket-body"
        onClick={() => setCollapsed(false)} title="Show the docket">
        <span className="docket-strip-count">{n}</span>{" "}
        <span className="docket-strip-label">Docket</span>
      </button>

      <div id="docket-body" className="docket-body">
        <header className="docket-head">
          <h2>Docket</h2>
          <span className="count" key={n} aria-label={`${n} legs`}>{n}</span>
          {n > 0 && <button type="button" className="link-button small" onClick={() => slip.clear()}>Clear</button>}
          <button type="button" className="docket-collapse" aria-label="Collapse the docket"
            aria-expanded={!collapsed} aria-controls="docket-body" onClick={() => setCollapsed(true)}>»</button>
          <button type="button" className="docket-close" aria-label="Close the docket"
            onClick={() => setSheetOpen(false)}>×</button>
        </header>

        {n === 0 ? (
          <EmptyState figure="basket" title="Nothing on the docket">
            Tap a price on Explore (a game or any market) to add it. It stays here as you move between pages.
          </EmptyState>
        ) : (
          <>
            <ul className="slip-legs">
              {legs.map((l) => {
                const e: LegEvidence | undefined = evBy.get(`${l.ticker}:${l.side}`);
                const cl = comboNow?.legs.find((x) => x.ticker === l.ticker);
                const v = e?.verdict ? VERDICT[e.verdict] : null;
                const isOpen = openLeg === l.ticker;
                return (
                  <li key={l.ticker} className="slip-leg">
                    <div className="leg-main">
                      <div className="side-toggle" role="group" aria-label={`Side for ${l.label}`}>
                        {(["yes", "no"] as const).map((s) => (
                          <button key={s} type="button" aria-pressed={l.side === s}
                            onClick={() => slip.setSide(l.ticker, s)}>{s.toUpperCase()}</button>
                        ))}
                      </div>
                      <button type="button" className="leg-label" aria-expanded={isOpen}
                        onClick={() => setOpenLeg(isOpen ? null : l.ticker)} title={l.ticker}>
                        {l.label}
                      </button>
                      <span className="leg-p">
                        {comboLoading ? "…" : pct(cl?.probability)}
                      </span>
                      <button type="button" className="x" aria-label={`Remove ${l.label}`}
                        onClick={() => slip.remove(l.ticker)}>×</button>
                    </div>
                    <div className="leg-sub">
                      {evLoading && !e ? <span className="shimmer" aria-hidden="true" />
                        : v ? <Tip text={v.tip} className={`verdict ${v.cls}`}>{v.text}</Tip>
                        : e && !e.supported ? <Tip text={e.reason ?? "No box-score check for this market"} className="verdict v-thin">no check</Tip> : null}
                      {e?.windows && <span className="muted small">L10 {e.windows.last10[0]}/{e.windows.last10[1]}</span>}
                      {e?.injury && <Tip text={e.injury.detail || e.injury.status} className="inj small">{e.injury.status}</Tip>}
                    </div>
                    <div className={`drawer${isOpen ? " open" : ""}`}>
                      <div>{isOpen && <LegResearch ev={e} loading={evLoading} />}</div>
                    </div>
                  </li>
                );
              })}
            </ul>

            <div className="slip-summary">
              {n >= 2 ? (
                <>
                  <div className="big-num" aria-live="polite">
                    <span className="label"><Term id="fair-price">Fair price</Term></span>
                    <span className="value">{comboLoading ? <span className="shimmer" aria-label="Pricing…" />
                      : fairT == null ? "—" : `${(fairT * 100).toFixed(1)}¢`}</span>
                    {fair && !comboLoading ? <span className="muted small">pays {(1 / fair).toFixed(1)}×</span> : null}
                  </div>
                  {adjT != null && fair != null && Math.abs((adj ?? 0) - fair) >= 0.005 && (
                    <div className="big-num alt">
                      <span className="label"><Tip text="Market prices × how often these legs actually landed together in past games">History-adjusted</Tip></span>
                      <span className="value">{(adjT * 100).toFixed(1)}¢</span>
                      <span className="muted small">{(adj ?? 0) > fair ? "legs move together" : "legs pull apart"}</span>
                    </div>
                  )}
                  {evNow?.correlation.map((c) => c.lift != null && (
                    <p key={`${c.game_key}-${c.team}`} className="small corr-line">
                      {c.team} legs all hit <b>{c.together}/{c.games}</b> past games (independent: {c.expected?.toFixed(1)}) → ×{c.lift.toFixed(2)}
                    </p>
                  ))}
                  {comboNow?.kalshi && (
                    <p className="small">
                      {comboNow.kalshi.eligible
                        ? <span className="badge paper">Combinable on Kalshi</span>
                        : <span className="badge stale">Not combinable on Kalshi</span>}
                      {comboNow.kalshi.history?.return_per_dollar != null && (
                        <span className="muted">
                          {" "}· past {comboNow.kalshi.history.bucket} combos paid ${comboNow.kalshi.history.return_per_dollar.toFixed(2)}/$1
                          {" "}(all Kalshi users, {comboNow.kalshi.history.n.toLocaleString()} settled)
                        </span>
                      )}
                    </p>
                  )}
                </>
              ) : (
                <p className="small muted">Single leg: price {comboLoading ? "…" : cents(comboNow?.legs[0]?.probability)}. Add another leg to price a combo.</p>
              )}
            </div>

            <MustHappen legs={legs} />
            <WhereWrong items={riskItems} loading={evLoading || comboLoading} />
            <PriceImplies legs={legs} combo={comboNow} adjusted={adj} scanAt={scanAt} now={now} />
            <MyEvidence legs={legs} ev={evNow} loading={evLoading} error={ev?.key === key ? ev.err : null} />
            <FromHistory legs={legs} />
            <section className="dk-section" aria-labelledby="dk-pay">
              <h3 id="dk-pay">What I would pay</h3>
              <SlipCheck legs={legs} quote={quote} onQuote={setQuote} refPrice={adj ?? fair} />
            </section>
            <SecondOpinion legs={legs} quoteCents={q > 0 && q < 1 ? Math.round(q * 100) : undefined} />
            <SaveOrPass legs={legs} fair={fair} />
          </>
        )}
        <SavedList />
        <p className="fine small muted">Estimates, not advice. You place any trade yourself on Kalshi.</p>
      </div>
    </aside>
  );
}
