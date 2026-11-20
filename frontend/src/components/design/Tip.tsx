import { type ReactNode, useEffect, useId, useRef, useState } from "react";

import { TOOLTIP_CLOSE_DELAY_MS } from "../Term";

/** A short explanation on a label, for things that aren't glossary terms (use <Term> for
 * those). Replaces native `title`, which never shows on touch and isn't read reliably.
 *  - hover or keyboard focus shows it; the tooltip itself is hoverable (WCAG 1.4.13);
 *  - tap (touch) or Enter/Space toggles it;
 *  - Escape closes it and keeps focus on the trigger; tapping elsewhere closes it.
 * The text is plain (no links or controls inside a tooltip). */
export function Tip({ text, children, className = "" }: { text: string; children: ReactNode; className?: string }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLSpanElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const touch = useRef(false);

  const cancel = () => { if (timer.current) clearTimeout(timer.current); timer.current = null; };
  const show = () => { cancel(); setOpen(true); };
  const later = () => { cancel(); timer.current = setTimeout(() => setOpen(false), TOOLTIP_CLOSE_DELAY_MS); };
  useEffect(() => cancel, []);
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  return (
    <span ref={wrap} className={`tip-wrap ${className}`}
      onPointerEnter={(e) => { touch.current = e.pointerType === "touch"; if (!touch.current) show(); }}
      onMouseLeave={later}>
      <button ref={btn} type="button" className="tip" aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onFocus={() => { if (!touch.current) show(); }}
        onBlur={() => setOpen(false)}
        onClick={() => { cancel(); setOpen((o) => (touch.current ? !o : true)); }}
        onKeyDown={(e) => {
          if (e.key === "Escape" && open) { e.stopPropagation(); setOpen(false); btn.current?.focus(); }
        }}>
        {children}
      </button>
      {open && <span role="tooltip" id={id} className="tooltip" onMouseEnter={cancel} onMouseLeave={later}>{text}</span>}
    </span>
  );
}
