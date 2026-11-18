// Fail if the production bundle contains anything secret-like. Run after `npm run build`.
// Checks generic patterns AND the actual non-empty key values from the repo's .env
// (values are never printed).
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");
if (!existsSync(dist)) {
  console.error("dist/ not found; run `npm run build` first");
  process.exit(2);
}

const patterns = [
  [/KRT_[A-Z0-9_]+/, "backend env variable name"],
  [/-----BEGIN [A-Z ]*PRIVATE KEY-----/, "PEM private key"],
  [/kalshi-access-(key|signature)/i, "Kalshi auth header"],
  [/api[_-]?key\s*[:=]\s*["'][^"']+["']/i, "inline API key"],
];

const secrets = [];
const envFile = join(root, "..", ".env");
if (existsSync(envFile)) {
  for (const line of readFileSync(envFile, "utf8").split(/\r?\n/)) {
    const m = /^\s*(KRT_[A-Z0-9_]*(KEY|SECRET|TOKEN|PASSWORD|AGENT)[A-Z0-9_]*)\s*=\s*(.+?)\s*$/.exec(line);
    if (m && m[3] && !m[3].startsWith("#") && m[3].length >= 8) secrets.push([m[1], m[3]]);
  }
}

function walk(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

let failures = 0;
for (const file of walk(dist)) {
  const text = readFileSync(file, "utf8");
  for (const [re, what] of patterns) {
    if (re.test(text)) {
      console.error(`FAIL ${relative(root, file)}: contains ${what}`);
      failures++;
    }
  }
  for (const [name, value] of secrets) {
    if (text.includes(value)) {
      console.error(`FAIL ${relative(root, file)}: contains the value of ${name}`);
      failures++;
    }
  }
}
const html = readFileSync(join(dist, "index.html"), "utf8");
if (!html.includes("Content-Security-Policy")) {
  console.error("FAIL dist/index.html: missing Content-Security-Policy");
  failures++;
}
if (failures) process.exit(1);
console.log(`Bundle clean: ${walk(dist).length} files scanned, ${secrets.length} .env secret value(s) checked, CSP present.`);
