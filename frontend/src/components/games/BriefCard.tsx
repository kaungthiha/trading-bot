import type { Brief, BriefLean } from "../../api/types";
import { Tip } from "../design/Tip";

export const LEAN: Record<BriefLean, { text: string; cls: string; tip: string }> = {
  strong: { text: "strong case", cls: "v-ok", tip: "Several facts point this way and at most one against. A lead to research, not a forecast." },
  mixed: { text: "mixed", cls: "v-thin", tip: "Facts point both ways, or not enough of them point one way." },
  weak: { text: "weak case", cls: "v-down", tip: "More facts point against this side than for it." },
  thin: { text: "thin data", cls: "v-thin", tip: "Too few games on record to judge." },
  avoid: { text: "avoid", cls: "v-down", tip: "The player is listed out or doubtful." },
};

export function LeanChip({ lean }: { lean: BriefLean }) {
  const l = LEAN[lean];
  return <Tip text={l.tip} className={`verdict ${l.cls}`}>{l.text}</Tip>;
}

/** The case for and against one leg. Facts only, each with its numbers; no probability. */
export function BriefCard({ brief, compact = false }: { brief: Brief; compact?: boolean }) {
  return (
    <div className="brief" aria-label="Brief: the case for and against">
      <p className="brief-head"><LeanChip lean={brief.lean} /> <span className="small">{brief.headline}</span></p>
      {brief.for.length > 0 && (
        <ul className="brief-list for" aria-label="For">
          {brief.for.map((p) => <li key={p.text}><span aria-hidden="true">+</span> {p.text}</li>)}
        </ul>
      )}
      {brief.against.length > 0 && (
        <ul className="brief-list against" aria-label="Against">
          {brief.against.map((p) => <li key={p.text}><span aria-hidden="true">−</span> {p.text}</li>)}
        </ul>
      )}
      {!compact && brief.context.length > 0 && (
        <details className="brief-more small">
          <summary>{brief.context.length} more fact{brief.context.length > 1 ? "s" : ""} (neutral)</summary>
          <ul className="brief-list context">
            {brief.context.map((p) => <li key={p.text}><span aria-hidden="true">·</span> {p.text}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}
