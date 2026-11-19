import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError } from "../../api/client";
import { docketTitle, saved, useSaved } from "../docket/saved";
import { StatusLabel } from "../design/StatusLabel";
import { slip } from "../games/slip";
import { PageHead } from "../Hairline";
import { useDataRefresh } from "../useDataRefresh";
import { type Candidate, SOURCES, type SectionData, type SourceId } from "./sources";
import { exact, rel } from "./time";
import { NOTE_MAX, type TriageEntry, type TriageStatus, useTriage } from "./triage";
import "./today.css";

type Load = { state: "loading" } | { state: "ok"; data: SectionData } | { state: "error"; message: string };
type Filter = "review" | "researching" | "passed";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "review", label: "To review" },
  { id: "researching", label: "Researching" },
  { id: "passed", label: "Passed" },
];

const statusOf = (e: TriageEntry | undefined): Filter =>
  e?.status === "researching" ? "researching" : e?.status === "passed" ? "passed" : "review";

function errText(e: unknown): string {
  return e instanceof ApiError ? e.message : "Backend unreachable";
}

/** Today's desk: one triage queue over the existing sources. It reads, it doesn't trade:
 * every action is a link into the page that already does the research. */
export function TodayPage() {
  const [loads, setLoads] = useState<Record<SourceId, Load>>(() =>
    Object.fromEntries(SOURCES.map((s) => [s.id, { state: "loading" }])) as Record<SourceId, Load>);
  const [filter, setFilter] = useState<Filter>("review");
  const [triage, setTriage] = useTriage();
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback((id: SourceId) => {
    const src = SOURCES.find((s) => s.id === id)!;
    setLoads((l) => ({ ...l, [id]: { state: "loading" } }));
    src.load().then(
      (data) => setLoads((l) => ({ ...l, [id]: { state: "ok", data } })),
      (e) => setLoads((l) => ({ ...l, [id]: { state: "error", message: errText(e) } })),
    );
  }, []);
  const loadAll = useCallback(() => { SOURCES.forEach((s) => load(s.id)); setNow(Date.now()); }, [load]);
  useEffect(loadAll, [loadAll]);
  useDataRefresh(loadAll);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(t);
  }, []);

  const counts = useMemo(() => {
    const c: Record<Filter, number> = { review: 0, researching: 0, passed: 0 };
    for (const l of Object.values(loads)) {
      if (l.state !== "ok") continue;
      for (const it of l.data.items) c[statusOf(triage[it.key])] += 1;
    }
    return c;
  }, [loads, triage]);

  return (
    <div className="today">
      <PageHead figure="sieve" title="Today's desk">
        What deserves a look today, grouped by where it came from. Each group keeps its own
        maths, so nothing here is ranked against a different kind of idea.
      </PageHead>
      <div className="today-tools">
        <div className="segmented" role="group" aria-label="Show">
          {FILTERS.map((f) => (
            <button key={f.id} type="button" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
              {f.label} <span className="seg-count">{counts[f.id]}</span>
            </button>
          ))}
        </div>
        <button type="button" className="ghost-button" onClick={loadAll}>Reload all</button>
        <span className="small muted">Your marks are saved in this browser only.</span>
      </div>
      {SOURCES.map((s) => (
        s.id === "scanner" ? [<SavedSection key="saved" now={now} />,
          <Section key={s.id} id={s.id} title={s.title} blurb={s.blurb} load={loads[s.id]}
            filter={filter} triage={triage} setTriage={setTriage} now={now} onRetry={() => load(s.id)} />] :
        <Section key={s.id} id={s.id} title={s.title} blurb={s.blurb} load={loads[s.id]}
          filter={filter} triage={triage} setTriage={setTriage} now={now} onRetry={() => load(s.id)} />
      ))}
    </div>
  );
}

function Section({ id, title, blurb, load, filter, triage, setTriage, now, onRetry }: {
  id: SourceId; title: string; blurb: string; load: Load; filter: Filter;
  triage: Record<string, TriageEntry>;
  setTriage: (key: string, patch: Partial<Omit<TriageEntry, "at">>) => void;
  now: number; onRetry: () => void }) {
  const hid = `today-${id}`;
  const shown = load.state === "ok"
    ? load.data.items.filter((it) => statusOf(triage[it.key]) === filter) : [];
  return (
    <section className="today-section" aria-labelledby={hid} aria-busy={load.state === "loading"}>
      <header className="today-section-head">
        <h2 id={hid}>{title}</h2>
        {load.state === "ok" && (
          <span className="small muted">
            {load.data.items.length} item{load.data.items.length === 1 ? "" : "s"}
            {load.data.asOf && <> · as of <time dateTime={load.data.asOf} title={exact(load.data.asOf)}>{rel(load.data.asOf, now)}</time></>}
          </span>
        )}
        <p className="small muted today-blurb">{blurb}</p>
      </header>
      {load.state === "loading" && <div className="today-skeleton" aria-hidden="true"><span /><span /></div>}
      {load.state === "loading" && <p className="visually-hidden">Loading {title.toLowerCase()}…</p>}
      {load.state === "error" && (
        <div className="today-error" role="alert">
          <StatusLabel tone="stale">Couldn't load</StatusLabel> <span className="small">{load.message}</span>
          <button type="button" className="ghost-button" onClick={onRetry}>Retry</button>
        </div>
      )}
      {load.state === "ok" && (
        <>
          {shown.length > 0 ? (
            <ul className="cand-list">
              {shown.map((c) => (
                <CandidateRow key={c.key} c={c} entry={triage[c.key]} now={now}
                  onStatus={(st) => setTriage(c.key, { status: triage[c.key]?.status === st ? null : st })}
                  onNote={(note) => setTriage(c.key, { note })} />
              ))}
            </ul>
          ) : (
            <p className="small muted today-empty">
              {load.data.items.length === 0 ? "Nothing here right now."
                : `Nothing ${filter === "review" ? "left to review" : `marked ${filter}`} in this group.`}
            </p>
          )}
          {load.data.note && <p className="small muted today-note">{load.data.note}</p>}
        </>
      )}
    </section>
  );
}

