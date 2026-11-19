import { useState } from "react";

import { api, ApiError } from "../../api/client";
import type { LegEvidence, NewsResult } from "../../api/types";
import { CHART } from "../../styles/palette";
import { Figure } from "./Figure";
import { pct } from "./format";

const HIT = CHART.gain;
const MISS = CHART.loss;
const LINE = CHART.ink;
const BASE = CHART.base;

/** Last 10 games, oldest to newest, against the leg's line. */
export function MiniBars({ ev }: { ev: LegEvidence }) {
  const rows = [...(ev.recent ?? [])].reverse().filter((r) => r.value != null);
  if (rows.length === 0) return null;
  const W = 240, H = 64, pad = 4;
  const vals = rows.map((r) => r.value as number);
  const line = ev.line ?? null;
  const hi = Math.max(...vals, line ?? 0, 1) * 1.1;
  const lo = Math.min(0, ...vals, line ?? 0) * 1.1;
  const y = (v: number) => pad + (hi - v) / (hi - lo) * (H - 2 * pad);
  const bw = (W - 40) / rows.length;
  const hits = rows.filter((r) => r.hit).length;
  const unit = ev.stat ? "" : ev.kind === "team_margin" || ev.kind === "team_win" ? " margin" : "";
  return (
    <figure className="minibars">
      <svg width={W} height={H} role="img"
        aria-label={`Last ${rows.length} games: the ${ev.side.toUpperCase()} side happened ${hits} times${line != null ? `; line ${line}` : ""}`}>
        <line x1={0} x2={W - 40} y1={y(0)} y2={y(0)} stroke={BASE} strokeWidth={1} />
        {rows.map((r, i) => {
          const v = r.value as number;
          const top = Math.min(y(v), y(0));
          const h = Math.max(Math.abs(y(v) - y(0)), 1.5);
          return (
            <rect key={`${r.date}-${i}`} x={i * bw + 1} y={top} width={Math.max(bw - 2, 2)} height={h} rx={2}
              fill={r.hit ? HIT : MISS}>
              <title>{`${r.date} ${r.home ? "vs" : "@"} ${r.opponent}: ${v}${unit}${r.hit ? " ✓" : " ✗"}`}</title>
            </rect>
          );
        })}
        {line != null && line !== 0 && (
          <>
            <line x1={0} x2={W - 40} y1={y(line)} y2={y(line)} stroke={LINE} strokeWidth={1.5} strokeDasharray="4 3" />
            <text x={W - 36} y={y(line) + 4} fontSize={11} fill={CHART.muted}>{line}</text>
          </>
        )}
      </svg>
      <figcaption className="small muted">
        last {rows.length} · <span className="swatch" style={{ background: HIT }} /> {ev.side.toUpperCase()} hit{" "}
        <span className="swatch" style={{ background: MISS }} /> miss
      </figcaption>
    </figure>
  );
}

function Win({ label, w }: { label: string; w?: [number, number] }) {
  if (!w || w[1] === 0) return null;
  return <span className="win-chip"><b>{w[0]}/{w[1]}</b> {label}</span>;
}

export function LegResearch({ ev, loading }: { ev: LegEvidence | undefined; loading: boolean }) {
  const [news, setNews] = useState<NewsResult | null>(null);
  const [newsErr, setNewsErr] = useState<string | null>(null);
  if (loading && !ev) {
    return <div className="research loading"><Figure name="sieve" size={110} /><span className="small muted">Checking box scores…</span></div>;
  }
  if (!ev) return null;
  if (!ev.supported) return <div className="research"><p className="small muted">{ev.reason}</p></div>;
  const name = ev.subject?.name ?? "";
  const q = `${name} ${ev.subject?.type === "player" ? "injury minutes" : "injury report"}`;
  const newsUrl = `https://news.google.com/search?q=${encodeURIComponent(q)}`;
  return (
    <div className="research">
      <MiniBars ev={ev} />
      <div className="win-row">
        <Win label="L5" w={ev.windows?.last5} />
        <Win label="L10" w={ev.windows?.last10} />
        <Win label="season" w={ev.windows?.season} />
        <Win label="last season" w={ev.windows?.last_season} />
      </div>
      <p className="small">
        History ≈ <b>{pct(ev.estimate)}</b> <span className="muted">({pct(ev.interval?.[0])}–{pct(ev.interval?.[1])})</span>
        {" "}vs price <b>{pct(ev.market)}</b>
        {ev.season_avg != null && <span className="muted"> · avg {ev.season_avg}</span>}
      </p>
      {ev.injury && <p className="small inj-note"><b>{ev.injury.status}</b>: {ev.injury.detail}</p>}
      <div className="research-links small">
        {ev.subject?.espn_url && <a href={ev.subject.espn_url} target="_blank" rel="noopener noreferrer">ESPN</a>}
        <a href={newsUrl} target="_blank" rel="noopener noreferrer">News search</a>
        <button type="button" className="link-button small" onClick={() => {
          setNewsErr(null);
          api.news(`${name} NBA`).then(setNews, (e) => setNewsErr(e instanceof ApiError ? e.message : "Search failed"));
        }}>Headlines here</button>
      </div>
      {newsErr && <p role="alert" className="small">{newsErr}</p>}
      {news && !news.configured && (
        <div className="news-off small">
          <Figure name="plug" size={90} />
          <span>Headline search is off. Add a Brave Search key to <code>.env</code> (see the README), or use the links above.</span>
        </div>
      )}
      {news?.configured && (
        <ul className="news small">
          {news.items.length === 0 && <li className="muted">Nothing from the past week.</li>}
          {news.items.map((n) => (
            <li key={n.url}><a href={n.url} target="_blank" rel="noopener noreferrer nofollow">{n.title}</a>{" "}
              <span className="muted">{n.source} · {n.age}</span></li>
          ))}
        </ul>
      )}
      <p className="small muted fine">Box scores don't know tonight's matchup, minutes or rest. Use them to sanity-check a price, not as a forecast.</p>
    </div>
  );
}
