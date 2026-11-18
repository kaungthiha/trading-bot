import { useState } from "react";

import type { CalibrationBin } from "../api/types";

// Reliability diagram. Single series (no legend: the title names it). Colour: categorical
// slot 1 (#2a78d6), validated against the #fcfcfb chart surface with the dataviz
// validator (all checks pass). Muted ink #898781 for axes/reference; recessive grid.
const SERIES = "#2a78d6";
const MUTED = "#898781";
const GRID = "#e6e5e1";
const SIZE = 220;
const PAD = { left: 40, right: 12, top: 10, bottom: 34 };
const W = SIZE + PAD.left + PAD.right;
const H = SIZE + PAD.top + PAD.bottom;

const x = (p: number) => PAD.left + p * SIZE;
const y = (p: number) => PAD.top + (1 - p) * SIZE;
const pct = (p: number) => `${Math.round(p * 100)}%`;

interface Props {
  title: string;
  bins: CalibrationBin[];
}

export function CalibrationChart({ title, bins }: Props) {
  const pts = bins.filter((b) => b.count > 0 && b.mean_p != null && b.observed_rate != null);
  const [hover, setHover] = useState<number | null>(null);
  const maxCount = Math.max(1, ...pts.map((b) => b.count));
  const h = hover != null ? pts[hover] : undefined;

  return (
    <figure className="calibration">
      <figcaption className="small">
        <strong>{title}</strong>
        <span className="muted"> · forecast probability vs observed YES rate; dashed line = perfect calibration</span>
      </figcaption>
      {pts.length === 0 ? (
        <p className="muted small">No resolved forecasts to plot yet.</p>
      ) : (
        <div className="chart-wrap">
          <svg
            width={W}
            height={H}
            viewBox={`0 0 ${W} ${H}`}
            role="img"
            aria-label={`${title}: ${pts.length} bins. Table view below.`}
          >
            <rect x={PAD.left} y={PAD.top} width={SIZE} height={SIZE} fill="#fcfcfb" />
            {[0, 0.25, 0.5, 0.75, 1].map((t) => (
              <g key={t}>
                <line x1={x(t)} x2={x(t)} y1={y(0)} y2={y(1)} stroke={GRID} strokeWidth={1} />
                <line x1={x(0)} x2={x(1)} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth={1} />
                <text x={x(t)} y={y(0) + 14} textAnchor="middle" fontSize={10} fill={MUTED}>
                  {pct(t)}
                </text>
                <text x={x(0) - 6} y={y(t) + 3} textAnchor="end" fontSize={10} fill={MUTED}>
                  {pct(t)}
                </text>
              </g>
            ))}
            <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} stroke={MUTED} strokeWidth={1.5}
              strokeDasharray="4 4" />
            <text x={x(0.5)} y={H - 4} textAnchor="middle" fontSize={10} fill={MUTED}>
              Mean forecast
            </text>
            <text x={10} y={y(0.5)} textAnchor="middle" fontSize={10} fill={MUTED}
              transform={`rotate(-90 10 ${y(0.5)})`}>
              Observed
            </text>
            {pts.map((b, i) => {
              // Marker area grows with sample size (>= 8px diameter), so thin bins read as thin.
              const r = 4 + 4 * Math.sqrt(b.count / maxCount);
              return (
                <g key={b.lower}>
                  <circle cx={x(b.mean_p!)} cy={y(b.observed_rate!)} r={r} fill={SERIES}
                    stroke="#fcfcfb" strokeWidth={2} />
                  {/* Hit target larger than the mark. */}
                  <circle
                    cx={x(b.mean_p!)}
                    cy={y(b.observed_rate!)}
                    r={Math.max(12, r + 4)}
                    fill="transparent"
                    tabIndex={0}
                    aria-label={`Bin ${pct(b.lower)} to ${pct(b.upper)}: ${b.count} forecasts, mean ${pct(b.mean_p!)}, observed ${pct(b.observed_rate!)}`}
                    onMouseEnter={() => setHover(i)}
                    onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover(i)}
                    onBlur={() => setHover(null)}
                  />
                </g>
              );
            })}
          </svg>
          {h && (
            <div className="chart-tooltip" role="status"
              style={{ left: x(h.mean_p!) + 14, top: y(h.observed_rate!) - 10 }}>
              <div className="ticker">
                bin {pct(h.lower)}–{pct(h.upper)}
              </div>
              <div>
                {h.count} forecasts · mean {pct(h.mean_p!)} · observed {pct(h.observed_rate!)}
              </div>
            </div>
          )}
        </div>
      )}
    </figure>
  );
}
