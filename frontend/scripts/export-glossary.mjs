// Serialise the typed glossary registry (src/glossary/terms.ts) to JSON for the backend's
// GET /api/glossary, so there is exactly one editorial source. Run: npm run glossary:export
// A vitest check fails if backend/app/glossary.json is out of date.
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { serializeGlossary } from "../src/glossary/serialize.ts";

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, "..", "..", "backend", "app", "glossary.json");
writeFileSync(out, serializeGlossary(), "utf8");
console.log(`Wrote ${out}`);
