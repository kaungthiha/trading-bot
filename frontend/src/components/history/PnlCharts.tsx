import { useState } from "react";

import type { HistoryReport } from "../../api/types";
import { CHART } from "../../styles/palette";

// Two charts, one axis each (never dual-axis): cumulative realized P&L (single series, no
// legend; the title names it) and daily P&L bars (diverging gain/loss pair, legend shown).
// Colours from the validated chart palette (styles/palette.ts; gain/loss pass every
// validator check incl. CVD); sign is ALSO encoded by bar direction.
const BLUE = CHART.gain;
const RED = CHART.loss;
const MUTED = CHART.muted;
const GRID = CHART.grid;
const BASE = CHART.base;
const SURFACE = CHART.surface;
const W = 720;
const H = 180;
const PAD = { left: 52, right: 12, top: 10, bottom: 26 };
const IW = W - PAD.left - PAD.right;

type Day = HistoryReport["timeline"][number];
const money = (n: number) => `${n < 0 ? "−" : n > 0 ? "+" : ""}$${Math.abs(n).toFixed(2)}`;

function niceTicks(lo: number, hi: number): number[] {
  const span = Math.max(hi - lo, 1);
  const raw = span / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  // Round both ends OUT to a tick, so the top tick is never below the highest value.
  const top = Math.ceil(hi / step - 1e-9) * step;
  for (let v = Math.floor(lo / step) * step; v <= top + 1e-9; v += step) out.push(Number(v.toFixed(6)));
  return out;
}

function scale(values: number[]) {
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const ticks = niceTicks(lo, hi);
  const y0 = ticks[0]!;
  const y1 = ticks[ticks.length - 1]!;
  const y = (v: number) => PAD.top + (1 - (v - y0) / (y1 - y0 || 1)) * H;
  return { ticks, y };
}

function Axis({ ticks, y, days, x }: { ticks: number[]; y: (v: number) => number; days: Day[]; x: (i: number) => number }) {
  const every = Math.max(1, Math.ceil(days.length / 8));
  return (
    <g>
      <rect x={PAD.left} y={PAD.top} width={IW} height={H} fill={SURFACE} />
      {ticks.map((t) => (
        <g key={t}>
          <line x1={PAD.left} x2={PAD.left + IW} y1={y(t)} y2={y(t)} stroke={t === 0 ? BASE : GRID} />
          <text x={PAD.left - 6} y={y(t) + 3} textAnchor="end" fontSize={10} fill={MUTED}>{money(t)}</text>
        </g>
      ))}
      {days.map((d, i) => i % every === 0 && (
        <text key={d.date} x={x(i)} y={PAD.top + H + 16} textAnchor="middle" fontSize={10} fill={MUTED}>
          {d.date.slice(5)}
        </text>
      ))}
    </g>
  );
}

function Tip({ day, at }: { day: Day; at: number }) {
  const pct = (at / W) * 100; // the SVG scales with its container, so place by percentage
  return (
    <div className="chart-tooltip" style={{ left: `${pct}%`, top: 0,
                                            transform: pct > 60 ? "translateX(-100%)" : "none" }}>
      <div>{day.date}</div>
      <div>Day: <strong>{money(Number(day.pnl))}</strong> ({day.markets} market{day.markets > 1 ? "s" : ""}, {day.wins} won)</div>
      <div>Total so far: <strong>{money(Number(day.cumulative))}</strong></div>
    </div>
  );
}

