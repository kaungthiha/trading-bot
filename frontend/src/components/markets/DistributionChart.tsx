import { useState } from "react";

import type { LadderBucket } from "../../api/types";

// Implied distribution as bars. Single series (no legend: the caption names it). Colours
// reuse the validated chart palette from CalibrationChart (series #2a78d6 on #fcfcfb,
// muted ink #898781, recessive grid #e6e5e1). The strike table beside it is the table view.
const SERIES = "#2a78d6";
const MUTED = "#898781";
const GRID = "#e6e5e1";
const H = 150;
const PAD = { left: 36, right: 8, top: 8, bottom: 30 };

function barPath(x: number, y: number, w: number, h: number): string {
  const r = Math.min(4, w / 2, h);
  return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`;
}

export function DistributionChart({ title, buckets }: { title: string; buckets: LadderBucket[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const n = buckets.length;
  const slot = Math.max(10, Math.min(28, 640 / Math.max(n, 1)));
  const W = PAD.left + PAD.right + slot * n;
  const max = Math.max(0.01, ...buckets.map((b) => b.p));
  const top = Math.ceil(max * 20) / 20; // round the axis up to 5%
  const y = (p: number) => PAD.top + (1 - p / top) * H;
  const every = Math.ceil(n / 10); // ~10 x labels at most
  const h = hover != null ? buckets[hover] : undefined;

  return (
    <figure className="distribution">
      <figcaption className="small">
        <strong>{title}</strong>
        <span className="muted"> · probability of each range, read from the market prices</span>
      </figcaption>
      <div className="chart-wrap">
        <svg width={W} height={H + PAD.top + PAD.bottom} role="img"
          aria-label={`${title}: implied probability across ${n} ranges. The strike table lists the same numbers.`}
          onMouseLeave={() => setHover(null)}>
          <rect x={PAD.left} y={PAD.top} width={slot * n} height={H} fill="#fcfcfb" />
          {[0, top / 2, top].map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={PAD.left + slot * n} y1={y(t)} y2={y(t)} stroke={GRID} />
              <text x={PAD.left - 4} y={y(t) + 3} textAnchor="end" fontSize={10} fill={MUTED}>
                {Math.round(t * 100)}%
              </text>
            </g>
          ))}
          {buckets.map((b, i) => {
            const x = PAD.left + i * slot + 1; // 2px surface gap between bars
            const bh = Math.max(0, y(0) - y(b.p));
            return (
              <g key={b.label} onMouseEnter={() => setHover(i)}>
                <rect x={PAD.left + i * slot} y={PAD.top} width={slot} height={H} fill="transparent" />
                {bh > 0 && (
                  <path d={barPath(x, y(b.p), slot - 2, bh)} fill={SERIES}
                    opacity={hover == null || hover === i ? 1 : 0.55} />
                )}
                {i % every === 0 && b.hi != null && (
                  <text x={PAD.left + (i + 1) * slot} y={y(0) + 13} textAnchor="middle" fontSize={10}
                    fill={MUTED}>
                    {b.hi}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
        {h && hover != null && (
          <div className="chart-tooltip" style={{ left: PAD.left + hover * slot + slot, top: 4 }}>
            {h.label}: <strong>{(h.p * 100).toFixed(1)}%</strong>
          </div>
        )}
      </div>
    </figure>
  );
}