export function CandidateRow({ c, entry, now, onStatus, onNote }: {
  c: Candidate; entry: TriageEntry | undefined; now: number;
  onStatus: (s: TriageStatus) => void; onNote: (note: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(entry?.note ?? "");
  const st = entry?.status ?? null;
  const tid = `cand-${c.key.replace(/[^A-Za-z0-9_-]/g, "_")}`;
  return (
    <li className={`cand${st ? ` is-${st}` : ""}`} aria-labelledby={tid}>
      <div className="cand-main">
        <span className="cand-title" id={tid}>{c.title}</span>
        <span className="cand-sub small muted">
          <StatusLabel tone={c.tone}>{c.kind}</StatusLabel>{c.sub && <span className="cand-sub-text">{c.sub}</span>}
        </span>
        {entry?.note && !editing && <span className="cand-note small">Note: {entry.note}</span>}
      </div>
      <div className="cand-measure">
        <span className="cand-label">{c.measureLabel}</span>
        <span className={c.measureSign ? `ev-${c.measureSign}` : undefined}>{c.measure}</span>
      </div>
      <div className="cand-time small">
        {c.asOf && <span>{c.asOfLabel} <time dateTime={c.asOf} title={exact(c.asOf)}>{rel(c.asOf, now)}</time></span>}
        {c.closes && <span>{c.closeLabel} <time dateTime={c.closes} title={exact(c.closes)}>{rel(c.closes, now)}</time></span>}
      </div>
      <div className="cand-actions">
        <a className="cand-research" href={c.research}>{c.researchLabel}</a>
        <button type="button" aria-pressed={st === "researching"} onClick={() => onStatus("researching")}>
          Researching
        </button>
        <button type="button" aria-pressed={st === "passed"} onClick={() => onStatus("passed")}>Pass</button>
        <button type="button" aria-expanded={editing} onClick={() => { setDraft(entry?.note ?? ""); setEditing(!editing); }}>
          Note
        </button>
      </div>
      {editing && (
        <form className="cand-note-form" onSubmit={(e) => { e.preventDefault(); onNote(draft.trim()); setEditing(false); }}>
          <label className="visually-hidden" htmlFor={`${tid}-note`}>Note on {c.title}</label>
          <input id={`${tid}-note`} value={draft} maxLength={NOTE_MAX} autoFocus
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Escape") setEditing(false); }}
            placeholder="Why you're watching or passing" />
          <button type="submit" className="ghost-button">Save</button>
        </form>
      )}
    </li>
  );
}

/** Research you saved from the Docket. Its own decision (watching / passed), so the triage
 * filter above doesn't apply. The price shown is the snapshot from when you saved it. */
function SavedSection({ now }: { now: number }) {
  const items = useSaved();
  const [show, setShow] = useState<"watch" | "pass">("watch");
  const shown = items.filter((d) => d.decision === show);
  const n = (d: "watch" | "pass") => items.filter((x) => x.decision === d).length;
  return (
    <section className="today-section" aria-labelledby="today-saved">
      <header className="today-section-head">
        <h2 id="today-saved">Saved research</h2>
        <span className="small muted">{items.length} saved from the Docket</span>
        <div className="segmented small-seg" role="group" aria-label="Saved research to show">
          <button type="button" aria-pressed={show === "watch"} onClick={() => setShow("watch")}>
            Watching <span className="seg-count">{n("watch")}</span></button>
          <button type="button" aria-pressed={show === "pass"} onClick={() => setShow("pass")}>
            Passed <span className="seg-count">{n("pass")}</span></button>
        </div>
        <p className="small muted today-blurb">Combos and legs you saved, with the price when you saved them (not live).</p>
      </header>
      {shown.length === 0 ? (
        <p className="small muted today-empty">
          {items.length === 0 ? "Nothing saved yet. Use \"Save to watch\" on the Docket." : `Nothing ${show === "watch" ? "being watched" : "passed"}.`}
        </p>
      ) : (
        <ul className="cand-list">
          {shown.map((d) => (
            <li key={d.id} className="cand" aria-label={docketTitle(d.legs)}>
              <div className="cand-main">
                <span className="cand-title">{docketTitle(d.legs)}</span>
                {d.note && <span className="cand-note small">Note: {d.note}</span>}
              </div>
              <div className="cand-measure">
                <span className="cand-label">Fair when saved (snapshot)</span>
                <span>{d.fair != null ? `${(d.fair * 100).toFixed(1)}¢` : "—"}</span>
              </div>
              <div className="cand-time small">
                <span>saved <time dateTime={d.at} title={exact(d.at)}>{rel(d.at, now)}</time></span>
              </div>
              <div className="cand-actions">
                <button type="button" className="cand-load" onClick={() => slip.replace(d.legs)}>Load into docket</button>
                <button type="button" onClick={() => saved.remove(d.id)} aria-label={`Delete saved: ${docketTitle(d.legs)}`}>Delete</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