export function PnlCharts({ timeline }: { timeline: Day[] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (timeline.length < 2) {
    return <p className="muted small">The P&L charts appear once trades have closed on at least two different days.</p>;
  }
  const n = timeline.length;
  const slot = IW / n;
  const x = (i: number) => PAD.left + slot * (i + 0.5);
  const cum = timeline.map((d) => Number(d.cumulative));
  const day = timeline.map((d) => Number(d.pnl));
  const c = scale(cum);
  const b = scale(day);
  const path = cum.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${c.y(v).toFixed(1)}`).join(" ");
  const hit = (i: number) => (
    <rect key={`h${i}`} x={PAD.left + slot * i} y={PAD.top} width={slot} height={H} fill="transparent"
      onMouseEnter={() => setHover(i)} />
  );
  const last = cum[n - 1]!;

  return (
    <div className="pnl-charts">
      <figure>
        <figcaption className="small"><strong>Cumulative realized P&L</strong>
          <span className="muted"> · net of fees, by the day each market settled or was sold</span></figcaption>
        <div className="chart-wrap" onMouseLeave={() => setHover(null)}>
          <svg viewBox={`0 0 ${W} ${H + PAD.top + PAD.bottom}`} width="100%" role="img"
            aria-label={`Cumulative realized P&L over ${n} days, now ${money(last)}. Table view below.`}>
            <Axis ticks={c.ticks} y={c.y} days={timeline} x={x} />
            <path d={path} fill="none" stroke={BLUE} strokeWidth={2} strokeLinejoin="round" />
            <text x={x(n - 1) - 4} y={c.y(last) - 8} textAnchor="end" fontSize={11} fill={CHART.ink}>{money(last)}</text>
            {hover != null && (
              <g pointerEvents="none">
                <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + H} stroke={MUTED} strokeDasharray="3 3" />
                <circle cx={x(hover)} cy={c.y(cum[hover]!)} r={4.5} fill={BLUE} stroke={SURFACE} strokeWidth={2} />
              </g>
            )}
            {timeline.map((_, i) => hit(i))}
          </svg>
          {hover != null && <Tip day={timeline[hover]!} at={x(hover)} />}
        </div>
      </figure>

      <figure>
        <figcaption className="small"><strong>P&L by day</strong>{" "}
          <span className="legend"><span className="swatch" style={{ background: BLUE }} /> gain (above the line){" "}
            <span className="swatch" style={{ background: RED }} /> loss (below)</span></figcaption>
        <div className="chart-wrap" onMouseLeave={() => setHover(null)}>
          <svg viewBox={`0 0 ${W} ${H + PAD.top + PAD.bottom}`} width="100%" role="img"
            aria-label={`Daily realized P&L for ${n} days. Table view below.`}>
            <Axis ticks={b.ticks} y={b.y} days={timeline} x={x} />
            {day.map((v, i) => {
              const bw = Math.max(2, Math.min(28, slot - 2)); // 2px surface gap between bars
              const top = Math.min(b.y(v), b.y(0));
              const h = Math.abs(b.y(v) - b.y(0));
              if (h < 0.5) return null;
              const r = Math.min(4, bw / 2, h);
              const x0 = x(i) - bw / 2;
              // rounded at the data end, square at the baseline
              const d = v >= 0
                ? `M${x0},${top + h} V${top + r} Q${x0},${top} ${x0 + r},${top} H${x0 + bw - r} Q${x0 + bw},${top} ${x0 + bw},${top + r} V${top + h} Z`
                : `M${x0},${top} V${top + h - r} Q${x0},${top + h} ${x0 + r},${top + h} H${x0 + bw - r} Q${x0 + bw},${top + h} ${x0 + bw},${top + h - r} V${top} Z`;
              return <path key={i} d={d} fill={v >= 0 ? BLUE : RED} opacity={hover == null || hover === i ? 1 : 0.55} />;
            })}
            {timeline.map((_, i) => hit(i))}
          </svg>
          {hover != null && <Tip day={timeline[hover]!} at={x(hover)} />}
        </div>
      </figure>

      <details className="small">
        <summary>Show as a table</summary>
        <table className="market-table">
          <thead><tr><th scope="col">Day</th><th scope="col">Markets closed</th><th scope="col">Won</th>
            <th scope="col">Day P&L</th><th scope="col">Cumulative</th><th scope="col">By type</th></tr></thead>
          <tbody>
            {[...timeline].reverse().map((d) => (
              <tr key={d.date}>
                <td>{d.date}</td><td>{d.markets}</td><td>{d.wins}</td>
                <td>{money(Number(d.pnl))}</td><td>{money(Number(d.cumulative))}</td>
                <td>{Object.entries(d.by_type).map(([k, v]) => `${k} ${money(Number(v))}`).join(" · ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
