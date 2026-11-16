// Prints the CSP source ("sha256-<base64>") of the single inline classic script in a built HTML file.
// Used by frontend/Dockerfile so the portal CSP can allow the theme bootstrap without 'unsafe-inline'.
// Exits non-zero when there is no inline script or more than one: the CSP must be reviewed then.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const file = process.argv[2];
if (!file) {
  console.error("usage: inline-script-hash.mjs <built index.html>");
  process.exit(2);
}
const html = readFileSync(file, "utf8");
const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)];
if (scripts.length !== 1) {
  console.error(`expected exactly one inline script in ${file}, found ${scripts.length}`);
  process.exit(1);
}
process.stdout.write(`sha256-${createHash("sha256").update(scripts[0][1], "utf8").digest("base64")}`);
