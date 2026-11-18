import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

import { LearnMoreDialog } from "../components/LearnMoreDialog";
import type { TermId } from "./terms";

interface GlossaryCtx {
  openDetail: (id: TermId, returnFocusTo?: HTMLElement | null) => void;
}

const Ctx = createContext<GlossaryCtx | null>(null);

/** Hosts the single detailed-definition dialog and restores focus when it closes. */
export function GlossaryProvider({ children }: { children: ReactNode }) {
  const [openId, setOpenId] = useState<TermId | null>(null);
  const returnFocus = useRef<HTMLElement | null>(null);

  const openDetail = useCallback((id: TermId, from?: HTMLElement | null) => {
    if (from !== undefined) returnFocus.current = from;
    setOpenId(id);
  }, []);

  const close = useCallback(() => {
    setOpenId(null);
    const el = returnFocus.current;
    returnFocus.current = null;
    // Return focus to the trigger after the dialog unmounts.
    if (el) setTimeout(() => el.focus(), 0);
  }, []);

  const value = useMemo(() => ({ openDetail }), [openDetail]);
  return (
    <Ctx.Provider value={value}>
      {children}
      {openId && (
        <LearnMoreDialog id={openId} onClose={close} onNavigate={(id) => setOpenId(id)} />
      )}
    </Ctx.Provider>
  );
}

export function useGlossary(): GlossaryCtx {
  const ctx = useContext(Ctx);
  // Outside a provider (isolated component tests) the detail view is simply unavailable.
  return ctx ?? { openDetail: () => undefined };
}
