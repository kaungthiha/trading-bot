import type { ElementType, ReactNode } from "react";

/** Layout primitives for the Walnut Atelier theme. Presentational only: no data fetching
 * and no financial maths; callers pass values the backend already computed. */

export function Surface({ as: Tag = "div", inset = false, flush = false, className = "",
  children, ...rest }: {
  as?: ElementType; inset?: boolean; flush?: boolean; className?: string; children: ReactNode;
  [aria: `aria-${string}`]: string | undefined }) {
  const cls = ["surface", inset && "inset", flush && "flush", className].filter(Boolean).join(" ");
  return <Tag className={cls} {...rest}>{children}</Tag>;
}

/** Etched 1px rule. Decorative unless `label` is given (then it's a real separator). */
export function HairlineDivider({ strong = false, label }: { strong?: boolean; label?: string }) {
  return label
    ? <hr className={`etched${strong ? " strong" : ""}`} aria-label={label} />
    : <hr className={`etched${strong ? " strong" : ""}`} aria-hidden="true" />;
}

/** One labelled number. `sign` adds the +/- colour AND keeps the sign in the text, so
 * meaning never rests on colour alone. */
export function Metric({ label, value, sub, sign }: {
  label: ReactNode; value: ReactNode; sub?: ReactNode; sign?: "pos" | "neg" }) {
  return (
    <div className="metric">
      <span className="metric-label">{label}</span>
      <span className={`metric-value${sign ? ` ev-${sign}` : ""}`}>{value}</span>
      {sub && <span className="metric-sub">{sub}</span>}
    </div>
  );
}
