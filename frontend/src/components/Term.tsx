import { useId, useState, type ReactNode } from "react";

import { getTerm, type TermId } from "../glossary/terms";

interface TermProps {
  id: TermId;
  children: ReactNode;
}

/**
 * Accessible glossary trigger. Hover or keyboard focus shows a short, non-interactive
 * tooltip (role="tooltip"); Escape dismisses it while keeping focus on the trigger.
 * Placeholder for milestone 07, which adds the touch/click detail dialog ("Learn more").
 */
export function Term({ id, children }: TermProps) {
  const entry = getTerm(id);
  const tooltipId = useId();
  const [open, setOpen] = useState(false);

  return (
    <span className="term-wrap" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <span
        className="term"
        tabIndex={0}
        data-term-id={id}
        aria-describedby={open ? tooltipId : undefined}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
      >
        {children}
      </span>
      {open && (
        <span role="tooltip" id={tooltipId} className="tooltip">
          {entry.shortDefinition}
        </span>
      )}
    </span>
  );
}
