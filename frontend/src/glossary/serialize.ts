import { TERMS } from "./terms.ts";

/** Deterministic JSON form of the registry (sorted by id, stable formatting). */
export function serializeGlossary(): string {
  const terms = Object.values(TERMS)
    .map((t) => ({ ...t }))
    .sort((a, b) => a.id.localeCompare(b.id));
  return `${JSON.stringify({ source: "frontend/src/glossary/terms.ts", count: terms.length, terms }, null, 2)}\n`;
}
