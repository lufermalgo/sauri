// Checks that the runtime inside a packaged Sauri.app is byte for byte the runtime it was staged from, and that every
// pinned binary still equals runtime-manifest.json. Packaging must never rewrite them: a re-signed whisper-cli no
// longer equals its pin in engine-hashes.json, and the transcription engine then refuses to start.
//
// Usage: node desktop/scripts/verify-package.mjs <Sauri.app> <runtime dir it was staged from>
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const fileSha = (file) => createHash("sha256").update(fs.readFileSync(file)).digest("hex");

function* regularFiles(base, dir = base) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* regularFiles(base, full);
    else if (entry.isFile()) yield path.relative(base, full);
  }
}

/** Problems in a packaged runtime; empty when it is intact. */
export function runtimeProblems(packaged, source) {
  const problems = [];
  const manifest = JSON.parse(fs.readFileSync(path.join(packaged, "runtime-manifest.json"), "utf8"));
  for (const artifact of manifest.artifacts) {
    for (const [name, pin] of Object.entries(artifact.binaries ?? {})) {
      const file = path.join(packaged, "bin", name);
      if (!fs.existsSync(file)) problems.push(`bin/${name} is missing`);
      else if (fileSha(file) !== pin.sha256) problems.push(`bin/${name} differs from its pin`);
    }
  }
  let changed = 0;
  for (const rel of regularFiles(packaged)) {
    const original = path.join(source, rel);
    if (!fs.existsSync(original) || fileSha(original) !== fileSha(path.join(packaged, rel))) {
      changed += 1;
      if (changed <= 20) problems.push(`${rel} differs from the staged runtime`);
    }
  }
  if (changed > 20) problems.push(`... ${changed} files differ in total`);
  return problems;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const [appPath, source] = process.argv.slice(2);
  if (!appPath || !source) {
    console.error("usage: verify-package.mjs <Sauri.app> <runtime dir>");
    process.exit(2);
  }
  const problems = runtimeProblems(path.join(appPath, "Contents", "Resources", "runtime"), source);
  if (problems.length > 0) {
    console.error(`the packaged runtime was changed:\n  ${problems.join("\n  ")}`);
    process.exit(1);
  }
  console.log("packaged runtime is the staged runtime, pinned binaries intact");
}
