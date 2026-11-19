import { href, type Section } from "../../router";
import { Glyph, type GlyphName } from "./Glyph";

/** Task-based sections (audit P1). Old URLs still resolve to the same pages (see router.ts);
 * Docket joins in Phase 3. Tools holds the former Terminal tabs, below the line. */
export const NAV: { id: Section; href: string; label: string; glyph: GlyphName }[] = [
  { id: "today", href: href.today(), label: "Today", glyph: "today" },
  { id: "explore", href: "#/games", label: "Explore", glyph: "explore" },
  { id: "journal", href: href.journal(), label: "Journal", glyph: "history" },
  { id: "learn", href: href.learn(), label: "Learn", glyph: "glossary" },
];
export const UTILITY = { id: "tools" as const, href: href.tools(), label: "Tools", glyph: "terminal" as const };

/** Walnut rail on desktop and tablet; a bottom bar on phones (same element, CSS only). */
export function LeftRail({ section }: { section: Section }) {
  const item = (n: { id: Section; href: string; label: string; glyph: GlyphName }) => (
    <li key={n.id}>
      <a href={n.href} className="app-rail-link" aria-current={section === n.id ? "page" : undefined}>
        <Glyph name={n.glyph} />
        <span>{n.label}</span>
      </a>
    </li>
  );
  return (
    <nav aria-label="Primary" className="app-rail wood">
      <span className="app-rail-mark display" aria-hidden="true">KR</span>
      <hr className="etched app-rail-rule" aria-hidden="true" />
      <ul>
        {NAV.map(item)}
        <li className="app-rail-sep" aria-hidden="true"><hr className="etched" /></li>
        {item(UTILITY)}
      </ul>
    </nav>
  );
}
