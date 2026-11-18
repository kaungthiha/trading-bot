import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { ALL_TERMS, TERMS, getTerm } from "./terms";

// Vitest runs from the frontend root (jsdom makes import.meta.url non-file).
const SRC = join(process.cwd(), "src");

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

describe("glossary registry", () => {
  it("keys match entry ids (no duplicates)", () => {
    for (const [key, entry] of Object.entries(TERMS)) expect(entry.id).toBe(key);
  });

  it("entries have non-empty short definitions within length budget", () => {
    for (const t of ALL_TERMS) {
      expect(t.shortDefinition.trim().length).toBeGreaterThan(0);
      expect(t.shortDefinition.length).toBeLessThanOrEqual(200);
      expect(t.category).toBeTruthy();
      expect(t.example.trim().length).toBeGreaterThan(0);
    }
  });

  it("related term ids exist", () => {
    for (const t of ALL_TERMS) for (const r of t.relatedTermIds) expect(TERMS).toHaveProperty(r);
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
    expect(used.size).toBeGreaterThan(0);
    for (const id of used) expect(TERMS, `unknown term id "${id}"`).toHaveProperty(id);
  });
});
