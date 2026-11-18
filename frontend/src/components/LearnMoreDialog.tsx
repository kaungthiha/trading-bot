import { useEffect, useId, useRef } from "react";

import { CATEGORY_LABELS, getTerm, TERMS, type TermId } from "../glossary/terms";

interface Props {
  id: TermId;
  onClose: () => void;
  onNavigate: (id: TermId) => void;
}

/**
 * Detailed definition. This is a modal DIALOG (it contains links and buttons), never an
 * ARIA tooltip. Focus moves inside on open, Tab is trapped, Escape or the backdrop closes,
 * and the provider returns focus to the triggering term.
 */
export function LearnMoreDialog({ id, onClose, onNavigate }: Props) {
  const t = getTerm(id);
  const titleId = useId();
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
  }, [id]);

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab" || !ref.current) return;
    const focusables = ref.current.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    if (focusables.length === 0) return;
    const first = focusables[0]!;
    const last = focusables[focusables.length - 1]!;
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  const related = t.relatedTermIds.filter((r): r is TermId => r in TERMS);

  return (
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={ref}
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={onKeyDown}
      >
        <header className="dialog-header">
          <h2 id={titleId}>{t.label}</h2>
          <button ref={closeRef} type="button" className="dialog-close" onClick={onClose}
            aria-label="Close definition">
            ×
          </button>
        </header>
        <p className="ticker">
          {CATEGORY_LABELS[t.category]}
          {t.aliases.length > 0 && <> · also: {t.aliases.join(", ")}</>}
        </p>
        <p>
          <strong>{t.shortDefinition}</strong>
        </p>
        <p>{t.deepExplanation}</p>
        {t.formula && (
          <p>
            <span className="muted">Formula: </span>
            <code>{t.formula}</code>
          </p>
        )}
        <p>
          <span className="muted">Example: </span>
          {t.example}
        </p>
        {related.length > 0 && (
          <div className="small">
            <span className="muted">Related: </span>
            {related.map((r) => (
              <button key={r} type="button" className="link-button related"
                onClick={() => onNavigate(r)}>
                {getTerm(r).label}
              </button>
            ))}
          </div>
        )}
        {t.sourceUrls && t.sourceUrls.length > 0 && (
          <div className="small">
            <span className="muted">Sources: </span>
            {t.sourceUrls.map((u) => (
              <a key={u} href={u} target="_blank" rel="noopener noreferrer" className="source-link">
                {new URL(u).hostname}
              </a>
            ))}
          </div>
        )}
        <p className="small">
          <a href={`#/glossary?term=${t.id}`} onClick={onClose}>
            Open in glossary
          </a>
          <span className="muted"> · reviewed {t.reviewedAt}</span>
        </p>
      </div>
    </div>
  );
}
