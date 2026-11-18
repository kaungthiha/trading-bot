import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from "react";

import { useGlossary } from "../glossary/GlossaryContext";
import { getTerm, type TermId } from "../glossary/terms";

// Grace period before a hover-opened tooltip closes, so moving the pointer from the term
// onto the tooltip (or briefly off it) doesn't dismiss it prematurely.
export const TOOLTIP_CLOSE_DELAY_MS = 150;

interface TermProps {
  id: TermId;
  children: ReactNode;
}

/**
 * Accessible glossary trigger (W3C APG tooltip pattern + WCAG 1.4.13):
 *  - hover or keyboard focus shows a short, NON-interactive tooltip (role="tooltip");
 *  - the tooltip is hoverable (moving the pointer onto it keeps it open) and persistent;
 *  - Escape dismisses it without moving focus;
 *  - click / tap / Enter / Space opens the detailed dialog (works without hover on touch).
 * Links and controls live only in the dialog, never in the tooltip.
 */
export function Term({ id, children }: TermProps) {
  const entry = getTerm(id);
  const tooltipId = useId();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLSpanElement>(null);
  const lastPointer = useRef<string>("mouse");
  const { openDetail } = useGlossary();
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function cancelClose() {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closeTimer.current = null;
  }
  function show() {
    cancelClose();
    setOpen(true);
  }
  function hide() {
    cancelClose();
    setOpen(false);
  }
  function scheduleClose() {
    cancelClose();
    closeTimer.current = setTimeout(() => setOpen(false), TOOLTIP_CLOSE_DELAY_MS);
  }
  useEffect(() => cancelClose, []);

  function openDialog() {
    hide();
    openDetail(id, triggerRef.current);
  }

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === "Escape") {
      hide();
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openDialog();
    }
  }

  function onPointerEnter(e: PointerEvent) {
    lastPointer.current = e.pointerType;
    if (e.pointerType !== "touch") show(); // touch users get the dialog on tap
  }

  return (
    <span className="term-wrap" onPointerEnter={onPointerEnter} onMouseEnter={() => {
      if (lastPointer.current !== "touch") show();
    }} onMouseLeave={scheduleClose}>
      <span
        ref={triggerRef}
        className="term"
        role="button"
        tabIndex={0}
        aria-haspopup="dialog"
        data-term-id={id}
        aria-describedby={open ? tooltipId : undefined}
        onFocus={show}
        onBlur={hide}
        onKeyDown={onKeyDown}
        onClick={openDialog}
      >
        {children}
      </span>
      {open && (
        <span role="tooltip" id={tooltipId} className="tooltip" onMouseEnter={cancelClose}
          onMouseLeave={scheduleClose}>
          {entry.shortDefinition}
          <span className="tooltip-hint"> (click for more)</span>
        </span>
      )}
    </span>
  );
}
