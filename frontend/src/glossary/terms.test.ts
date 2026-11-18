import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { serializeGlossary } from "./serialize";
import { ALL_TERMS, TERMS, getTerm, searchTerms } from "./terms";

// Vitest runs from the frontend root (jsdom makes import.meta.url non-file).
const SRC = join(process.cwd(), "src");
const SPEC_GLOSSARY = join(process.cwd(), "..", "kalshi_research_terminal_fable_package_2026-11-18",
  "kalshi_research_terminal_fable_package", "docs", "GLOSSARY.md");
const EXPORTED = join(process.cwd(), "..", "backend", "app", "glossary.json");

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

/** Parse docs/GLOSSARY.md: ## `id` / **Meaning:** ... / **Example:** ... */
function specEntries(): Map<string, { meaning: string; example: string }> {
  const text = readFileSync(SPEC_GLOSSARY, "utf8");
  const out = new Map<string, { meaning: string; example: string }>();
  for (const block of text.split(/^## `/m).slice(1)) {
    const id = block.slice(0, block.indexOf("`"));
    const meaning = /\*\*Meaning:\*\* (.+)/.exec(block)?.[1]?.trim() ?? "";
    const example = /\*\*Example:\*\* (.+)/.exec(block)?.[1]?.trim() ?? "";
    out.set(id, { meaning, example });
  }
  return out;
}

describe("glossary registry", () => {
  it("has at least 42 terms and keys match ids", () => {
    expect(ALL_TERMS.length).toBeGreaterThanOrEqual(42);
    for (const [key, entry] of Object.entries(TERMS)) expect(entry.id).toBe(key);
  });

  it("covers every canonical spec term without diverging from its wording", () => {
    const spec = specEntries();
    expect(spec.size).toBe(42);
    for (const [id, { meaning, example }] of spec) {
      expect(TERMS, `missing canonical term ${id}`).toHaveProperty(id);
      const t = TERMS[id as keyof typeof TERMS];
      expect(t.shortDefinition.startsWith(meaning), `${id} short definition diverges`).toBe(true);
      expect(t.example, `${id} example diverges`).toBe(example);
    }
  });

  it("every entry is complete and within the length budget", () => {
    for (const t of ALL_TERMS) {
      expect(t.shortDefinition.trim().length).toBeGreaterThan(0);
      expect(t.shortDefinition.length, t.id).toBeLessThanOrEqual(200);
      expect(t.example.trim().length).toBeGreaterThan(0);
      expect(t.deepExplanation.length, t.id).toBeGreaterThan(80);
      expect(t.reviewedAt).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      for (const u of t.sourceUrls ?? []) expect(u).toMatch(/^https:\/\//);
    }
  });

  it("related term ids exist and do not self-reference", () => {
    for (const t of ALL_TERMS) {
      for (const r of t.relatedTermIds) {
        expect(TERMS, `${t.id} -> ${r}`).toHaveProperty(r);
        expect(r).not.toBe(t.id);
      }
    }
  });

  it("aliases and labels do not collide across terms", () => {
    const seen = new Map<string, string>();
    for (const t of ALL_TERMS) {
      for (const name of [t.label, ...t.aliases].map((s) => s.toLowerCase())) {
        const owner = seen.get(name);
        expect(owner === undefined || owner === t.id, `"${name}" used by ${owner} and ${t.id}`).toBe(true);
        seen.set(name, t.id);
      }
    }
  });

  it("rejects unknown term ids at compile time", () => {
    // @ts-expect-error -- "not-a-term" is not a TermId; typecheck fails if this compiles.
    expect(() => getTerm("not-a-term").label).toThrow();
  });

  it("every <Term id> / termId used in source exists in the registry", () => {
    const used = new Set<string>();
    for (const file of walk(SRC).filter((f) => f.endsWith(".tsx") && !f.includes(".test."))) {
      const text = readFileSync(file, "utf8");
      for (const m of text.matchAll(/<Term\s+id="([^"]+)"/g)) used.add(m[1]!);
      for (const m of text.matchAll(/termId="([^"]+)"/g)) used.add(m[1]!);
    }
    expect(used.size).toBeGreaterThan(10);
    for (const id of used) expect(TERMS, `unknown term id "${id}"`).toHaveProperty(id);
  });

  it("search matches labels, aliases, ids and categories", () => {
    expect(searchTerms("EV").map((t) => t.id)).toContain("expected-value");
    expect(searchTerms("holdout").map((t) => t.id)).toContain("out-of-sample");
    expect(searchTerms("  SPREAD ").map((t) => t.id)).toContain("spread");
    const risk = searchTerms("", "risk");
    expect(risk.length).toBeGreaterThan(3);
    expect(risk.every((t) => t.category === "risk")).toBe(true);
    expect(searchTerms("zzzz-nothing")).toEqual([]);
  });

  it("backend copy (backend/app/glossary.json) is in sync -- run `npm run glossary:export`", () => {
    expect(readFileSync(EXPORTED, "utf8").replace(/\r\n/g, "\n")).toBe(serializeGlossary());
  });
});
