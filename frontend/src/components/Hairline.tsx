import { basket, cabinet, loupe, plot, plug, riffle, sieve, stack, terrain, vault } from "@lucasmarkes/hairline";
import type { ReactNode } from "react";
import { useEffect, useRef } from "react";

/** Hairline line figures (MIT, no dependencies, no network): the app's visual signature.
 * Each answers the pointer. Decorative, so hidden from screen readers next to real text.
 * Mounted through the plain-JS API so only the figures named here are bundled. */
const FIGURES = { basket, cabinet, loupe, plot, plug, riffle, sieve, stack, terrain, vault } as const;
export type FigureName = keyof typeof FIGURES;

const canDraw = () =>
  typeof window !== "undefined" && typeof window.matchMedia === "function"
  && typeof IntersectionObserver !== "undefined";

export function Figure({ name, size = 150, play = false }: { name: FigureName; size?: number; play?: boolean }) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!el.current || !canDraw()) return;
    let fig: { destroy: () => void } | null = null;
    try {
      fig = FIGURES[name](el.current, { theme: "light", intensity: 0.6, play });
    } catch {
      return; // decoration only: never break the page over a drawing
    }
    return () => fig?.destroy();
  }, [name, play]);
  return <div ref={el} className="hl-figure" style={{ width: size }} aria-hidden="true" />;
}

export function EmptyState({ figure, title, children }: {
  figure: FigureName; title: string; children?: ReactNode }) {
  return (
    <div className="empty-state">
      <Figure name={figure} />
      <p className="empty-title">{title}</p>
      {children && <div className="small muted">{children}</div>}
    </div>
  );
}

/** Page title with its figure: one line of purpose, optional actions on the right. */
export function PageHead({ figure, title, children, actions }: {
  figure: FigureName; title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <Figure name={figure} size={84} />
      <div>
        <h2>{title}</h2>
        {children && <p>{children}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}
