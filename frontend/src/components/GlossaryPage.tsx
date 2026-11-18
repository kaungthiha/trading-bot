import { useEffect, useMemo, useRef, useState } from "react";

import { useGlossary } from "../glossary/GlossaryContext";
import {
  ALL_TERMS,
  CATEGORY_LABELS,
  searchTerms,
  type TermCategory,
  type TermId,
} from "../glossary/terms";
import { Term } from "./Term";

export function GlossaryPage({ focusTerm }: { focusTerm?: string | null }) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<TermCategory | "">("");
  const results = useMemo(() => searchTerms(query, category || undefined), [query, category]);
  const { openDetail } = useGlossary();
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (focusTerm) {
      document.getElementById(`term-${focusTerm}`)?.scrollIntoView?.({ block: "center" });
    } else {
      headingRef.current?.focus();
    }
  }, [focusTerm]);

  return (
    <section className="panel glossary" aria-labelledby="glossary-h">
      <h2 id="glossary-h" ref={headingRef} tabIndex={-1}>
        Glossary
      </h2>
      <p className="small muted">
        {ALL_TERMS.length} terms. Definitions are educational, not trade recommendations. The
        same definitions power every tooltip in the app.
      </p>

      <section aria-labelledby="examples-h" className="examples">
        <h3 id="examples-h">Try it</h3>
        <p className="small">
          Hover or focus a dotted term for a short definition; click, tap or press Enter for the
          full explanation. Press Escape to dismiss.
        </p>
        <ul className="small">
          <li>
            A signal&apos;s <Term id="edge">edge</Term> is what is left after the ask, fees and
            slippage are subtracted from the model probability.
          </li>
          <li>
            Buying 50 contracts can cost more per contract than buying 5 because of{" "}
            <Term id="slippage">slippage</Term> through the order book.
          </li>
          <li>
            A lower <Term id="brier-score">Brier score</Term> means better probability forecasts;
            always guessing 50% scores 0.25.
          </li>
        </ul>
      </section>

      <form className="filters" role="search" onSubmit={(e) => e.preventDefault()}>
        <label>
          Search terms
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. spread, EV, holdout" maxLength={60} />
        </label>
        <label>
          Category
          <select value={category} onChange={(e) => setCategory(e.target.value as TermCategory | "")}>
            <option value="">All</option>
            {(Object.keys(CATEGORY_LABELS) as TermCategory[]).map((c) => (
              <option key={c} value={c}>
                {CATEGORY_LABELS[c]}
              </option>
            ))}
          </select>
        </label>
      </form>
      <p className="small muted" role="status" aria-live="polite">
        {results.length} {results.length === 1 ? "term" : "terms"} shown
      </p>

      <dl className="glossary-list">
        {results.map((t) => (
          <div key={t.id} id={`term-${t.id}`}
            className={`glossary-item${focusTerm === t.id ? " highlighted" : ""}`}>
            <dt>
              {t.label}{" "}
              <span className="ticker">
                {CATEGORY_LABELS[t.category]}
                {t.aliases.length > 0 && <> · {t.aliases.join(", ")}</>}
              </span>
            </dt>
            <dd>
              <p>{t.shortDefinition}</p>
              <p className="small muted">Example: {t.example}</p>
              <button type="button" className="link-button small"
                onClick={(e) => openDetail(t.id as TermId, e.currentTarget)}>
                Learn more about {t.label}
              </button>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
