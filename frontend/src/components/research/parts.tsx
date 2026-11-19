import { type ReactNode, useState } from "react";

import { href } from "../../router";

/** Where you are, as links back. The last crumb is the page itself (not a link). */
export function Breadcrumbs({ trail }: { trail: { label: string; href?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="crumbs">
      <ol>
        <li><a href={href.today()}>Today</a></li>
        {trail.map((c, i) => (
          <li key={`${c.label}-${i}`}>
            {c.href && i < trail.length - 1 ? <a href={c.href}>{c.label}</a>
              : <span aria-current={i === trail.length - 1 ? "page" : undefined}>{c.label}</span>}
          </li>
        ))}
      </ol>
    </nav>
  );
}

/** Copies this page's link. The link holds only public ids (no prices, no account data). */
export function CopyLink() {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const copy = () => {
    const url = window.location.href;
    const done = () => setState("copied");
    const fail = () => setState("failed");
    try {
      if (navigator.clipboard?.writeText) navigator.clipboard.writeText(url).then(done, fail);
      else fail();
    } catch { fail(); }
  };
  return (
    <span className="copy-link">
      <button type="button" className="ghost-button" onClick={copy}>Copy link</button>
      <span role="status" className="small muted">
        {state === "copied" ? "Link copied." : state === "failed" ? "Couldn't copy; use the address bar." : ""}
      </span>
    </span>
  );
}

/** Layer 1 / 2 / 3 of progressive disclosure. Layer 1 is always open. */
export function Layer({ n, title, open, children, id }: {
  n: 1 | 2 | 3; title: string; open?: boolean; children: ReactNode; id: string }) {
  if (n === 1) {
    return (
      <section className="rs-layer rs-l1" aria-labelledby={id}>
        <h3 id={id}>{title}</h3>
        {children}
      </section>
    );
  }
  return (
    <details className={`rs-layer rs-l${n}`} open={open}>
      <summary><h3 id={id}>{title}</h3></summary>
      <div role="group" aria-labelledby={id}>{children}</div>
    </details>
  );
}

/** Material risks: never inside a collapsed layer. */
export function BeforeActing({ items, title = "Before acting" }: { items: string[]; title?: string }) {
  if (items.length === 0) return null;
  return (
    <section className="warning-box rs-before" aria-label={title}>
      <strong>{title}</strong>
      <ul>{items.map((t) => <li key={t}>{t}</li>)}</ul>
    </section>
  );
}

export function Metric({ label, value, sub, sign }: {
  label: ReactNode; value: ReactNode; sub?: ReactNode; sign?: "pos" | "neg" | null }) {
  return (
    <div className="metric">
      <span className="metric-label">{label}</span>
      <span className={`metric-value${sign ? ` ev-${sign}` : ""}`}>{value}</span>
      {sub && <span className="metric-sub">{sub}</span>}
    </div>
  );
}

export const money = (s: string | null | undefined) => {
  if (s == null || s === "") return "—";
  const n = Number(s);
  if (Number.isNaN(n)) return "—";
  return `${n < 0 ? "−" : ""}$${Math.abs(n).toFixed(2)}`;
};
export const centsOf = (s: string | number | null | undefined, digits = 1) => {
  if (s == null || s === "") return "—";
  const n = Number(s);
  return Number.isNaN(n) ? "—" : `${(n * 100).toFixed(digits)}¢`;
};
export const signOf = (s: string | null | undefined): "pos" | "neg" | null => {
  const n = Number(s);
  return s == null || Number.isNaN(n) || n === 0 ? null : n > 0 ? "pos" : "neg";
};
