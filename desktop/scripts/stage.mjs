// Lays out what the installed app carries next to its code (process.resourcesPath), in the shape main.ts reads:
//   runtime/      the relocatable runtime from build-runtime.sh, without the downloadable pieces (design D9)
//   app-sources/  the backend code the core and the engines run, and the two engine catalogs from scripts/engines
//   portal/       the portal built for same-origin serving (VITE_API_BASE_URL='')
//   THIRD_PARTY_NOTICES.md and build.json
// The runtime already holds every Python package (components/*) and its licenses folder, so only Sauri's own
// sources are added. On APFS the runtime is cloned (copy-on-write), so staging costs almost no disk.
//
// Usage: node scripts/stage.mjs [--runtime DIR] [--portal DIR]   (defaults: SAURI_RUNTIME_DIR or the build cache,
// SAURI_PORTAL_DIR or frontend/dist)
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { parseArgs } from "node:util";
import { strayBytecode } from "./verify-package.mjs";

const desktop = path.resolve(import.meta.dirname, "..");
const repo = path.resolve(desktop, "..");
const out = path.join(desktop, ".stage");

const { values } = parseArgs({ options: { runtime: { type: "string" }, portal: { type: "string" } } });
const runtime = path.resolve(
  values.runtime ??
    process.env.SAURI_RUNTIME_DIR ??
    path.join(os.homedir(), "Library", "Caches", "sauri-runtime-build", "runtime-current"),
);
const portal = path.resolve(values.portal ?? process.env.SAURI_PORTAL_DIR ?? path.join(repo, "frontend", "dist"));

function fail(message) {
  console.error(`stage: ${message}`);
  process.exit(1);
}

const readJson = (file) => JSON.parse(fs.readFileSync(file, "utf8"));

// The runtime must be the one this checkout pins: same manifest, every piece present.
const manifestFile = path.join(runtime, "runtime-manifest.json");
if (!fs.existsSync(manifestFile)) fail(`no runtime at ${runtime}; run desktop/scripts/build-runtime.sh or set RUNTIME_DIR`);
const manifest = readJson(manifestFile);
const pinned = readJson(path.join(desktop, "runtime-manifest.json"));
if (JSON.stringify(manifest) !== JSON.stringify(pinned)) {
  fail(`${manifestFile} differs from desktop/runtime-manifest.json; rebuild the runtime for this checkout`);
}
const downloadable = manifest.artifacts.filter((item) => item.distribution === "downloadable").map((item) => item.path);
for (const item of manifest.artifacts) {
  if (item.path && !downloadable.includes(item.path) && !fs.existsSync(path.join(runtime, item.path))) {
    fail(`runtime piece ${item.name} is missing (${item.path})`);
  }
}
if (!fs.existsSync(path.join(portal, "index.html"))) fail(`no portal build at ${portal}; run the portal build first`);

fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });

/** Copy-on-write clone; symlinks are kept as links, never followed. */
function clone(from, to, skip = () => false) {
  fs.cpSync(from, to, {
    recursive: true,
    mode: fs.constants.COPYFILE_FICLONE,
    verbatimSymlinks: true,
    preserveTimestamps: true,
    filter: (src) => !skip(path.relative(from, src)),
  });
}

// FluidAudio's LuxTTS lexicon is espeak-ng output (GPL-3.0-or-later) and CC-BY-SA-4.0 word lists, outside
// FluidAudio's Apache-2.0 (its ThirdPartyLicenses/LuxTtsEnglishG2P-LICENSE.md). Sauri never runs text-to-speech
// and `fluidaudiocli transcribe` works without it, so it is not shipped.
const NOT_SHIPPED = ["bin/FluidAudio_LuxTtsG2pResources.bundle"];
// Runtime without its build stamps, the downloadable components, stray bytecode and what is not shipped.
const runtimeSkip = (rel) =>
  rel === ".stamps" || rel === ".gitignore" || downloadable.includes(rel) || NOT_SHIPPED.includes(rel) ||
  strayBytecode(rel);
clone(runtime, path.join(out, "runtime"), runtimeSkip);

// Sauri's own sources: no tests, caches or container files.
const sourceSkip = (rel) => {
  const parts = rel.split(path.sep);
  const name = parts.at(-1) ?? "";
  return (
    parts.some((part) => ["tests", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"].includes(part)) ||
    name === "Dockerfile" ||
    name.endsWith(".pyc") ||
    name === ".DS_Store"
  );
};
const sources = [
  "backend/app",
  "backend/alembic",
  "backend/alembic.ini",
  "backend/engine-common",
  "backend/host-engine",
  "backend/asr-engine",
  "backend/diar-engine",
  "backend/llm-engine",
  "scripts/engines/model-catalog.json",
  "scripts/engines/engine-hashes.json",
];
for (const rel of sources) {
  const from = path.join(repo, rel);
  if (!fs.existsSync(from)) fail(`missing source ${rel}`);
  clone(from, path.join(out, "app-sources", rel), sourceSkip);
}

clone(portal, path.join(out, "portal"));
fs.copyFileSync(path.join(repo, "THIRD_PARTY_NOTICES.md"), path.join(out, "THIRD_PARTY_NOTICES.md"));

const version = readJson(path.join(desktop, "package.json")).version;
let sha = "";
try {
  sha = execFileSync("git", ["rev-parse", "--short=12", "HEAD"], { cwd: repo }).toString().trim();
} catch {}
fs.writeFileSync(
  path.join(out, "build.json"),
  `${JSON.stringify({ version, sha, runtime: manifest.platform, excluded: [...downloadable, ...NOT_SHIPPED] }, null, 2)}\n`,
);

// Nothing staged may point outside the stage: a link that escapes would ship a path from this Mac.
const escapes = [];
(function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name);
    if (entry.isSymbolicLink()) {
      const target = path.resolve(path.dirname(file), fs.readlinkSync(file));
      if (!target.startsWith(out + path.sep)) escapes.push(path.relative(out, file));
    } else if (entry.isDirectory()) walk(file);
  }
})(out);
if (escapes.length > 0) fail(`links leaving the stage: ${escapes.slice(0, 5).join(", ")}`);

console.log(`staged Sauri ${version} (${sha || "no sha"}) in ${path.relative(repo, out)}; left out: ${[...downloadable, ...NOT_SHIPPED].join(", ")}`);
